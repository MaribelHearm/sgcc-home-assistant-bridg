# SGCC Home Assistant Bridge 详细文档

本文放 README 没展开的细节：配置、实体、架构、故障排查、上游关系和限制说明。

## 1. 项目定位

SGCC Home Assistant Bridge 是国家电网 / 网上国网 / 95598 到 Home Assistant 的非官方本地桥接程序。

主链路：

```text
schedule / startup
  -> account login/session check
       password + Tencent click captcha via multimodal LLM
       qrcode fallback only when configured/needed
  -> per-run headful Chromium under Xvfb
  -> Path B scraper
       Vuex $store snapshot + component data
  -> parser / normalized AccountData model
  -> SQLite /data/sgcc.sqlite3 fact store
       data + fetch runs + session checks + publisher state
  -> Home Assistant publisher
       MQTT Discovery device/entities
       REST states API compatibility
```

主要模块：`config`、`redact`、`browser`、`login`、`session`、`scraper`、`parser`、`store`、`model`、`ha_mapping`、`sensor_updator`、`mqtt_publisher`、`captcha_selenium`、`click_captcha_solver`、`llm_config`。

## 2. 部署方式

### Docker Compose 本地构建

```bash
cp example.env .env
$EDITOR .env
docker compose build
docker compose up -d
```

默认 compose：

- 使用 `Dockerfile-for-github-action` 构建镜像。
- 读取 `.env`。
- 使用 host 网络访问 Home Assistant / MQTT broker。
- 挂载本机 `/data` 到容器 `/data`。
- SQLite 默认写入 `/data/sgcc.sqlite3`。
- 通过 `restart: unless-stopped` 常驻调度。

### GHCR 镜像

```yaml
services:
  sgcc_electricity_app:
    image: ghcr.io/maribelhearm/sgcc-home-assistant-bridge:latest
    container_name: sgcc_electricity_arc
    env_file:
      - .env
    network_mode: host
    volumes:
      - /data:/data
    restart: unless-stopped
    init: true
```

固定版本可以使用：

```text
ghcr.io/maribelhearm/sgcc-home-assistant-bridge:v0.1.0
```

### Home Assistant Add-on 配置

如果使用 Add-on 形式：

- 安装完成后进入 “配置 / Configuration”。
- 填写国家电网账号密码、MQTT、REST、LLM 验证码接口。
- 推荐保持 `PUBLISHER=both`。
- 保存后在 “信息 / Info” 中启动。
- 失败时查看日志和 `/data/errors`。

## 3. 配置项

| 变量 | 用途 |
| --- | --- |
| `PHONE_NUMBER` | 国家电网登录手机号/账号。 |
| `PASSWORD` | 国家电网登录密码。 |
| `IGNORE_USER_ID` | 忽略指定户号，多个用英文逗号分隔。 |
| `HASS_URL` | Home Assistant 地址，REST 发布使用。 |
| `HASS_TOKEN` | Home Assistant 长期访问令牌，REST 发布使用。 |
| `JOB_START_TIME` | 每日抓取开始时间，格式 `HH:MM`。 |
| `RETRY_TIMES_LIMIT` | 登录、验证码或抓取失败时的重试次数上限。 |
| `LLM_API_KEY` | OpenAI 兼容多模态接口 Key；也兼容 `ARK_API_KEY`。 |
| `LLM_BASE_URL` | OpenAI 兼容接口 Base URL；也兼容 `ARK_BASE_URL`。 |
| `LLM_MODEL` | 多模态模型名或接入点 ID；也兼容 `ARK_MODEL`。 |
| `LOGIN_FALLBACK` | 登录失败兜底方式；`qrcode` 表示二维码人工扫码。 |
| `PUBLISHER` | 发布方式：`mqtt`、`rest`、`both`。 |
| `MQTT_HOST` | MQTT broker 地址。 |
| `MQTT_PORT` | MQTT broker 端口。 |
| `MQTT_USERNAME` | MQTT 用户名，可留空。 |
| `MQTT_PASSWORD` | MQTT 密码，可留空。 |
| `MQTT_DISCOVERY_PREFIX` | Home Assistant MQTT Discovery 前缀，默认 `homeassistant`。 |
| `SGCC_DB_PATH` | SQLite 数据库路径，默认 `/data/sgcc.sqlite3`。 |
| `SCRAPER_SETTLE_SECONDS` | Path B 抓取等待 Vuex/组件数据稳定的秒数。 |
| `REPUBLISH_INTERVAL_MINUTES` | 已有数据重发布或补抓的间隔分钟数。 |
| `SGCC_BROWSER_PROFILE` | Chromium 用户数据目录，默认建议放在 `/data/chrome-profile`。 |

