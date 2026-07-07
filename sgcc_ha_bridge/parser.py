"""Pure parsers for SGCC Vue/Vuex snapshots.

The scraper feeds already decrypted Vuex/component dictionaries into this module.
This module deliberately does not import selenium or touch the browser.
"""
from __future__ import annotations

import re
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from .model import Account, AccountData, Balance, DailyReading, MonthlyReading, YearlyReading


_ACCOUNT_RE = re.compile(r"(?<!\d)(\d{13})(?!\d)")
_MASKED_ACCOUNT_RE = re.compile(r"\*+(\d{4})$")

_BALANCE_KEYS = (
    # Confirmed structured current-balance fields. Keep this list small: new
    # aliases should come from SGCC_MONEY_DIAG evidence, not guesses.
    "accountBalance",
)
_LEGACY_BALANCE_ALIAS_KEYS = (
    # Quarantined compatibility aliases from older releases.  They are only
    # accepted from the same dict as account/time context, never by merging the
    # whole Vue tree.  This keeps plausible old guesses working without making
    # every money-like field a first-class parser contract.
    "accountBal",
    "accountBalanceAmt",
    "acctBal",
    "acctBalance",
    "acctBalanceAmt",
    "balanceAmt",
    "availableBalance",
    "availableBal",
    "currentBalance",
    "curBalance",
    "remainBalance",
    "remainingBalance",
    "surplusBalance",
    "surplusAmt",
    "userBalance",
    "账户余额",
    "电费余额",
    "当前余额",
    "账户结余",
    "结余金额",
)
_PREPAY_BALANCE_KEYS = (
    "prepayBal",
    "prepayBalance",
)
_LEGACY_PREPAY_BALANCE_ALIAS_KEYS = (
    "prepay_balance",
    "prepayAmt",
    "prepaidBalance",
    "prepaidBal",
    "prepaidAmt",
    "prepaymentBalance",
    "advanceBalance",
    "advanceAmt",
    "预付费余额",
    "预存余额",
    "预存电费",
)
_ARREARS_KEYS = (
    "historyOwe",
)
_LEGACY_ARREARS_ALIAS_KEYS = (
    "arrears",
    "amountDue",
    "oweAmt",
    "oweAmount",
    "oweFee",
    "oweBalance",
    "payableAmt",
    "needPayAmt",
    "totalOwe",
    "欠费",
    "欠费金额",
    "应交金额",
    "待缴金额",
)
_BALANCE_TIME_KEYS = ("amtTime", "queryTime")
_LABEL_KEYS = ("label",)
_VALUE_KEYS = ("value",)
_ACCOUNT_CONTEXT_KEYS = ("consNo", "consNo_dst", "accountNo", "acctNo", "user_id", "userId", "selectValue")
_BALANCE_CONTEXT_KEYS = _ACCOUNT_CONTEXT_KEYS + _BALANCE_TIME_KEYS + ("elecAddr", "elecAddr_dst", "address")

_EXPLICIT_ACCOUNT_BALANCE_LABELS = ("账户余额",)
_EXPLICIT_PREPAY_BALANCE_LABELS = ("预付费余额",)
_EXPLICIT_ARREARS_LABELS = ("应交金额",)
_HISTORICAL_BALANCE_LABEL_TERMS = (
    "上月",
    "上期",
    "上次",
    "期初",
    "上年",
    "去年",
    "previous",
    "prev",
    "last",
)

_DIRECT_AMOUNT_KEYS = _BALANCE_KEYS + _PREPAY_BALANCE_KEYS + _ARREARS_KEYS


