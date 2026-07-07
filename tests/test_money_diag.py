import io
import logging
import unittest

from sgcc_ha_bridge.model import Account, AccountData, Balance
from sgcc_ha_bridge.money_diag import collect_money_candidates, log_money_diagnostics


class MoneyDiagnosticsTestCase(unittest.TestCase):
    def test_collects_structured_money_candidates_by_category(self):
        store = {
            "state": {
                "userAcc": {
                    "accountNo": "1234567890016",
                    "queryTime": "2026-07-07 00:00:00",
                    "accountBalance": "86.44元",
                    "address": "secret address",
                },
                "mixinGetYuEdata": {
                    "consNo": "1234567890016",
                    "historyOwe": "0.00",
                },
                "powerData": {
                    "mothEleList": [
                        {
                            "month": "202606",
                            "monthEleCost": "212.33",
                            "monthEleNum": "423.0",
                        }
                    ]
                },
            }
        }
        components = [
            {"data": {"consNo": "1234567890016", "prepayBalance": "217.7"}}
        ]

        candidates = collect_money_candidates(store=store, components=components)
        by_source = {item.source: item for item in candidates}

        self.assertEqual(by_source["store.state.userAcc.accountBalance"].category, "account_balance")
        self.assertEqual(by_source["store.state.mixinGetYuEdata.historyOwe"].category, "arrears_due")
        self.assertEqual(by_source["store.state.powerData.mothEleList[0].monthEleCost"].category, "bill_charge")
        self.assertEqual(by_source["component[0].data.prepayBalance"].category, "prepay_balance")
        self.assertNotIn("store.state.powerData.mothEleList[0].monthEleNum", by_source)
        self.assertEqual(by_source["store.state.userAcc.accountBalance"].account, "*********0016")
        self.assertEqual(by_source["store.state.userAcc.accountBalance"].time, "2026-07-07 00:00:00")

    def test_log_money_diagnostics_redacts_account_and_omits_raw_objects(self):
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        root = logging.getLogger()
        old_level = root.level
        root.addHandler(handler)
        root.setLevel(logging.INFO)
        try:
            parsed = AccountData(
                account=Account(account_no="1234567890016"),
                balance=Balance(
                    account_no="1234567890016",
                    observed_at="2026-07-07 00:00:00",
                    balance_cny=None,
                    prepay_balance_cny=0.0,
                    arrears_cny=0.0,
                ),
            )
            log_money_diagnostics(
                {
                    "url": "https://95598.cn/osgweb/userAcc",
                    "store": {"state": {"userAcc": {"accountNo": "1234567890016", "accountBalance": "86.44元"}}},
                    "components": [],
                },
                parsed,
                "账户余额",
                limit=5,
            )
        finally:
            root.removeHandler(handler)
            root.setLevel(old_level)

        output = stream.getvalue()
        self.assertIn("Path B 金额诊断摘要", output)
        self.assertIn("category=account_balance", output)
        self.assertIn("Path B 金额候选[1]: category=", output)
        self.assertNotIn("Path B 金额候选[1]:,", output)
        self.assertIn("account=*********0016", output)
        self.assertNotIn("1234567890016", output)

    def test_sum_money_candidate_is_classified_as_account_balance_in_yue_context(self):
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

        candidates = collect_money_candidates(components=components)
        by_source = {item.source: item for item in candidates}

        self.assertEqual(
            by_source["component[0].data.mixinGetYuEdata.sumMoney"].category,
            "account_balance",
        )
        self.assertEqual(
            by_source["component[0].data.mixinGetYuEdata.sumMoney"].time,
            "2026-07-07 03:14:50",
        )

    def test_limit_is_applied(self):
        store = {"state": {f"accountBalance{i}": str(i) for i in range(10)}}
        candidates = collect_money_candidates(store=store, components=[], limit=3)
        self.assertEqual(len(candidates), 3)


if __name__ == "__main__":
    unittest.main()
