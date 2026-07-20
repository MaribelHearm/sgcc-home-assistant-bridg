import sys
import unittest
from types import ModuleType, SimpleNamespace

sys.modules.setdefault("schedule", SimpleNamespace(CancelJob=object()))
_data_fetcher_stub = ModuleType("sgcc_ha_bridge.data_fetcher")
_data_fetcher_stub.DataFetcher = object
sys.modules.setdefault("sgcc_ha_bridge.data_fetcher", _data_fetcher_stub)

from sgcc_ha_bridge import main
from sgcc_ha_bridge.login_guard import NonRetryableFetchError


class FakeFetcher:
    def __init__(self, failures_before_success=0, non_retryable=False):
        self.calls = []
        self.failures_before_success = failures_before_success
        self.non_retryable = non_retryable

    def fetch(self, trigger_type="manual"):
        self.calls.append(trigger_type)
        if self.non_retryable:
            raise NonRetryableFetchError("captcha")
        if len(self.calls) <= self.failures_before_success:
            raise RuntimeError("temporary")
        return "success"

    @staticmethod
    def _redact_text(value):
        return str(value)


class RunTaskRetryBackoffTestCase(unittest.TestCase):
    def setUp(self):
        self.old_limit = getattr(main, "RETRY_TIMES_LIMIT", None)
        self.old_sleep = main.time.sleep
        self.old_uniform = main.random.uniform
        main.RETRY_TIMES_LIMIT = 3
        self.sleeps = []
        main.time.sleep = self.sleeps.append
        main.random.uniform = lambda a, b: 0

    def tearDown(self):
        if self.old_limit is None:
            delattr(main, "RETRY_TIMES_LIMIT")
        else:
            main.RETRY_TIMES_LIMIT = self.old_limit
        main.time.sleep = self.old_sleep
        main.random.uniform = self.old_uniform

    def test_retry_failures_sleep_with_backoff(self):
        fetcher = FakeFetcher(failures_before_success=2)

        main.run_task(fetcher, "schedule")

        self.assertEqual(fetcher.calls, ["schedule", "retry", "retry"])
        self.assertEqual(self.sleeps, [30.0, 60.0])

    def test_non_retryable_failure_does_not_sleep_or_retry(self):
        fetcher = FakeFetcher(non_retryable=True)

        main.run_task(fetcher, "schedule")

        self.assertEqual(fetcher.calls, ["schedule"])
        self.assertEqual(self.sleeps, [])


if __name__ == "__main__":
    unittest.main()