def parse_account_data(
    store: Optional[dict[str, Any]] = None,
    components: Optional[list[dict[str, Any]] | dict[str, Any]] = None,
    observed_at: Optional[str] = None,
) -> AccountData:
    """Normalize Vuex/component snapshots into the shared AccountData model.

    ``store`` may be either raw ``$store.state`` or a snapshot dict containing
    ``state``/``getters``/``snapshots``.  ``components`` accepts the shape
    returned by :func:`vue_state.selected_vue_data` or raw component ``$data``.
    Store candidates are considered before component candidates; component data
    is a fallback for routes where SGCC keeps business payloads in local data.
    """
    observed_at = observed_at or _now_iso()
    values = list(_iter_store_values(store)) + list(_iter_component_values(components))

    account_obj = _pick_account_obj(values)
    account_no = _pick_account_no(values, account_obj)
    account = Account(
        account_no=account_no,
        display_name=_pick_first_text(account_obj, "newConsName_dst", "consName_dst", "custName", "consName"),
        address=_pick_first_text(account_obj, "elecAddr_dst", "elecAddr", "addr"),
        province=_pick_first_text(account_obj, "proCode", "province", "provinceCode"),
    )

    balance_obj = _pick_balance_obj(values)
    balance = _parse_balance(balance_obj, account_no, observed_at) if balance_obj else None

    power_obj = _pick_power_obj(values)
    yearly = _parse_yearly(power_obj, account_no) if power_obj else None
    monthly = _parse_monthly(values, power_obj, account_no)
    daily = _parse_daily(values, account_no)

    # Bill detail can fill a month when powerData/tableData is absent.
    bill_month = _parse_bill_month(values, account_no)
    if bill_month and all(row.year_month != bill_month.year_month for row in monthly):
        monthly.append(bill_month)
    if not yearly:
        bill_yearly = _parse_bill_yearly(values, account_no)
        if bill_yearly:
            yearly = bill_yearly

    return AccountData(account=account, balance=balance, yearly=yearly, monthly=monthly, daily=daily)


def merge_account_data(*items: AccountData) -> AccountData:
    """Merge partial AccountData objects for the same account, preferring later non-empty data."""
    if not items:
        return AccountData(account=Account(account_no=""))
    result = items[0]
    for item in items[1:]:
        account = result.account
        if item.account.account_no and (not account.account_no or "*" in account.account_no):
            account = replace(account, account_no=item.account.account_no)
        if item.account.display_name and not account.display_name:
            account = replace(account, display_name=item.account.display_name)
        if item.account.address and not account.address:
            account = replace(account, address=item.account.address)
        if item.account.province and not account.province:
            account = replace(account, province=item.account.province)

        balance = item.balance or result.balance
        yearly = item.yearly or result.yearly
        monthly = _merge_by_key(result.monthly, item.monthly, lambda x: x.year_month)
        daily = _merge_by_key(result.daily, item.daily, lambda x: x.date)
        if account.account_no:
            if balance and (not balance.account_no or "*" in balance.account_no):
                balance = replace(balance, account_no=account.account_no)
            if yearly and (not yearly.account_no or "*" in yearly.account_no):
                yearly = replace(yearly, account_no=account.account_no)
            monthly = [
                replace(row, account_no=account.account_no)
                if not row.account_no or "*" in row.account_no else row
                for row in monthly
            ]
            daily = [
                replace(row, account_no=account.account_no)
                if not row.account_no or "*" in row.account_no else row
                for row in daily
            ]
        result = AccountData(account=account, balance=balance, yearly=yearly, monthly=monthly, daily=daily)
    return result


def _iter_store_values(store: Any) -> Iterable[Any]:
    if not store:
        return
    # Explicit snapshot ordering: state first, getters second, then nested snapshots.
    if isinstance(store, dict):
        if isinstance(store.get("state"), dict):
            yield from _walk_values(store["state"])
        if isinstance(store.get("getters"), dict):
            yield from _walk_values(store["getters"])
        for snap in store.get("snapshots") or []:
            yield from _iter_store_values(snap)
        if "state" not in store and "getters" not in store and "snapshots" not in store:
            yield from _walk_values(store)
    else:
        yield from _walk_values(store)


def _iter_component_values(components: Any) -> Iterable[Any]:
    if not components:
        return
    if isinstance(components, dict):
        if "data" in components and isinstance(components["data"], dict):
            yield from _walk_values(components["data"])
        else:
            yield from _walk_values(components)
        return
    if isinstance(components, list):
        for component in components:
            if isinstance(component, dict) and isinstance(component.get("data"), dict):
                yield from _walk_values(component["data"])
            else:
                yield from _walk_values(component)


