import logging
import sys
import unittest
from datetime import date, datetime
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

try:
    import schedule as schedule_module
except ImportError:
    schedule_module = SimpleNamespace(CancelJob=object())
sys.modules["schedule"] = schedule_module
_data_fetcher_stub = ModuleType("sgcc_ha_bridge.data_fetcher")
_data_fetcher_stub.DataFetcher = object
sys.modules.setdefault("sgcc_ha_bridge.data_fetcher", _data_fetcher_stub)

from sgcc_ha_bridge import main


class DailyScheduleJitterTestCase(unittest.TestCase):
    def test_missing_value_keeps_legacy_ten_minute_window(self):
        with patch.dict(main.os.environ, {}, clear=True):
            self.assertEqual(main._daily_jitter_minutes(), 10)

    def test_zero_disables_random_sampling(self):
        randint = Mock()

        offset, run_times = main._daily_schedule_times("07:00", 0, randint=randint)

        self.assertEqual(offset, 0)
        self.assertEqual(run_times, ["07:00"])
        randint.assert_not_called()

    def test_valid_window_is_passed_to_random_sampler(self):
        randint = Mock(return_value=-37)

        offset, run_times = main._daily_schedule_times("07:00", 60, randint=randint)

        self.assertEqual(offset, -37)
        self.assertEqual(run_times, ["06:23"])
        randint.assert_called_once_with(-60, 60)

    def test_valid_boundaries_are_accepted(self):
        self.assertEqual(main._daily_jitter_minutes("0"), 0)
        self.assertEqual(main._daily_jitter_minutes("180"), 180)

    def test_invalid_values_fall_back_to_legacy_default(self):
        for raw_value in ("", "abc", "-1", "181", None):
            with self.subTest(raw_value=raw_value), self.assertLogs(level=logging.WARNING):
                if raw_value is None:
                    with patch.dict(main.os.environ, {"SGCC_DAILY_JITTER_MINUTES": ""}, clear=True):
                        result = main._daily_jitter_minutes()
                else:
                    result = main._daily_jitter_minutes(raw_value)
                self.assertEqual(result, 10)

    def test_two_daily_runs_share_offset_and_remain_twelve_hours_apart(self):
        randint = Mock(return_value=8)

        offset, run_times = main._daily_schedule_times("07:00", 10, daily_runs=2, randint=randint)

        self.assertEqual(offset, 8)
        self.assertEqual(run_times, ["07:08", "19:08"])
        randint.assert_called_once_with(-10, 10)

    def test_schedule_time_wraps_across_midnight(self):
        randint = Mock(return_value=-10)

        _, run_times = main._daily_schedule_times("00:05", 10, daily_runs=2, randint=randint)

        self.assertEqual(run_times, ["23:55", "11:55"])


class FakeJob:
    def __init__(self, func, args):
        self.func = func
        self.args = args
        self.next_run = None


class FakeEvery:
    def __init__(self, scheduler):
        self.scheduler = scheduler

    @property
    def day(self):
        return self

    def at(self, run_time):
        self.run_time = run_time
        return self

    def do(self, func, *args):
        job = FakeJob(func, args)
        self.scheduler.jobs.append(job)
        return job


class FakeScheduler:
    CancelJob = object()

    def __init__(self):
        self.jobs = []
        self.cancelled = []

    def every(self):
        return FakeEvery(self)

    def cancel_job(self, job):
        self.cancelled.append(job)
        if job in self.jobs:
            self.jobs.remove(job)


