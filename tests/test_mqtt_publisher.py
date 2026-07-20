import json
import unittest
from unittest import mock
from datetime import datetime
from types import SimpleNamespace

from sgcc_ha_bridge import mqtt_publisher
from sgcc_ha_bridge.config import FetcherConfig
from sgcc_ha_bridge.entity_identity import account_entity_key
from sgcc_ha_bridge.model import Account, AccountData, Balance, DailyReading, MonthlyReading, YearlyReading
from sgcc_ha_bridge.mqtt_publisher import MqttPublisher


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

    def test_accounts_with_same_last_four_digits_use_distinct_nodes(self):
        cfg = FetcherConfig(
            MQTT_HOST="broker.local",
            MQTT_DISCOVERY_PREFIX="homeassistant",
        )
        publisher = MqttPublisher(cfg)
        self.assertTrue(publisher.connect())
        accounts = ("1234567891234", "9999999991234")
        for account_no in accounts:
            self.assertTrue(publisher.publish_account_data(AccountData(
                account=Account(account_no=account_no),
                balance=Balance(
                    account_no=account_no,
                    observed_at="2026-07-11T10:00:00+08:00",
                    balance_cny=10,
                ),
            )))

        active_balance_topics = {
            topic
            for topic, payload, _ in FakeClient.instances[-1].published
            if topic.endswith("/balance/config") and payload
        }
        self.assertEqual(len(active_balance_topics), 2)
        self.assertNotEqual(
            account_entity_key(accounts[0]),
            account_entity_key(accounts[1]),
        )

    def test_legacy_action_is_not_applied_before_canonical_publish_succeeds(self):
        account_no = "1234567890123"
        publisher = MqttPublisher(FetcherConfig(
            MQTT_HOST="broker.local",
            MQTT_DISCOVERY_PREFIX="homeassistant",
        ))
        self.assertTrue(publisher.connect())
        data = AccountData(
            account=Account(account_no=account_no),
            balance=Balance(
                account_no=account_no,
                observed_at="2026-07-11T10:00:00+08:00",
                balance_cny=10,
            ),
        )

        with (
            mock.patch.object(
                publisher,
                "_publish",
                side_effect=RuntimeError("new discovery publish failed"),
            ),
            mock.patch.object(publisher, "_publish_legacy_aliases") as publish_legacy,
            mock.patch.object(publisher, "remove_legacy_discovery") as remove_legacy,
        ):
            self.assertFalse(publisher.publish_account_data(
                data,
                legacy_action="publish",
            ))

        publish_legacy.assert_not_called()
        remove_legacy.assert_not_called()

    def test_publish_legacy_aliases_preserves_v015_identity_and_uses_canonical_state(self):
        account_no = "1234567890123"
        publisher = MqttPublisher(FetcherConfig(
            MQTT_HOST="broker.local",
            MQTT_DISCOVERY_PREFIX="homeassistant",
        ))
        self.assertTrue(publisher.connect())
        data = AccountData(
            account=Account(account_no=account_no),
            balance=Balance(
                account_no=account_no,
                observed_at="2026-07-11T10:00:00+08:00",
                balance_cny=10,
            ),
        )

        self.assertTrue(publisher.publish_account_data(
            data,
            legacy_action="publish",
        ))

        messages = {
            topic: payload
            for topic, payload, _ in FakeClient.instances[-1].published
        }
        legacy_topic = "homeassistant/sensor/sgcc_xxxxxxxxx0123/balance/config"
        self.assertIn(legacy_topic, messages)
        payload = json.loads(messages[legacy_topic])
        canonical_node = f"sgcc_{account_entity_key(account_no)}"
        self.assertEqual(payload["unique_id"], "sgcc_*********0123_balance")
        self.assertEqual(payload["object_id"], "sgcc_0123_balance")
        self.assertNotIn("default_entity_id", payload)
        self.assertEqual(payload["state_topic"], f"sgcc/{canonical_node}/balance/state")
        self.assertNotIn(account_no, json.dumps(payload, ensure_ascii=False))

    def test_legacy_remove_action_tombstones_after_canonical_publish(self):
        account_no = "1234567890123"
        publisher = MqttPublisher(FetcherConfig(
            MQTT_HOST="broker.local",
            MQTT_DISCOVERY_PREFIX="homeassistant",
        ))
        self.assertTrue(publisher.connect())
        data = AccountData(
            account=Account(account_no=account_no),
            balance=Balance(
                account_no=account_no,
                observed_at="2026-07-11T10:00:00+08:00",
                balance_cny=10,
            ),
        )

        self.assertTrue(publisher.publish_account_data(
            data,
            legacy_action="remove",
        ))
        legacy_messages = [
            (topic, payload, retain)
            for topic, payload, retain in FakeClient.instances[-1].published
            if "/sgcc_xxxxxxxxx0123/" in topic
        ]
        self.assertTrue(legacy_messages)
        self.assertTrue(all(payload == "" and retain for _, payload, retain in legacy_messages))

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

        with mock.patch.object(mqtt_publisher, "datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2026, 6, 18)
            self.assertTrue(publisher.publish_account_data(data))
        client = FakeClient.instances[-1]
        all_text = "\n".join(f"{topic} {payload}" for topic, payload, _ in client.published)
        self.assertNotIn(account_no, all_text)
        self.assertIn("*********0123", all_text)

        config_messages = {
            topic: json.loads(payload)
            for topic, payload, retain in client.published
            if topic.endswith("/config") and payload
        }
        state_messages = {
            topic: payload
            for topic, payload, retain in client.published
            if topic.endswith("/state")
        }

        node = f"sgcc_{account_entity_key(account_no)}"
        balance_topic = f"homeassistant/sensor/{node}/balance/config"
        self.assertIn(balance_topic, config_messages)
        balance_payload = config_messages[balance_topic]
        self.assertEqual(
            balance_payload["unique_id"],
            f"sgcc_{account_entity_key(account_no)}_balance",
        )
        self.assertEqual(
            balance_payload["default_entity_id"],
            f"sensor.sgcc_{account_entity_key(account_no)}_balance",
        )
        self.assertEqual(balance_payload["state_topic"], f"sgcc/{node}/balance/state")
        self.assertEqual(balance_payload["unit_of_measurement"], "CNY")
        self.assertEqual(balance_payload["device_class"], "monetary")
        self.assertEqual(balance_payload["state_class"], "total")
        self.assertEqual(balance_payload["device"]["identifiers"], [node])
        self.assertEqual(balance_payload["device"]["name"], "国网电费 *********0123")
        self.assertEqual(balance_payload["device"]["manufacturer"], "SGCC bridge")
        self.assertTrue(next(retain for topic, _, retain in client.published if topic == balance_topic))
        self.assertTrue(next(retain for topic, _, retain in client.published if topic == f"sgcc/{node}/balance/state"))
        self.assertEqual(state_messages[f"sgcc/{node}/balance/state"], "88.12")

        month_valley_config = config_messages[
            f"homeassistant/sensor/{node}/month_valley/config"
        ]
        self.assertEqual(month_valley_config["unit_of_measurement"], "kWh")
        self.assertEqual(month_valley_config["device_class"], "energy")
        self.assertEqual(month_valley_config["state_class"], "measurement")
        self.assertEqual(state_messages[f"sgcc/{node}/month_valley/state"], "3.0")

        self.assertIn(f"homeassistant/sensor/{node}/year_usage/config", config_messages)
        self.assertEqual(
            config_messages[f"homeassistant/sensor/{node}/year_usage/config"]["state_class"],
            "total_increasing",
        )

        history_topic = f"homeassistant/sensor/{node}/history/config"
        self.assertIn(history_topic, config_messages)
        history_payload = config_messages[history_topic]
        self.assertEqual(
            history_payload["object_id"],
            f"sgcc_{account_entity_key(account_no)}_history",
        )
        self.assertEqual(history_payload["json_attributes_topic"], f"sgcc/{node}/history/attributes")
        self.assertEqual(state_messages[f"sgcc/{node}/history/state"], f"{current_day} d3 m2")
        history_attrs = json.loads(
            state_messages.get(f"sgcc/{node}/history/attributes")
            or next(payload for topic, payload, _ in client.published if topic == f"sgcc/{node}/history/attributes")
        )
        self.assertEqual(history_attrs["daily_count"], 3)
        self.assertEqual(history_attrs["daily_start_date"], f"{current_month}-16")
        self.assertEqual(history_attrs["daily_end_date"], current_day)
        self.assertEqual(history_attrs["monthly_count"], 2)
        self.assertEqual(history_attrs["monthly_start"], "2026-05")
        self.assertEqual(history_attrs["monthly_end"], current_month)
        self.assertEqual(history_attrs["daily"][0]["valley_kwh"], 1.0)
        self.assertEqual(history_attrs["daily"][1]["peak_kwh"], 3.5)

        daily_latest_topic = f"homeassistant/sensor/{node}/daily_20260618/config"
        monthly_latest_topic = f"homeassistant/sensor/{node}/monthly_202606/config"
        monthly_prev_topic = f"homeassistant/sensor/{node}/monthly_202605/config"
        yearly_topic = f"homeassistant/sensor/{node}/year_2026/config"

        self.assertIn(daily_latest_topic, config_messages)
        self.assertIn(monthly_latest_topic, config_messages)
        self.assertIn(monthly_prev_topic, config_messages)
        self.assertIn(yearly_topic, config_messages)

        daily_latest_payload = config_messages[daily_latest_topic]
        self.assertEqual(daily_latest_payload["name"], f"日用电 {current_day} *********0123")
        self.assertEqual(daily_latest_payload["state_topic"], f"sgcc/{node}/daily_20260618/state")
        self.assertEqual(daily_latest_payload["json_attributes_topic"], f"sgcc/{node}/daily_20260618/attributes")
        self.assertEqual(daily_latest_payload["unit_of_measurement"], "kWh")
        self.assertEqual(daily_latest_payload["device_class"], "energy")
        self.assertEqual(daily_latest_payload["state_class"], "measurement")
        self.assertEqual(state_messages[f"sgcc/{node}/daily_20260618/state"], "7.5")
        daily_latest_attrs = json.loads(
            next(payload for topic, payload, _ in client.published if topic == f"sgcc/{node}/daily_20260618/attributes")
        )
        self.assertEqual(daily_latest_attrs["date"], current_day)
        self.assertEqual(daily_latest_attrs["peak_kwh"], 3.5)

        monthly_latest_payload = config_messages[monthly_latest_topic]
        self.assertEqual(monthly_latest_payload["name"], f"月度历史 {current_month} *********0123")
        self.assertEqual(monthly_latest_payload["state_topic"], f"sgcc/{node}/monthly_202606/state")
        self.assertEqual(monthly_latest_payload["json_attributes_topic"], f"sgcc/{node}/monthly_202606/attributes")
        self.assertEqual(state_messages[f"sgcc/{node}/monthly_202606/state"], "56.7")
        monthly_latest_attrs = json.loads(
            next(payload for topic, payload, _ in client.published if topic == f"sgcc/{node}/monthly_202606/attributes")
        )
        self.assertEqual(monthly_latest_attrs["month"], current_month)
        self.assertEqual(monthly_latest_attrs["charge_cny"], 23.45)
        self.assertEqual(monthly_latest_attrs["begin_date"], f"{current_month}-01")
        self.assertEqual(monthly_latest_attrs["end_date"], f"{current_month}-30")

        yearly_payload = config_messages[yearly_topic]
        self.assertEqual(yearly_payload["name"], "年度历史 2026 *********0123")
        self.assertEqual(yearly_payload["state_topic"], f"sgcc/{node}/year_2026/state")
        self.assertEqual(yearly_payload["json_attributes_topic"], f"sgcc/{node}/year_2026/attributes")
        self.assertEqual(yearly_payload["state_class"], "total_increasing")
        self.assertEqual(state_messages[f"sgcc/{node}/year_2026/state"], "321.0")
        yearly_attrs = json.loads(
            next(payload for topic, payload, _ in client.published if topic == f"sgcc/{node}/year_2026/attributes")
        )
        self.assertEqual(yearly_attrs["year"], "2026")
        self.assertEqual(yearly_attrs["charge_cny"], 123.45)


    def test_publish_skips_entities_without_state_values(self):
        account_no = "1234567890123"
        cfg = FetcherConfig(
            MQTT_HOST="broker.local",
            MQTT_DISCOVERY_PREFIX="homeassistant",
        )
        publisher = MqttPublisher(cfg)
        self.assertTrue(publisher.connect())

        data = AccountData(
            account=Account(account_no=account_no),
            balance=Balance(
                account_no=account_no,
                observed_at="2026-06-21T18:03:34+08:00",
                balance_cny=None,
                prepay_balance_cny=127.5,
                arrears_cny=70.0,
            ),
        )

        self.assertTrue(publisher.publish_account_data(data))
        config_messages = {
            topic: payload
            for topic, payload, _ in FakeClient.instances[-1].published
            if topic.endswith("/config")
        }
        active_config_topics = {topic for topic, payload in config_messages.items() if payload}
        state_messages = {topic: payload for topic, payload, _ in FakeClient.instances[-1].published if topic.endswith("/state")}
        node = f"sgcc_{account_entity_key(account_no)}"

        self.assertEqual(config_messages[f"homeassistant/sensor/{node}/balance/config"], "")
        self.assertNotIn(f"homeassistant/sensor/{node}/balance/config", active_config_topics)
        self.assertNotIn("homeassistant/sensor/sgcc_xxxxxxxxx0123/balance/config", config_messages)
        self.assertNotIn(f"homeassistant/sensor/{node}/month_valley/config", config_messages)
        self.assertNotIn(f"homeassistant/sensor/{node}/month_flat/config", config_messages)
        self.assertNotIn(f"homeassistant/sensor/{node}/month_peak/config", config_messages)
        self.assertNotIn(f"homeassistant/sensor/{node}/month_tip/config", config_messages)
        self.assertIn(f"homeassistant/sensor/{node}/prepay_balance/config", active_config_topics)
        self.assertIn(f"homeassistant/sensor/{node}/arrears/config", active_config_topics)
        self.assertEqual(state_messages[f"sgcc/{node}/prepay_balance/state"], "127.5")
        self.assertEqual(state_messages[f"sgcc/{node}/arrears/state"], "70.0")

    def test_month_tou_falls_back_to_latest_available_month(self):
        account_no = "1234567890123"
        cfg = FetcherConfig(
            MQTT_HOST="broker.local",
            MQTT_DISCOVERY_PREFIX="homeassistant",
        )
        publisher = MqttPublisher(cfg)
        self.assertTrue(publisher.connect())

        data = AccountData(
            account=Account(account_no=account_no),
            monthly=[
                MonthlyReading(
                    account_no=account_no,
                    year_month="2026-05",
                    total_usage_kwh=56.7,
                    total_charge_cny=23.45,
                ),
            ],
            daily=[
                DailyReading(
                    account_no=account_no,
                    date="2026-06-29",
                    total_usage_kwh=6.5,
                    valley_usage_kwh=1.0,
                    flat_usage_kwh=2.0,
                    peak_usage_kwh=3.0,
                    tip_usage_kwh=0.5,
                ),
                DailyReading(
                    account_no=account_no,
                    date="2026-06-30",
                    total_usage_kwh=7.5,
                    valley_usage_kwh=1.5,
                    flat_usage_kwh=2.5,
                    peak_usage_kwh=3.5,
                    tip_usage_kwh=0.0,
                ),
            ],
        )

        self.assertTrue(publisher.publish_account_data(data))
        config_messages = {
            topic: json.loads(payload)
            for topic, payload, _ in FakeClient.instances[-1].published
            if topic.endswith("/config") and payload
        }
        state_messages = {
            topic: payload
            for topic, payload, _ in FakeClient.instances[-1].published
            if topic.endswith("/state")
        }

        node = f"sgcc_{account_entity_key(account_no)}"
        month_valley_topic = f"homeassistant/sensor/{node}/month_valley/config"
        self.assertIn(month_valley_topic, config_messages)
        self.assertEqual(state_messages[f"sgcc/{node}/month_valley/state"], "2.5")
        tou_attrs = json.loads(
            next(
                payload
                for topic, payload, _ in FakeClient.instances[-1].published
                if topic == f"sgcc/{node}/month_valley/attributes"
            )
        )
        self.assertEqual(tou_attrs["month"], "2026-06")
        self.assertEqual(tou_attrs["daily_count"], 2)
        self.assertIn(tou_attrs["source"], {
            "daily_readings_current_month",
            "daily_readings_latest_available_month",
        })

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

    def test_remove_account_data_clears_all_retained_discovery_configs(self):
        account_no = "1234567890123"
        publisher = MqttPublisher(FetcherConfig(
            MQTT_HOST="broker.local",
            MQTT_DISCOVERY_PREFIX="homeassistant",
        ))
        self.assertTrue(publisher.connect())
        data = AccountData(
            account=Account(account_no=account_no),
            yearly=YearlyReading(account_no=account_no, year="2026", total_usage_kwh=1.0),
            monthly=[MonthlyReading(
                account_no=account_no,
                year_month="2026-06",
                total_usage_kwh=1.0,
            )],
            daily=[DailyReading(
                account_no=account_no,
                date="2026-06-18",
                total_usage_kwh=1.0,
            )],
        )

        self.assertTrue(publisher.remove_account_data(
            data,
            remove_legacy=True,
        ))

        messages = FakeClient.instances[-1].published
        self.assertTrue(messages)
        self.assertTrue(all(topic.endswith("/config") for topic, _, _ in messages))
        self.assertTrue(all(payload == "" and retain for _, payload, retain in messages))
        topics = {topic for topic, _, _ in messages}
        self.assertIn(
            "homeassistant/sensor/sgcc_xxxxxxxxx0123/balance/config",
            topics,
        )
        self.assertIn(
            "homeassistant/sensor/sgcc_xxxxxxxxx0123/daily_20260618/config",
            topics,
        )
        self.assertIn(
            "homeassistant/sensor/sgcc_xxxxxxxxx0123/monthly_202606/config",
            topics,
        )
        self.assertIn(
            "homeassistant/sensor/sgcc_xxxxxxxxx0123/year_2026/config",
            topics,
        )
        self.assertNotIn(account_no, "\n".join(topics))



if __name__ == "__main__":
    unittest.main()
