# v0.1.8 实体身份兼容与迁移

v0.1.6 把账户身份从“仅户号末四位 / 脱敏户号”升级为隐私且防碰撞的 `末四位_稳定摘要`。新的 canonical 身份能区分末四位相同的不同户号，但 v0.1.6/v0.1.7 会在发布新 MQTT Discovery 后删除旧 Discovery，导致仍引用旧实体 ID 的 Lovelace、自动化或脚本失效。

v0.1.8 是兼容迁移版本，不要求改变 `PUBLISHER`。它的 MQTT 旧 ID 兼容不会新增 HA API 依赖；如果原本使用 `PUBLISHER=rest|both`，bridge 仍会像之前一样通过 HA REST API 发布状态实体。

## 先说结论：三条路径，HA API 有两个用途

### 1. HA REST states 发布：HA API 用途之一

当配置为：

```env
PUBLISHER="rest" # 或 both
HASS_URL="http://homeassistant:8123"
HASS_TOKEN="..."
```

bridge 会持续调用：

```text
POST /api/states/<entity_id>
```

把国网数据发布为 HA state machine 中的 REST 状态实体。这条路径：

- 需要 HA URL 和 token；
- 由 `PUBLISHER=rest|both` 控制；
- 使用 `sensor.electricity_charge_balance_<entity-key>` 等 REST 命名；
- 不使用 MQTT Discovery，也不受 `MQTT_LEGACY_DISCOVERY_MODE` 控制；
- 旧 REST 实体清理由 `SGCC_CLEANUP_LEGACY_ENTITY_IDS` 单独控制。

### 2. MQTT Discovery 与旧 ID 兼容：不使用 HA API

保持默认配置：

```env
MQTT_LEGACY_DISCOVERY_MODE="compat"
```

bridge 会在 canonical v2 发布成功后，额外恢复无冲突的 v0.1.5 MQTT Discovery 身份。这样仍写着旧 entity ID 的 dashboard、自动化和脚本可以继续读取相同状态。

- MQTT 发布和 `compat` 本身不需要 Home Assistant token 或 API；
- 不会修改 HA 中 canonical 实体的现有 entity ID；
- 旧别名和 canonical 实体复用同一个 MQTT 状态主题；
- 这是默认升级路径。

如果同时使用 `PUBLISHER=both`，REST 那一半仍然会使用 HA API；“不需要 HA API”只是在说明 MQTT 兼容机制本身没有新增这一依赖。

### 3. HA 实体注册表迁移：HA API 用途之二

如果 HA 曾经给 canonical 实体生成中文 ID、冲突后缀 `_2`，或者你希望统一成稳定 ID，可以通过 HA UI、实体注册表 API 或 WebSocket 将其重命名，例如：

```text
sensor.guo_wang_dian_fei_0123_dian_fei_yu_e_0123_2
→ sensor.sgcc_0123_e2161a7e19_balance
```

这一步使用的是 HA entity registry API/WebSocket，和 `/api/states` 发布不是同一件事。它只修改 HA 实体注册表中的 `entity_id`：

- 不会创建旧 MQTT 别名；
- 不会开启或替代 `compat`；
- 不会自动更新 dashboard、自动化、脚本中的旧引用；
- 通常保留同一 `unique_id` 对应实体的历史记录；
- 不是普通升级的必做步骤。

### “引用方”是什么

“引用方”就是**写有某个 entity ID 的配置或程序**。常见引用方包括：

- Lovelace/dashboard 卡片中的 `entity`、`states()`、`state_attr()`；
- automation 的 trigger、condition、action；
- script、scene、template sensor 和 helper 配置；
- Node-RED、AppDaemon、Pyscript；
- 通过 HA REST/WebSocket API 读取该 entity ID 的外部程序。

重命名 entity ID 后，Home Assistant 不会替你修改这些字符串，所以必须逐项扫描和更新。

## 怎么选

