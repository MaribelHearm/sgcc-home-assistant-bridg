"""Path B scraper: read decrypted SGCC data from live Vue/Vuex state.

The caller owns the Selenium driver.  This module never quits/closes the driver
and assumes the browser is already authenticated.
"""
from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import asdict
from typing import Any, Optional

from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from .const import BALANCE_URL, ELECTRIC_USAGE_URL
from .model import AccountData, mask_account_no
from .parser import merge_account_data, parse_account_data
from .money_diag import log_money_diagnostics, money_diag_enabled
from . import vue_state


class Scraper:
    """Scrape AccountData from an attached, logged-in Selenium driver."""

    def __init__(self, driver, wait_seconds: int = 12, settle_seconds: Optional[float] = None):
        self.driver = driver
        self.wait_seconds = wait_seconds
        self.settle_seconds = self._settle_seconds_from_env() if settle_seconds is None else settle_seconds

    @staticmethod
    def _settle_seconds_from_env() -> float:
        try:
            return max(0.0, float(os.getenv("SCRAPER_SETTLE_SECONDS", "3.0")))
        except (TypeError, ValueError):
            return 3.0

    def fetch_all(self, max_accounts: Optional[int] = None) -> list[AccountData]:
        """Navigate balance/usage views and return one AccountData per account.

        Multi-account handling is deliberately inclusive:

        * scrape the currently selected/default account first;
        * then iterate every visible selector option by index;
        * de-duplicate parsed accounts by account number.

        Some SGCC/Element UI account selectors only list accounts that can be
        switched to, excluding the currently selected account; others include
        the current account but can render duplicate/near-identical display
        text for multiple residential accounts.  Counting de-duplicated option
        text would therefore under-count real accounts.
        """
        self._navigate(BALANCE_URL, "账户余额")
        selector_option_count = len(self._visible_account_options())
        logging.info(f"Path B 账户候选: 当前账户 + {selector_option_count} 个下拉选项。")

        results: list[AccountData] = []
        seen_accounts: set[str] = set()

        current = self._fetch_current_account()
        self._append_unique_result(results, seen_accounts, current)
        if max_accounts is not None and len(results) >= max_accounts:
            return results

        for index in range(selector_option_count):
            data = self._fetch_selected_account(index)
            self._append_unique_result(results, seen_accounts, data)
            if max_accounts is not None and len(results) >= max_accounts:
                break
        return results

    def fetch_one(self) -> AccountData:
        """Convenience wrapper for the current/default account."""
        data = self._fetch_current_account()
        return data if data is not None else AccountData(account=parse_account_data().account)

    def _fetch_current_account(self) -> Optional[AccountData]:
        return self._fetch_account(selection_index=None)

    def _fetch_selected_account(self, index: int) -> Optional[AccountData]:
        return self._fetch_account(selection_index=index)

    def _fetch_account(self, selection_index: Optional[int]) -> Optional[AccountData]:
        partials: list[AccountData] = []

        self._navigate(BALANCE_URL, "账户余额")
        if selection_index is not None and not self._select_account(selection_index):
            logging.warning(f"Path B 无法选择账户下拉第 {selection_index + 1} 项，已跳过该候选。")
            return None
        partials.append(self._parse_current_page("账户余额"))
        target_account_no = partials[-1].account.account_no

        self._navigate(ELECTRIC_USAGE_URL, "电量电费查询")
        if selection_index is not None:
            current_account_no = self._current_account_no()
            if target_account_no and current_account_no == target_account_no:
                logging.info(f"Path B 电量电费页已保持账户: {mask_account_no(target_account_no)}")
            elif not self._select_account(selection_index):
                logging.warning(
                    f"Path B 电量电费页无法再次选择账户下拉第 {selection_index + 1} 项，继续使用当前账户状态。"
                )
        self._click_tab("月度电费")
        partials.append(self._parse_current_page("月度电费"))
        self._click_tab("日用电量")
        self._expand_daily_range_to_30_days()
        partials.append(self._parse_current_page("日用电量"))

        return merge_account_data(*partials)

    def _append_unique_result(
        self,
        results: list[AccountData],
        seen_accounts: set[str],
        data: Optional[AccountData],
    ) -> bool:
        if data is None:
            return False
        identity = self._account_identity(data)
        if identity and identity in seen_accounts:
            logging.info(f"Path B 跳过重复账户候选: {mask_account_no(data.account.account_no)}")
            return False
        if identity:
            seen_accounts.add(identity)
        results.append(data)
        return True

    @staticmethod
    def _account_identity(data: AccountData) -> Optional[str]:
        account_no = data.account.account_no if data and data.account else ""
        return account_no or None

    def _current_account_no(self) -> str:
        try:
            snapshot = self._snapshot()
            data = parse_account_data(store=snapshot.get("store"), components=snapshot.get("components"))
            return data.account.account_no
        except Exception:
            return ""

    def _parse_current_page(self, label: str = "当前页") -> AccountData:
        snapshot = self._snapshot()
        data = parse_account_data(store=snapshot.get("store"), components=snapshot.get("components"))
        logging.info(
            "Path B 当前页解析摘要: "
            f"account={'yes' if data.account.account_no else 'no'}, "
            f"balance={'yes' if data.balance else 'no'}, "
            f"monthly={len(data.monthly)}, daily={len(data.daily)}, "
            f"yearly={'yes' if data.yearly else 'no'}"
        )
        if money_diag_enabled():
            log_money_diagnostics(snapshot, data, label)
        return data

    def _snapshot(self) -> dict[str, Any]:
        store = {}
        try:
            if hasattr(vue_state, "selected_store_snapshot"):
                store = vue_state.selected_store_snapshot(self.driver) or {}
            else:
                store = {"state": vue_state.selected_store_state(self.driver)}
        except Exception:
            store = {}
        try:
            components = vue_state.selected_vue_data(
                self.driver,
                include_money_diag=money_diag_enabled(),
            ) or []
        except Exception:
            components = []
        return {"store": store, "components": components, "url": self.driver.current_url}

    def _navigate(self, url: str, label: str) -> None:
        target_path = url.split("/osgweb", 1)[-1]
        current_url = self.driver.current_url or ""
        previous_signature = self._business_signature(label) if target_path in current_url else None
        logging.info(f"Path B 导航到 {label}: {url}")
        self.driver.execute_script("window.location.href = arguments[0];", url)
        try:
            WebDriverWait(self.driver, self.wait_seconds).until(
                lambda d: target_path in (d.current_url or "")
                or d.execute_script("return document.readyState") in ("interactive", "complete")
            )
        except TimeoutException:
            logging.warning(f"Path B 等待 {label} URL/readyState 超时，继续尝试读取页面状态。")
        self._wait_for_business_ready(label, previous_signature)
        try:
            self.driver.execute_script("window.stop();")
        except Exception:
            pass
        logging.info(f"Path B {label} 页面当前 URL: {self.driver.current_url}")

    def _click_tab(self, tab_text: str) -> bool:
        xpaths = [
            f"//div[contains(@class,'el-tabs__item') and contains(normalize-space(.), '{tab_text}')]",
            f"//*[contains(normalize-space(.), '{tab_text}')]",
        ]
        for xpath in xpaths:
            try:
                element = WebDriverWait(self.driver, 4).until(EC.element_to_be_clickable((By.XPATH, xpath)))
                previous_signature = self._business_signature(tab_text)
                self.driver.execute_script("arguments[0].click();", element)
                self._wait_for_business_ready(tab_text, previous_signature)
                return True
            except Exception:
                continue
        return False

    def _expand_daily_range_to_30_days(self, min_expected_count: int = 20) -> bool:
        """Best-effort switch from the default 7-day daily view to 近30天.

        SGCC defaults the 日用电量 tab to a short range.  Clicking 近30天
        updates Vue component state in-place; failures must not abort the whole
        scrape, because the current 7-day data is still better than no data.
        """
        try:
            before_count = self._current_daily_count()
            if before_count >= min_expected_count:
                logging.info(f"Path B 日用电量已包含 {before_count} 条，无需切换近30天。")
                return True

            if not self._click_daily_range("近30天"):
                logging.warning("Path B 未找到/无法点击日用电量近30天控件，保留当前日用电量数据。")
                return False

            expanded = self._wait_for_daily_range_expansion(before_count, min_expected_count)
            after_count = self._current_daily_count()
            if expanded:
                logging.info(f"Path B 日用电量近30天已生效: {before_count} -> {after_count} 条。")
                return True
            logging.warning(f"Path B 等待日用电量近30天数据超时: {before_count} -> {after_count} 条，保留当前数据。")
            return False
        except Exception as e:
            logging.warning(f"Path B 切换日用电量近30天失败，保留当前数据: {e}")
            return False

    def _click_daily_range(self, range_text: str) -> bool:
        xpaths = [
            f"//label[contains(@class,'el-radio-button') and contains(normalize-space(.), '{range_text}')]",
            f"//label[contains(@class,'el-radio') and contains(normalize-space(.), '{range_text}')]",
            f"//button[contains(normalize-space(.), '{range_text}')]",
            f"//span[contains(normalize-space(.), '{range_text}')]/ancestor::*[self::label or self::button or self::div[contains(@class,'el-radio')]][1]",
            f"//*[contains(normalize-space(.), '{range_text}') and string-length(normalize-space(.)) <= 20]",
        ]
        for xpath in xpaths:
            try:
                elements = self.driver.find_elements(By.XPATH, xpath)
            except Exception:
                continue
            for element in elements:
                try:
                    if not self._is_enabled_visible(element):
                        continue
                    self.driver.execute_script("arguments[0].click();", element)
                    return True
                except Exception:
                    continue
        return False

    def _wait_for_daily_range_expansion(
        self,
        previous_count: int,
        min_expected_count: int = 20,
        timeout_seconds: Optional[float] = None,
        poll_frequency: float = 0.2,
    ) -> bool:
        timeout = self.wait_seconds if timeout_seconds is None else max(0.0, timeout_seconds)
        deadline = time.monotonic() + timeout
        while True:
            count = self._current_daily_count()
            if self._daily_count_looks_expanded(count, previous_count, min_expected_count):
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(max(0.0, poll_frequency))

    @staticmethod
    def _daily_count_looks_expanded(count: int, previous_count: int, min_expected_count: int = 20) -> bool:
        return count >= min_expected_count or (previous_count <= 7 and count > 7)

    def _current_daily_count(self) -> int:
        try:
            snapshot = self._snapshot()
            data = parse_account_data(store=snapshot.get("store"), components=snapshot.get("components"))
            return len(data.daily)
        except Exception:
            return 0

    def _wait_for_business_ready(self, label: str, previous_signature: Optional[str] = None) -> None:
        """Bounded replacement for the old fixed settle sleep.

        The upper bound is exactly ``settle_seconds``: if SGCC business data or
        the relevant tab/container is visible sooner, continue immediately; if
        not, WebDriverWait times out and preserves the old worst-case wait.
        """
        if self.settle_seconds <= 0:
            return
        try:
            WebDriverWait(self.driver, self.settle_seconds, poll_frequency=0.2).until(
                lambda d: self._business_ready_signal(d, label, previous_signature)
            )
        except TimeoutException:
            pass

    def _business_ready_signal(self, driver, label: str, previous_signature: Optional[str]) -> bool:
        signature = self._business_signature(label)
        if not signature:
            return False
        if previous_signature is not None and signature == previous_signature:
            return False
        return True

    def _business_signature(self, label: str) -> Optional[str]:
        snapshot = self._snapshot()
        components = snapshot.get("components") or []
        try:
            parsed: Optional[AccountData] = parse_account_data(store=snapshot.get("store"), components=components)
        except Exception:
            parsed = None

        if label == "账户余额":
            return repr(parsed.balance) if parsed is not None and parsed.balance is not None else None
        if label == "电量电费查询":
            if self._has_visible_text("月度电费") or self._has_visible_text("日用电量"):
                return f"usage-tabs:{self.driver.current_url}"
            return None
        if label == "月度电费":
            if parsed is not None and parsed.monthly:
                return repr(parsed.monthly)
            if self._component_data_matches_label(components, label):
                return self._component_signature(components, label)
            return None
        if label == "日用电量":
            if parsed is not None and parsed.daily:
                return repr(parsed.daily)
            if self._component_data_matches_label(components, label):
                return self._component_signature(components, label)
            return None
        if self._component_data_matches_label(components, label):
            return self._component_signature(components, label)
        return None

    def _component_data_matches_label(self, components: list[dict[str, Any]], label: str) -> bool:
        values_by_key: dict[str, Any] = {}
        for component in components:
            data = component.get("data") if isinstance(component, dict) else None
            if isinstance(data, dict):
                values_by_key.update(data)

        if label == "账户余额":
            return self._has_business_payload(values_by_key, "mixinGetYuEdata", "consInfoobj", "consInfo")
        if label == "电量电费查询":
            return self._has_business_payload(
                values_by_key,
                "powerData",
                "mothData",
                "tableData",
                "billNumberList",
                "BillList",
                "billList",
                "activeName",
            )
        if label == "月度电费":
            return self._has_business_payload(values_by_key, "powerData", "mothData", "tableData", "BillList", "billList")
        if label == "日用电量":
            return self._has_business_payload(values_by_key, "sevenEleList", "sevenEleList_t", "new_sevenEleList", "tableData_t")
        return any(self._has_payload(value) for value in values_by_key.values())

    def _has_business_payload(self, values_by_key: dict[str, Any], *keys: str) -> bool:
        return any(self._has_payload(values_by_key.get(key)) for key in keys)

    def _component_signature(self, components: list[dict[str, Any]], label: str) -> str:
        values_by_key: dict[str, Any] = {}
        for component in components:
            data = component.get("data") if isinstance(component, dict) else None
            if isinstance(data, dict):
                values_by_key.update(data)
        if label == "月度电费":
            keys = ("powerData", "mothData", "tableData", "BillList", "billList")
        elif label == "日用电量":
            keys = ("sevenEleList", "sevenEleList_t", "new_sevenEleList", "tableData_t")
        elif label == "账户余额":
            keys = ("mixinGetYuEdata", "consInfoobj", "consInfo")
        else:
            keys = tuple(sorted(values_by_key))
        return repr({key: values_by_key.get(key) for key in keys if self._has_payload(values_by_key.get(key))})

    def _has_payload(self, value: Any) -> bool:
        if value is None:
            return False
        if isinstance(value, str):
            return bool(value.strip())
        if isinstance(value, (int, float, bool)):
            return True
        if isinstance(value, list):
            return bool(value) and any(self._has_payload(item) for item in value)
        if isinstance(value, dict):
            return bool(value) and any(self._has_payload(item) for item in value.values())
        return True

    def _has_visible_text(self, text: str) -> bool:
        elements = self.driver.find_elements(By.XPATH, f"//*[contains(normalize-space(.), '{text}')]")
        return any(self._is_displayed(element) for element in elements)

    def _is_displayed(self, element) -> bool:
        try:
            return element.is_displayed()
        except Exception:
            return False

    def _visible_account_options(self) -> list[str]:
        """Return visible account selector option texts, without exposing them in logs."""
        if not self._open_account_selector():
            return []
        time.sleep(1)
        options = self.driver.find_elements(
            By.XPATH,
            "//ul[contains(@class,'el-dropdown-menu')]//li"
            " | //div[contains(@class,'el-select-dropdown')]//li",
        )
        texts: list[str] = []
        for option in options:
            try:
                klass = option.get_attribute("class") or ""
                text = (option.text or "").strip()
                if option.is_displayed() and text and "disabled" not in klass and "is-disabled" not in klass:
                    texts.append(text)
            except Exception:
                continue
        self._close_popups()
        return texts

    def _select_account(self, index: int) -> bool:
        if not self._open_account_selector():
            return False
        time.sleep(1)
        options = [
            option
            for option in self.driver.find_elements(
                By.XPATH,
                "//ul[contains(@class,'el-dropdown-menu')]//li"
                " | //div[contains(@class,'el-select-dropdown')]//li",
            )
            if self._is_enabled_visible(option)
        ]
        if index >= len(options):
            self._close_popups()
            return False
        self.driver.execute_script("arguments[0].click();", options[index])
        time.sleep(self.settle_seconds)
        return True

    def _open_account_selector(self) -> bool:
        selectors = [
            (By.XPATH, "//span[contains(normalize-space(.), '切换用户')]"),
            (By.CSS_SELECTOR, ".houseNum .el-select .el-input__inner"),
            (By.CSS_SELECTOR, ".houseNum .el-select .el-input__suffix"),
            (By.CSS_SELECTOR, ".el-dropdown > span"),
            (By.CLASS_NAME, "el-input__suffix"),
        ]
        for by, value in selectors:
            try:
                elements = self.driver.find_elements(by, value)
                for element in elements:
                    if element.is_displayed():
                        self.driver.execute_script("arguments[0].click();", element)
                        return True
            except Exception:
                continue
        return False

    def _is_enabled_visible(self, element) -> bool:
        try:
            klass = element.get_attribute("class") or ""
            return element.is_displayed() and "disabled" not in klass and "is-disabled" not in klass
        except Exception:
            return False

    def _close_popups(self) -> None:
        try:
            self.driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
        except Exception:
            pass


def redact_account_data(data: AccountData) -> dict[str, Any]:
    """Return a log-safe dict for live verification output."""
    raw = asdict(data)
    account_no = data.account.account_no
    masked = mask_account_no(account_no)
    raw["account"]["account_no"] = masked
    raw["account"]["display_name"] = ""
    raw["account"]["address"] = ""
    if raw.get("balance"):
        raw["balance"]["account_no"] = masked
    for key in ("yearly",):
        if raw.get(key):
            raw[key]["account_no"] = masked
    for key in ("monthly", "daily"):
        for row in raw.get(key) or []:
            row["account_no"] = masked
    return raw
