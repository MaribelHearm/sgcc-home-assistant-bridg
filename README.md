# SGCC Electricity ARC

[![License](https://img.shields.io/github/license/MaribelHearm/sgcc-electricity-arc)](LICENSE)
[![Release](https://img.shields.io/github/v/tag/MaribelHearm/sgcc-electricity-arc?label=release)](https://github.com/MaribelHearm/sgcc-electricity-arc/tags)
[![Docker Build Check](https://github.com/MaribelHearm/sgcc-electricity-arc/actions/workflows/docker-image.yml/badge.svg)](https://github.com/MaribelHearm/sgcc-electricity-arc/actions/workflows/docker-image.yml)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-MQTT%20Discovery-41BDF5)](https://www.home-assistant.io/integrations/mqtt/)

把国家电网（95598）的电费、余额与用电量接入 Home Assistant 的非官方本地桥接程序。

本项目基于 [`ARC-MX/sgcc_electricity_new`](https://github.com/ARC-MX/sgcc_electricity_new) 二次开发，原作者为 renhai-lab，原项目采用 Apache-2.0 许可证。感谢原作者和社区为国家电网 Home Assistant 集成方向做出的基础工作。

> 当前版本定位：保留 Home Assistant / Docker 部署外壳，重写核心登录、抓取、解析、SQLite 存储与 MQTT Discovery 发布链路。

## 为什么做这个版本

国网网页与风控变化后，很多旧方案会遇到扫码依赖、验证码误判、会话失效、历史数据不完整或 Home Assistant 实体恢复不稳定的问题。本版本的目标是：

- **无人值守**：优先使用账号密码 + 多模态点选验证码，不把扫码当主路径。
- **数据不缺**：落库日/月/年、余额、峰平谷尖与抓取运行记录，便于补发和恢复。
- **HA 原生体验**：通过 MQTT Discovery 自动创建设备和实体，同时保留 REST states API 兼容路径。
- **本地可观测**：SQLite 作为本地事实源，错误现场保存到本机，账号与户号默认脱敏。

## 和上游项目的主要区别

| 方向 | 上游项目 | 本项目 |
| --- | --- | --- |
| 登录路径 | 旧网页登录/扫码/验证码逻辑 | 真实浏览器账号密码登录，多模态点选验证码，二维码仅兜底 |
| 抓取方式 | 页面文本、旧逻辑与简单扩展 | Path B：读取 SGCC Vue2/Vuex store 与组件数据 |
| 存储模型 | 可选 SQLite/MySQL，偏每日用电与 key-value | 规范化 SQLite：账户、余额、日/月/年、运行记录、会话检查、发布状态 |
| HA 发布 | REST 传感器为主 | MQTT Discovery 为主，REST 兼容 |
| 数据覆盖 | 近日电量与基础字段 | 日用电、月度、年度、余额、峰/平/谷/尖、历史数据摘要 |
| 运行方式 | 继承原有 Add-on/Docker 结构 | 每轮 headful Chromium + Xvfb，用完即关，减少会话残留 |

## 特性

- **每天现登**：按计划使用国网账号密码登录，避免依赖长期在线浏览器会话。
- **多模态点选验证码**：通过 OpenAI 兼容多模态 LLM 识别腾讯点选验证码坐标；失败时可用二维码扫码兜底。
- **用完即关 headful Chromium**：每轮任务启动带 Xvfb 的有头 Chromium，抓取完成后关闭，降低常驻浏览器状态残留。
- **Path B 抓取**：从 SGCC Vue2/Vuex `$store` 与组件 `data` 中读取已解密业务数据，而不是只依赖页面文本或截图。
- **SQLite 事实源**：抓取结果、运行记录与会话检查写入本地 `/data/sgcc.sqlite3`，便于追踪和恢复。
- **MQTT Discovery + REST 双通道**：优先通过 Home Assistant MQTT Discovery 自动创建设备和实体，同时保留 REST 发布兼容路径。

## 架构概览

```text
schedule / startup
  -> account login (password + Tencent click captcha via multimodal LLM)
  -> fallback qrcode login when configured
  -> per-run headful Chromium under Xvfb
  -> Path B scraper (Vuex $store + component data)
  -> parser / normalized AccountData model
  -> SQLite /data/sgcc.sqlite3
  -> Home Assistant publisher
       -> MQTT Discovery device/entities
       -> REST states API compatibility
```

主要模块包括：`config`、`redact`、`browser`、`login`、`session`、`scraper`、`parser`、`store`、`model`、`ha_mapping`、`sensor_updator`、`mqtt_publisher`、`captcha_selenium`、`click_captcha_solver`。

## 快速开始

### 1. 准备 Home Assistant MQTT Broker

推荐先在 Home Assistant 中启用 Mosquitto broker，并开启 MQTT 集成的自动发现。容器示例使用 `network_mode: host`，因此 `MQTT_HOST` 通常可填写 Home Assistant 主机地址、`127.0.0.1`（同机部署）或你的 broker 局域网地址。

如果只想使用旧 REST 路径，可以把 `PUBLISHER=rest`；推荐保持 `PUBLISHER=both`，让 MQTT Discovery 负责自动建实体，REST 作为兼容通道。

### 2. 配置环境变量

```bash
cp example.env .env
$EDITOR .env
```

至少需要填写：

- `PHONE_NUMBER`、`PASSWORD`：国家电网账号。
- `LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL`：OpenAI 兼容多模态模型，用于验证码坐标识别。
- `HASS_URL`、`HASS_TOKEN`：REST 发布使用。
- `MQTT_HOST`、`MQTT_PORT`、`MQTT_USERNAME`、`MQTT_PASSWORD`：MQTT Discovery 发布使用。

请不要把真实 `.env`、Home Assistant Token、国网密码或 LLM API Key 提交到仓库。

### 3. 构建并启动

```bash
docker compose build
docker compose up -d
```

默认 compose 会：

- 使用仓库内 `Dockerfile-for-github-action` 本地构建镜像；
- 读取 `.env`；
- 使用 host 网络访问 Home Assistant / MQTT broker；
- 挂载本机 `/data` 到容器 `/data`，SQLite 默认写入 `/data/sgcc.sqlite3`；
- 通过 `restart: unless-stopped` 常驻调度。

查看日志：

```bash
docker compose logs -f sgcc_electricity_app
```

### 4. Home Assistant 实体

当 `PUBLISHER=mqtt` 或 `PUBLISHER=both` 且 MQTT broker 可用时，程序会向 `MQTT_DISCOVERY_PREFIX`（默认 `homeassistant`）发布 discovery 配置。Home Assistant 会自动出现一个“国网电费 ****后四位”的 device，并包含余额、欠费、年度/月度/日用电等传感器。

户号会在实体名称、unique id 与日志中脱敏，只保留末四位用于区分。

## 配置项

| 变量 | 用途 |
| --- | --- |
| `PHONE_NUMBER` | 国家电网登录手机号/账号。 |
| `PASSWORD` | 国家电网登录密码。 |
| `IGNORE_USER_ID` | 忽略指定户号，多个用英文逗号分隔。 |
| `HASS_URL` | Home Assistant 地址，REST 发布使用。 |
| `HASS_TOKEN` | Home Assistant 长期访问令牌，REST 发布使用。 |
| `JOB_START_TIME` | 每日抓取开始时间，格式 `HH:MM`。 |
| `RETRY_TIMES_LIMIT` | 登录、验证码或抓取失败时的重试次数上限。 |
| `LLM_API_KEY` | OpenAI 兼容多模态接口 Key。 |
| `LLM_BASE_URL` | OpenAI 兼容接口 Base URL。 |
| `LLM_MODEL` | 用于验证码识别的多模态模型名称。 |
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

## 数据与隐私

- 户号在日志、MQTT discovery、entity unique id 等位置会脱敏，通常只保留末四位用于识别。
- SQLite 数据库默认保存在本机 `/data/sgcc.sqlite3`，作为抓取事实源和运行观测记录。
- 程序不会把电费/用电数据发送到 Home Assistant、MQTT broker 与你配置的 LLM 验证码接口之外的目的地。
- 腾讯点选验证码识别会把验证码截图发送给你配置的 OpenAI 兼容 LLM 服务；请根据所选服务的隐私条款自行评估。
- 请妥善保护 `.env` 中的国网账号、Home Assistant Token、MQTT 凭据和 LLM API Key。

## 项目状态

- 已在个人 Home Assistant 场景中完成真实账号抓取验证。
- 国网页面、腾讯验证码与账号风控策略可能随时变化；如果失败，请优先查看 `/data/errors` 中保存的现场信息。
- 本项目不是国家电网、95598、腾讯验证码或 Home Assistant 官方项目。

## 鸣谢

- 上游项目：[`ARC-MX/sgcc_electricity_new`](https://github.com/ARC-MX/sgcc_electricity_new)
- 原作者：renhai-lab
- 感谢 Home Assistant、Selenium、MQTT 与相关开源社区。

## 许可证

本项目遵循 Apache License 2.0。详见 [`LICENSE`](LICENSE) 与 [`NOTICE`](NOTICE)。
