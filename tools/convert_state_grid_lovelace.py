#!/usr/bin/env python3
"""Convert Lovelace YAML snippets from state_grid entity names to this project.

This is intentionally an offline field-replacement helper. It does not add a
state_grid compatibility layer to the backend.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sgcc_ha_bridge.entity_identity import account_entity_key


def sgcc_entities(entity_key: str) -> dict[str, str]:
    base = f"sensor.sgcc_{entity_key}"
    return {
        "history": f"{base}_history",
        "balance": f"{base}_balance",
        "arrears": f"{base}_arrears",
        "prepay": f"{base}_prepay_balance",
        "latest_daily": f"{base}_last_daily_usage",
        "month_usage": f"{base}_month_usage",
        "month_charge": f"{base}_month_charge",
        "year_usage": f"{base}_year_usage",
        "year_charge": f"{base}_year_charge",
        "month_valley": f"{base}_month_valley",
        "month_flat": f"{base}_month_flat",
        "month_peak": f"{base}_month_peak",
        "month_tip": f"{base}_month_tip",
    }


# state_grid keys seen in lxg20082008/state_grid and older README examples.
KEY_MAP: dict[str, str] = {
    "balance": "balance",
    "daily_ele": "latest_daily",
    "daily_ele_num": "latest_daily",
    "monthly_ele": "month_usage",
    "month_ele_num": "month_usage",
    "month_ele_cost": "month_charge",
    "yearly_ele": "year_usage",
    "year_ele_num": "year_usage",
    "year_ele_cost": "year_charge",
    "month_v_ele_num": "month_valley",
    "month_n_ele_num": "month_flat",
    "month_p_ele_num": "month_peak",
    "month_t_ele_num": "month_tip",
    "valley_ele": "month_valley",
    "normal_ele": "month_flat",
    "peak_ele": "month_peak",
    "sharp_ele": "month_tip",
    "recent_30_daily_ele_list": "history",
    "recent_12_monthly_ele_list": "history",
}

STATE_GRID_ENTITY_RE = re.compile(
    r"sensor\.state_grid(?:_[A-Za-z0-9]+)?_(?P<key>"
    + "|".join(re.escape(k) for k in sorted(KEY_MAP, key=len, reverse=True))
    + r")\b"
)

DAILY_GRAPH_RE = re.compile(r"sensor\.state_grid(?:_[A-Za-z0-9]+)?_recent_30_daily_ele_list\b")
MONTHLY_GRAPH_RE = re.compile(r"sensor\.state_grid(?:_[A-Za-z0-9]+)?_recent_12_monthly_ele_list\b")
ANY_ENTITY_LINE_RE = re.compile(r"^\s*-?\s*entity:\s*")


def _replace_graph_access(line: str, graph_kind: str | None) -> str:
    if not graph_kind:
        return line
    attr = "daily" if graph_kind == "daily" else "monthly"
    line = line.replace("entity.attributes.graph", f"entity.attributes.{attr}")
    line = line.replace("entity.attributes['graph']", f"entity.attributes['{attr}']")
    line = line.replace('entity.attributes["graph"]', f'entity.attributes["{attr}"]')
    line = line.replace("attributes.graph", f"attributes.{attr}")
    line = line.replace("attributes['graph']", f"attributes['{attr}']")
    line = line.replace('attributes["graph"]', f'attributes["{attr}"]')
    return line


def convert_text(text: str, entity_key: str) -> tuple[str, dict[str, int]]:
    entities = sgcc_entities(entity_key)
    counts: dict[str, int] = {"entity": 0, "daily_graph": 0, "monthly_graph": 0}

    graph_kind: str | None = None
    converted_lines: list[str] = []
    for line in text.splitlines(keepends=True):
        if DAILY_GRAPH_RE.search(line):
            graph_kind = "daily"
        elif MONTHLY_GRAPH_RE.search(line):
            graph_kind = "monthly"
        elif ANY_ENTITY_LINE_RE.search(line) and "state_grid" in line:
            graph_kind = None

        before_graph = line
        line = _replace_graph_access(line, graph_kind)
        if line != before_graph:
            counts[f"{graph_kind}_graph"] += 1

        def repl(match: re.Match[str]) -> str:
            key = match.group("key")
            counts["entity"] += 1
            return entities[KEY_MAP[key]]

        line = STATE_GRID_ENTITY_RE.sub(repl, line)
        converted_lines.append(line)

    return "".join(converted_lines), counts


def main() -> int:
    parser = argparse.ArgumentParser(
        description="把 state_grid Lovelace YAML 里的实体字段替换成本项目字段。"
    )
    parser.add_argument("input", help="输入 Lovelace YAML 文件，使用 - 表示 stdin")
    parser.add_argument("output", nargs="?", help="输出文件；不填则写 stdout")
    identity = parser.add_mutually_exclusive_group(required=True)
    identity.add_argument(
        "--entity-key",
        help="Home Assistant canonical 账户键，例如 0123_e2161a7e19",
    )
    identity.add_argument(
        "--account-no",
        help="完整 13 位户号；仅在本机计算账户键，不写入输出文件",
    )
    parser.add_argument("--output", "-o", dest="output_option", help="输出文件；不填则写 stdout")
    parser.add_argument("--quiet", action="store_true", help="不在 stderr 打印替换统计")
    args = parser.parse_args()

    output = args.output_option or args.output
    if args.output_option and args.output and args.output_option != args.output:
        parser.error("output positional and --output point to different files")

    if args.input == "-":
        src = sys.stdin.read()
    else:
        src = Path(args.input).read_text(encoding="utf-8")

    entity_key = args.entity_key or account_entity_key(args.account_no)
    out, counts = convert_text(src, entity_key)

    if output:
        Path(output).write_text(out, encoding="utf-8")
    else:
        print(out, end="")

    if not args.quiet:
        print(
            f"converted entities={counts['entity']} daily_graph={counts['daily_graph']} monthly_graph={counts['monthly_graph']}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