def _walk_values(value: Any) -> Iterable[Any]:
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from _walk_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_values(child)


def _pick_account_obj(values: list[Any]) -> dict[str, Any]:
    for value in values:
        if isinstance(value, dict) and any(k in value for k in ("consNo", "consNo_dst", "elecAddr", "elecAddr_dst", "custName")):
            # Prefer objects that actually describe a power account, not request params.
            if any(k in value for k in ("elecAddr_dst", "elecAddr", "consName_dst", "newConsName_dst", "proCode")):
                return value
    for value in values:
        if isinstance(value, dict) and any(k in value for k in ("consNo", "consNo_dst")):
            return value
    return {}


def _pick_account_no(values: list[Any], account_obj: dict[str, Any]) -> str:
    for obj in [account_obj] + [v for v in values if isinstance(v, dict)]:
        for key in ("consNo", "user_id", "userId", "selectValue", "consNo_dst", "accountNo", "acctNo"):
            account_no = _extract_account_no(obj.get(key) if isinstance(obj, dict) else None)
            if account_no and "*" not in account_no:
                return account_no
    # Last resort: preserve masked suffix if no full account number exists.
    for value in values:
        masked = _extract_masked_account(value)
        if masked:
            return masked
    return ""


def _pick_balance_obj(values: list[Any]) -> dict[str, Any]:
    """Pick one well-scoped balance source instead of merging the whole tree.

    Compatibility rules here must be backed by real SGCC_MONEY_DIAG evidence.
    Diagnostics can be broad; the parser stays narrow and explainable.
    """
    candidates: list[tuple[int, int, dict[str, Any]]] = []
    for index, value in enumerate(values):
        if isinstance(value, list):
            label_group = _balance_values_from_label_rows(value)
            if _has_any_float(label_group, _DIRECT_AMOUNT_KEYS):
                candidates.append((_label_balance_candidate_priority(label_group), index, label_group))
            continue
        if not isinstance(value, dict):
            continue

        normalized = _normalize_balance_obj(value)
        priority = _balance_candidate_priority(value)
        if priority > 0:
            candidates.append((priority, index, normalized))
            continue

    if not candidates:
        return {}
    # Highest priority wins; keep original traversal order for equal priority.
    return min(candidates, key=lambda item: (-item[0], item[1]))[2]


def _pick_power_obj(values: list[Any]) -> dict[str, Any]:
    for value in values:
        if isinstance(value, dict) and isinstance(value.get("dataInfo"), dict) and isinstance(value.get("mothEleList"), list):
            return value
    return {}


def _parse_balance(raw: dict[str, Any], account_no: str, observed_at: str) -> Balance:
    raw = _normalize_balance_obj(raw)
    account_no = account_no or _extract_account_no(raw.get("consNo")) or _extract_account_no(raw.get("consNo_dst"))
    return Balance(
        account_no=account_no,
        observed_at=str(_pick_first_value(raw, *_BALANCE_TIME_KEYS) or observed_at),
        balance_cny=_first_float(raw, *_BALANCE_KEYS),
        prepay_balance_cny=_first_float(raw, *_PREPAY_BALANCE_KEYS),
        arrears_cny=_first_float(raw, *_ARREARS_KEYS),
    )


def _normalize_balance_obj(raw: dict[str, Any]) -> dict[str, Any]:
    """Return direct balance-like data plus confirmed structured mappings."""
    normalized = dict(raw)
    for key, value in _balance_values_from_known_structures(raw).items():
        normalized.setdefault(key, value)
    for key, value in _balance_values_from_legacy_aliases(raw).items():
        normalized.setdefault(key, value)
    return normalized


def _balance_candidate_priority(raw: dict[str, Any]) -> int:
    if _balance_values_from_known_structures(raw):
        return 100
    if _is_confirmed_account_balance_source(raw):
        return 90
    if _is_legacy_balance_alias_source(raw):
        return 80
    return 0


def _is_confirmed_account_balance_source(raw: dict[str, Any]) -> bool:
    if _first_float(raw, *_BALANCE_KEYS) is None:
        return False
    return _has_balance_source_context(raw)


