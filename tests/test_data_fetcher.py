import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from sgcc_ha_bridge.data_fetcher import DataFetcher, SessionExpiredFetchError
from sgcc_ha_bridge.login_guard import NonRetryableFetchError
from sgcc_ha_bridge.model import Account, AccountData, Balance, SessionCheck


def session_check(status: str) -> SessionCheck:
    return SessionCheck(
        checked_at="2026-07-16T00:00:00+08:00",
        status=status,
        current_url="https://95598.cn/osgweb/login" if status == "expired" else "https://95598.cn/osgweb/userAcc",
        check_method="test",
        redirected_to_login=status == "expired",
    )


def account_data(account_no: str = "1234567890123", useful: bool = True) -> AccountData:
    return AccountData(
        account=Account(account_no=account_no),
        balance=Balance(account_no=account_no, observed_at="2026-07-16", balance_cny=0.0) if useful else None,
    )


class PathBSessionRetryTestCase(unittest.TestCase):
    def setUp(self):
        self.fetcher = DataFetcher.__new__(DataFetcher)
        self.fetcher.config = SimpleNamespace(IGNORE_USER_ID=[])
        self.fetcher._random_delay = Mock()
        self.driver = object()
        self.store = Mock()

    @patch("sgcc_ha_bridge.data_fetcher.check_session")
    def test_empty_result_retries_in_same_session_then_succeeds(self, check):
        useful = account_data()
        scraper = Mock()
        scraper.fetch_all.side_effect = [[], [useful]]
        check.return_value = session_check("authenticated")

        result = self.fetcher._fetch_path_b_in_session(scraper, self.driver, self.store)

        self.assertEqual(result, [useful])
        self.assertEqual(scraper.fetch_all.call_count, 2)
        self.fetcher._random_delay.assert_called_once_with(1, 3)
        self.store.record_session_check.assert_called_once()

    @patch("sgcc_ha_bridge.data_fetcher.check_session")
    def test_expired_session_allows_outer_retry(self, check):
        scraper = Mock()
        scraper.fetch_all.return_value = []
        check.return_value = session_check("expired")

        with self.assertRaises(SessionExpiredFetchError):
            self.fetcher._fetch_path_b_in_session(scraper, self.driver, self.store)

        scraper.fetch_all.assert_called_once()
        self.fetcher._random_delay.assert_not_called()

    @patch("sgcc_ha_bridge.data_fetcher.check_session")
    def test_authenticated_empty_results_stop_before_outer_login_retry(self, check):
        scraper = Mock()
        scraper.fetch_all.return_value = []
        check.return_value = session_check("authenticated")

        with self.assertRaises(NonRetryableFetchError):
            self.fetcher._fetch_path_b_in_session(scraper, self.driver, self.store)

        self.assertEqual(scraper.fetch_all.call_count, 2)
        self.assertEqual(check.call_count, 2)

    @patch("sgcc_ha_bridge.data_fetcher.check_session")
    def test_unknown_session_is_not_treated_as_expired(self, check):
        scraper = Mock()
        scraper.fetch_all.return_value = []
        check.return_value = session_check("unknown")

        with self.assertRaises(NonRetryableFetchError):
            self.fetcher._fetch_path_b_in_session(scraper, self.driver, self.store)

        self.assertEqual(scraper.fetch_all.call_count, 2)

    @patch("sgcc_ha_bridge.data_fetcher.check_session")
    def test_ignored_accounts_do_not_trigger_session_retry(self, check):
        ignored = account_data(account_no="1234567890123")
        self.fetcher.config.IGNORE_USER_ID = [ignored.account.account_no]
        scraper = Mock()
        scraper.fetch_all.return_value = [ignored]

        with self.assertRaises(NonRetryableFetchError):
            self.fetcher._fetch_path_b_in_session(scraper, self.driver, self.store)

        scraper.fetch_all.assert_called_once()
        check.assert_not_called()
        self.fetcher._random_delay.assert_not_called()

    @patch("sgcc_ha_bridge.data_fetcher.check_session")
    def test_metadata_only_result_retries_in_same_session(self, check):
        metadata_only = account_data(useful=False)
        useful = account_data()
        scraper = Mock()
        scraper.fetch_all.side_effect = [[metadata_only], [useful]]
        check.return_value = session_check("authenticated")

        result = self.fetcher._fetch_path_b_in_session(scraper, self.driver, self.store)

        self.assertEqual(result, [useful])
        self.assertEqual(scraper.fetch_all.call_count, 2)


class LoginFallbackPolicyTestCase(unittest.TestCase):
    def test_manual_trigger_allows_configured_fallback(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertTrue(DataFetcher._allow_login_fallback("manual"))

    def test_scheduled_trigger_disallows_fallback_by_default(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(DataFetcher._allow_login_fallback("schedule"))

    def test_scheduled_trigger_allows_unified_unattended_fallback(self):
        with patch.dict(
            os.environ,
            {"SGCC_LOGIN_FALLBACK_UNATTENDED": "true"},
            clear=True,
        ):
            self.assertTrue(DataFetcher._allow_login_fallback("schedule"))

    def test_scheduled_trigger_keeps_legacy_qrcode_switch_compatible(self):
        with patch.dict(
            os.environ,
            {"SGCC_QRCODE_FALLBACK_UNATTENDED": "true"},
            clear=True,
        ):
            self.assertTrue(DataFetcher._allow_login_fallback("schedule"))


if __name__ == "__main__":
    unittest.main()
