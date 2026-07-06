import unittest

from sgcc_ha_bridge.vue_state import SELECTED_VUE_DATA_SCRIPT


class VueStateScriptTestCase(unittest.TestCase):
    def test_balance_page_local_fields_are_collected(self):
        for key in ("accountBalance", "queryTime", "accountNo", "address"):
            self.assertIn(f"'{key}'", SELECTED_VUE_DATA_SCRIPT)


if __name__ == "__main__":
    unittest.main()