class DailyJitterSchedulerTestCase(unittest.TestCase):
    def test_last_run_resamples_next_day_without_restart(self):
        scheduler = FakeScheduler()
        run_job = Mock()
        randint = Mock(side_effect=[-10, 15])
        current = [datetime(2026, 7, 20, 6, 0)]
        daily = main.DailyJitterScheduler(
            scheduler,
            "07:00",
            30,
            1,
            run_job,
            randint=randint,
            now=lambda: current[0],
        )

        self.assertEqual(daily.schedule_day(), [datetime(2026, 7, 20, 6, 50)])
        first_job = scheduler.jobs[0]
        current[0] = datetime(2026, 7, 20, 6, 50)
        result = first_job.args[0](*first_job.args[1:])

        self.assertIs(result, main.schedule.CancelJob)
        run_job.assert_called_once_with()
        self.assertEqual(scheduler.jobs[0].next_run, datetime(2026, 7, 21, 7, 15))
        self.assertEqual(randint.call_args_list[0].args, (-30, 30))
        self.assertEqual(randint.call_args_list[1].args, (-30, 30))

    def test_two_runs_share_daily_offset_and_resample_after_second(self):
        scheduler = FakeScheduler()
        run_job = Mock()
        randint = Mock(side_effect=[8, -4])
        current = [datetime(2026, 7, 20, 6, 0)]
        daily = main.DailyJitterScheduler(
            scheduler,
            "07:00",
            10,
            2,
            run_job,
            randint=randint,
            now=lambda: current[0],
        )

        self.assertEqual(
            daily.schedule_day(),
            [datetime(2026, 7, 20, 7, 8), datetime(2026, 7, 20, 19, 8)],
        )
        first_job, second_job = list(scheduler.jobs)
        current[0] = datetime(2026, 7, 20, 7, 8)
        first_job.args[0](*first_job.args[1:])
        self.assertEqual(randint.call_count, 1)

        current[0] = datetime(2026, 7, 20, 19, 8)
        second_job.args[0](*second_job.args[1:])

        self.assertEqual(randint.call_count, 2)
        self.assertEqual(scheduler.jobs[0].next_run, datetime(2026, 7, 21, 6, 56))
        self.assertEqual(scheduler.jobs[1].next_run, datetime(2026, 7, 21, 18, 56))

    def test_start_after_first_run_only_schedules_remaining_second_run(self):
        scheduler = FakeScheduler()
        current = datetime(2026, 7, 20, 12, 0)
        daily = main.DailyJitterScheduler(
            scheduler,
            "07:00",
            0,
            2,
            Mock(),
            now=lambda: current,
        )

        self.assertEqual(daily.schedule_day(), [datetime(2026, 7, 20, 19, 0)])
        self.assertEqual(len(scheduler.jobs), 1)

    def test_start_after_all_runs_schedules_next_day(self):
        scheduler = FakeScheduler()
        current = datetime(2026, 7, 20, 22, 0)
        daily = main.DailyJitterScheduler(
            scheduler,
            "07:00",
            0,
            1,
            Mock(),
            now=lambda: current,
        )

        self.assertEqual(daily.schedule_day(), [datetime(2026, 7, 21, 7, 0)])
        self.assertEqual(daily._scheduled_for, date(2026, 7, 21))

    @patch("sgcc_ha_bridge.main.safe_scheduled_job", side_effect=lambda func, *args: func(*args))
    def test_real_schedule_scheduler_replaces_completed_job(self, safe_job):
        if not hasattr(schedule_module, "Scheduler"):
            self.skipTest("schedule dependency is not installed")

        scheduler = schedule_module.Scheduler()
        run_job = Mock()
        randint = Mock(side_effect=[0, 5])
        current = [datetime(2026, 7, 20, 6, 0)]
        daily = main.DailyJitterScheduler(
            scheduler,
            "07:00",
            10,
            1,
            run_job,
            randint=randint,
            now=lambda: current[0],
        )
        daily.schedule_day()
        first_job = scheduler.jobs[0]
        current[0] = datetime(2026, 7, 20, 7, 0)

        scheduler._run_job(first_job)

        self.assertEqual(len(scheduler.jobs), 1)
        self.assertEqual(scheduler.jobs[0].next_run, datetime(2026, 7, 21, 7, 5))
        run_job.assert_called_once_with()

    def test_positive_offset_crossing_midnight_keeps_next_logical_day(self):
        scheduler = FakeScheduler()
        randint = Mock(side_effect=[180, 0])
        current = [datetime(2026, 7, 20, 20, 0)]
        daily = main.DailyJitterScheduler(
            scheduler,
            "23:30",
            180,
            1,
            Mock(),
            randint=randint,
            now=lambda: current[0],
        )

        self.assertEqual(daily.schedule_day(), [datetime(2026, 7, 21, 2, 30)])
        job = scheduler.jobs[0]
        current[0] = datetime(2026, 7, 21, 2, 30)
        job.args[0](*job.args[1:])

        self.assertEqual(scheduler.jobs[0].next_run, datetime(2026, 7, 21, 23, 30))

    def test_two_runs_crossing_midnight_share_offset_and_advance_logical_day(self):
        scheduler = FakeScheduler()
        randint = Mock(side_effect=[60, -30])
        current = [datetime(2026, 7, 20, 22, 0)]
        daily = main.DailyJitterScheduler(
            scheduler,
            "23:30",
            60,
            2,
            Mock(),
            randint=randint,
            now=lambda: current[0],
        )

        self.assertEqual(
            daily.schedule_day(),
            [datetime(2026, 7, 21, 0, 30), datetime(2026, 7, 21, 12, 30)],
        )
        _, second_job = list(scheduler.jobs)
        current[0] = datetime(2026, 7, 21, 12, 30)
        second_job.args[0](*second_job.args[1:])

        self.assertEqual(
            [job.next_run for job in scheduler.jobs],
            [datetime(2026, 7, 21, 23, 0), datetime(2026, 7, 22, 11, 0)],
        )

    def test_delayed_last_run_is_skipped_but_next_day_is_scheduled(self):
        scheduler = FakeScheduler()
        run_job = Mock()
        randint = Mock(side_effect=[0, 5])
        current = [datetime(2026, 7, 20, 6, 0)]
        daily = main.DailyJitterScheduler(
            scheduler,
            "07:00",
            10,
            1,
            run_job,
            randint=randint,
            now=lambda: current[0],
        )
        daily.schedule_day()
        job = scheduler.jobs[0]
        current[0] = datetime(2026, 7, 20, 14, 0)

        job.args[0](*job.args[1:])

        run_job.assert_not_called()
        self.assertEqual(scheduler.jobs[0].next_run, datetime(2026, 7, 21, 7, 5))


if __name__ == "__main__":
    unittest.main()
