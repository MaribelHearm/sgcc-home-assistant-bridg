import json
import logging
from datetime import datetime
from typing import Any, Optional

from .cache_validity import has_useful_account_data
from .config import FetcherConfig
from .model import AccountData, DailyReading, MonthlyReading, mask_account_no

try:
    import paho.mqtt.client as mqtt
except Exception:  # pragma: no cover - exercised only when dependency is absent
    mqtt = None


class MqttPublisher:
    """Home Assistant MQTT Discovery publisher for SGCC account data."""

    def __init__(self, config: Optional[FetcherConfig] = None):
        self.config = config or FetcherConfig.from_env()
        self.host = self.config.MQTT_HOST
        self.port = self.config.MQTT_PORT
        self.username = self.config.MQTT_USERNAME
        self.password = self.config.MQTT_PASSWORD
        self.discovery_prefix = self.config.MQTT_DISCOVERY_PREFIX or "homeassistant"
        self.client = None
        self.connected = False

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.disconnect()

    def connect(self) -> bool:
        if mqtt is None:
            logging.warning("paho-mqtt 未安装，跳过 MQTT 发布。")
            return False
        if not self.host:
            logging.warning("MQTT_HOST 未配置，跳过 MQTT 发布。")
            return False

        try:
            try:
                self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
            except Exception:
                self.client = mqtt.Client()
            if self.username:
                self.client.username_pw_set(self.username, self.password or None)
            rc = self.client.connect(self.host, self.port, keepalive=60)
            if rc != 0:
                logging.warning(f"MQTT 连接失败，返回码: {rc}")
                self.connected = False
                return False
            self.client.loop_start()
            self.connected = True
            return True
        except Exception as e:
            logging.warning(f"MQTT 连接失败: {e}")
            self.connected = False
            return False

    def disconnect(self) -> None:
        if self.client is None:
            return
        try:
            self.client.loop_stop()
            self.client.disconnect()
        except Exception as e:
            logging.warning(f"MQTT 断开连接失败: {e}")
        finally:
            self.connected = False

    def publish_account_data(self, account_data: AccountData) -> bool:
        if self.client is None or not self.connected:
            logging.warning("MQTT 未连接，跳过发布。")
            return False

        try:
            account_no = account_data.account.account_no
            masked = mask_account_no(account_no)
            if not has_useful_account_data(account_data):
                logging.warning(f"MQTT 发布跳过户号 {masked}: 当前 AccountData 没有有效国网业务数据。")
                return False
            node = self._safe_topic_part(f"sgcc_{masked}")
            device = {
                "identifiers": [f"sgcc_{masked}"],
                "name": f"国网电费 {masked}",
                "manufacturer": "SGCC bridge",
            }

            published_configs = 0
            published_states = 0
            suffix = account_no[-4:] if account_no else self._safe_topic_part(masked)[-4:]
            for spec in self._sensor_specs(account_data, masked, device):
                value = spec.pop("value")
                key = spec.pop("key")
                delete_when_none = spec.pop("delete_when_none", True)
                state_topic = f"sgcc/{node}/{key}/state"
                config_topic = f"{self.discovery_prefix}/sensor/{node}/{key}/config"
                if value is None:
                    if not delete_when_none:
                        # Some stable aggregate sensors may be temporarily empty
                        # around a month boundary before the first daily reading
                        # for the new month arrives.  Keep their retained
                        # discovery config intact instead of deleting the HA
                        # entity and breaking dashboards that reference it.
                        continue
                    # MQTT Discovery retained configs without matching states leave
                    # Home Assistant with unknown/unavailable entities.  Publish an
                    # empty retained config to remove stale entities from earlier
                    # versions, and do not recreate them until a real value exists.
                    self._publish(config_topic, "", retain=True)
                    continue
                attributes = spec.pop("attributes", None)
                payload = {
                    "name": spec.pop("name"),
                    "unique_id": f"sgcc_{masked}_{key}",
                    "object_id": f"sgcc_{suffix}_{key}",
                    "state_topic": state_topic,
                    "device": device,
                }
                if attributes is not None:
                    payload["json_attributes_topic"] = f"sgcc/{node}/{key}/attributes"
                payload.update({k: v for k, v in spec.items() if v is not None})
                self._publish(config_topic, json.dumps(payload, ensure_ascii=False), retain=True)
                published_configs += 1
                if attributes is not None:
                    self._publish(
                        payload["json_attributes_topic"],
                        json.dumps(attributes, ensure_ascii=False),
                        retain=True,
                    )
                self._publish(state_topic, self._format_value(value), retain=True)
                published_states += 1
            if published_configs and not published_states:
                logging.warning("MQTT Discovery 配置已发布，但当前账户数据没有可用状态值；本次 MQTT 发布不视为成功。")
            return published_configs > 0 and published_states > 0
        except Exception as e:
            logging.warning(f"MQTT 发布失败: {e}")
            return False

    def remove_account_data(self, account_data: AccountData) -> bool:
        """Remove every retained MQTT Discovery entity for one account."""
        if self.client is None or not self.connected:
            logging.warning("MQTT 未连接，跳过账户 Discovery 清理。")
            return False

        account_no = account_data.account.account_no if account_data and account_data.account else ""
        if not account_no:
            return False
        try:
            masked = mask_account_no(account_no)
            node = self._safe_topic_part(f"sgcc_{masked}")
            device = {
                "identifiers": [f"sgcc_{masked}"],
                "name": f"国网电费 {masked}",
                "manufacturer": "SGCC bridge",
            }
            keys = sorted({
                str(spec.get("key") or "")
                for spec in self._sensor_specs(account_data, masked, device)
                if spec.get("key")
            })
            for key in keys:
                config_topic = f"{self.discovery_prefix}/sensor/{node}/{key}/config"
                self._publish(config_topic, "", retain=True)
            logging.info(f"MQTT 已清理失效户号 {masked} 的 {len(keys)} 个 Discovery 配置。")
            return bool(keys)
        except Exception as e:
            logging.warning(f"MQTT 账户 Discovery 清理失败: {e}")
            return False

    def _publish(self, topic: str, payload: Any, retain: bool = False) -> None:
        result = self.client.publish(topic, payload=payload, retain=retain)
        rc = getattr(result, "rc", 0)
        if rc != 0:
            raise RuntimeError(f"publish rc={rc} topic={topic}")

    def _sensor_specs(self, account_data: AccountData, masked: str, device: dict) -> list[dict]:
        balance = account_data.balance
        latest_daily = self._latest_daily(account_data.daily)
        latest_monthly = self._latest_monthly(account_data.monthly)
        yearly = account_data.yearly
        month_tou = self._month_tou(account_data.daily)

        return [
            {
                "key": "balance",
                "name": f"电费余额 {masked}",
                "value": balance.balance_cny if balance else None,
                "unit_of_measurement": "CNY",
                "device_class": "monetary",
                "state_class": "total",
            },
            {
                "key": "prepay_balance",
                "name": f"预付费余额 {masked}",
                "value": balance.prepay_balance_cny if balance else None,
                "unit_of_measurement": "CNY",
                "device_class": "monetary",
                "state_class": "total",
            },
            {
                "key": "arrears",
                "name": f"应交金额 {masked}",
                "value": balance.arrears_cny if balance else None,
                "unit_of_measurement": "CNY",
                "device_class": "monetary",
                "state_class": "total",
            },
            {
                "key": "last_daily_usage",
                "name": f"最近日用电 {masked}",
                "value": latest_daily.total_usage_kwh if latest_daily else None,
                "unit_of_measurement": "kWh",
                "device_class": "energy",
                "state_class": "measurement",
                "attributes": self._daily_attributes(latest_daily),
            },
            {
                "key": "month_usage",
                "name": f"月度用电 {masked}",
                "value": latest_monthly.total_usage_kwh if latest_monthly else None,
                "unit_of_measurement": "kWh",
                "device_class": "energy",
                "state_class": "measurement",
                "attributes": self._monthly_attributes(latest_monthly),
            },
            {
                "key": "month_charge",
                "name": f"月度电费 {masked}",
                "value": latest_monthly.total_charge_cny if latest_monthly else None,
                "unit_of_measurement": "CNY",
                "device_class": "monetary",
                "state_class": "measurement",
                "attributes": self._monthly_attributes(latest_monthly),
            },
            {
                "key": "month_valley",
                "name": f"月度谷时电量 {masked}",
                "value": month_tou["valley"],
                "delete_when_none": False,
                "unit_of_measurement": "kWh",
                "device_class": "energy",
                "state_class": "measurement",
                "attributes": self._tou_attributes(account_data.daily),
            },
            {
                "key": "month_flat",
                "name": f"月度平时电量 {masked}",
                "value": month_tou["flat"],
                "delete_when_none": False,
                "unit_of_measurement": "kWh",
                "device_class": "energy",
                "state_class": "measurement",
                "attributes": self._tou_attributes(account_data.daily),
            },
            {
                "key": "month_peak",
                "name": f"月度峰时电量 {masked}",
                "value": month_tou["peak"],
                "delete_when_none": False,
                "unit_of_measurement": "kWh",
                "device_class": "energy",
                "state_class": "measurement",
                "attributes": self._tou_attributes(account_data.daily),
            },
            {
                "key": "month_tip",
                "name": f"月度尖时电量 {masked}",
                "value": month_tou["tip"],
                "delete_when_none": False,
                "unit_of_measurement": "kWh",
                "device_class": "energy",
                "state_class": "measurement",
                "attributes": self._tou_attributes(account_data.daily),
            },
            {
                "key": "year_usage",
                "name": f"年度用电 {masked}",
                "value": yearly.total_usage_kwh if yearly else None,
                "unit_of_measurement": "kWh",
                "device_class": "energy",
                "state_class": "total_increasing",
            },
            {
                "key": "year_charge",
                "name": f"年度电费 {masked}",
                "value": yearly.total_charge_cny if yearly else None,
                "unit_of_measurement": "CNY",
                "device_class": "monetary",
                "state_class": "total_increasing",
            },
            {
                "key": "history",
                "name": f"历史数据 {masked}",
                "value": self._history_state(account_data),
                "icon": "mdi:history",
                "attributes": self._history_attributes(account_data),
            },
            *self._daily_history_sensor_specs(account_data, masked),
            *self._monthly_history_sensor_specs(account_data, masked),
            *self._yearly_history_sensor_specs(account_data, masked),
        ]


    @staticmethod
    def _daily_attributes(row: Optional[DailyReading]) -> dict[str, Any]:
        return {
            "date": row.date if row else None,
            "valley_kwh": row.valley_usage_kwh if row else None,
            "flat_kwh": row.flat_usage_kwh if row else None,
            "peak_kwh": row.peak_usage_kwh if row else None,
            "tip_kwh": row.tip_usage_kwh if row else None,
        }

    @staticmethod
    def _monthly_attributes(row: Optional[MonthlyReading]) -> dict[str, Any]:
        return {
            "month": row.year_month if row else None,
            "begin_date": row.begin_date if row else None,
            "end_date": row.end_date if row else None,
        }

    @staticmethod
    def _tou_attributes(rows: list[DailyReading]) -> dict[str, Any]:
        month_prefix = MqttPublisher._tou_month_prefix(rows)
        current_rows = [row for row in rows if str(row.date or "")[:7] == month_prefix]
        return {
            "month": month_prefix,
            "daily_count": len(current_rows),
            "source": "daily_readings_current_month" if month_prefix == datetime.now().strftime("%Y-%m") else "daily_readings_latest_available_month",
        }

    @staticmethod
    def _history_state(account_data: AccountData) -> str:
        daily_count = len(account_data.daily)
        monthly_count = len(account_data.monthly)
        latest_daily = MqttPublisher._latest_daily(account_data.daily)
        latest_monthly = MqttPublisher._latest_monthly(account_data.monthly)
        if latest_daily and latest_daily.date:
            latest = latest_daily.date
        elif latest_monthly and latest_monthly.year_month:
            latest = latest_monthly.year_month
        elif account_data.yearly and account_data.yearly.year:
            latest = account_data.yearly.year
        else:
            latest = "no-data"
        return f"{latest} d{daily_count} m{monthly_count}"

    @staticmethod
    def _history_attributes(account_data: AccountData) -> dict[str, Any]:
        yearly = account_data.yearly
        latest_daily = MqttPublisher._latest_daily(account_data.daily)
        latest_monthly = MqttPublisher._latest_monthly(account_data.monthly)
        daily_dates = sorted(row.date for row in account_data.daily if row.date)
        monthly_keys = sorted(row.year_month for row in account_data.monthly if row.year_month)
        return {
            "latest_daily_date": latest_daily.date if latest_daily else None,
            "daily_start_date": daily_dates[0] if daily_dates else None,
            "daily_end_date": daily_dates[-1] if daily_dates else None,
            "latest_month": latest_monthly.year_month if latest_monthly else None,
            "monthly_start": monthly_keys[0] if monthly_keys else None,
            "monthly_end": monthly_keys[-1] if monthly_keys else None,
            "year": yearly.year if yearly else None,
            "year_usage_kwh": yearly.total_usage_kwh if yearly else None,
            "year_charge_cny": yearly.total_charge_cny if yearly else None,
            "monthly_count": len(account_data.monthly),
            "daily_count": len(account_data.daily),
            "monthly": [
                {
                    "month": row.year_month,
                    "usage_kwh": row.total_usage_kwh,
                    "charge_cny": row.total_charge_cny,
                    "begin_date": row.begin_date,
                    "end_date": row.end_date,
                }
                for row in account_data.monthly
            ],
            "daily": [
                {
                    "date": row.date,
                    "usage_kwh": row.total_usage_kwh,
                    "valley_kwh": row.valley_usage_kwh,
                    "flat_kwh": row.flat_usage_kwh,
                    "peak_kwh": row.peak_usage_kwh,
                    "tip_kwh": row.tip_usage_kwh,
                }
                for row in account_data.daily
            ],
        }

    @staticmethod
    def _daily_history_sensor_specs(account_data: AccountData, masked: str) -> list[dict[str, Any]]:
        specs: list[dict[str, Any]] = []
        rows = sorted(
            [row for row in account_data.daily if row.date],
            key=lambda row: row.date,
            reverse=True,
        )
        for row in rows:
            key_suffix = row.date.replace("-", "")
            specs.append({
                "key": f"daily_{key_suffix}",
                "name": f"日用电 {row.date} {masked}",
                "value": row.total_usage_kwh,
                "unit_of_measurement": "kWh",
                "device_class": "energy",
                "state_class": "measurement",
                "attributes": {
                    "date": row.date,
                    "valley_kwh": row.valley_usage_kwh,
                    "flat_kwh": row.flat_usage_kwh,
                    "peak_kwh": row.peak_usage_kwh,
                    "tip_kwh": row.tip_usage_kwh,
                },
            })
        return specs

    @staticmethod
    def _monthly_history_sensor_specs(account_data: AccountData, masked: str) -> list[dict[str, Any]]:
        specs: list[dict[str, Any]] = []
        rows = sorted(
            [row for row in account_data.monthly if row.year_month],
            key=lambda row: row.year_month,
            reverse=True,
        )
        for row in rows:
            key_suffix = row.year_month.replace("-", "")
            specs.append({
                "key": f"monthly_{key_suffix}",
                "name": f"月度历史 {row.year_month} {masked}",
                "value": row.total_usage_kwh,
                "unit_of_measurement": "kWh",
                "device_class": "energy",
                "state_class": "measurement",
                "attributes": {
                    "month": row.year_month,
                    "charge_cny": row.total_charge_cny,
                    "begin_date": row.begin_date,
                    "end_date": row.end_date,
                },
            })
        return specs

    @staticmethod
    def _yearly_history_sensor_specs(account_data: AccountData, masked: str) -> list[dict[str, Any]]:
        yearly = account_data.yearly
        if yearly is None or not yearly.year:
            return []
        return [{
            "key": f"year_{yearly.year}",
            "name": f"年度历史 {yearly.year} {masked}",
            "value": yearly.total_usage_kwh,
            "unit_of_measurement": "kWh",
            "device_class": "energy",
            "state_class": "total_increasing",
            "attributes": {
                "year": yearly.year,
                "charge_cny": yearly.total_charge_cny,
            },
        }]

    @staticmethod
    def _latest_daily(rows: list[DailyReading]) -> Optional[DailyReading]:
        dated = [row for row in rows if row.date]
        return max(dated, key=lambda row: row.date) if dated else None

    @staticmethod
    def _latest_monthly(rows: list[MonthlyReading]) -> Optional[MonthlyReading]:
        dated = [row for row in rows if row.year_month]
        return max(dated, key=lambda row: row.year_month) if dated else None

    @staticmethod
    def _month_tou(rows: list[DailyReading]) -> dict[str, Optional[float]]:
        month_prefix = MqttPublisher._tou_month_prefix(rows)
        current_rows = [row for row in rows if str(row.date or "")[:7] == month_prefix]
        if not current_rows:
            return {"valley": None, "flat": None, "peak": None, "tip": None}
        return {
            "valley": sum(row.valley_usage_kwh or 0 for row in current_rows),
            "flat": sum(row.flat_usage_kwh or 0 for row in current_rows),
            "peak": sum(row.peak_usage_kwh or 0 for row in current_rows),
            "tip": sum(row.tip_usage_kwh or 0 for row in current_rows),
        }

    @staticmethod
    def _tou_month_prefix(rows: list[DailyReading]) -> str:
        current_month_prefix = datetime.now().strftime("%Y-%m")
        if any(str(row.date or "")[:7] == current_month_prefix for row in rows):
            return current_month_prefix
        dated_months = sorted({str(row.date or "")[:7] for row in rows if str(row.date or "")[:7]})
        return dated_months[-1] if dated_months else current_month_prefix

    @staticmethod
    def _safe_topic_part(value: str) -> str:
        return value.replace("*", "x").replace("/", "_").replace(" ", "_")

    @staticmethod
    def _format_value(value: Any) -> str:
        if isinstance(value, float):
            return str(round(value, 4))
        return str(value)
