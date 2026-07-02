import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "convert_state_grid_lovelace", ROOT / "tools" / "convert_state_grid_lovelace.py"
)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(module)


class ConvertStateGridLovelaceTests(unittest.TestCase):
    def test_replaces_state_grid_entities_with_sgcc_entities(self):
        src = """
entity: sensor.state_grid_123456_balance
entity: sensor.state_grid_123456_daily_ele_num
entity: sensor.state_grid_123456_month_p_ele_num
entity: sensor.state_grid_yearly_ele
"""
        out, counts = module.convert_text(src, "4840")
        self.assertIn("sensor.guo_wang_dian_fei_4840_dian_fei_yu_e_4840", out)
        self.assertIn("sensor.guo_wang_dian_fei_4840_zui_jin_ri_yong_dian_4840", out)
        self.assertIn("sensor.guo_wang_dian_fei_4840_yue_du_feng_shi_dian_liang_4840", out)
        self.assertIn("sensor.guo_wang_dian_fei_4840_nian_du_yong_dian_4840", out)
        self.assertEqual(counts["entity"], 4)

    def test_replaces_graph_attribute_by_series_context(self):
        src = """
series:
  - entity: sensor.state_grid_123456_recent_30_daily_ele_list
    data_generator: |
      return entity.attributes.graph;
  - entity: sensor.state_grid_123456_recent_12_monthly_ele_list
    data_generator: |
      return entity.attributes["graph"];
"""
        out, counts = module.convert_text(src, "4840")
        self.assertEqual(out.count("sensor.guo_wang_dian_fei_4840_li_shi_shu_ju_4840"), 2)
        self.assertIn("entity.attributes.daily", out)
        self.assertIn('entity.attributes["monthly"]', out)
        self.assertEqual(counts["daily_graph"], 1)
        self.assertEqual(counts["monthly_graph"], 1)


if __name__ == "__main__":
    unittest.main()
