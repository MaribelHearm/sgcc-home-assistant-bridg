import unittest

from sgcc_ha_bridge.vue_state import SELECTED_VUE_DATA_SCRIPT, _selected_vue_data_script, selected_vue_data


class VueStateScriptTestCase(unittest.TestCase):
    def test_balance_page_local_fields_are_collected(self):
        for key in ("accountBalance", "queryTime", "accountNo", "address"):
            self.assertIn(f'"{key}"', SELECTED_VUE_DATA_SCRIPT)

    def test_diag_only_money_fields_are_not_collected_by_default(self):
        for key in ("balance", "bal"):
            self.assertNotIn(f'"{key}"', SELECTED_VUE_DATA_SCRIPT)

    def test_money_diag_fields_are_collected_when_requested(self):
        script = _selected_vue_data_script(include_money_diag=True)

        for key in ("balance", "bal"):
            self.assertIn(f'"{key}"', script)

    def test_selected_vue_data_passes_money_diag_flag(self):
        class FakeDriver:
            def __init__(self):
                self.script = ""

            def execute_script(self, script):
                self.script = script
                return []

        driver = FakeDriver()

        selected_vue_data(driver, include_money_diag=True)

        self.assertIn('"balance"', driver.script)


if __name__ == "__main__":
    unittest.main()
