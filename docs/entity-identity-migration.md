# v0.1.8 实体身份兼容与迁移

v0.1.6 把账户身份从“仅户号末四位 / 脱敏户号”升级为隐私且防碰撞的 `末四位_稳定摘要`。新的 canonical 身份能区分末四位相同的不同户号，但 v0.1.6/v0.1.7 会在发布新 MQTT Discovery 后删除旧 Discovery，导致仍引用旧实体 ID 的 Lovelace、自动化或脚本失效。

v0.1.8 是兼容迁移版本：默认不要求使用 Home Assistant API，也不要求改变 `PUBLISHER`。升级后程序会从 SQLite 缓存或下一次成功抓取自动重发兼容 Discovery。

## 谁会受影响

- 从 v0.1.5 或更早版本升级，并且继续使用旧 MQTT 实体的用户可能受影响。
- 全新安装通常只会看到 canonical v2 实体，不需要迁移旧消费者。
- `PUBLISHER=rest` 的旧 REST states API 实体使用另一套命名和清理开关，见下文。

## 三套身份

| 路径 | 身份示意 | v0.1.8 行为 |
| --- | --- | --- |
| v0.1.5 MQTT | 旧 `unique_id` 使用脱敏户号；HA 可能保留原中文/自定义 `entity_id` | `compat` 在无冲突时恢复同一 `unique_id`，尽量让 HA registry 恢复原实体 ID |
| canonical v2 MQTT | `sensor.sgcc_<末四位_稳定摘要>_<key>`，例如 `sensor.sgcc_0123_e2161a7e19_balance` | 始终发布；Discovery 设置同格式的 `default_entity_id` |
| canonical v2 REST | `sensor.electricity_charge_balance_<末四位_稳定摘要>` 等 | `PUBLISHER=rest|both` 时继续发布；与 MQTT 清理模式互不联动 |

`unique_id` 是 Home Assistant 实体注册表中的集成身份；`default_entity_id` 是首次注册或恢复时建议使用的实体 ID；最终 `entity_id` 仍可能受既有 registry 记录、用户重命名和名称冲突影响。请以 Home Assistant 当前实体注册表为准，不要把 `_2` 写成新的上游契约。

## 默认升级步骤

1. 升级到 v0.1.8，并保持：

   ```env
   PUBLISHER="mqtt" # rest / both 也继续支持
   MQTT_LEGACY_DISCOVERY_MODE="compat"
   ```

2. 启动后等待缓存重发，或等待下一次正常抓取；不需要为了迁移额外触发国网登录。
3. 在 Home Assistant 的“开发者工具 → 状态”或“设置 → 设备与服务 → 实体”确认：
   - canonical v2 实体有真实状态；
   - 原旧实体在无冲突时重新出现并有相同状态；
   - 日志未报告末四位冲突。
4. 先逐步把 Lovelace、自动化、脚本、场景、模板和外部消费者改到 canonical 实体。
5. 保持 `compat` 一段观察期。只有确认所有旧引用都已清零后，才考虑 `cleanup`。

## `MQTT_LEGACY_DISCOVERY_MODE`

| 模式 | 行为 | 适用场景 |
| --- | --- | --- |
| `compat`（默认） | 先发布 canonical v2；权威账户集合证明末四位唯一时，恢复旧 MQTT Discovery；冲突别名会撤销 | 普通升级和迁移观察期 |
| `off` | 只发布 canonical v2，不创建也不删除旧 retained Discovery | 需要完全自行管理 broker 旧配置时 |
| `cleanup` | canonical v2 成功后 tombstone 旧 MQTT Discovery | 所有旧消费者迁移完成后的显式清理 |

### 同尾号例外

旧身份只包含末四位，无法区分两个末四位相同的户号。只要一次完整、权威的账户枚举发现冲突，v0.1.8 就不会让任何一个账户占用该旧别名，并会撤销已有冲突 Discovery。两户号各自的 canonical v2 实体仍正常发布。

非权威或不完整的账户枚举不会创建或删除旧别名，避免部分抓取误判。被 `IGNORE_USER_ID` 忽略的账户仍参与冲突判断，但不会成为旧别名 owner。

## 可选的 HA UI/API 迁移

普通升级不需要 HA API。希望让 canonical 实体使用整洁且固定的 ID 时，可以在 Home Assistant UI 中重命名，或使用受支持的实体注册表 API/工具迁移。迁移前应：

1. 备份 Home Assistant；
2. 按 MQTT `unique_id` 确认源实体，而不是从中文显示名猜测；
3. 确认目标 `sensor.sgcc_<entity-key>_<key>` 未被占用；
4. 全面扫描 dashboard、automation、script、scene、template、Node-RED 等消费者；
5. 先改消费者并验证，再清理旧 Discovery。

不要直接编辑 Home Assistant `.storage` 文件。

## REST 发布与清理

`PUBLISHER=rest|mqtt|both` 保持可选：

- `rest`：只发布 HA REST states API 实体；
- `mqtt`：只发布 MQTT Discovery；
- `both`：同时发布两条路径。

`SGCC_CLEANUP_LEGACY_ENTITY_IDS=true` 只清理旧 REST states API 实体，默认关闭。它不会清理 MQTT Discovery；MQTT 使用 `MQTT_LEGACY_DISCOVERY_MODE=cleanup`。两种清理都应在对应消费者完成迁移后才启用。

## 验证与回滚

验证至少包括：

- canonical 状态、单位和属性正常；
- `compat` 下无冲突旧实体恢复；
- 同尾号场景只保留 canonical 实体；
- MQTT topic/payload 不包含完整户号；
- Lovelace、自动化和脚本不再出现 entity-not-found。

如迁移异常：

1. 立即恢复 `MQTT_LEGACY_DISCOVERY_MODE=compat`；
2. 不要启用任何 cleanup；
3. 回滚消费者引用或恢复 HA 备份；
4. 如需回滚程序，把 app/browser 镜像一起固定回上一版本；
5. 附带脱敏 Debug bundle 报告问题。

Home Assistant MQTT Discovery 与实体注册表行为参考：

- [Home Assistant MQTT integration](https://www.home-assistant.io/integrations/mqtt/)
- [Home Assistant entity registry](https://developers.home-assistant.io/docs/entity_registry_index/)
