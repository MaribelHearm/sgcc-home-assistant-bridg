import os
import sys
import unittest


from sgcc_ha_bridge.ha_mapping import account_data_summary, account_data_to_update_args, with_history_daily_if_empty
from sgcc_ha_bridge.model import Account, AccountData, Balance, DailyReading


class FakeStore:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def get_daily(self, account_no, limit=31):
        self.calls.append((account_no, limit))
        return list(self.rows)


class HistoryDailyBackfillTestCase(unittest.TestCase):
    def test_with_history_daily_if_empty_uses_store_for_publish_copy(self):
        account_data = AccountData(account=Account(account_no="1234567890123"), daily=[])
        history = [
            DailyReading(account_no="1234567890123", date="2026-06-18", total_usage_kwh=8.0),
            DailyReading(account_no="1234567890123", date="2026-06-19", total_usage_kwh=9.5),
        ]
        store = FakeStore(history)

        publish_data = with_history_daily_if_empty(account_data, store, limit=31)
        update_args = account_data_to_update_args(publish_data)

        self.assertIsNot(publish_data, account_data)
        self.assertEqual(account_data.daily, [])
        self.assertEqual(store.calls, [("1234567890123", 31)])
        self.assertEqual(update_args["last_daily_date"], "2026-06-19")
        self.assertEqual(update_args["last_daily_usage"], 9.5)
        self.assertIsNotNone(update_args["tou_data"])
        self.assertEqual(len(update_args["tou_data"]["daily"]), 2)

    def test_with_history_daily_if_empty_does_not_query_when_current_daily_exists(self):
        current = [DailyReading(account_no="1234567890123", date="2026-06-20", total_usage_kwh=1.0)]
        account_data = AccountData(account=Account(account_no="1234567890123"), daily=current)
        store = FakeStore([])

        self.assertIs(with_history_daily_if_empty(account_data, store), account_data)
        self.assertEqual(store.calls, [])


class BalanceMappingTestCase(unittest.TestCase):
    def test_account_data_summary_shows_balance_field_availability(self):
        account_data = AccountData(
            account=Account(account_no="1234567890123"),
            balance=Balance(
                account_no="1234567890123",
                observed_at="2026-07-06T05:16:28+08:00",
                balance_cny=None,
                prepay_balance_cny=155.31,
                arrears_cny=None,
            ),
        )

        self.assertIn(
            "balance=yes(amount=no, prepay=yes, arrears=no)",
            account_data_summary(account_data),
        )

    def test_prepay_balance_is_not_published_as_charge_balance(self):
        account_data = AccountData(
            account=Account(account_no="1234567890123"),
            balance=Balance(
                account_no="1234567890123",
                observed_at="2026-06-21T18:03:34+08:00",
                balance_cny=None,
                prepay_balance_cny=127.5,
                arrears_cny=70.0,
            ),
        )

        args = account_data_to_update_args(account_data)

        self.assertIsNone(args["balance"])
        self.assertEqual(args["prepay_balance"], 127.5)
        self.assertEqual(args["arrears"], 70.0)
        self.assertEqual(args["enhanced_balance"]["amount_due"], 70.0)


if __name__ == "__main__":
    unittest.main()
