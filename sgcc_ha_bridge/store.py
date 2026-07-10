"""SQLite persistence for the unified SGCC data model.

This module is intentionally independent from the legacy ``db.py`` storage.
It persists the dataclasses defined in ``model.py`` without introducing new
business data structures or third-party dependencies.
"""
from __future__ import annotations

import os
import sqlite3
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from .model import (
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

DEFAULT_DB_PATH = "/data/sgcc.sqlite3"


class Store:
    """SQLite store for AccountData, fetch runs, session checks and publisher state."""

    _FETCH_RUN_COLUMNS = {
        "trigger_type",
        "status",
        "started_at",
        "finished_at",
        "session_status_before",
        "session_status_after",
        "error_type",
        "error_message_redacted",
    }

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = db_path or os.getenv("SGCC_DB_PATH", DEFAULT_DB_PATH)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self._configure_connection()
        self.init_schema()

    def _configure_connection(self) -> None:
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("PRAGMA busy_timeout=5000")

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()

    def init_schema(self) -> None:
        """Create the SQLite schema if it does not exist."""
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS accounts (
                account_no TEXT PRIMARY KEY NOT NULL,
                display_name TEXT NOT NULL DEFAULT '',
                address TEXT NOT NULL DEFAULT '',
                province TEXT NOT NULL DEFAULT '',
                is_active INTEGER NOT NULL DEFAULT 1,
                last_seen_fetch_run_id INTEGER
            );

            CREATE TABLE IF NOT EXISTS fetch_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trigger_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'running',
                started_at TEXT NOT NULL DEFAULT '',
                finished_at TEXT,
                session_status_before TEXT,
                session_status_after TEXT,
                error_type TEXT,
                error_message_redacted TEXT
            );

            CREATE TABLE IF NOT EXISTS balances (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_no TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                balance_cny REAL,
                prepay_balance_cny REAL,
                arrears_cny REAL,
                fetch_run_id INTEGER NOT NULL,
                UNIQUE(account_no, observed_at),
                FOREIGN KEY(account_no) REFERENCES accounts(account_no) ON UPDATE CASCADE ON DELETE CASCADE,
                FOREIGN KEY(fetch_run_id) REFERENCES fetch_runs(id)
            );

            CREATE TABLE IF NOT EXISTS readings_daily (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_no TEXT NOT NULL,
                date TEXT NOT NULL,
                total_usage_kwh REAL,
                valley_usage_kwh REAL,
                flat_usage_kwh REAL,
                peak_usage_kwh REAL,
                tip_usage_kwh REAL,
                fetch_run_id INTEGER NOT NULL,
                UNIQUE(account_no, date),
                FOREIGN KEY(account_no) REFERENCES accounts(account_no) ON UPDATE CASCADE ON DELETE CASCADE,
                FOREIGN KEY(fetch_run_id) REFERENCES fetch_runs(id)
            );

            CREATE TABLE IF NOT EXISTS readings_monthly (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_no TEXT NOT NULL,
                year_month TEXT NOT NULL,
                total_usage_kwh REAL,
                total_charge_cny REAL,
                begin_date TEXT,
                end_date TEXT,
                fetch_run_id INTEGER NOT NULL,
                UNIQUE(account_no, year_month),
                FOREIGN KEY(account_no) REFERENCES accounts(account_no) ON UPDATE CASCADE ON DELETE CASCADE,
                FOREIGN KEY(fetch_run_id) REFERENCES fetch_runs(id)
            );

            CREATE TABLE IF NOT EXISTS readings_yearly (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_no TEXT NOT NULL,
                year TEXT NOT NULL,
                total_usage_kwh REAL,
                total_charge_cny REAL,
                fetch_run_id INTEGER NOT NULL,
                UNIQUE(account_no, year),
                FOREIGN KEY(account_no) REFERENCES accounts(account_no) ON UPDATE CASCADE ON DELETE CASCADE,
                FOREIGN KEY(fetch_run_id) REFERENCES fetch_runs(id)
            );

            CREATE TABLE IF NOT EXISTS session_checks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                checked_at TEXT NOT NULL,
                status TEXT NOT NULL,
                current_url TEXT NOT NULL DEFAULT '',
                check_method TEXT NOT NULL DEFAULT '',
                redirected_to_login INTEGER NOT NULL DEFAULT 0,
                evidence_redacted TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS publisher_state (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                publisher TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                last_published_at TEXT,
                last_value TEXT,
                last_success INTEGER NOT NULL DEFAULT 0,
                last_error_redacted TEXT,
                UNIQUE(publisher, entity_id)
            );
            """
        )
        self._ensure_account_lifecycle_columns()
        self.conn.commit()

    def _ensure_account_lifecycle_columns(self) -> None:
        """Apply additive account lifecycle migration for existing databases."""
        columns = {
            row["name"]
            for row in self.conn.execute("PRAGMA table_info(accounts)").fetchall()
        }
        if "is_active" not in columns:
            self.conn.execute(
                "ALTER TABLE accounts ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1"
            )
        if "last_seen_fetch_run_id" not in columns:
            self.conn.execute(
                "ALTER TABLE accounts ADD COLUMN last_seen_fetch_run_id INTEGER"
            )

    def upsert_account(self, account: Account) -> None:
        self.conn.execute(
            """
            INSERT INTO accounts (
                account_no, display_name, address, province, is_active
            )
            VALUES (
                :account_no, :display_name, :address, :province, 1
            )
            ON CONFLICT(account_no) DO UPDATE SET
                display_name = excluded.display_name,
                address = excluded.address,
                province = excluded.province,
                is_active = 1
            """,
            asdict(account),
        )
        self.conn.commit()

    def start_run(self, run: FetchRun) -> int:
        data = asdict(run)
        cur = self.conn.execute(
            """
            INSERT INTO fetch_runs (
                trigger_type, status, started_at, finished_at,
                session_status_before, session_status_after,
                error_type, error_message_redacted
            ) VALUES (
                :trigger_type, :status, :started_at, :finished_at,
                :session_status_before, :session_status_after,
                :error_type, :error_message_redacted
            )
            """,
            data,
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def finish_run(self, run_id: int, status: str, **fields: Any) -> None:
        updates = {"status": status, **fields}
        if "finished_at" not in updates:
            updates["finished_at"] = datetime.now(timezone.utc).isoformat()
        unknown = set(updates) - self._FETCH_RUN_COLUMNS
        if unknown:
            raise ValueError(f"Unknown fetch_runs fields: {', '.join(sorted(unknown))}")

        assignments = ", ".join(f"{name} = :{name}" for name in updates)
        params = {**updates, "id": run_id}
        cur = self.conn.execute(
            f"UPDATE fetch_runs SET {assignments} WHERE id = :id",
            params,
        )
        if cur.rowcount != 1:
            self.conn.rollback()
            raise ValueError(f"fetch_run not found: {run_id}")
        self.conn.commit()

    def record_session_check(self, check: SessionCheck) -> int:
        data = asdict(check)
        data["redirected_to_login"] = 1 if check.redirected_to_login else 0
        cur = self.conn.execute(
            """
            INSERT INTO session_checks (
                checked_at, status, current_url, check_method,
                redirected_to_login, evidence_redacted
            ) VALUES (
                :checked_at, :status, :current_url, :check_method,
                :redirected_to_login, :evidence_redacted
            )
            """,
            data,
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def save_account_data(self, account_data: AccountData, fetch_run_id: int) -> None:
        """Persist one AccountData unit, replacing rows with the same natural key."""
        with self.conn:
            self._upsert_account_no_commit(account_data.account, fetch_run_id)
            if account_data.balance is not None:
                self._upsert_balance_no_commit(account_data.balance, fetch_run_id)
            if account_data.yearly is not None:
                self._upsert_yearly_no_commit(account_data.yearly, fetch_run_id)
            for item in account_data.monthly:
                self._upsert_monthly_no_commit(item, fetch_run_id)
            for item in account_data.daily:
                self._upsert_daily_no_commit(item, fetch_run_id)

    def reconcile_active_accounts(
        self,
        account_nos: Iterable[str],
        fetch_run_id: int,
    ) -> list[str]:
        """Mark accounts missing from one authoritative successful fetch inactive.

        Historical readings remain available for diagnostics and MQTT cleanup.
        An empty set is rejected so a partial/failed scrape cannot deactivate
        every cached account.
        """
        authoritative = sorted({
            str(value).strip()
            for value in account_nos
            if value is not None and str(value).strip()
        })
        if not authoritative:
            raise ValueError("authoritative account set must not be empty")

        placeholders = ", ".join("?" for _ in authoritative)
        with self.conn:
            rows = self.conn.execute(
                f"""
                SELECT account_no
                FROM accounts
                WHERE is_active = 1
                  AND account_no NOT IN ({placeholders})
                ORDER BY account_no
                """,
                authoritative,
            ).fetchall()
            deactivated = [row["account_no"] for row in rows]
            self.conn.execute(
                f"""
                UPDATE accounts
                SET is_active = 0
                WHERE is_active = 1
                  AND account_no NOT IN ({placeholders})
                """,
                authoritative,
            )
            self.conn.execute(
                f"""
                UPDATE accounts
                SET is_active = 1,
                    last_seen_fetch_run_id = ?
                WHERE account_no IN ({placeholders})
                """,
                [fetch_run_id, *authoritative],
            )
        return deactivated

    def list_account_nos(self, active_only: Optional[bool] = None) -> list[str]:
        sql = "SELECT account_no FROM accounts"
        params: list[Any] = []
        if active_only is True:
            sql += " WHERE is_active = 1"
        elif active_only is False:
            sql += " WHERE is_active = 0"
        sql += " ORDER BY account_no"
        return [row["account_no"] for row in self.conn.execute(sql, params).fetchall()]

    def upsert_publisher_state(self, state: PublisherState) -> None:
        data = asdict(state)
        data["last_success"] = 1 if state.last_success else 0
        self.conn.execute(
            """
            INSERT INTO publisher_state (
                publisher, entity_id, last_published_at,
                last_value, last_success, last_error_redacted
            ) VALUES (
                :publisher, :entity_id, :last_published_at,
                :last_value, :last_success, :last_error_redacted
            )
            ON CONFLICT(publisher, entity_id) DO UPDATE SET
                last_published_at = excluded.last_published_at,
                last_value = excluded.last_value,
                last_success = excluded.last_success,
                last_error_redacted = excluded.last_error_redacted
            """,
            data,
        )
        self.conn.commit()

    def get_account(self, account_no: str) -> Optional[Account]:
        row = self.conn.execute(
            "SELECT account_no, display_name, address, province FROM accounts WHERE account_no = ?",
            (account_no,),
        ).fetchone()
        return Account(**dict(row)) if row else None

    def get_account_data(
        self,
        account_no: str,
        daily_limit: int = 31,
        monthly_limit: int = 24,
    ) -> Optional[AccountData]:
        account = self.get_account(account_no)
        if account is None:
            return None
        return AccountData(
            account=account,
            balance=self.get_latest_balance(account_no),
            yearly=(self.get_yearly(account_no, 1) or [None])[0],
            monthly=self.get_monthly(account_no, monthly_limit),
            daily=self.get_daily(account_no, daily_limit),
        )

    def get_latest_balance(self, account_no: str) -> Optional[Balance]:
        row = self.conn.execute(
            """
            SELECT account_no, observed_at, balance_cny, prepay_balance_cny, arrears_cny
            FROM balances
            WHERE account_no = ?
            ORDER BY observed_at DESC, id DESC
            LIMIT 1
            """,
            (account_no,),
        ).fetchone()
        return Balance(**dict(row)) if row else None

    def get_daily(self, account_no: str, limit: int = 31) -> list[DailyReading]:
        rows = self.conn.execute(
            """
            SELECT account_no, date, total_usage_kwh, valley_usage_kwh,
                   flat_usage_kwh, peak_usage_kwh, tip_usage_kwh
            FROM readings_daily
            WHERE account_no = ?
            ORDER BY date DESC
            LIMIT ?
            """,
            (account_no, limit),
        ).fetchall()
        return [DailyReading(**dict(row)) for row in rows]

    def get_monthly(self, account_no: str, limit: int = 24) -> list[MonthlyReading]:
        rows = self.conn.execute(
            """
            SELECT account_no, year_month, total_usage_kwh, total_charge_cny, begin_date, end_date
            FROM readings_monthly
            WHERE account_no = ?
            ORDER BY year_month DESC
            LIMIT ?
            """,
            (account_no, limit),
        ).fetchall()
        return [MonthlyReading(**dict(row)) for row in rows]

    def get_yearly(self, account_no: str, limit: int = 10) -> list[YearlyReading]:
        rows = self.conn.execute(
            """
            SELECT account_no, year, total_usage_kwh, total_charge_cny
            FROM readings_yearly
            WHERE account_no = ?
            ORDER BY year DESC
            LIMIT ?
            """,
            (account_no, limit),
        ).fetchall()
        return [YearlyReading(**dict(row)) for row in rows]

    def _upsert_account_no_commit(self, account: Account, fetch_run_id: int) -> None:
        data = {**asdict(account), "fetch_run_id": fetch_run_id}
        self.conn.execute(
            """
            INSERT INTO accounts (
                account_no, display_name, address, province,
                is_active, last_seen_fetch_run_id
            )
            VALUES (
                :account_no, :display_name, :address, :province,
                1, :fetch_run_id
            )
            ON CONFLICT(account_no) DO UPDATE SET
                display_name = excluded.display_name,
                address = excluded.address,
                province = excluded.province,
                is_active = 1,
                last_seen_fetch_run_id = excluded.last_seen_fetch_run_id
            """,
            data,
        )

    def _upsert_balance_no_commit(self, balance: Balance, fetch_run_id: int) -> None:
        data = {**asdict(balance), "fetch_run_id": fetch_run_id}
        self.conn.execute(
            """
            INSERT INTO balances (
                account_no, observed_at, balance_cny,
                prepay_balance_cny, arrears_cny, fetch_run_id
            ) VALUES (
                :account_no, :observed_at, :balance_cny,
                :prepay_balance_cny, :arrears_cny, :fetch_run_id
            )
            ON CONFLICT(account_no, observed_at) DO UPDATE SET
                balance_cny = excluded.balance_cny,
                prepay_balance_cny = excluded.prepay_balance_cny,
                arrears_cny = excluded.arrears_cny,
                fetch_run_id = excluded.fetch_run_id
            """,
            data,
        )

    def _upsert_daily_no_commit(self, reading: DailyReading, fetch_run_id: int) -> None:
        data = {**asdict(reading), "fetch_run_id": fetch_run_id}
        self.conn.execute(
            """
            INSERT INTO readings_daily (
                account_no, date, total_usage_kwh, valley_usage_kwh,
                flat_usage_kwh, peak_usage_kwh, tip_usage_kwh, fetch_run_id
            ) VALUES (
                :account_no, :date, :total_usage_kwh, :valley_usage_kwh,
                :flat_usage_kwh, :peak_usage_kwh, :tip_usage_kwh, :fetch_run_id
            )
            ON CONFLICT(account_no, date) DO UPDATE SET
                total_usage_kwh = excluded.total_usage_kwh,
                valley_usage_kwh = excluded.valley_usage_kwh,
                flat_usage_kwh = excluded.flat_usage_kwh,
                peak_usage_kwh = excluded.peak_usage_kwh,
                tip_usage_kwh = excluded.tip_usage_kwh,
                fetch_run_id = excluded.fetch_run_id
            """,
            data,
        )

    def _upsert_monthly_no_commit(self, reading: MonthlyReading, fetch_run_id: int) -> None:
        data = {**asdict(reading), "fetch_run_id": fetch_run_id}
        self.conn.execute(
            """
            INSERT INTO readings_monthly (
                account_no, year_month, total_usage_kwh, total_charge_cny,
                begin_date, end_date, fetch_run_id
            ) VALUES (
                :account_no, :year_month, :total_usage_kwh, :total_charge_cny,
                :begin_date, :end_date, :fetch_run_id
            )
            ON CONFLICT(account_no, year_month) DO UPDATE SET
                total_usage_kwh = excluded.total_usage_kwh,
                total_charge_cny = excluded.total_charge_cny,
                begin_date = excluded.begin_date,
                end_date = excluded.end_date,
                fetch_run_id = excluded.fetch_run_id
            """,
            data,
        )

    def _upsert_yearly_no_commit(self, reading: YearlyReading, fetch_run_id: int) -> None:
        data = {**asdict(reading), "fetch_run_id": fetch_run_id}
        self.conn.execute(
            """
            INSERT INTO readings_yearly (
                account_no, year, total_usage_kwh, total_charge_cny, fetch_run_id
            ) VALUES (
                :account_no, :year, :total_usage_kwh, :total_charge_cny, :fetch_run_id
            )
            ON CONFLICT(account_no, year) DO UPDATE SET
                total_usage_kwh = excluded.total_usage_kwh,
                total_charge_cny = excluded.total_charge_cny,
                fetch_run_id = excluded.fetch_run_id
            """,
            data,
        )
