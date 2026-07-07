"""Vue状态注入辅助工具，用于读取95598页面数据。

向浏览器注入JavaScript，扫描所有DOM元素查找__vue__属性，
从Vue组件实例中提取结构化数据。
"""

from __future__ import annotations

import json
from typing import Any


CORE_WANTED_KEYS = (
    "mixinGetYuEdata",
    "consInfoobj",
    "consInfo",
    "electric",
    "powerData",
    "mothData",
    "tableData",
    "tableData_t",
    "sevenEleList",
    "sevenEleList_t",
    "new_sevenEleList",
    "tariffC",
    "start",
    "end",
    "queryYear",
    "activeName",
    "billNumberList",
    "BillList",
    "billList",
    "billMonth",
    "NewtotalBillProvince",
    "optionalYearArray",
    "selectYear",
    "listData",
)

PARSER_MONEY_KEYS = (
    # parser 当前明确支持或受限兼容的字段，默认采集以保持旧兼容可用。
    "accountBalance",
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
    "prepayBal",
    "prepayBalance",
    "prepay_balance",
    "prepayAmt",
    "prepaidBalance",
    "prepaidBal",
    "prepaidAmt",
    "prepaymentBalance",
    "advanceBalance",
    "advanceAmt",
    "historyOwe",
    "arrears",
    "amountDue",
    "oweAmt",
    "oweAmount",
    "oweFee",
    "oweBalance",
    "payableAmt",
    "needPayAmt",
    "totalOwe",
    "sumMoney",
    "estiAmt",
    "queryTime",
    "amtTime",
    "accountNo",
    "acctNo",
    "address",
)

DIAG_ONLY_MONEY_KEYS = (
    # 泛字段只供 SGCC_MONEY_DIAG 取证；parser 默认不把它们当余额。
    "balance",
    "bal",
)


SELECTED_VUE_DATA_SCRIPT_TEMPLATE = """
const clone = (value) => {
  try { return JSON.parse(JSON.stringify(value)); } catch (e) { return null; }
};
const wantedKeys = __WANTED_KEYS__;
return Array.from(document.querySelectorAll('*'))
  .map((el, index) => {
    const vm = el.__vue__;
    if (!vm) return null;
    const data = {};
    wantedKeys.forEach((key) => {
      if (Object.prototype.hasOwnProperty.call(vm, key)) {
        data[key] = clone(vm[key]);
      }
    });
    if (!Object.keys(data).length) return null;
    return {
      index,
      tag: el.tagName,
      id: el.id || '',
      className: String(el.className || '').slice(0, 160),
      text: (el.innerText || el.textContent || '').trim().slice(0, 500),
      data
    };
  })
  .filter(Boolean);
"""


def _selected_vue_data_script(include_money_diag: bool = False) -> str:
    keys = [*CORE_WANTED_KEYS, *PARSER_MONEY_KEYS]
    if include_money_diag:
        keys.extend(DIAG_ONLY_MONEY_KEYS)
    keys = list(dict.fromkeys(keys))
    return SELECTED_VUE_DATA_SCRIPT_TEMPLATE.replace(
        "__WANTED_KEYS__",
        json.dumps(keys, ensure_ascii=False),
    )


SELECTED_VUE_DATA_SCRIPT = _selected_vue_data_script(include_money_diag=False)


STORE_SNAPSHOT_SCRIPT = """
const clone = (value) => {
  try { return JSON.parse(JSON.stringify(value)); } catch (e) { return null; }
};
const root = Array.from(document.querySelectorAll('*'))
  .map((el) => el.__vue__)
  .find((vm) => vm && vm.$store);
if (!root || !root.$store) {
  return { state: {}, getters: {}, url: location.href, route: null };
}
return {
  state: clone(root.$store.state) || {},
  getters: clone(root.$store.getters) || {},
  url: location.href,
  route: root.$route ? clone(root.$route) : null
};
"""


def selected_store_snapshot(driver) -> dict[str, Any]:
    """读取当前页面根 Vue 实例的 Vuex state/getters 快照。"""
    return driver.execute_script(STORE_SNAPSHOT_SCRIPT) or {"state": {}, "getters": {}}


def selected_store_state(driver) -> dict[str, Any]:
    """仅读取当前页面 Vuex $store.state，供只需要 state 的调用方使用。"""
    snapshot = selected_store_snapshot(driver)
    return snapshot.get("state") or {}


def selected_vue_data(driver, include_money_diag: bool = False) -> list[dict[str, Any]]:
    """执行JS脚本，从当前页面提取Vue状态数据。"""
    return driver.execute_script(_selected_vue_data_script(include_money_diag)) or []
