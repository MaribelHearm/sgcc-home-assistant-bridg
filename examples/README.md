# Examples

示例只提供可复制配置，不会自动安装 Home Assistant 卡片资源。

## 目录

- `basic/lovelace-sgcc-electricity.yaml`：偏基础的 Home Assistant Lovelace view 示例，优先使用内置 `sections`、`tile`、`entities`、`grid` 卡片。
- `lovelace-cards/`：三套卡片预设。
  - `sgcc-electricity-card-xiaoshi-original.yaml`：消逝 / xiaoshi 原版风格预设，已替换成本项目实体字段。
  - `sgcc-electricity-card-xiaoshi-style.yaml`：消逝风格优化版，已替换成本项目实体字段。
  - `sgcc-electricity-card.yaml`：作者当前自用 Lovelace 页面导出示例，依赖 HACS 卡片。
- `custom-cards/sgcc-electricity-card.js`：前两套卡片预设使用的前端卡片文件。
- `migration/`：已有 `state_grid` 仪表盘迁移说明。

## 使用前需要替换

把 YAML 里的 `4840` 替换为自己的户号后四位。

如果使用 `custom:sgcc-electricity-card`，需要把：

```text
examples/custom-cards/sgcc-electricity-card.js
```

放到 Home Assistant 的 `/config/www/sgcc/`，并在 Lovelace resources 添加：

```text
/local/sgcc/sgcc-electricity-card.js
```

类型选择 `module`。

## 字段迁移

已有 `state_grid` 仪表盘 YAML 时，建议使用：

```bash
python tools/convert_state_grid_lovelace.py input.yaml output.yaml --suffix 4840
```

说明见 [migration/README.md](migration/README.md) 和 [../docs/state-grid-lovelace-migration.md](../docs/state-grid-lovelace-migration.md)。