def _is_legacy_balance_alias_source(raw: dict[str, Any]) -> bool:
    if _first_float(raw, *_LEGACY_BALANCE_ALIAS_KEYS) is None:
        return False
    return _has_legacy_balance_source_context(raw)


def _label_balance_candidate_priority(candidate: dict[str, Any]) -> int:
    if _first_float(candidate, *_BALANCE_KEYS) is not None:
        return 85
    if _first_float(candidate, *_PREPAY_BALANCE_KEYS) is not None:
        return 75
    if _first_float(candidate, *_ARREARS_KEYS) is not None:
        return 65
    return 0


def _balance_values_from_known_structures(raw: dict[str, Any]) -> dict[str, Any]:
    """Map confirmed SGCC structured fields to the normalized balance shape."""
    if _is_confirmed_sum_money_balance(raw):
        return {"accountBalance": raw.get("sumMoney")}
    return {}


def _is_confirmed_sum_money_balance(raw: dict[str, Any]) -> bool:
    return (
        _safe_float(raw.get("sumMoney")) is not None
        and any(key in raw for key in ("prepayBal", "historyOwe", "estiAmt"))
    )


def _balance_values_from_legacy_aliases(raw: dict[str, Any]) -> dict[str, Any]:
    """Map old guessed aliases only when the source still looks like a balance payload."""
    if not _has_legacy_balance_source_context(raw):
        return {}

    has_current_balance = (
        _first_float(raw, *_BALANCE_KEYS) is not None
        or _is_confirmed_sum_money_balance(raw)
        or _first_float(raw, *_LEGACY_BALANCE_ALIAS_KEYS) is not None
    )
    if not has_current_balance:
        return {}

    mapped: dict[str, Any] = {}
    balance_value = _pick_first_value(raw, *_LEGACY_BALANCE_ALIAS_KEYS)
    if _safe_float(balance_value) is not None:
        mapped["accountBalance"] = balance_value

    prepay_value = _pick_first_value(raw, *_LEGACY_PREPAY_BALANCE_ALIAS_KEYS)
    if _safe_float(prepay_value) is not None:
        mapped["prepayBalance"] = prepay_value

    arrears_value = _pick_first_value(raw, *_LEGACY_ARREARS_ALIAS_KEYS)
    if _safe_float(arrears_value) is not None:
        mapped["historyOwe"] = arrears_value

    return mapped


def _has_balance_source_context(raw: dict[str, Any]) -> bool:
    return any(key in raw for key in _BALANCE_CONTEXT_KEYS)


def _has_legacy_balance_source_context(raw: dict[str, Any]) -> bool:
    # Legacy aliases are less certain than accountBalance/sumMoney, so require
    # account or timestamp context from the same dict.  Address-only context is
    # kept for confirmed accountBalance but not for guessed aliases.
    return any(key in raw for key in _ACCOUNT_CONTEXT_KEYS + _BALANCE_TIME_KEYS)


def _balance_values_from_label_rows(rows: list[Any]) -> dict[str, Any]:
    """Narrow fallback for a single label/value list container."""
    selected: dict[str, Any] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        for key, value in _balance_values_from_label_row(row).items():
            selected.setdefault(key, value)
    # Label rows are only a narrow fallback for one explicit current-balance
    # list. Prepay/arrears labels may supplement that list, not create one.
    if _first_float(selected, *_BALANCE_KEYS) is None:
        return {}
    return selected


def _balance_values_from_label_row(raw: dict[str, Any]) -> dict[str, Any]:
    """Parse only explicit, debug-confirmed balance labels.

    Do not treat generic "余额/结余" as current balance. Historical labels such
    as 上月余额/期初结余 are intentionally ignored.
    """
    label = _pick_first_text(raw, *_LABEL_KEYS)
    if not label or _is_historical_balance_label(label):
        return {}
    value = _pick_first_value(raw, *_VALUE_KEYS)
    if _safe_float(value) is None:
        return {}

    if _label_matches(label, _EXPLICIT_PREPAY_BALANCE_LABELS):
        return {"prepayBalance": value}
    if _label_matches(label, _EXPLICIT_ARREARS_LABELS):
        return {"historyOwe": value}
    if _label_matches(label, _EXPLICIT_ACCOUNT_BALANCE_LABELS):
        return {"accountBalance": value}
    return {}


