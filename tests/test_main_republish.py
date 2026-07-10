import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace

sys.modules.setdefault("schedule", SimpleNamespace())
_data_fetcher_stub = ModuleType("sgcc_ha_bridge.data_fetcher")
_data_fetcher_stub.DataFetcher = object
sys.modules.setdefault("sgcc_ha_bridge.data_fetcher", _data_fetcher_stub)

from sgcc_ha_bridge import main
from sgcc_ha_bridge.config import FetcherConfig
from sgcc_ha_bridge.model import Account, AccountData, DailyReading, FetchRun, MonthlyReading
from sgcc_ha_bridge.store import Store


class FakeMqttPublisher:
    published = []
    removed = []

    def __init__(self, config):
        self.config = config
        self.connected = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def publish_account_data(self, data):
        FakeMqttPublisher.published.append(data)
        return True

    def remove_account_data(self, data):
        FakeMqttPublisher.removed.append(data)
        return True


class RepublishMqttFromStoreTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmpdir.name) / "sgcc.sqlite3")
        self.old_db_path = os.environ.get("SGCC_DB_PATH")
        os.environ["SGCC_DB_PATH"] = self.db_path
        self.old_publisher = main.MqttPublisher
        main.MqttPublisher = FakeMqttPublisher
        FakeMqttPublisher.published.clear()
        FakeMqttPublisher.removed.clear()

    def tearDown(self):
        main.MqttPublisher = self.old_publisher
        if self.old_db_path is None:
            os.environ.pop("SGCC_DB_PATH", None)
        else:
            os.environ["SGCC_DB_PATH"] = self.old_db_path
        self.tmpdir.cleanup()

    def _save(self, account_data):
        with Store(self.db_path) as store:
            run_id = store.start_run(FetchRun(trigger_type="test", started_at="2026-06-21T00:00:00+08:00"))
            store.save_account_data(account_data, run_id)

    def test_empty_account_cache_is_not_success(self):
        with Store(self.db_path) as store:
            store.upsert_account(Account(account_no="1234567890123"))

        self.assertFalse(main.republish_mqtt_from_store(FetcherConfig(PUBLISHER="mqtt")))
        self.assertEqual(FakeMqttPublisher.published, [])

    def test_fresh_daily_cache_republishes(self):
        self._save(AccountData(
            account=Account(account_no="1234567890123"),
            daily=[DailyReading(account_no="1234567890123", date=main.datetime.now().strftime("%Y-%m-%d"), total_usage_kwh=1.2)],
        ))

        self.assertTrue(main.republish_mqtt_from_store(FetcherConfig(PUBLISHER="mqtt")))
        self.assertEqual(len(FakeMqttPublisher.published), 1)

    def test_stale_daily_cache_still_republishes_useful_data(self):
        self._save(AccountData(
            account=Account(account_no="1234567890123"),
            daily=[DailyReading(account_no="1234567890123", date="2020-01-01", total_usage_kwh=1.2)],
        ))

        self.assertFalse(main.republish_mqtt_from_store(FetcherConfig(PUBLISHER="mqtt")))
        self.assertEqual(len(FakeMqttPublisher.published), 1)

    def test_monthly_only_cache_still_republishes_useful_data(self):
        self._save(AccountData(
            account=Account(account_no="1234567890123"),
            monthly=[MonthlyReading(account_no="1234567890123", year_month="2026-06", total_usage_kwh=12.3)],
        ))

        self.assertFalse(main.republish_mqtt_from_store(FetcherConfig(PUBLISHER="mqtt")))
        self.assertEqual(len(FakeMqttPublisher.published), 1)

    def test_inactive_and_ignored_accounts_are_cleaned_not_republished(self):
        self._save(AccountData(
            account=Account(account_no="1234567899314"),
            daily=[DailyReading(
                account_no="1234567899314",
                date=main.datetime.now().strftime("%Y-%m-%d"),
                total_usage_kwh=1.2,
            )],
        ))
        self._save(AccountData(
            account=Account(account_no="1234567897402"),
            daily=[DailyReading(account_no="1234567897402", date="2020-01-01", total_usage_kwh=9.9)],
        ))
        self._save(AccountData(
            account=Account(account_no="1234567893445"),
            daily=[DailyReading(account_no="1234567893445", date="2020-01-01", total_usage_kwh=9.9)],
        ))
        with Store(self.db_path) as store:
            run_id = store.start_run(FetchRun(trigger_type="test", started_at="reconcile"))
            store.reconcile_active_accounts(
                ["1234567899314", "1234567893445"],
                run_id,
            )

        self.assertTrue(main.republish_mqtt_from_store(FetcherConfig(
            PUBLISHER="mqtt",
            IGNORE_USER_ID=["1234567893445"],
        )))
        self.assertEqual(
            [item.account.account_no for item in FakeMqttPublisher.published],
            ["1234567899314"],
        )
        self.assertEqual(
            sorted(item.account.account_no for item in FakeMqttPublisher.removed),
            ["1234567893445", "1234567897402"],
        )


class CacheFileUpdator:
    def __init__(self, cache_file: Path):
        self.cache_file = cache_file

    def _get_cache_file(self):
        return str(self.cache_file)


class CacheFreshnessGuardTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmpdir.name) / "sgcc.sqlite3")
        self.cache_file = Path(self.tmpdir.name) / "sgcc_cache.json"
        self.old_db_path = os.environ.get("SGCC_DB_PATH")
        os.environ["SGCC_DB_PATH"] = self.db_path

    def tearDown(self):
        if self.old_db_path is None:
            os.environ.pop("SGCC_DB_PATH", None)
        else:
            os.environ["SGCC_DB_PATH"] = self.old_db_path
        self.tmpdir.cleanup()

    def _save(self, account_data):
        with Store(self.db_path) as store:
            run_id = store.start_run(FetchRun(trigger_type="test", started_at="2026-06-21T00:00:00+08:00"))
            store.save_account_data(account_data, run_id)

    def test_both_publisher_requires_rest_and_mqtt_cache_before_skip_fetch(self):
        self._save(AccountData(
            account=Account(account_no="1234567890123"),
            daily=[DailyReading(account_no="1234567890123", date=main.datetime.now().strftime("%Y-%m-%d"), total_usage_kwh=1.2)],
        ))

        updator = CacheFileUpdator(self.cache_file)

        self.assertTrue(main.has_recent_cached_business_data(updator, FetcherConfig(PUBLISHER="mqtt")))
        self.assertFalse(main.has_recent_cached_business_data(updator, FetcherConfig(PUBLISHER="both")))

    def test_legacy_mixed_today_and_stale_cache_is_not_recent(self):
        today = main.datetime.now().strftime("%Y-%m-%d")
        self.cache_file.write_text(
            '{'
            f'"1234567890123": {{"timestamp": "{today}T01:00:00", "balance": 1.0}},'
            '"1234567890456": {"timestamp": "2020-01-01T01:00:00", "balance": 2.0}'
            '}'
        )

        self.assertFalse(main.has_recent_cached_business_data(
            CacheFileUpdator(self.cache_file),
            FetcherConfig(PUBLISHER="rest"),
        ))

    def test_legacy_ignores_configured_stale_accounts(self):
        today = main.datetime.now().strftime("%Y-%m-%d")
        self.cache_file.write_text(
            '{'
            f'"active-account": {{"timestamp": "{today}T01:00:00", "balance": 1.0}},'
            '"ignored-account": {"timestamp": "2020-01-01T01:00:00", "balance": 2.0}'
            '}'
        )

        self.assertTrue(main.has_recent_cached_business_data(
            CacheFileUpdator(self.cache_file),
            FetcherConfig(PUBLISHER="rest", IGNORE_USER_ID=["ignored-account"]),
        ))

    def test_store_freshness_ignores_configured_stale_accounts(self):
        self._save(AccountData(
            account=Account(account_no="ignored-account"),
            daily=[DailyReading(account_no="ignored-account", date="2020-01-01", total_usage_kwh=9.9)],
        ))
        self._save(AccountData(
            account=Account(account_no="active-account"),
            daily=[DailyReading(
                account_no="active-account",
                date=main.datetime.now().strftime("%Y-%m-%d"),
                total_usage_kwh=1.2,
            )],
        ))

        self.assertTrue(main.has_recent_cached_business_data(
            None,
            FetcherConfig(PUBLISHER="mqtt", IGNORE_USER_ID=["ignored-account"]),
        ))

    def test_store_freshness_requires_every_active_account_to_be_recent(self):
        self._save(AccountData(
            account=Account(account_no="fresh-account"),
            daily=[DailyReading(
                account_no="fresh-account",
                date=main.datetime.now().strftime("%Y-%m-%d"),
                total_usage_kwh=1.2,
            )],
        ))
        self._save(AccountData(
            account=Account(account_no="stale-account"),
            daily=[DailyReading(account_no="stale-account", date="2020-01-01", total_usage_kwh=9.9)],
        ))

        self.assertFalse(main.has_recent_cached_business_data(None, FetcherConfig(PUBLISHER="mqtt")))

    def test_store_freshness_ignores_inactive_stale_accounts(self):
        self._save(AccountData(
            account=Account(account_no="fresh-account"),
            daily=[DailyReading(
                account_no="fresh-account",
                date=main.datetime.now().strftime("%Y-%m-%d"),
                total_usage_kwh=1.2,
            )],
        ))
        self._save(AccountData(
            account=Account(account_no="stale-account"),
            daily=[DailyReading(account_no="stale-account", date="2020-01-01", total_usage_kwh=9.9)],
        ))
        with Store(self.db_path) as store:
            run_id = store.start_run(FetchRun(trigger_type="test", started_at="reconcile"))
            store.reconcile_active_accounts(["fresh-account"], run_id)

        self.assertTrue(main.has_recent_cached_business_data(None, FetcherConfig(PUBLISHER="mqtt")))


class FakeFetcher:
    def __init__(self):
        self.calls = []

    def fetch(self, trigger_type="manual"):
        self.calls.append(trigger_type)
        return "success"

    @staticmethod
    def _redact_text(value):
        return str(value)


class FakeUpdator:
    def __init__(self, republish_result=False):
        self.republish_result = republish_result

    def republish(self):
        return self.republish_result


class RepublishOrFetchGuardTestCase(unittest.TestCase):
    def test_publish_failure_with_fresh_store_cache_does_not_login_again(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "sgcc.sqlite3")
            old_db_path = os.environ.get("SGCC_DB_PATH")
            os.environ["SGCC_DB_PATH"] = db_path
            try:
                with Store(db_path) as store:
                    run_id = store.start_run(FetchRun(trigger_type="test", started_at="2026-06-21T00:00:00+08:00"))
                    store.save_account_data(AccountData(
                        account=Account(account_no="1234567890123"),
                        daily=[DailyReading(
                            account_no="1234567890123",
                            date=main.datetime.now().strftime("%Y-%m-%d"),
                            total_usage_kwh=1.2,
                        )],
                    ), run_id)

                fetcher = FakeFetcher()
                main.republish_or_fetch(None, fetcher, FetcherConfig(PUBLISHER="mqtt"))

                self.assertEqual(fetcher.calls, [])
            finally:
                if old_db_path is None:
                    os.environ.pop("SGCC_DB_PATH", None)
                else:
                    os.environ["SGCC_DB_PATH"] = old_db_path


if __name__ == "__main__":
    unittest.main()