`example.env` 还包含少量抓取等待参数，可在网络慢、页面加载不稳定或硬件性能较弱时微调。

## 4. LLM 验证码接口

项目使用 OpenAI 兼容 Chat Completions 调用多模态模型识别腾讯点选/滑块验证码。

推荐主配置：

```env
LLM_BASE_URL="https://ark.cn-beijing.volces.com/api/v3"
LLM_API_KEY="ark-xxxxxxxx"
LLM_MODEL="ep-xxxxxxxx"
```

兼容上游 / 火山方舟写法：

```env
ARK_API_KEY="ark-xxxxxxxx"
ARK_MODEL="ep-xxxxxxxx"
```

优先级：

1. `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL`
2. `ARK_API_KEY` / `ARK_BASE_URL` / `ARK_MODEL`
3. `VOLCENGINE_ARK_API_KEY` / `VOLCENGINE_ARK_BASE_URL` / `VOLCENGINE_ARK_MODEL`
4. 默认 `LLM_BASE_URL=https://ark.cn-beijing.volces.com/api/v3`

火山方舟用户建议在控制台创建多模态模型接入点，`LLM_MODEL` 填 `ep-...` 接入点 ID，而不是只填模型族名称。

## 5. Home Assistant 实体

当 `PUBLISHER=mqtt` 或 `PUBLISHER=both` 且 MQTT broker 可用时，程序会向 `MQTT_DISCOVERY_PREFIX` 发布 discovery 配置。Home Assistant 会自动出现一个“国网电费 ****后四位”的 device。

户号会在实体名称、unique id 和日志中脱敏，只保留末四位用于区分。Discovery key 会进入 MQTT topic、`unique_id` 和 `object_id`；实际 entity id 由 Home Assistant 实体注册表生成，请以 HA 实际显示为准。

| 类型 | Discovery key | 显示名称示例 | 说明 |
| --- | --- | --- | --- |
| 金额汇总 | `balance` / `prepay_balance` / `arrears` | 电费余额 / 预付费余额 / 应交金额 | 当前账户金额状态。 |
| 最新日数据 | `last_daily_usage` | 最近日用电 | state 是最近一天用电量；属性含 `date`、`valley_kwh`、`flat_kwh`、`peak_kwh`、`tip_kwh`。 |
| 最新月数据 | `month_usage` / `month_charge` | 月度用电 / 月度电费 | state 是最新月度用电或电费；属性含月份和起止日期。 |
| 本月分时汇总 | `month_valley` / `month_flat` / `month_peak` / `month_tip` | 月度谷/平/峰/尖时电量 | 由当前月已抓到的日读数汇总。 |
| 年度汇总 | `year_usage` / `year_charge` | 年度用电 / 年度电费 | state 是年度累计用电或电费。 |
| 历史摘要 | `history` | 历史数据 | state 类似 `2026-06-17 d7 m5`；属性包含 `daily`、`monthly`、年度摘要和数据范围。 |
| 日历史实体 | `daily_YYYYMMDD` | 日用电 2026-06-17 | 每个日读数一条独立实体；属性含峰平谷尖拆分。 |
| 月历史实体 | `monthly_YYYYMM` | 月度历史 2026-05 | 每个月度读数一条独立实体；属性含电费和起止日期。 |
| 年历史实体 | `year_YYYY` | 年度历史 2026 | 年度历史独立实体；属性含年度电费。 |

建议：

- 概览卡片使用 `balance`、`arrears`、`last_daily_usage`、`month_usage`、`month_charge`、`year_usage`。
- 表格或自动化使用 `daily_YYYYMMDD`、`monthly_YYYYMM`、`year_YYYY`。
- 曲线图读取 `history` 实体属性中的 `daily` / `monthly` 数组，这样横轴按国网页面日期绘制，而不是按 HA 状态更新时间绘制。

## 6. Lovelace 示例

示例文件：

```text
examples/lovelace-sgcc-electricity.yaml
```

使用方式：

