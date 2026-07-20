import json
import logging
import os
from datetime import datetime, timedelta

import requests
from .const import *
from .cache_validity import has_useful_legacy_cache_entry
from .entity_identity import account_entity_postfix, legacy_account_postfix


def _mask_user_id(user_id) -> str:
    user_id = str(user_id or "")
    return f"****{user_id[-4:]}" if len(user_id) >= 4 else "****"


class SensorUpdator:

    def __init__(self):
        HASS_URL = os.getenv("HASS_URL")
        HASS_TOKEN = os.getenv("HASS_TOKEN")
        if not HASS_URL:
            raise ValueError("HASS_URL 未配置")
        if not HASS_TOKEN:
            logging.warning("HASS_TOKEN 未配置，Home Assistant REST API 调用可能失败。")
        self.base_url = HASS_URL[:-1] if HASS_URL.endswith("/") else HASS_URL
        self.token = HASS_TOKEN or ""
        self._legacy_entity_cleanup_done: set[str] = set()
        self._init_balance_notify()

    def _init_balance_notify(self):
        push_type = os.getenv("PUSH_TYPE", "None").lower()
        if push_type == "pushplus":
            from .notify import PushplusNotify
            self.balance_notify = PushplusNotify()
        elif push_type == "urlpush":
            from .notify import UrlPushNotify
            self.balance_notify = UrlPushNotify()
        else:
            self.balance_notify = None


    def update_one_userid(
        self,
        user_id: str,
        balance: float,
        last_daily_date: str,
        last_daily_usage: float,
        yearly_charge: float,
        yearly_usage: float,
        month_charge: float,
        month_usage: float,
        prepay_balance: float = None,
        arrears: float = None,
        tou_data: dict = None,
        enhanced_balance: dict = None,
        notify=True,
        cache_values: dict | None = None,
    ):
        logging.info(f"[{_mask_user_id(user_id)}] 开始更新 Home Assistant 传感器数据...")
        if arrears is None and enhanced_balance and enhanced_balance.get("amount_due") is not None:
            arrears = enhanced_balance["amount_due"]
        if cache_values is None:
            cache_values = {
                "balance": balance,
                "last_daily_date": last_daily_date,
                "last_daily_usage": last_daily_usage,
                "yearly_charge": yearly_charge,
                "yearly_usage": yearly_usage,
                "month_charge": month_charge,
                "month_usage": month_usage,
                "prepay_balance": prepay_balance,
                "arrears": arrears,
                "tou_data": tou_data,
                "enhanced_balance": enhanced_balance,
            }
        cache_values = dict(cache_values)
        cache_values.pop("user_id", None)
        self._save_to_cache(user_id, **cache_values)
        postfix = account_entity_postfix(user_id)
        publish_ok = True

        def record_publish_result(result) -> None:
            nonlocal publish_ok
            # Older tests/subclasses may still return None. Treat only explicit
            # False as a failed HA REST publish.
            if result is False:
                publish_ok = False

        if balance is not None:
            if notify and self.balance_notify is not None:
                try:
                    self.balance_notify(user_id, balance)
                except Exception as notify_error:
                    logging.warning(
                        f"[{_mask_user_id(user_id)}] 余额通知失败，已与国网抓取及 HA 发布隔离: {notify_error}"
                    )
            record_publish_result(self.update_balance(postfix, balance, enhanced_balance))
        else:
            record_publish_result(self.delete_sensor_state(BALANCE_SENSOR_NAME + postfix))
        if last_daily_usage is not None:
            record_publish_result(self.update_last_daily_usage(postfix, last_daily_date, last_daily_usage))
        if yearly_usage is not None:
            record_publish_result(self.update_yearly_data(postfix, yearly_usage, usage=True))
        if yearly_charge is not None:
            record_publish_result(self.update_yearly_data(postfix, yearly_charge))
        if month_usage is not None:
            record_publish_result(self.update_month_data(postfix, month_usage, usage=True))
        if month_charge is not None:
            record_publish_result(self.update_month_data(postfix, month_charge))

        # 分时电量传感器
        if tou_data:
            record_publish_result(self._update_tou_sensors(postfix, tou_data))

        if prepay_balance is not None:
            record_publish_result(self.update_prepay_balance(postfix, prepay_balance))
        else:
            record_publish_result(self.delete_sensor_state(PREPAY_BALANCE_SENSOR_NAME + postfix))
        if arrears is not None:
            record_publish_result(self.update_arrears(postfix, arrears))
        else:
            record_publish_result(self.delete_sensor_state(ARREARS_SENSOR_NAME + postfix))

        if publish_ok:
            self._cleanup_legacy_entities(user_id)
            logging.info(f"[{_mask_user_id(user_id)}] Home Assistant 传感器数据更新完成!")
        else:
            logging.warning(f"[{_mask_user_id(user_id)}] Home Assistant 传感器数据未完全发布成功。")
        return publish_ok

    def _cleanup_legacy_entities(self, user_id: str) -> None:
        """Best-effort cleanup for entity IDs that used only the last four digits."""
        if os.getenv("SGCC_CLEANUP_LEGACY_ENTITY_IDS", "").strip().lower() not in {
            "1",
            "true",
            "yes",
            "on",
        }:
            return
        cleaned = getattr(self, "_legacy_entity_cleanup_done", None)
        if cleaned is None:
            cleaned = set()
            self._legacy_entity_cleanup_done = cleaned
        if user_id in cleaned:
            return
        postfix = legacy_account_postfix(user_id)
        cleanup_ok = True
        for sensor_base in (
            BALANCE_SENSOR_NAME,
            DAILY_USAGE_SENSOR_NAME,
            YEARLY_USAGE_SENSOR_NAME,
            YEARLY_CHARGE_SENSOR_NAME,
            MONTH_USAGE_SENSOR_NAME,
            MONTH_CHARGE_SENSOR_NAME,
            MONTH_VALLEY_SENSOR_NAME,
            MONTH_FLAT_SENSOR_NAME,
            MONTH_PEAK_SENSOR_NAME,
            MONTH_TIP_SENSOR_NAME,
            PREPAY_BALANCE_SENSOR_NAME,
            ARREARS_SENSOR_NAME,
        ):
            try:
                if self.delete_sensor_state(sensor_base + postfix) is False:
                    cleanup_ok = False
            except Exception as cleanup_error:
                cleanup_ok = False
                logging.warning(
                    f"[{_mask_user_id(user_id)}] 清理旧 Home Assistant 实体失败，已忽略: {cleanup_error}"
                )
        if cleanup_ok:
            cleaned.add(user_id)
        else:
            logging.warning(
                f"[{_mask_user_id(user_id)}] 旧 Home Assistant 实体未完全清理，后续发布将重试。"
            )

    def _get_cache_file(self):
        from .const import get_data_dir
        return os.path.join(get_data_dir(), 'sgcc_cache.json')

    def _save_to_cache(self, user_id, balance, last_daily_date, last_daily_usage, yearly_charge, yearly_usage, month_charge, month_usage, prepay_balance=None, arrears=None, tou_data=None, enhanced_balance=None):
        cache_file = self._get_cache_file()
        abs_cache_file = os.path.abspath(cache_file)
        data = {}
        try:
            if os.path.exists(cache_file):
                with open(cache_file, 'r') as f:
                    data = json.load(f)
        except Exception as e:
            logging.warning(f"加载缓存文件失败: {e}")

        cache_entry = {
            "balance": balance,
            "last_daily_date": last_daily_date,
            "last_daily_usage": last_daily_usage,
            "yearly_charge": yearly_charge,
            "yearly_usage": yearly_usage,
            "month_charge": month_charge,
            "month_usage": month_usage,
            "prepay_balance": prepay_balance,
            "arrears": arrears,
            "timestamp": datetime.now().isoformat()
        }

        if tou_data:
            cache_entry["tou_data"] = tou_data
        if enhanced_balance:
            cache_entry["enhanced_balance"] = enhanced_balance

        if not has_useful_legacy_cache_entry(cache_entry):
            logging.warning(f"[{_mask_user_id(user_id)}] 缓存条目没有任何有效国网业务数据，跳过写入，避免空缓存阻止后续真实抓取。")
            return

        data[user_id] = cache_entry

        try:
            with open(cache_file, 'w') as f:
                json.dump(data, f, indent=2)
            logging.debug(f"已保存数据到缓存文件: {abs_cache_file}")
        except Exception as e:
            logging.error(f"保存缓存文件失败 {abs_cache_file}: {e}")

    def republish(self):
        cache_file = self._get_cache_file()
        abs_cache_file = os.path.abspath(cache_file)
        if not os.path.exists(cache_file):
            logging.info(f"未找到缓存文件 {abs_cache_file}，跳过重新推送。")
            return False

        data = {}
        try:
            with open(cache_file, 'r') as f:
                data = json.load(f)
        except Exception as e:
            logging.error(f"加载缓存文件失败 {abs_cache_file}: {e}")
            return False

        # 检查缓存数据的日期是否与当前日期一致，且必须包含真实业务值。
        today_str = datetime.now().strftime("%Y-%m-%d")
        valid_items = []
        for user_id, values in data.items():
            if not isinstance(values, dict):
                continue
            cache_timestamp = values.get("timestamp", "")
            cache_date = cache_timestamp[:10] if cache_timestamp else ""
            if cache_date != today_str:
                logging.info(f"缓存数据日期({cache_date})与当前日期({today_str})不一致，需要从国家电网重新获取数据。")
                return False
            if not has_useful_legacy_cache_entry(values):
                logging.warning(f"缓存用户 {str(user_id)[-4:]} 只有户号/空值，没有有效国网业务数据，跳过缓存重推。")
                continue
            valid_items.append((user_id, values))

        if not valid_items:
            logging.info("未找到包含真实国网业务数据的当天缓存，需要从国家电网重新获取数据。")
            return False

        try:
            ok = True
            republished_count = 0
            for user_id, values in valid_items:
                logging.info(f"正在从缓存重新推送用户 {_mask_user_id(user_id)} 的数据。")
                clean_values = {k: v for k, v in values.items() if k != 'timestamp'}
                if self.update_one_userid(user_id, **clean_values, notify=False) is False:
                    ok = False
                else:
                    republished_count += 1
            return ok and republished_count > 0
        except Exception as e:
            logging.error(f"重新推送数据失败: {e}")
            return False


    def delete_sensor_state(self, sensorName: str) -> bool:
        """删除当前没有源数据的旧 REST 状态，避免 HA 留下陈旧/误导实体。"""
        headers = {
            "Content-Type": "application/json",
            "Authorization": "Bearer " + self.token,
        }
        url = self.base_url + API_PATH + sensorName
        try:
            response = requests.delete(url, headers=headers, timeout=10)
            if response.status_code in (200, 404):
                if response.status_code == 200:
                    logging.info(f"Home Assistant 传感器 {sensorName} 当前无源数据，已删除旧状态。")
                return True
            logging.warning(f"删除 Home Assistant 传感器 {sensorName} 旧状态失败: {response.status_code}, {response.content}")
            return False
        except Exception as e:
            logging.warning(f"删除 Home Assistant 传感器 {sensorName} 旧状态失败: {e}")
            return False

    def get_sensor_state(self, sensor_name):
        headers = {
            "Content-Type": "application/json",
            "Authorization": "Bearer " + self.token,
        }
        url = self.base_url + API_PATH + sensor_name
        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                return response.json()
            return None
        except Exception as e:
            logging.warning(f"获取传感器 {sensor_name} 状态失败: {e}")
            return None

    def should_update(self, sensor_name, new_state, check_attributes=None):
        current_state_obj = self.get_sensor_state(sensor_name)
        if not current_state_obj:
            return True

        # 检查状态
        try:
            current_state = current_state_obj.get('state')
            if current_state in ['unknown', 'unavailable', None]:
                return True

            curr_val = float(current_state)
            new_val = float(new_state)
            if abs(curr_val - new_val) > 0.001:
                return True
        except (ValueError, TypeError):
            # 如果无法作为浮点数比较，则假定不同
            return True

        # 如需则检查属性
        if check_attributes:
            curr_attrs = current_state_obj.get('attributes', {})
            for k, v in check_attributes.items():
                # 转换为字符串进行比较以避免类型不匹配
                if str(curr_attrs.get(k)) != str(v):
                    return True

        return False

    def update_last_daily_usage(self, postfix: str, last_daily_date: str, sensorState: float):
        sensorName = DAILY_USAGE_SENSOR_NAME + postfix

        if not self.should_update(sensorName, sensorState, {"last_reset": last_daily_date}):
             logging.info(f"跳过 {sensorName} 的更新，状态相同。")
             return True

        request_body = {
            "state": sensorState,
            "unique_id": sensorName,
            "attributes": {
                "last_reset": last_daily_date,
                "unit_of_measurement": "kWh",
                "icon": "mdi:lightning-bolt",
                "device_class": "energy",
                "state_class": "measurement",
            },
        }

        ok = self.send_url(sensorName, request_body)
        if ok:
            logging.info(f"Home Assistant 传感器 {sensorName} 状态已更新: {sensorState} kWh")
        return ok

    def update_balance(self, postfix: str, sensorState: float, enhanced_balance: dict = None):
        sensorName = BALANCE_SENSOR_NAME + postfix

        if not self.should_update(sensorName, sensorState):
             logging.info(f"跳过 {sensorName} 的更新，状态相同。")
             return True

        last_reset = datetime.now().strftime("%Y-%m-%d, %H:%M:%S")
        attributes = {
            "last_reset": last_reset,
            "unit_of_measurement": "CNY",
            "icon": "mdi:cash",
            "device_class": "monetary",
            "state_class": "total",
        }
        if enhanced_balance:
            if enhanced_balance.get("amount_due") is not None:
                attributes["amount_due"] = enhanced_balance["amount_due"]

        request_body = {
            "state": sensorState,
            "unique_id": sensorName,
            "attributes": attributes,
        }

        ok = self.send_url(sensorName, request_body)
        if ok:
            logging.info(f"Home Assistant 传感器 {sensorName} 状态已更新: {sensorState} CNY")
        return ok

    def update_month_data(self, postfix: str, sensorState: float, usage=False):
        sensorName = (
            MONTH_USAGE_SENSOR_NAME + postfix
            if usage
            else MONTH_CHARGE_SENSOR_NAME + postfix
        )
        current_date = datetime.now()
        first_day_of_current_month = current_date.replace(day=1)
        last_day_of_previous_month = first_day_of_current_month - timedelta(days=1)
        last_reset = last_day_of_previous_month.strftime("%Y-%m")

        if not self.should_update(sensorName, sensorState, {"last_reset": last_reset}):
             logging.info(f"跳过 {sensorName} 的更新，状态相同。")
             return True

        request_body = {
            "state": sensorState,
            "unique_id": sensorName,
            "attributes": {
                "last_reset": last_reset,
                "unit_of_measurement": "kWh" if usage else "CNY",
                "icon": "mdi:lightning-bolt" if usage else "mdi:cash",
                "device_class": "energy" if usage else "monetary",
                "state_class": "measurement",
            },
        }

        ok = self.send_url(sensorName, request_body)
        if ok:
            logging.info(f"Home Assistant 传感器 {sensorName} 状态已更新: {sensorState} {'kWh' if usage else 'CNY'}")
        return ok

    def update_yearly_data(self, postfix: str, sensorState: float, usage=False):
        sensorName = (
            YEARLY_USAGE_SENSOR_NAME + postfix
            if usage
            else YEARLY_CHARGE_SENSOR_NAME + postfix
        )
        if datetime.now().month == 1:
            last_year = datetime.now().year -1
            last_reset = datetime.now().replace(year=last_year).strftime("%Y")
        else:
            last_reset = datetime.now().strftime("%Y")

        if not self.should_update(sensorName, sensorState, {"last_reset": last_reset}):
             logging.info(f"跳过 {sensorName} 的更新，状态相同。")
             return True

        request_body = {
            "state": sensorState,
            "unique_id": sensorName,
            "attributes": {
                "last_reset": last_reset,
                "unit_of_measurement": "kWh" if usage else "CNY",
                "icon": "mdi:lightning-bolt" if usage else "mdi:cash",
                "device_class": "energy" if usage else "monetary",
                "state_class": "total_increasing",
            },
        }
        ok = self.send_url(sensorName, request_body)
        if ok:
            logging.info(f"Home Assistant 传感器 {sensorName} 状态已更新: {sensorState} {'kWh' if usage else 'CNY'}")
        return ok

    def _update_tou_sensors(self, postfix: str, tou_data: dict):
        """更新月度分时电量传感器（谷/平/峰/尖）"""
        current_date = datetime.now()
        first_day = current_date.replace(day=1)
        last_day_prev = first_day - timedelta(days=1)
        last_reset = last_day_prev.strftime("%Y-%m")

        tou_fields = [
            ("valley_usage", MONTH_VALLEY_SENSOR_NAME, "谷"),
            ("flat_usage", MONTH_FLAT_SENSOR_NAME, "平"),
            ("peak_usage", MONTH_PEAK_SENSOR_NAME, "峰"),
            ("tip_usage", MONTH_TIP_SENSOR_NAME, "尖"),
        ]

        # 尝试从 daily 数据汇总当月分时电量
        daily_rows = tou_data.get("daily", [])
        if not daily_rows:
            return True

        ok = True
        current_month_prefix = current_date.strftime("%Y-%m")
        month_valley = sum(r.get("valley_usage", 0) or 0 for r in daily_rows if str(r.get("date", "")[:7]) == current_month_prefix)
        month_flat = sum(r.get("flat_usage", 0) or 0 for r in daily_rows if str(r.get("date", "")[:7]) == current_month_prefix)
        month_peak = sum(r.get("peak_usage", 0) or 0 for r in daily_rows if str(r.get("date", "")[:7]) == current_month_prefix)
        month_tip = sum(r.get("tip_usage", 0) or 0 for r in daily_rows if str(r.get("date", "")[:7]) == current_month_prefix)

        tou_values = {
            "valley_usage": month_valley,
            "flat_usage": month_flat,
            "peak_usage": month_peak,
            "tip_usage": month_tip,
        }

        for field_key, sensor_base, label in tou_fields:
            value = tou_values.get(field_key, 0)
            if value is None:
                continue
            sensorName = sensor_base + postfix
            if not self.should_update(sensorName, value, {"last_reset": last_reset}):
                logging.info(f"跳过 {sensorName} 的更新，状态相同。")
                continue
            request_body = {
                "state": value,
                "unique_id": sensorName,
                "attributes": {
                    "last_reset": last_reset,
                    "unit_of_measurement": "kWh",
                    "icon": "mdi:lightning-bolt",
                    "device_class": "energy",
                    "state_class": "measurement",
                    "friendly_name": f"月度{label}时电量",
                },
            }
            send_ok = self.send_url(sensorName, request_body)
            ok = send_ok and ok
            if send_ok:
                logging.info(f"Home Assistant 传感器 {sensorName} 状态已更新: {value} kWh ({label})")
        return ok

    def update_prepay_balance(self, postfix: str, sensorState: float):
        """更新预付费余额传感器"""
        sensorName = PREPAY_BALANCE_SENSOR_NAME + postfix
        if not self.should_update(sensorName, sensorState):
            logging.info(f"跳过 {sensorName} 的更新，状态相同。")
            return True
        last_reset = datetime.now().strftime("%Y-%m-%d, %H:%M:%S")
        request_body = {
            "state": sensorState,
            "unique_id": sensorName,
            "attributes": {
                "last_reset": last_reset,
                "unit_of_measurement": "CNY",
                "icon": "mdi:cash-check",
                "device_class": "monetary",
                "state_class": "total",
                "friendly_name": "预付费余额",
            },
        }
        ok = self.send_url(sensorName, request_body)
        if ok:
            logging.info(f"Home Assistant 传感器 {sensorName} 状态已更新: {sensorState} CNY")
        return ok


    def update_arrears(self, postfix: str, sensorState: float):
        """更新应交金额/欠费传感器"""
        sensorName = ARREARS_SENSOR_NAME + postfix
        if not self.should_update(sensorName, sensorState):
            logging.info(f"跳过 {sensorName} 的更新，状态相同。")
            return True
        last_reset = datetime.now().strftime("%Y-%m-%d, %H:%M:%S")
        request_body = {
            "state": sensorState,
            "unique_id": sensorName,
            "attributes": {
                "last_reset": last_reset,
                "unit_of_measurement": "CNY",
                "icon": "mdi:cash-alert",
                "device_class": "monetary",
                "state_class": "total",
                "friendly_name": "应交金额",
            },
        }
        ok = self.send_url(sensorName, request_body)
        if ok:
            logging.info(f"Home Assistant 传感器 {sensorName} 状态已更新: {sensorState} CNY")
        return ok

    def send_url(self, sensorName, request_body) -> bool:
        headers = {
            "Content-Type": "application/json",
            "Authorization": "Bearer " + self.token,
        }
        url = self.base_url + API_PATH + sensorName  # /api/states/<entity_id>
        try:
            response = requests.post(url, verify=False, json=request_body, headers=headers, timeout=10)
            logging.debug(
                f"Home Assistant REST API 调用，POST {url}。响应[{response.status_code}]: {response.content}"
            )
            if 200 <= response.status_code < 300:
                return True
            logging.error(
                f"Home Assistant REST API 调用失败，POST {url} 返回 HTTP {response.status_code}: {response.content}"
            )
            return False
        except Exception as e:
            logging.error(f"Home Assistant REST API 调用失败，原因是 {e}")
            return False
