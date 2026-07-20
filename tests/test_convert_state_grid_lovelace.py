import importlib.util
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from sgcc_ha_bridge.entity_identity import account_entity_key

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
        entity_key = account_entity_key("1234567890123")
        out, counts = module.convert_text(src, entity_key)
        self.assertIn(f"sensor.sgcc_{entity_key}_balance", out)
        self.assertIn(f"sensor.sgcc_{entity_key}_last_daily_usage", out)
        self.assertIn(f"sensor.sgcc_{entity_key}_month_peak", out)
        self.assertIn(f"sensor.sgcc_{entity_key}_year_usage", out)
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
        entity_key = account_entity_key("1234567890123")
        out, counts = module.convert_text(src, entity_key)
        self.assertEqual(out.count(f"sensor.sgcc_{entity_key}_history"), 2)
        self.assertIn("entity.attributes.daily", out)
        self.assertIn('entity.attributes["monthly"]', out)
        self.assertEqual(counts["daily_graph"], 1)
        self.assertEqual(counts["monthly_graph"], 1)

    def test_cli_accepts_account_number_and_output_positional(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "input.yaml"
            dst = Path(tmp) / "output.yaml"
            src.write_text("entity: sensor.state_grid_123456_balance\n", encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "tools" / "convert_state_grid_lovelace.py"),
                    str(src),
                    str(dst),
                    "--account-no",
                    "1234567890123",
                    "--quiet",
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.stderr, "")
            self.assertIn(
                "sensor.sgcc_0123_e2161a7e19_balance",
                dst.read_text(encoding="utf-8"),
            )

    def test_shipped_lovelace_examples_use_current_entity_identity(self):
        example_files = [
            ROOT / "examples/basic/lovelace-sgcc-electricity.yaml",
            *sorted((ROOT / "examples/lovelace-cards").glob("*.yaml")),
        ]
        entity_pattern = re.compile(
            r"sensor\.sgcc_(?P<key>[0-9]{4}_[0-9a-f]{10})_[a-z0-9_]+"
        )

        for path in example_files:
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("sensor.guo_wang_dian_fei_", text, path)
            matches = list(entity_pattern.finditer(text))
            self.assertTrue(matches, path)
            self.assertEqual(
                {match.group("key") for match in matches},
                {"0123_e2161a7e19"},
                path,
            )
            self.assertNotIn("sensor.sgcc_0123_balance", text, path)

    def test_every_shipped_example_documents_canonical_identity(self):
        example_files = sorted((ROOT / "examples").rglob("*"))
        text_files = [
            path
            for path in example_files
            if path.is_file() and path.suffix in {".md", ".yaml", ".js"}
        ]
        combined = "\n".join(path.read_text(encoding="utf-8") for path in text_files)

        self.assertIn("sensor.sgcc_0123_e2161a7e19_balance", combined)
        self.assertNotIn("4840_0123456789", combined)
        self.assertNotIn("户号 ****4840", combined)


if __name__ == "__main__":
    unittest.main()
