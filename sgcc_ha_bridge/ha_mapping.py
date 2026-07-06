from dataclasses import replace

from .model import AccountData


def _latest_daily(account_data: AccountData):
    rows = [row for row in account_data.daily if row.date]
    return max(rows, key=lambda row: row.date) if rows else None


def _latest_monthly(account_data: AccountData):
    rows = [row for row in account_data.monthly if row.year_month]
    return max(rows, key=lambda row: row.year_month) if rows else None


def _range_text(values: list[str]) -> str:
    values = sorted(v for v in values if v)
    if not values:
        return "-"
    if len(values) == 1:
        return values[0]
    return f"{values[0]}..{values[-1]}"


def account_data_summary(account_data: AccountData) -> str:
    daily_range = _range_text([row.date for row in account_data.daily])
    monthly_range = _range_text([row.year_month for row in account_data.monthly])
    balance_model = account_data.balance
    if balance_model is None:
        balance_text = "balance=no"
    else:
        balance_text = (
            "balance=yes("
            f"amount={'yes' if balance_model.balance_cny is not None else 'no'}, "
            f"prepay={'yes' if balance_model.prepay_balance_cny is not None else 'no'}, "
            f"arrears={'yes' if balance_model.arrears_cny is not None else 'no'}"
            ")"
        )
    return (
        f"{balance_text}, "
        f"daily={len(account_data.daily)}({daily_range}), "
        f"monthly={len(account_data.monthly)}({monthly_range}), "
        f"yearly={'yes' if account_data.yearly else 'no'}"
    )


def with_history_daily_if_empty(account_data: AccountData, store, limit: int = 31) -> AccountData:
    """Return a publish-only copy with historical daily rows when this scrape has none.

    The returned object is intended for REST/MQTT/cache publication only.  It
    must not be saved back as part of the current fetch run, otherwise stale
    rows would look like newly scraped data.
    """
    if account_data.daily:
        return account_data
    account_no = account_data.account.account_no
    if not account_no or store is None:
        return account_data
    history_daily = store.get_daily(account_no, limit)
    if not history_daily:
        return account_data
    return replace(account_data, daily=sorted(history_daily, key=lambda row: row.date or ""))


def account_data_to_update_args(account_data: AccountData) -> dict:
    user_id = account_data.account.account_no
    balance_model = account_data.balance
    yearly = account_data.yearly
    latest_month = _latest_monthly(account_data)
    latest_day = _latest_daily(account_data)

    balance = None
    prepay_balance = None
    arrears = None
    enhanced_balance = None
    if balance_model is not None:
        # Keep the three SGCC money concepts separate.  Prepaid accounts may
        # only expose prepay_balance_cny; publishing that value as
        # electricity_charge_balance makes HA show a plausible but wrong
        # account balance.
        balance = balance_model.balance_cny
        prepay_balance = balance_model.prepay_balance_cny
        arrears = balance_model.arrears_cny
        if arrears is not None:
            enhanced_balance = {
                "as_of": balance_model.observed_at,
                "amount_due": arrears,
                "user_id": user_id,
            }

    tou_daily = []
    for row in account_data.daily:
        tou_daily.append({
            "date": row.date,
            "total_usage": row.total_usage_kwh,
            "valley_usage": row.valley_usage_kwh,
            "flat_usage": row.flat_usage_kwh,
            "peak_usage": row.peak_usage_kwh,
            "tip_usage": row.tip_usage_kwh,
        })
    tou_data = {
        "year": yearly.year if yearly else "",
        "yearly_usage": yearly.total_usage_kwh if yearly else None,
        "yearly_charge": yearly.total_charge_cny if yearly else None,
        "months": [
            {
                "month": row.year_month,
                "usage": row.total_usage_kwh,
                "charge": row.total_charge_cny,
                "begin_date": row.begin_date,
                "end_date": row.end_date,
            }
            for row in account_data.monthly
        ],
        "daily": tou_daily,
    } if tou_daily else None

    return {
        "user_id": user_id,
        "balance": balance,
        "prepay_balance": prepay_balance,
        "arrears": arrears,
        "last_daily_date": latest_day.date if latest_day else None,
        "last_daily_usage": latest_day.total_usage_kwh if latest_day else None,
        "yearly_charge": yearly.total_charge_cny if yearly else None,
        "yearly_usage": yearly.total_usage_kwh if yearly else None,
        "month_charge": latest_month.total_charge_cny if latest_month else None,
        "month_usage": latest_month.total_usage_kwh if latest_month else None,
        "tou_data": tou_data,
        "enhanced_balance": enhanced_balance,
    }
