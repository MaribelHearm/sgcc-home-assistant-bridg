"""Structured money diagnostics for Path B Vue/Vuex snapshots.

This module is intentionally observational: it does not change parser output and
it does not scrape rendered DOM text.  It inspects the structured data already
captured from Vuex state/getters and Vue component ``data`` to help users report
which SGCC money-like fields exist on their province/account pages.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Iterable, Optional

from .model import AccountData, mask_account_no
from .redact import redact_text, redact_url


DEFAULT_MONEY_DIAG_LIMIT = 80

_LABEL_KEYS = ("label", "name", "title", "text", "itemName", "fieldName", "field", "desc", "caption")
_ACCOUNT_KEYS = ("consNo", "consNo_dst", "accountNo", "acctNo", "user_id", "userId", "selectValue")
_TIME_KEYS = ("amtTime", "queryTime", "date", "time", "dataTime", "updateTime", "asOfTime")
_PERIOD_KEYS = ("billMonth", "month", "ym", "yearMonth", "queryYear", "year", "begDate", "beginDate", "endDate")
_EXACT_NON_MONEY_KEYS = {key.casefold() for key in _ACCOUNT_KEYS + _TIME_KEYS + _PERIOD_KEYS}

_PREPAY_TERMS = (
    "prepay", "prepaid", "prepayment", "advance", "预付", "预存", "预缴", "预交",
)
_ARREARS_TERMS = (
    "historyowe", "arrears", "amountdue", "oweamt", "oweamount", "owefee",
    "owebalance", "payable", "needpay", "欠费", "应交", "待缴", "待交",
)
_ACCOUNT_BALANCE_TERMS = (
    "accountbalance", "accountbal", "acctbalance", "acctbal", "currentbalance", "curbalance",
    "remainbalance", "remainingbalance", "surplusbalance", "userbalance", "availablebalance",
    "账户余额", "电费余额", "当前余额", "账户结余",
)
_PREVIOUS_TERMS = ("previous", "prev", "last", "lastmonth", "上期", "上月", "上次")
_BILL_CHARGE_TERMS = (
    "monthelecost", "totalelecost", "monthamt", "totalamt", "billamt", "billamount",
    "billcharge", "charge", "cost", "fee", "账单", "出账", "本期电费", "月电费", "电费金额", "电费",
)
_PAYMENT_TERMS = (
    "recharge", "payment", "paid", "payamount", "payamt", "payfee", "充值", "缴费", "交费", "实缴", "支付",
)
_GENERIC_MONEY_TERMS = (
    "balance", "amount", "amt", "money", "fee", "cost", "charge", "余额", "金额", "结余", "电费",
)


@dataclass(frozen=True)
class MoneyCandidate:
    category: str
    source: str
    key: str
    value: float
    raw_value: str
    label: str = ""
    account: str = ""
    time: str = ""
    period: str = ""


def money_diag_enabled() -> bool:
    return str(os.getenv("SGCC_MONEY_DIAG", "false")).strip().lower() in {"1", "true", "yes", "on"}


def money_diag_limit() -> int:
    try:
        return max(1, int(os.getenv("SGCC_MONEY_DIAG_LIMIT", str(DEFAULT_MONEY_DIAG_LIMIT))))
    except (TypeError, ValueError):
        return DEFAULT_MONEY_DIAG_LIMIT


def collect_money_candidates(
    store: Any = None,
    components: Any = None,
    limit: Optional[int] = None,
) -> list[MoneyCandidate]:
    """Collect structured money-like fields from Vue/Vuex snapshots.

    Only structured snapshot data is inspected.  Rendered DOM text is not used as
    a fallback source, because display copy lacks enough business context to
    distinguish current balance, prepay balance, arrears, and bill charges.
    """
    max_items = DEFAULT_MONEY_DIAG_LIMIT if limit is None else max(1, limit)
    result: list[MoneyCandidate] = []
    seen: set[tuple[str, str, str]] = set()
    for root_path, root_value in _iter_source_roots(store, components):
        for candidate in _walk_money_candidates(root_value, root_path, ancestors=[]):
            dedupe_key = (candidate.category, candidate.source, _format_float(candidate.value))
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            result.append(candidate)
            if len(result) >= max_items:
                return result
    return result


def log_money_diagnostics(
    snapshot: dict[str, Any],
    parsed: AccountData,
    page_label: str,
    limit: Optional[int] = None,
) -> None:
    max_items = money_diag_limit() if limit is None else max(1, limit)
    candidates = collect_money_candidates(
        store=snapshot.get("store"),
        components=snapshot.get("components"),
        limit=max_items,
    )
    balance = parsed.balance if parsed else None
    account_no = parsed.account.account_no if parsed and parsed.account else ""
    logging.info(
        "Path B 金额诊断摘要: "
        f"page={page_label}, "
        f"url={redact_url(str(snapshot.get('url') or ''))}, "
        f"account={mask_account_no(account_no)}, "
        f"parsed_balance={balance.balance_cny if balance else None}, "
        f"parsed_prepay={balance.prepay_balance_cny if balance else None}, "
        f"parsed_arrears={balance.arrears_cny if balance else None}, "
        f"candidates={len(candidates)}"
    )
    for index, candidate in enumerate(candidates, 1):
        logging.info(_format_candidate_line(index, candidate))


def _format_candidate_line(index: int, candidate: MoneyCandidate) -> str:
    parts = [
        f"Path B 金额候选[{index}]:",
        f"category={candidate.category}",
        f"source={candidate.source}",
        f"key={candidate.key}",
        f"value={_format_float(candidate.value)}",
    ]
    if candidate.time:
        parts.append(f"time={candidate.time}")
    if candidate.period:
        parts.append(f"period={candidate.period}")
    if candidate.account:
        parts.append(f"account={candidate.account}")
    if candidate.label:
        parts.append(f"label={redact_text(candidate.label[:40])}")
    return f"{parts[0]} {', '.join(parts[1:])}"


def _iter_source_roots(store: Any, components: Any) -> Iterable[tuple[str, Any]]:
    if isinstance(store, dict):
        yielded = False
        if isinstance(store.get("state"), dict):
            yielded = True
            yield "store.state", store["state"]
        if isinstance(store.get("getters"), dict):
            yielded = True
            yield "store.getters", store["getters"]
        for index, snap in enumerate(store.get("snapshots") or []):
            for child_path, child_value in _iter_source_roots(snap, None):
                yielded = True
                yield f"store.snapshots[{index}].{child_path.removeprefix('store.')}", child_value
        if not yielded:
            yield "store", store
    elif store:
        yield "store", store

    if isinstance(components, dict):
        if isinstance(components.get("data"), dict):
            yield "component.data", components["data"]
        else:
            yield "components", components
    elif isinstance(components, list):
        for index, component in enumerate(components):
            if isinstance(component, dict) and isinstance(component.get("data"), dict):
                yield f"component[{index}].data", component["data"]
            else:
                yield f"component[{index}]", component


def _walk_money_candidates(value: Any, path: str, ancestors: list[dict[str, Any]]) -> Iterable[MoneyCandidate]:
    if isinstance(value, dict):
        next_ancestors = [value] + ancestors
        for key, child in value.items():
            child_path = f"{path}.{_path_key(key)}"
            if _is_scalar(child):
                candidate = _candidate_from_scalar(str(key), child, child_path, next_ancestors)
                if candidate:
                    yield candidate
            else:
                yield from _walk_money_candidates(child, child_path, next_ancestors)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk_money_candidates(child, f"{path}[{index}]", ancestors)


def _candidate_from_scalar(
    key: str,
    value: Any,
    source: str,
    ancestors: list[dict[str, Any]],
) -> Optional[MoneyCandidate]:
    key_folded = key.casefold()
    if key_folded in _EXACT_NON_MONEY_KEYS:
        return None
    amount = _safe_float(value)
    if amount is None:
        return None
    if _looks_like_identifier_amount(key, value):
        return None

    label = _nearest_text(ancestors, _LABEL_KEYS)
    context = " ".join([key, source, label]).casefold()
    category = (
        "account_balance"
        if _is_sum_money_balance(key, source, ancestors)
        else _classify_money_context(context)
    )
    if category is None:
        return None

    account = _nearest_account(ancestors)
    time_value = _nearest_value(ancestors, _TIME_KEYS)
    period_value = _nearest_value(ancestors, _PERIOD_KEYS)
    return MoneyCandidate(
        category=category,
        source=source,
        key=key,
        value=amount,
        raw_value=str(value).strip()[:80],
        label=label,
        account=account,
        time=_format_context_value(time_value),
        period=_format_context_value(period_value),
    )


def _is_sum_money_balance(key: str, source: str, ancestors: list[dict[str, Any]]) -> bool:
    if key.casefold() != "summoney":
        return False
    source_compact = re.sub(r"[\s_\-.]+", "", source).casefold()
    if "mixingetyuedata" in source_compact:
        return True
    for obj in ancestors:
        if isinstance(obj, dict) and any(k in obj for k in ("prepayBal", "historyOwe", "estiAmt")):
            return True
    return False


def _classify_money_context(context: str) -> Optional[str]:
    compact = re.sub(r"[\s_\-.]+", "", context)
    haystacks = (context, compact)

    def has_any(terms: tuple[str, ...]) -> bool:
        return any(term.casefold() in hay for hay in haystacks for term in terms)

    if has_any(_PREPAY_TERMS):
        return "prepay_balance"
    if has_any(_ARREARS_TERMS):
        return "arrears_due"
    if has_any(_PREVIOUS_TERMS) and has_any(("balance", "余额", "结余")):
        return "previous_balance"
    if has_any(_ACCOUNT_BALANCE_TERMS):
        return "account_balance"
    if has_any(_BILL_CHARGE_TERMS):
        return "bill_charge"
    if has_any(_PAYMENT_TERMS):
        return "payment_or_recharge"
    if has_any(_GENERIC_MONEY_TERMS):
        return "generic_money"
    return None


def _nearest_text(ancestors: list[dict[str, Any]], keys: tuple[str, ...]) -> str:
    value = _nearest_value(ancestors, keys)
    return _format_context_value(value)


def _nearest_value(ancestors: list[dict[str, Any]], keys: tuple[str, ...]) -> Any:
    for obj in ancestors:
        if not isinstance(obj, dict):
            continue
        for key in keys:
            value = obj.get(key)
            if value not in (None, "") and _is_scalar(value):
                return value
    return None


def _nearest_account(ancestors: list[dict[str, Any]]) -> str:
    value = _nearest_value(ancestors, _ACCOUNT_KEYS)
    if value in (None, ""):
        return ""
    return mask_account_no(str(value))


def _is_scalar(value: Any) -> bool:
    return value is not None and not isinstance(value, (dict, list, tuple, set)) and not isinstance(value, bool)


def _safe_float(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (dict, list, tuple, set)):
        return None
    text = str(value).strip().replace(",", "")
    if text in ("", "-", "—", "None", "null"):
        return None
    if _looks_like_date_time(text):
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _looks_like_date_time(text: str) -> bool:
    return bool(re.search(r"20\d{2}[-/年]\d{1,2}[-/月]\d{1,2}", text))


def _looks_like_identifier_amount(key: str, value: Any) -> bool:
    text = str(value).strip()
    key_text = key.casefold()
    if key_text in {k.casefold() for k in _ACCOUNT_KEYS}:
        return True
    if re.fullmatch(r"\d{10,}", text):
        return True
    return False


def _format_context_value(value: Any) -> str:
    if value in (None, ""):
        return ""
    text = str(value).strip().replace("\n", " ")
    if not text:
        return ""
    return text[:80]


def _format_float(value: float) -> str:
    text = f"{value:.6f}".rstrip("0").rstrip(".")
    return text if text else "0"


def _path_key(key: Any) -> str:
    text = str(key)
    if re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*", text):
        return text
    safe = text.replace("'", "\\'")[:80]
    return f"['{safe}']"
