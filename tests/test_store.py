import os
import sqlite3
import tempfile
import unittest

from sgcc_ha_bridge.model import (
    Account,
    AccountData,
    Balance,
    DailyReading,
    FetchRun,
    MonthlyReading,
    PublisherState,
    SessionCheck,
    YearlyReading,
)
from sgcc_ha_bridge.store import Store


class StoreTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmpdir.name, "sgcc-test.sqlite3")
        self.store = Store(self.db_path)

    def tearDown(self):
        self.store.close()
        self.tmpdir.cleanup()

    def test_init_schema_creates_expected_tables(self):
        rows = self.store.conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
        table_names = {row["name"] for row in rows}
        self.assertTrue(
            {
                "accounts",
                "balances",
                "readings_daily",
                "readings_monthly",
                "readings_yearly",
                "fetch_runs",
                "session_checks",
                "publisher_state",
            }.issubset(table_names)
        )
        self.assertEqual(
            self.store.conn.execute("PRAGMA foreign_keys").fetchone()[0],
            1,
        )
        account_columns = {
            row["name"]
            for row in self.store.conn.execute("PRAGMA table_info(accounts)").fetchall()
        }
        self.assertIn("is_active", account_columns)
        self.assertIn("last_seen_fetch_run_id", account_columns)

    def test_init_schema_migrates_existing_accounts_table(self):
        self.store.close()
        os.remove(self.db_path)
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """
            CREATE TABLE accounts (
                account_no TEXT PRIMARY KEY NOT NULL,
                display_name TEXT NOT NULL DEFAULT '',
                address TEXT NOT NULL DEFAULT '',
                province TEXT NOT NULL DEFAULT ''
            )
            """
        )
        conn.execute(
            "INSERT INTO accounts (account_no) VALUES (?)",
            ("1234567897402",),
        )
        conn.commit()
        conn.close()

        self.store = Store(self.db_path)

        row = self.store.conn.execute(
            "SELECT is_active, last_seen_fetch_run_id FROM accounts WHERE account_no = ?",
            ("1234567897402",),
        ).fetchone()
        self.assertEqual(row["is_active"], 1)
        self.assertIsNone(row["last_seen_fetch_run_id"])

    def test_save_account_data_roundtrip(self):
        run_id = self.store.start_run(
            FetchRun(
                trigger_type="manual",
                started_at="2026-06-18T04:00:00+08:00",
                session_status_before="authenticated",
            )
        )
        data = AccountData(
            account=Account(
                account_no="1234567890123",
                display_name="home",
                address="redacted address",
                province="Shanghai",
            ),
            balance=Balance(
                account_no="1234567890123",
                observed_at="2026-06-18T04:01:00+08:00",
                balance_cny=88.12,
                prepay_balance_cny=12.34,
                arrears_cny=0.0,
            ),
            yearly=YearlyReading(
                account_no="1234567890123",
                year="2026",
                total_usage_kwh=321.0,
                total_charge_cny=123.45,
            ),
            monthly=[
                MonthlyReading(
                    account_no="1234567890123",
                    year_month="2026-06",
                    total_usage_kwh=56.7,
                    total_charge_cny=23.45,
                    begin_date="2026-06-01",
                    end_date="2026-06-30",
                )
            ],
            daily=[
                DailyReading(
                    account_no="1234567890123",
                    date="2026-06-17",
                    total_usage_kwh=6.5,
                    valley_usage_kwh=1.0,
                    flat_usage_kwh=2.0,
                    peak_usage_kwh=3.0,
                    tip_usage_kwh=0.5,
                )
            ],
        )

        self.store.save_account_data(data, run_id)

        self.assertEqual(self.store.get_account("1234567890123"), data.account)
        self.assertEqual(self.store.get_latest_balance("1234567890123"), data.balance)
        self.assertEqual(self.store.get_daily("1234567890123", limit=10), data.daily)
        self.assertEqual(self.store.get_monthly("1234567890123", limit=10), data.monthly)
        self.assertEqual(self.store.get_yearly("1234567890123", limit=10), [data.yearly])

    def test_reconcile_active_accounts_keeps_history_and_deactivates_missing_accounts(self):
        run1 = self.store.start_run(FetchRun(trigger_type="manual", started_at="run1"))
        run2 = self.store.start_run(FetchRun(trigger_type="manual", started_at="run2"))
        for account_no in ("1234567899314", "1234567897402"):
            self.store.save_account_data(
                AccountData(
                    account=Account(account_no=account_no),
                    daily=[DailyReading(account_no=account_no, date="2026-07-10", total_usage_kwh=1.0)],
                ),
                run1,
            )

        self.store.save_account_data(
            AccountData(account=Account(account_no="1234567899314")),
            run2,
        )
        deactivated = self.store.reconcile_active_accounts(
            ["1234567899314"],
            run2,
        )

        self.assertEqual(deactivated, ["1234567897402"])
        self.assertEqual(self.store.list_account_nos(active_only=True), ["1234567899314"])
        self.assertEqual(self.store.list_account_nos(active_only=False), ["1234567897402"])
        self.assertEqual(
            self.store.get_daily("1234567897402", limit=10)[0].total_usage_kwh,
            1.0,
        )

    def test_reconcile_active_accounts_rejects_empty_authoritative_set(self):
        with self.assertRaises(ValueError):
            self.store.reconcile_active_accounts([], 1)

    def test_save_account_data_reactivates_account(self):
        run1 = self.store.start_run(FetchRun(trigger_type="manual", started_at="run1"))
        run2 = self.store.start_run(FetchRun(trigger_type="manual", started_at="run2"))
        self.store.save_account_data(
            AccountData(account=Account(account_no="1234567897402")),
            run1,
        )
        self.store.save_account_data(
            AccountData(account=Account(account_no="1234567899314")),
            run1,
        )
        self.store.reconcile_active_accounts(["1234567899314"], run1)

        self.store.save_account_data(
            AccountData(account=Account(account_no="1234567897402")),
            run2,
        )

        self.assertEqual(
            self.store.list_account_nos(active_only=True),
            ["1234567897402", "1234567899314"],
        )

    def test_daily_upsert_is_idempotent_and_updates_value(self):
        run1 = self.store.start_run(FetchRun(trigger_type="manual", started_at="run1"))
        run2 = self.store.start_run(FetchRun(trigger_type="manual", started_at="run2"))
        account = Account(account_no="1234567890123")

        self.store.save_account_data(
            AccountData(
                account=account,
                daily=[DailyReading(account_no=account.account_no, date="2026-06-17", total_usage_kwh=1.0)],
            ),
            run1,
        )
        self.store.save_account_data(
            AccountData(
                account=account,
                daily=[DailyReading(account_no=account.account_no, date="2026-06-17", total_usage_kwh=2.5)],
            ),
            run2,
        )

        count = self.store.conn.execute(
            "SELECT COUNT(*) FROM readings_daily WHERE account_no = ? AND date = ?",
            (account.account_no, "2026-06-17"),
        ).fetchone()[0]
        self.assertEqual(count, 1)
        row = self.store.conn.execute(
            "SELECT total_usage_kwh, fetch_run_id FROM readings_daily WHERE account_no = ? AND date = ?",
            (account.account_no, "2026-06-17"),
        ).fetchone()
        self.assertEqual(row["total_usage_kwh"], 2.5)
        self.assertEqual(row["fetch_run_id"], run2)

    def test_start_finish_run_and_foreign_key(self):
        run_id = self.store.start_run(
            FetchRun(trigger_type="manual", started_at="2026-06-18T04:00:00+08:00")
        )
        self.store.finish_run(
            run_id,
            "success",
            finished_at="2026-06-18T04:02:00+08:00",
            session_status_after="authenticated",
        )

        row = self.store.conn.execute(
            "SELECT status, finished_at, session_status_after FROM fetch_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        self.assertEqual(row["status"], "success")
        self.assertEqual(row["finished_at"], "2026-06-18T04:02:00+08:00")
        self.assertEqual(row["session_status_after"], "authenticated")

        self.store.save_account_data(
            AccountData(
                account=Account(account_no="1234567890123"),
                balance=Balance(
                    account_no="1234567890123",
                    observed_at="2026-06-18T04:03:00+08:00",
                    balance_cny=10.0,
                ),
            ),
            run_id,
        )
        balance_row = self.store.conn.execute(
            "SELECT fetch_run_id FROM balances WHERE account_no = ?",
            ("1234567890123",),
        ).fetchone()
        self.assertEqual(balance_row["fetch_run_id"], run_id)

        with self.assertRaises(sqlite3.IntegrityError):
            self.store.save_account_data(
                AccountData(
                    account=Account(account_no="9999999999999"),
                    daily=[DailyReading(account_no="9999999999999", date="2026-06-18", total_usage_kwh=9.9)],
                ),
                999999,
            )

    def test_session_check_and_publisher_state_upsert(self):
        check_id = self.store.record_session_check(
            SessionCheck(
                checked_at="2026-06-18T04:00:00+08:00",
                status="authenticated",
                current_url="https://example.invalid/portal",
                check_method="dom",
                redirected_to_login=False,
                evidence_redacted="ok",
            )
        )
        self.assertGreater(check_id, 0)

        self.store.upsert_publisher_state(
            PublisherState(
                publisher="ha_rest",
                entity_id="sensor.sgcc_balance",
                last_published_at="2026-06-18T04:01:00+08:00",
                last_value="1.0",
                last_success=True,
            )
        )
        self.store.upsert_publisher_state(
            PublisherState(
                publisher="ha_rest",
                entity_id="sensor.sgcc_balance",
                last_published_at="2026-06-18T04:02:00+08:00",
                last_value="2.0",
                last_success=False,
                last_error_redacted="failed",
            )
        )
        row = self.store.conn.execute(
            "SELECT COUNT(*) AS n, last_value, last_success, last_error_redacted FROM publisher_state"
        ).fetchone()
        self.assertEqual(row["n"], 1)
        self.assertEqual(row["last_value"], "2.0")
        self.assertEqual(row["last_success"], 0)
        self.assertEqual(row["last_error_redacted"], "failed")


if __name__ == "__main__":
    unittest.main()
