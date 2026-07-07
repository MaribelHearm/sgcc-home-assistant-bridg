import os
import sys
import unittest


from sgcc_ha_bridge.parser import merge_account_data, parse_account_data


class ParserTestCase(unittest.TestCase):
    def test_parse_vuex_snapshot_extracts_account_balance_usage(self):
        store = {
            "state": {
                "account": {
                    "consNo": "1234567890123",
                    "consName_dst": "家庭用电",
                    "elecAddr_dst": "上海市某小区",
                    "proCode": "31",
                },
                "balance": {
                    "consNo": "1234567890123",
                    "amtTime": "2026-06-18T08:00:00+08:00",
                    "accountBalance": "88.12元",
                    "prepayBal": "12.34",
                    "historyOwe": "0.00",
                },
                "powerData": {
                    "dataInfo": {
                        "year": "2026",
                        "totalEleNum": "321.0",
                        "totalEleCost": "123.45",
                    },
                    "mothEleList": [
                        {
                            "month": "202606",
                            "monthEleNum": "56.7",
                            "monthEleCost": "23.45",
                            "begDate": "2026-06-01 00:00:00",
                            "endDate": "2026-06-30 23:59:59",
                        }
                    ],
                },
            }
        }
        components = [
            {
                "data": {
                    "sevenEleList": [
                        {
                            "day": "2026-06-17",
                            "dayElePq": "6.5",
                            "thisVPq": "1.0",
                            "thisNPq": "2.0",
                            "thisPPq": "3.0",
                            "thisTPq": "0.5",
                        }
                    ]
                }
            }
        ]

        data = parse_account_data(store=store, components=components)

        self.assertEqual(data.account.account_no, "1234567890123")
        self.assertEqual(data.account.display_name, "家庭用电")
        self.assertEqual(data.balance.balance_cny, 88.12)
        self.assertEqual(data.balance.prepay_balance_cny, 12.34)
        self.assertEqual(data.yearly.total_usage_kwh, 321.0)
        self.assertEqual(data.monthly[0].year_month, "2026-06")
        self.assertEqual(data.monthly[0].begin_date, "2026-06-01")
        self.assertEqual(data.daily[0].date, "2026-06-17")
        self.assertEqual(data.daily[0].peak_usage_kwh, 3.0)

    def test_parse_balance_prefers_scalar_amount_over_parent_container(self):
        store = {
            "state": {
                "account": {"consNo": "1234567890123", "elecAddr_dst": "addr"},
                "balance": {
                    "consNo": "1234567890123",
                    "amtTime": "2026-07-06 05:16:28",
                    "remainBalance": "155.31元",
                },
            }
        }

        data = parse_account_data(store=store)

        self.assertEqual(data.balance.observed_at, "2026-07-06 05:16:28")
        self.assertEqual(data.balance.balance_cny, 155.31)

    def test_empty_balance_container_does_not_mark_page_ready(self):
        data = parse_account_data(
            store={
                "state": {
                    "account": {"consNo": "1234567890123", "elecAddr_dst": "addr"},
                    "balance": {},
                }
            }
        )

        self.assertIsNone(data.balance)

    def test_parse_balance_from_user_acc_component_local_fields(self):
        components = [
            {
                "data": {
                    "accountNo": "*********9976",
                    "address": "*****",
                    "queryTime": "2026-07-06 18:20:00",
                    "accountBalance": "23.46元",
                }
            }
        ]

        data = parse_account_data(components=components)

        self.assertEqual(data.account.account_no, "*********9976")
        self.assertEqual(data.balance.account_no, "*********9976")
        self.assertEqual(data.balance.observed_at, "2026-07-06 18:20:00")
        self.assertEqual(data.balance.balance_cny, 23.46)
        self.assertIsNone(data.balance.prepay_balance_cny)

    def test_parse_balance_from_mixin_yue_sum_money_sample(self):
        components = [
            {
                "data": {
                    "mixinGetYuEdata": {
                        "consNo": "1234567895735",
                        "amtTime": "2026-07-07 05:15:50",
                        "estiAmt": "47.14",
                        "historyOwe": "0",
                        "prepayBal": "916.32",
                        "sumMoney": "869.18",
                    }
                }
            }
        ]

        data = parse_account_data(components=components)

        self.assertEqual(data.account.account_no, "1234567895735")
        self.assertEqual(data.balance.account_no, "1234567895735")
        self.assertEqual(data.balance.observed_at, "2026-07-07 05:15:50")
        self.assertEqual(data.balance.balance_cny, 869.18)
        self.assertEqual(data.balance.prepay_balance_cny, 916.32)
        self.assertEqual(data.balance.arrears_cny, 0.0)

    def test_parse_balance_from_mixin_yue_sum_money_with_zero_prepay_sample(self):
        components = [
            {
                "data": {
                    "mixinGetYuEdata": {
                        "consNo": "1234567897516",
                        "amtTime": "2026-07-07 03:14:50",
                        "historyOwe": "0",
                        "prepayBal": "0",
                        "sumMoney": "169.77",
                    }
                }
            }
        ]

        data = parse_account_data(components=components)

        self.assertEqual(data.balance.observed_at, "2026-07-07 03:14:50")
        self.assertEqual(data.balance.balance_cny, 169.77)
        self.assertEqual(data.balance.prepay_balance_cny, 0.0)
        self.assertEqual(data.balance.arrears_cny, 0.0)

    def test_sum_money_without_mixin_yue_context_is_not_balance(self):
        components = [{"data": {"summary": {"sumMoney": "999.99"}}}]

        data = parse_account_data(components=components)

        self.assertIsNone(data.balance)

    def test_parse_balance_from_label_value_rows(self):
        components = [
            {
                "data": {
                    "consInfo": {"consNo": "1234567890123", "elecAddr_dst": "addr"},
                    "listData": [
                        {"label": "账户余额", "value": "155.31元"},
                        {"label": "预付费余额", "value": "12.34"},
                        {"label": "应交金额", "value": "0.00"},
                    ],
                }
            }
        ]

        data = parse_account_data(components=components)

        self.assertEqual(data.balance.balance_cny, 155.31)
        self.assertEqual(data.balance.prepay_balance_cny, 12.34)
        self.assertEqual(data.balance.arrears_cny, 0.0)

    def test_merge_account_data_fills_masked_account_numbers(self):
        first = parse_account_data(store={"masked": "*********0123"})
        second = parse_account_data(
            store={
                "account": {"consNo": "1234567890123", "elecAddr_dst": "addr"},
                "balance": {"accountBalance": "10.5"},
            }
        )

        merged = merge_account_data(first, second)

        self.assertEqual(merged.account.account_no, "1234567890123")
        self.assertEqual(merged.balance.account_no, "1234567890123")
        self.assertEqual(merged.balance.balance_cny, 10.5)


if __name__ == "__main__":
    unittest.main()
