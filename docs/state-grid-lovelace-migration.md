# state_grid Lovelace 迁移说明

`state_grid` 仓库没有内置 Lovelace 卡片、YAML 或前端源码，README 里的仪表盘只是截图。这里不在后端直接兼容 `state_grid` 实体模型。

原因：

- `state_grid` 使用 `sensor.state_grid_<户号>_<key>` 实体；
- 图表数据使用 `recent_30_daily_ele_list` / `recent_12_monthly_ele_list` 的 `attributes.graph`；
- 本项目使用自己的实体命名，历史数据放在历史实体的 `daily` / `monthly` 属性；
- 后端额外发布一套 `state_grid` 实体会影响实体命名、MQTT discovery、REST 兼容层和现有卡片，维护成本会变成两套模型。

如果只是迁移已有卡片，用离线字段替换脚本：

```bash
python tools/convert_state_grid_lovelace.py input.yaml \
  --account-suffix 4840 \
  --output output.yaml
```

脚本会替换常见 `state_grid` 实体，并把图表里的 `attributes.graph` 按上下文替换为本项目历史实体的 `daily` / `monthly`。

转换后仍建议检查一次 YAML，特别是自定义 `data_generator` 里对单条数据字段名的读取逻辑。
