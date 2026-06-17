"""Path B scraper: read decrypted SGCC data from live Vue/Vuex state.

The caller owns the Selenium driver.  This module never quits/closes the driver
and assumes the browser is already authenticated.
"""
from __future__ import annotations

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

from const import BALANCE_URL, ELECTRIC_USAGE_URL
from model import AccountData, mask_account_no
from parser import merge_account_data, parse_account_data
import vue_state


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

        Multi-account handling is index-based: discover visible account choices,
        then select the same index on each business view.  For single-account
        sessions it performs one bounded pass without opening selectors again.
        """
        self._navigate(BALANCE_URL, "账户余额")
        account_count = max(1, len(self._visible_account_options()))
        if max_accounts is not None:
            account_count = min(account_count, max_accounts)

        results: list[AccountData] = []
        for index in range(account_count):
            partials: list[AccountData] = []

            self._navigate(BALANCE_URL, "账户余额")
            if account_count > 1:
                self._select_account(index)
            partials.append(self._parse_current_page())

            self._navigate(ELECTRIC_USAGE_URL, "电量电费查询")
            if account_count > 1:
                self._select_account(index)
            self._click_tab("月度电费")
            partials.append(self._parse_current_page())
            self._click_tab("日用电量")
            partials.append(self._parse_current_page())

            data = merge_account_data(*partials)
            results.append(data)
        return results

    def fetch_one(self) -> AccountData:
        """Convenience wrapper for the current/default account."""
        items = self.fetch_all(max_accounts=1)
        return items[0] if items else AccountData(account=parse_account_data().account)

    def _parse_current_page(self) -> AccountData:
        snapshot = self._snapshot()
        return parse_account_data(store=snapshot.get("store"), components=snapshot.get("components"))

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
            components = vue_state.selected_vue_data(self.driver) or []
        except Exception:
            components = []
        return {"store": store, "components": components, "url": self.driver.current_url}

    def _navigate(self, url: str, label: str) -> None:
        previous_signature = self._business_signature(label)
        self.driver.execute_script("window.location.href = arguments[0];", url)
        target_path = url.split("/osgweb", 1)[-1]
        try:
            WebDriverWait(self.driver, self.wait_seconds).until(
                lambda d: target_path in (d.current_url or "")
                or d.execute_script("return document.readyState") in ("interactive", "complete")
            )
        except TimeoutException:
            pass
        self._wait_for_business_ready(label, previous_signature)
        try:
            self.driver.execute_script("window.stop();")
        except Exception:
            pass

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
        # De-duplicate while preserving order.
        result: list[str] = []
        for text in texts:
            if text not in result:
                result.append(text)
        return result

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
