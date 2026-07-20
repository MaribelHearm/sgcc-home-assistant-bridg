# Lovelace 卡片示例

YAML 中的实体 ID 是 canonical v2 占位示例，例如 `sensor.sgcc_0123_e2161a7e19_balance`。请在 Home Assistant 中选择本次实际生成的 `sensor.sgcc_<末四位_稳定摘要>_*` 实体，并把示例账户键 `0123_e2161a7e19` 整体替换；这里不自动安装卡片资源。

## 内置三套示例

- `sgcc-electricity-card-xiaoshi-original.yaml`：消逝 / xiaoshi 原版风格预设。使用本项目 `custom:sgcc-electricity-card`，直接读取本项目实体，配置了 `variant: xiaoshi-original`。
- `sgcc-electricity-card-xiaoshi-style.yaml`：消逝风格优化版。使用本项目 `custom:sgcc-electricity-card`，直接读取本项目实体，配置了 `variant: xiaoshi`。
- `sgcc-electricity-card.yaml`：当前自用 Lovelace 页面配置，来自 `/sgcc-electricity/overview`，依赖 `stack-in-card`、`mushroom`、`apexcharts-card` 和 `card-mod`。

## 截图示例

| 示例 | 截图 |
| --- | --- |
| 消逝 / xiaoshi 原版风格预设 | <img src="../../assets/lovelace-cards/sgcc-electricity-card-xiaoshi-original.png" width="360" alt="消逝原版风格"> |
| 消逝风格优化版 | <img src="../../assets/lovelace-cards/sgcc-electricity-card-xiaoshi-style.png" width="360" alt="消逝风格优化版"> |
| 当前自用卡片（overview） | <img src="../../assets/lovelace-cards/sgcc-electricity-card.png" width="360" alt="当前自用卡片 overview"> |

三份 YAML 都是已经替换成本项目实体字段的预设。其中前两份需要把：

```text
examples/custom-cards/sgcc-electricity-card.js
```

放到 HA 的 `/config/www/sgcc/`，并在 Lovelace resources 添加：

```text
/local/sgcc/sgcc-electricity-card.js
```

类型选 `module`。

`sgcc-electricity-card.yaml` 则按真实自用页面导出，需要先安装对应 HACS 卡片。

如果你已有 `state_grid` 仪表盘 YAML，不建议后端兼容另一套实体模型；用 `tools/convert_state_grid_lovelace.py` 做字段替换。
