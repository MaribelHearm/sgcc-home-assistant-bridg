import json
import unittest
from datetime import datetime
from types import SimpleNamespace

import mqtt_publisher
from config import FetcherConfig
from model import Account, AccountData, Balance, DailyReading, MonthlyReading, YearlyReading
from mqtt_publisher import MqttPublisher


class FakeClient:
    instances = []

    def __init__(self, *args, **kwargs):
        self.published = []
        self.username = None
        self.password = None
        self.connected_to = None
        FakeClient.instances.append(self)

    def username_pw_set(self, username, password=None):
        self.username = username
        self.password = password

    def connect(self, host, port, keepalive=60):
        self.connected_to = (host, port, keepalive)
        return 0

    def loop_start(self):
        pass

    def loop_stop(self):
        pass

    def disconnect(self):
        pass

    def publish(self, topic, payload=None, retain=False):
        self.published.append((topic, payload, retain))
        return SimpleNamespace(rc=0)


class MqttPublisherTestCase(unittest.TestCase):
    def setUp(self):
        FakeClient.instances.clear()
        self.original_mqtt = mqtt_publisher.mqtt
        mqtt_publisher.mqtt = SimpleNamespace(
            Client=FakeClient,
            CallbackAPIVersion=SimpleNamespace(VERSION2=object()),
        )

    def tearDown(self):
        mqtt_publisher.mqtt = self.original_mqtt

    def test_publish_account_data_emits_discovery_and_state_without_full_account_no(self):
        current_month = "2026-06"
        current_day = "2026-06-18"
        account_no = "1234567890123"
        cfg = FetcherConfig(
            MQTT_HOST="broker.local",
            MQTT_USERNAME="user",
            MQTT_PASSWORD="pass",
            MQTT_DISCOVERY_PREFIX="homeassistant",
        )
        publisher = MqttPublisher(cfg)
        self.assertTrue(publisher.connect())

        data = AccountData(
            account=Account(account_no=account_no),
            balance=Balance(
                account_no=account_no,
                observed_at="2026-06-18T08:00:00+08:00",
                balance_cny=88.12,
                prepay_balance_cny=12.34,
                arrears_cny=0.56,
            ),
            yearly=YearlyReading(
                account_no=account_no,
                year="2026",
                total_usage_kwh=321.0,
                total_charge_cny=123.45,
            ),
            monthly=[
                MonthlyReading(
                    account_no=account_no,
                    year_month=current_month,
                    total_usage_kwh=56.7,
                    total_charge_cny=23.45,
                    begin_date=f"{current_month}-01",
                    end_date=f"{current_month}-30",
                ),
                MonthlyReading(
                    account_no=account_no,
                    year_month="2026-05",
                    total_usage_kwh=45.6,
                    total_charge_cny=20.01,
                    begin_date="2026-05-01",
                    end_date="2026-05-31",
                )
            ],
            daily=[
                DailyReading(
                    account_no=account_no,
                    date=f"{current_month}-17",
                    total_usage_kwh=6.5,
                    valley_usage_kwh=1.0,
                    flat_usage_kwh=2.0,
                    peak_usage_kwh=3.0,
                    tip_usage_kwh=0.5,
                ),
                DailyReading(
                    account_no=account_no,
                    date=current_day,
                    total_usage_kwh=7.5,
                    valley_usage_kwh=1.5,
                    flat_usage_kwh=2.5,
                    peak_usage_kwh=3.5,
                    tip_usage_kwh=0.0,
                ),
                DailyReading(
                    account_no=account_no,
                    date=f"{current_month}-16",
                    total_usage_kwh=5.5,
                    valley_usage_kwh=0.5,
                    flat_usage_kwh=1.5,
                    peak_usage_kwh=2.5,
                    tip_usage_kwh=1.0,
                ),
            ],
        )

        self.assertTrue(publisher.publish_account_data(data))
        client = FakeClient.instances[-1]
        all_text = "\n".join(f"{topic} {payload}" for topic, payload, _ in client.published)
        self.assertNotIn(account_no, all_text)
        self.assertIn("*********0123", all_text)

        config_messages = {
            topic: json.loads(payload)
            for topic, payload, retain in client.published
            if topic.endswith("/config")
        }
        state_messages = {
            topic: payload
            for topic, payload, retain in client.published
            if topic.endswith("/state")
        }

        balance_topic = "homeassistant/sensor/sgcc_xxxxxxxxx0123/balance/config"
        self.assertIn(balance_topic, config_messages)
        balance_payload = config_messages[balance_topic]
        self.assertEqual(balance_payload["unique_id"], "sgcc_*********0123_balance")
        self.assertEqual(balance_payload["state_topic"], "sgcc/sgcc_xxxxxxxxx0123/balance/state")
        self.assertEqual(balance_payload["unit_of_measurement"], "CNY")
        self.assertEqual(balance_payload["device_class"], "monetary")
        self.assertEqual(balance_payload["state_class"], "total")
        self.assertEqual(balance_payload["device"]["identifiers"], ["sgcc_*********0123"])
        self.assertEqual(balance_payload["device"]["name"], "国网电费 *********0123")
        self.assertEqual(balance_payload["device"]["manufacturer"], "SGCC bridge")
        self.assertTrue(next(retain for topic, _, retain in client.published if topic == balance_topic))
        self.assertTrue(next(retain for topic, _, retain in client.published if topic == "sgcc/sgcc_xxxxxxxxx0123/balance/state"))
        self.assertEqual(state_messages["sgcc/sgcc_xxxxxxxxx0123/balance/state"], "88.12")

        month_valley_config = config_messages[
            "homeassistant/sensor/sgcc_xxxxxxxxx0123/month_valley/config"
        ]
        self.assertEqual(month_valley_config["unit_of_measurement"], "kWh")
        self.assertEqual(month_valley_config["device_class"], "energy")
        self.assertEqual(month_valley_config["state_class"], "measurement")
        self.assertEqual(state_messages["sgcc/sgcc_xxxxxxxxx0123/month_valley/state"], "3.0")

        self.assertIn("homeassistant/sensor/sgcc_xxxxxxxxx0123/year_usage/config", config_messages)
        self.assertEqual(
            config_messages["homeassistant/sensor/sgcc_xxxxxxxxx0123/year_usage/config"]["state_class"],
            "total_increasing",
        )

        history_topic = "homeassistant/sensor/sgcc_xxxxxxxxx0123/history/config"
        self.assertIn(history_topic, config_messages)
        history_payload = config_messages[history_topic]
        self.assertEqual(history_payload["object_id"], "sgcc_0123_history")
        self.assertEqual(history_payload["json_attributes_topic"], "sgcc/sgcc_xxxxxxxxx0123/history/attributes")
        self.assertEqual(state_messages["sgcc/sgcc_xxxxxxxxx0123/history/state"], f"{current_day} d3 m2")
        history_attrs = json.loads(
            state_messages.get("sgcc/sgcc_xxxxxxxxx0123/history/attributes")
            or next(payload for topic, payload, _ in client.published if topic == "sgcc/sgcc_xxxxxxxxx0123/history/attributes")
        )
        self.assertEqual(history_attrs["daily_count"], 3)
        self.assertEqual(history_attrs["daily_start_date"], f"{current_month}-16")
        self.assertEqual(history_attrs["daily_end_date"], current_day)
        self.assertEqual(history_attrs["monthly_count"], 2)
        self.assertEqual(history_attrs["monthly_start"], "2026-05")
        self.assertEqual(history_attrs["monthly_end"], current_month)
        self.assertEqual(history_attrs["daily"][0]["valley_kwh"], 1.0)
        self.assertEqual(history_attrs["daily"][1]["peak_kwh"], 3.5)

        daily_latest_topic = "homeassistant/sensor/sgcc_xxxxxxxxx0123/daily_20260618/config"
        monthly_latest_topic = "homeassistant/sensor/sgcc_xxxxxxxxx0123/monthly_202606/config"
        monthly_prev_topic = "homeassistant/sensor/sgcc_xxxxxxxxx0123/monthly_202605/config"
        yearly_topic = "homeassistant/sensor/sgcc_xxxxxxxxx0123/year_2026/config"

        self.assertIn(daily_latest_topic, config_messages)
        self.assertIn(monthly_latest_topic, config_messages)
        self.assertIn(monthly_prev_topic, config_messages)
        self.assertIn(yearly_topic, config_messages)

        daily_latest_payload = config_messages[daily_latest_topic]
        self.assertEqual(daily_latest_payload["name"], f"日用电 {current_day} *********0123")
        self.assertEqual(daily_latest_payload["state_topic"], "sgcc/sgcc_xxxxxxxxx0123/daily_20260618/state")
        self.assertEqual(daily_latest_payload["json_attributes_topic"], "sgcc/sgcc_xxxxxxxxx0123/daily_20260618/attributes")
        self.assertEqual(daily_latest_payload["unit_of_measurement"], "kWh")
        self.assertEqual(daily_latest_payload["device_class"], "energy")
        self.assertEqual(daily_latest_payload["state_class"], "measurement")
        self.assertEqual(state_messages["sgcc/sgcc_xxxxxxxxx0123/daily_20260618/state"], "7.5")
        daily_latest_attrs = json.loads(
            next(payload for topic, payload, _ in client.published if topic == "sgcc/sgcc_xxxxxxxxx0123/daily_20260618/attributes")
        )
        self.assertEqual(daily_latest_attrs["date"], current_day)
        self.assertEqual(daily_latest_attrs["peak_kwh"], 3.5)

        monthly_latest_payload = config_messages[monthly_latest_topic]
        self.assertEqual(monthly_latest_payload["name"], f"月度历史 {current_month} *********0123")
        self.assertEqual(monthly_latest_payload["state_topic"], "sgcc/sgcc_xxxxxxxxx0123/monthly_202606/state")
        self.assertEqual(monthly_latest_payload["json_attributes_topic"], "sgcc/sgcc_xxxxxxxxx0123/monthly_202606/attributes")
        self.assertEqual(state_messages["sgcc/sgcc_xxxxxxxxx0123/monthly_202606/state"], "56.7")
        monthly_latest_attrs = json.loads(
            next(payload for topic, payload, _ in client.published if topic == "sgcc/sgcc_xxxxxxxxx0123/monthly_202606/attributes")
        )
        self.assertEqual(monthly_latest_attrs["month"], current_month)
        self.assertEqual(monthly_latest_attrs["charge_cny"], 23.45)
        self.assertEqual(monthly_latest_attrs["begin_date"], f"{current_month}-01")
        self.assertEqual(monthly_latest_attrs["end_date"], f"{current_month}-30")

        yearly_payload = config_messages[yearly_topic]
        self.assertEqual(yearly_payload["name"], "年度历史 2026 *********0123")
        self.assertEqual(yearly_payload["state_topic"], "sgcc/sgcc_xxxxxxxxx0123/year_2026/state")
        self.assertEqual(yearly_payload["json_attributes_topic"], "sgcc/sgcc_xxxxxxxxx0123/year_2026/attributes")
        self.assertEqual(yearly_payload["state_class"], "total_increasing")
        self.assertEqual(state_messages["sgcc/sgcc_xxxxxxxxx0123/year_2026/state"], "321.0")
        yearly_attrs = json.loads(
            next(payload for topic, payload, _ in client.published if topic == "sgcc/sgcc_xxxxxxxxx0123/year_2026/attributes")
        )
        self.assertEqual(yearly_attrs["year"], "2026")
        self.assertEqual(yearly_attrs["charge_cny"], 123.45)

    def test_publish_account_data_rejects_account_without_business_values(self):
        account_no = "1234567890123"
        cfg = FetcherConfig(
            MQTT_HOST="broker.local",
            MQTT_DISCOVERY_PREFIX="homeassistant",
        )
        publisher = MqttPublisher(cfg)
        self.assertTrue(publisher.connect())

        data = AccountData(account=Account(account_no=account_no))

        self.assertFalse(publisher.publish_account_data(data))
        client = FakeClient.instances[-1]
        self.assertEqual(client.published, [])



if __name__ == "__main__":
    unittest.main()
