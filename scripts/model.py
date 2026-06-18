"""统一数据模型契约（CC 重构地基）。

scraper/parser 产出这些 dataclass → store 负责持久化。两侧都 import 本模块,
不得各自另立结构。新增字段需同步:parser 填充、store schema、HA publisher。

字段命名对齐既有 vue_state.py 归一化输出与 HA sensor:
- arrears_cny      ← mixinGetYuEdata.historyOwe（欠费/应交）
- balance_cny      ← 电费账户余额（electricity_charge_balance sensor）
- prepay_balance_cny ← 预付费余额（prepay_balance sensor）
- yearly/monthly/daily ← powerData/tableData/billList（含分时谷平峰尖）
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ---------- 业务数据 ----------

@dataclass
class Account:
    account_no: str                 # 户号(13位),日志须打码
    display_name: str = ""
    address: str = ""
    province: str = ""


@dataclass
class Balance:
    account_no: str
    observed_at: str                # ISO8601
    balance_cny: Optional[float] = None        # 电费账户余额
    prepay_balance_cny: Optional[float] = None # 预付费余额
    arrears_cny: Optional[float] = None         # 欠费/应交(historyOwe)


@dataclass
class DailyReading:
    account_no: str
    date: str                       # YYYY-MM-DD
    total_usage_kwh: Optional[float] = None
    valley_usage_kwh: Optional[float] = None    # 谷
    flat_usage_kwh: Optional[float] = None       # 平
    peak_usage_kwh: Optional[float] = None        # 峰
    tip_usage_kwh: Optional[float] = None          # 尖


@dataclass
class MonthlyReading:
    account_no: str
    year_month: str                 # YYYY-MM
    total_usage_kwh: Optional[float] = None
    total_charge_cny: Optional[float] = None
    begin_date: Optional[str] = None
    end_date: Optional[str] = None


@dataclass
class YearlyReading:
    account_no: str
    year: str                       # YYYY
    total_usage_kwh: Optional[float] = None
    total_charge_cny: Optional[float] = None


@dataclass
class AccountData:
    """单个户号一次抓取的完整结果（scraper 的产出单元）。"""
    account: Account
    balance: Optional[Balance] = None
    yearly: Optional[YearlyReading] = None
    monthly: list[MonthlyReading] = field(default_factory=list)
    daily: list[DailyReading] = field(default_factory=list)


# ---------- 运行 / 会话记录（观测性） ----------

@dataclass
class FetchRun:
    trigger_type: str               # schedule|manual|retry|startup
    status: str = "running"         # running|success|failed|skipped_busy
    started_at: str = ""
    finished_at: Optional[str] = None
    session_status_before: Optional[str] = None
    session_status_after: Optional[str] = None
    error_type: Optional[str] = None
    error_message_redacted: Optional[str] = None


@dataclass
class SessionCheck:
    checked_at: str
    status: str                     # authenticated|expired|captcha_needed|blocked|unknown
    current_url: str = ""
    check_method: str = ""          # dom|balance_page|api_probe|store|combined
    redirected_to_login: bool = False
    evidence_redacted: str = ""


@dataclass
class PublisherState:
    publisher: str                  # ha_rest|mqtt
    entity_id: str
    last_published_at: Optional[str] = None
    last_value: Optional[str] = None
    last_success: bool = False
    last_error_redacted: Optional[str] = None


def mask_account_no(value: Optional[str], keep_last: int = 4) -> str:
    """户号打码,仅保留末若干位。"""
    if not value:
        return ""
    s = str(value)
    if len(s) <= keep_last:
        return "*" * len(s)
    return "*" * (len(s) - keep_last) + s[-keep_last:]