1. Home Assistant → 仪表盘 → 编辑仪表盘 → 添加视图/原始配置。
2. 粘贴示例内容作为一个 view。
3. 把示例中的 `4840` 替换成你自己的户号末四位。
4. 日/月历史实体按 HA 实际出现的数据范围增删。

曲线部分依赖 HACS 的 `apexcharts-card`；如果未安装，可以删除“历史曲线（可选 ApexCharts）”部分。

## 7. 数据与隐私

- 户号在日志、MQTT discovery、entity unique id 等位置会脱敏。
- SQLite 数据库默认保存在本机 `/data/sgcc.sqlite3`。
- 程序不会把电费/用电数据发送到 Home Assistant、MQTT broker 和你配置的 LLM 验证码接口之外的目的地。
- 腾讯点选验证码识别会把验证码截图发送给你配置的 OpenAI 兼容 LLM 服务；请根据所选服务隐私条款自行评估。
- 请不要提交真实 `.env`、国网密码、Home Assistant Token、MQTT 凭据和 LLM API Key。

## 8. 常见问题与排障

### RK001

`网络连接超时（RK001）` 通常不像普通网络超时，更像登录页/验证码风控命中。可能原因：

- Docker / Xvfb / Linux Chromium 指纹触发风控。
- 登录页资源或腾讯验证码脚本没完整加载。
- 当前账号、IP、会话组合被风控。

项目检测到 RK001 后会停止本轮，避免反复打账号。

### 验证码一直被识别为 slider

95598 页面可能预加载隐藏验证码 DOM，其中有“拖动下方拼图完成验证”等文本，但节点实际不可见。旧逻辑容易把这些隐藏 DOM 当成真实滑块验证码。

本项目会优先判断真实可见弹窗，减少隐藏 DOM 误判。

### HA 没出现实体

检查：

- MQTT broker 是否可连接。
- Home Assistant MQTT 集成是否启用 discovery。
- `MQTT_DISCOVERY_PREFIX` 是否为 `homeassistant`。
- `PUBLISHER` 是否为 `mqtt` 或 `both`。
- 容器日志里是否有 MQTT 发布失败。

### 日/月历史数量不固定

正常。不同地区、账号、页面状态返回的数据范围可能不同。项目只发布国网页面实际返回的数据，不额外猜测或补造历史。

### GHCR 镜像拉不下来

确认 package visibility 是 Public，然后测试：

```bash
docker pull ghcr.io/maribelhearm/sgcc-home-assistant-bridge:latest
```

## 9. 和上游项目的关系

上游项目已经具备账号密码登录、LLM 视觉验证码、二维码兜底、Vue state 辅助取数、余额、日/月/年用电、峰平谷尖、REST 传感器和可选 SQLite/MySQL 等能力。

本项目主要围绕真实 Home Assistant 长期运行场景做重构：

| 方向 | 上游项目 | 本项目 |
| --- | --- | --- |
| 登录路径 | 已有账号密码登录、LLM 视觉验证码和二维码兜底 | 拆出 `login.py` / `browser.py`，增加登录态判定、受控导航、错误现场保存和脱敏日志；二维码只作为 fallback。 |
| 浏览器运行 | Selenium + Chrome/Chromium | Xvfb 下有头 Chromium、持久 profile、页面/脚本超时控制、每轮用完释放。 |
| 抓取方式 | 页面取值与 Vue component data / Vue state 辅助解析 | 将 Vue/Vuex 取数主路径化，读取 store snapshot + 组件 data，交给 `parser.py` 合并归一。 |
| 数据覆盖 | 已覆盖余额、预付费/欠费、日/月/年用电、月峰/平/谷/尖等 | 统一归一、去重、落库和重发布这些业务数据，提升恢复与排障体验。 |
| 存储模型 | 可选 SQLite/MySQL，表结构偏每日用电与 key-value 扩展 | 规范化 SQLite fact store：账户、余额、日/月/年、抓取 run、会话检查、发布状态。 |
| HA 发布 | REST states API 传感器为主 | MQTT Discovery 自动建实体，同时保留 REST 兼容路径。 |
| 缓存恢复 | 有旧缓存/数据库能力 | 增加 SQLite/旧 REST 状态重发布、空缓存判定、retained MQTT state。 |

## 10. 关键词

SGCC、State Grid、国家电网、网上国网、95598、Home Assistant、MQTT Discovery、SQLite、Selenium、Chromium、captcha、LLM、electricity、energy。
