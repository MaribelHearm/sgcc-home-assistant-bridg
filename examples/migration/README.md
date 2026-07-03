# state_grid 字段迁移

本项目不在后端伪装 `sensor.state_grid_<户号>` 单实体。已有 `state_grid` / xiaoshi 仪表盘 YAML 时，使用离线字段替换工具更稳：

```bash
python tools/convert_state_grid_lovelace.py input.yaml output.yaml --suffix 4840
```

转换后请检查自定义 `data_generator` 或模板里读取的字段名。

详细说明见 [../../docs/state-grid-lovelace-migration.md](../../docs/state-grid-lovelace-migration.md)。