def _is_historical_balance_label(label: str) -> bool:
    folded = str(label).casefold()
    return any(term.casefold() in folded for term in _HISTORICAL_BALANCE_LABEL_TERMS)


def _label_matches(label: str, terms: tuple[str, ...]) -> bool:
    normalized = _normalize_label(label)
    return any(normalized == _normalize_label(term) for term in terms)


def _normalize_label(label: str) -> str:
    return re.sub(r"\s+", "", str(label)).rstrip(":：")


def _parse_yearly(power_obj: dict[str, Any], account_no: str) -> Optional[YearlyReading]:
    info = power_obj.get("dataInfo") or {}
    if not isinstance(info, dict):
        return None
    year = str(info.get("year") or "").strip()
    usage = _safe_float(info.get("totalEleNum"))
    charge = _safe_float(info.get("totalEleCost"))
    if not (year or usage is not None or charge is not None):
        return None
    return YearlyReading(account_no=account_no, year=year, total_usage_kwh=usage, total_charge_cny=charge)


def _parse_monthly(values: list[Any], power_obj: dict[str, Any], account_no: str) -> list[MonthlyReading]:
    rows: list[Any] = []
    if isinstance(power_obj.get("mothEleList"), list):
        rows.extend(power_obj["mothEleList"])
    for value in values:
        if isinstance(value, list) and value and all(isinstance(x, dict) for x in value[:3]):
            if any("monthEleNum" in x or "monthEleCost" in x for x in value if isinstance(x, dict)):
                rows.extend(value)

    result: list[MonthlyReading] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        ym = _normalize_ym(row.get("month") or row.get("ym") or row.get("billMonth"))
        usage = _safe_float(row.get("monthEleNum") or row.get("monthPq"))
        charge = _safe_float(row.get("monthEleCost") or row.get("monthAmt"))
        if not ym or (usage is None and charge is None):
            continue
        if ym in seen:
            continue
        seen.add(ym)
        result.append(MonthlyReading(
            account_no=account_no,
            year_month=ym,
            total_usage_kwh=usage,
            total_charge_cny=charge,
            begin_date=_date_only(row.get("begDate") or row.get("beginDate")),
            end_date=_date_only(row.get("endDate")),
        ))
    result.sort(key=lambda x: x.year_month)
    return result


def _parse_daily(values: list[Any], account_no: str) -> list[DailyReading]:
    rows: list[Any] = []
    for value in values:
        if isinstance(value, list) and value and all(isinstance(x, dict) for x in value[:3]):
            if any("dayElePq" in x or "thisVPq" in x for x in value if isinstance(x, dict)):
                rows.extend(value)

    result: list[DailyReading] = []
    seen: set[str] = set()
    current_year = str(datetime.now().year)
    for row in rows:
        if not isinstance(row, dict):
            continue
        date = _normalize_date(row.get("day"), current_year=current_year)
        usage = _safe_float(row.get("dayElePq"))
        valley = _safe_float(row.get("thisVPq"))
        flat = _safe_float(row.get("thisNPq"))
        peak = _safe_float(row.get("thisPPq"))
        tip = _safe_float(row.get("thisTPq"))
        if not date or (usage is None and valley is None and flat is None and peak is None and tip is None):
            continue
        if date in seen:
            continue
        seen.add(date)
        result.append(DailyReading(
            account_no=account_no,
            date=date,
            total_usage_kwh=usage,
            valley_usage_kwh=valley,
            flat_usage_kwh=flat,
            peak_usage_kwh=peak,
            tip_usage_kwh=tip,
        ))
    result.sort(key=lambda x: x.date)
    return result