| 当前目标 | 操作 | HA API |
| --- | --- | --- |
| 通过 REST states 发布实体 | 使用 `PUBLISHER=rest|both`，配置 `HASS_URL/HASS_TOKEN` | 运行时需要 |
| 只想让旧 MQTT 卡片马上恢复 | 保持 `compat`，等待缓存重发 | MQTT 兼容本身不需要 |
| 全新 MQTT 安装或没有旧 ID 引用 | 使用 canonical v2；通常无需额外操作 | MQTT 路径不需要 |
| 想去掉中文 ID 或 `_2`，统一成稳定 canonical ID | 先备份，再用 HA entity registry API 重命名，随后修改全部引用方 | 迁移时需要 |
| 正在逐步迁移旧 MQTT 卡片 | 保持 `compat`，一项项改到 canonical ID | 仅重命名 canonical 实体时需要 |
| 已确认旧 MQTT ID 引用为 0，想删除旧别名 | 改为 `cleanup`，验证后再考虑 `off` | 不需要 |

## 谁会受影响

- 从 v0.1.5 或更早版本升级，并且继续使用旧 MQTT 实体的用户可能受影响。
- 全新安装通常只会看到 canonical v2 实体，不需要迁移旧 ID 引用。
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
4. 先逐步把 Lovelace、自动化、脚本、场景、模板和外部程序中的旧 entity ID 改到 canonical 实体。
5. 保持 `compat` 一段观察期。只有确认所有旧引用都已清零后，才考虑 `cleanup`。

## `MQTT_LEGACY_DISCOVERY_MODE`

| 模式 | 行为 | 适用场景 |
| --- | --- | --- |
| `compat`（默认） | 先发布 canonical v2；权威账户集合证明末四位唯一时，恢复旧 MQTT Discovery；冲突别名会撤销 | 普通升级和迁移观察期 |
| `off` | 只发布 canonical v2，不创建也不删除旧 retained Discovery | 需要完全自行管理 broker 旧配置时 |
| `cleanup` | canonical v2 成功后 tombstone 旧 MQTT Discovery | 所有旧 entity ID 引用迁移完成后的显式清理 |

### 同尾号例外

旧身份只包含末四位，无法区分两个末四位相同的户号。只要一次完整、权威的账户枚举发现冲突，v0.1.8 就不会让任何一个账户占用该旧别名，并会撤销已有冲突 Discovery。两户号各自的 canonical v2 实体仍正常发布。

非权威或不完整的账户枚举不会创建或删除旧别名，避免部分抓取误判。被 `IGNORE_USER_ID` 忽略的账户仍参与冲突判断，但不会成为旧别名 owner。

## 可选的 HA UI/API 实体 ID 迁移

这里的 API 迁移不是 `/api/states` 发布，也不是“开启兼容”，而是修改 HA 实体注册表中的现有 `entity_id`。希望让 canonical MQTT 实体使用整洁且固定的 ID 时，可以在 Home Assistant UI 中重命名，或使用受支持的实体注册表 API/工具迁移。

推荐顺序：

1. 备份 Home Assistant；
2. 按 MQTT `unique_id` 确认源实体，而不是从中文显示名猜测；
3. 确认目标 `sensor.sgcc_<entity-key>_<key>` 未被占用；
4. 全面扫描 dashboard、automation、script、scene、template、Node-RED 和外部程序中的 entity ID 引用；
5. 调用 HA UI/API 重命名实体；
6. 修改全部引用方并验证；
7. 保持 `compat` 观察；确认旧引用为 0 后，才清理旧 Discovery。

不要直接编辑 Home Assistant `.storage` 文件。

## REST 发布与清理

`PUBLISHER=rest|mqtt|both` 保持可选：

- `rest`：只发布 HA REST states API 实体；
- `mqtt`：只发布 MQTT Discovery；
- `both`：同时发布两条路径。

`SGCC_CLEANUP_LEGACY_ENTITY_IDS=true` 只清理旧 REST states API 实体，默认关闭。它不会清理 MQTT Discovery；MQTT 使用 `MQTT_LEGACY_DISCOVERY_MODE=cleanup`。两种清理都应在对应旧 entity ID 引用完成迁移后才启用。

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
3. 回滚引用方中的 entity ID，或恢复 HA 备份；
4. 如需回滚程序，把 app/browser 镜像一起固定回上一版本；
5. 附带脱敏 Debug bundle 报告问题。

Home Assistant MQTT Discovery 与实体注册表行为参考：

- [Home Assistant MQTT integration](https://www.home-assistant.io/integrations/mqtt/)
- [Home Assistant entity registry](https://developers.home-assistant.io/docs/entity_registry_index/)
