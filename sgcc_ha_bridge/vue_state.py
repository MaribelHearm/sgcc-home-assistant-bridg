"""Vue状态注入辅助工具，用于读取95598页面数据。

向浏览器注入JavaScript，扫描所有DOM元素查找__vue__属性，
从Vue组件实例中提取结构化数据。
"""

from __future__ import annotations

from typing import Any


SELECTED_VUE_DATA_SCRIPT = """
const clone = (value) => {
  try { return JSON.parse(JSON.stringify(value)); } catch (e) { return null; }
};
const wantedKeys = [
  'mixinGetYuEdata',
  'consInfoobj',
  'consInfo',
  'electric',
  'powerData',
  'mothData',
  'tableData',
  'tableData_t',
  'sevenEleList',
  'sevenEleList_t',
  'new_sevenEleList',
  'tariffC',
  'start',
  'end',
  'queryYear',
  'activeName',
  'billNumberList',
  'BillList',
  'billList',
  'billMonth',
  'NewtotalBillProvince',
  'optionalYearArray',
  'selectYear',
  'listData',
  // 余额页 userAcc.vue 在部分省份会把当前余额放在组件本地字段，
  // 不一定进入 mixinGetYuEdata/consInfoobj 等旧字段。
  'accountBalance',
  'accountBal',
  'accountBalanceAmt',
  'currentBalance',
  'remainBalance',
  'remainingBalance',
  'userBalance',
  'queryTime',
  'amtTime',
  'accountNo',
  'acctNo',
  'address'
];
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


def selected_vue_data(driver) -> list[dict[str, Any]]:
    """执行JS脚本，从当前页面提取Vue状态数据。"""
    return driver.execute_script(SELECTED_VUE_DATA_SCRIPT) or []