def _parse_bill_month(values: list[Any], account_no: str) -> Optional[MonthlyReading]:
    bill = _pick_bill(values)
    if not bill:
        return None
    basic = bill.get("basicInfo") or {}
    ym = _normalize_ym(bill.get("ym") or basic.get("ym"))
    usage = _safe_float(basic.get("monthPq"))
    charge = _safe_float(basic.get("monthAmt"))
    if not ym or (usage is None and charge is None):
        return None
    return MonthlyReading(
        account_no=account_no or _extract_account_no(basic.get("consNo")),
        year_month=ym,
        total_usage_kwh=usage,
        total_charge_cny=charge,
        begin_date=_date_only(basic.get("begDate")),
        end_date=_date_only(basic.get("endDate")),
    )


def _parse_bill_yearly(values: list[Any], account_no: str) -> Optional[YearlyReading]:
    bill = _pick_bill(values)
    basic = bill.get("basicInfo") if bill else None
    if not isinstance(basic, dict):
        return None
    year = str(basic.get("year") or _normalize_ym(bill.get("ym"))[:4] or "")
    usage = _safe_float(basic.get("yearPq"))
    charge = _safe_float(basic.get("yearAmt"))
    if not (year or usage is not None or charge is not None):
        return None
    return YearlyReading(account_no=account_no, year=year, total_usage_kwh=usage, total_charge_cny=charge)


def _pick_bill(values: list[Any]) -> dict[str, Any]:
    for value in values:
        if isinstance(value, list) and value and isinstance(value[0], dict) and ("basicInfo" in value[0] or "pvQtyList" in value[0]):
            return value[0]
    for value in values:
        if isinstance(value, dict) and ("basicInfo" in value or "pvQtyList" in value):
            return value
    return {}


def _pick_first_text(obj: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = obj.get(key)
        if value is not None:
            text = str(value).strip()
            if text:
                return text
    return ""


def _pick_first_value(obj: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in obj and obj.get(key) not in (None, ""):
            return obj.get(key)
    return None


def _has_any_float(obj: dict[str, Any], keys: tuple[str, ...]) -> bool:
    return any(_first_float(obj, key) is not None for key in keys)


def _first_float(obj: dict[str, Any], *keys: str) -> Optional[float]:
    for key in keys:
        if key in obj:
            value = _safe_float(obj.get(key))
            if value is not None:
                return value
    return None


def _safe_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (dict, list, tuple, set)):
        return None
    try:
        text = str(value).strip().replace(",", "")
        if text in ("", "-", "—", "None", "null"):
            return None
        # Keep minus sign and decimal point; tolerate strings with units.
        match = re.search(r"-?\d+(?:\.\d+)?", text)
        return float(match.group(0)) if match else None
    except (TypeError, ValueError):
        return None


def _extract_account_no(value: Any) -> str:
    if value is None:
        return ""
    match = _ACCOUNT_RE.search(str(value))
    return match.group(1) if match else ""


def _extract_masked_account(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    match = _MASKED_ACCOUNT_RE.search(value.strip())
    return f"*********{match.group(1)}" if match else ""


def _normalize_ym(value: Any) -> str:
    text = str(value or "").strip().replace("/", "-")
    if len(text) == 6 and text.isdigit():
        return f"{text[:4]}-{text[4:]}"
    match = re.search(r"(20\d{2})[-年/]?(0?[1-9]|1[0-2])", text)
    if match:
        return f"{match.group(1)}-{int(match.group(2)):02d}"
    return text[:7] if len(text) >= 7 else text


def _normalize_date(value: Any, current_year: str) -> str:
    text = str(value or "").strip().replace("/", "-")
    if not text:
        return ""
    if re.fullmatch(r"\d{2}-\d{2}", text):
        return f"{current_year}-{text}"
    match = re.search(r"(20\d{2})[-年/](\d{1,2})[-月/](\d{1,2})", text)
    if match:
        return f"{match.group(1)}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"
    return text[:10] if len(text) >= 10 else text


def _date_only(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text[:10] if text else None


def _merge_by_key(old: list[Any], new: list[Any], key_func) -> list[Any]:
    merged = {key_func(item): item for item in old if key_func(item)}
    for item in new:
        key = key_func(item)
        if key:
            merged[key] = item
    return [merged[key] for key in sorted(merged)]


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
