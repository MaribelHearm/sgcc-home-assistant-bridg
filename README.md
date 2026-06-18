# SGCC Home Assistant Bridge

[![License](https://img.shields.io/github/license/MaribelHearm/sgcc-electricity-arc)](LICENSE)
[![Release](https://img.shields.io/github/v/tag/MaribelHearm/sgcc-electricity-arc?label=release)](https://github.com/MaribelHearm/sgcc-electricity-arc/tags)
[![Docker Build Check](https://github.com/MaribelHearm/sgcc-electricity-arc/actions/workflows/docker-image.yml/badge.svg)](https://github.com/MaribelHearm/sgcc-electricity-arc/actions/workflows/docker-image.yml)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-MQTT%20Discovery-41BDF5)](https://www.home-assistant.io/integrations/mqtt/)

Unofficial State Grid / SGCC / 95598 electricity data bridge for Home Assistant, with browser automation, SQLite storage, MQTT Discovery and REST publishing.

把国家电网（95598）的电费余额、欠费、日用电、月度用电、年度用电和峰平谷尖分时电量接入 Home Assistant 的非官方本地桥接程序。适用于希望在 Home Assistant 能源看板、自动化、仪表盘和长期历史中使用国网用电数据的家庭用户。

本项目基于 [`ARC-MX/sgcc_electricity_new`](https://github.com/ARC-MX/sgcc_electricity_new) 二次开发，原作者为 renhai-lab，原项目采用 Apache-2.0 许可证。感谢原作者和社区为国家电网 Home Assistant 集成方向做出的基础工作。

> 当前版本定位：在上游 Home Assistant / Docker 部署外壳与既有业务覆盖基础上，重构账号登录、验证码处理、浏览器取数、Vue 状态解析、SQLite 存储、MQTT Discovery 和 HA 发布链路。

## 适合谁使用

- 使用 Home Assistant 管理家庭用电、能源统计和自动化的用户。
- 使用国家电网、网上国网、95598 账号查询电费余额和用电量的用户。
- 希望通过 MQTT Discovery 自动生成 Home Assistant 传感器，并保留 REST states API 兼容发布的用户。
- 希望将 SGCC / State Grid 电费、日用电、月度账单、年度统计和分时电量保存到本地 SQLite 的用户。

## 为什么做这个版本

上游项目已经具备账号密码登录、LLM 视觉验证码、余额/日/月/年用电、峰平谷尖、Home Assistant REST 传感器和可选 SQLite/MySQL 存储等能力。本版本围绕真实运行中的扫码兜底、页面加载、缓存恢复、数据归一和 HA 实体恢复问题，对这些链路做了模块化重构与稳定性增强。

本版本的目标是：

- **减少人工介入**：继续沿用账号密码 + 多模态验证码方向，二维码用于失败兜底。
- **数据更可恢复**：把上游已有的余额、日/月/年、峰平谷尖等数据统一归一到结构化模型和 SQLite 事实库，便于补发、恢复和排障。
- **HA 接入更自动**：在原 REST states API 发布基础上增加 MQTT Discovery，让 Home Assistant 自动创建设备和实体。
- **运行更可观测**：记录抓取 run、会话检查、发布状态和错误现场；账号、户号与敏感字段默认脱敏。

## 和上游项目的主要区别

| 方向 | 上游项目 | 本项目 |
| --- | --- | --- |
| 登录路径 | 已有账号密码登录、LLM 视觉验证码和二维码兜底 | 拆出 `login.py` / `browser.py`，增加登录态判定、受控导航、错误现场保存和脱敏日志；二维码仍只作为 fallback |
| 浏览器运行 | Selenium + Chrome/Chromium，Docker 下偏 headless | Xvfb 下有头 Chromium、持久 profile、页面/脚本超时控制、每轮用完释放 |
| 抓取方式 | 已有页面取值与 Vue component data / Vue state 辅助解析 | 将 Vue/Vuex 取数主路径化：读取 store snapshot + 组件 data，统一交给 `parser.py` 合并归一 |
| 数据覆盖 | 已覆盖余额、预付费/欠费、日/月/年用电、月峰/平/谷/尖等 | 统一归一、去重、落库和重发布这些业务数据，提升恢复与排障体验 |
| 存储模型 | 可选 SQLite/MySQL，表结构偏每日用电与 key-value 扩展 | 新增规范化 SQLite fact store：账户、余额、日/月/年、抓取 run、会话检查、发布状态 |
| HA 发布 | REST states API 传感器为主 | 新增 MQTT Discovery 自动建实体，同时保留 REST 兼容路径 |
| 缓存恢复 | 有旧缓存/数据库能力 | 增加 SQLite/旧 REST 状态重发布、空缓存判定、retained MQTT state，减少 HA 重启后 `unknown` |

## 特性

- **国家电网 / SGCC / 95598 数据接入**：采集电费余额、预付费余额、欠费/应交金额、日用电、月度用电、年度用电和峰/平/谷/尖分时电量。
- **Home Assistant 能源数据桥接**：通过 MQTT Discovery 自动创建设备与传感器，余额、账单、电量和历史读数可用于 HA 仪表盘、自动化和能源分析。
- **账号密码主路径加固**：沿用上游账号密码 + LLM 视觉验证码方向，补充登录态判定、受控导航、错误现场保存和二维码 fallback 边界。
- **有头 Chromium 运行形态**：每轮任务在 Xvfb 下启动有头 Chromium，支持持久 profile、页面/脚本超时控制，抓取完成后释放 driver。
- **Path B 主路径化**：把上游已有的 Vue state/component data 取数能力整理为 `Scraper` + `Parser` 主链路，读取 SGCC Vue2/Vuex `$store` 与组件 `data` 中的业务数据。
- **统一数据模型**：用 `AccountData` 聚合账户、余额、日/月/年读数和峰平谷尖数据，减少散落 dict 与重复解析。
- **规范化 SQLite 事实源**：将抓取结果、运行记录、会话检查与发布状态写入 `/data/sgcc.sqlite3`，比上游每日表/key-value 存储更适合恢复和排障。
- **MQTT Discovery + REST 双通道**：新增 Home Assistant MQTT Discovery 自动创建设备和实体，同时保留上游 REST states API 兼容路径。
- **缓存与重发布增强**：启动时优先从 SQLite、旧缓存或旧 REST 状态恢复发布，跳过空缓存，减少 HA 重启后实体缺值。

## 架构概览

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

主要模块包括：`config`、`redact`、`browser`、`login`、`session`、`scraper`、`parser`、`store`、`model`、`ha_mapping`、`sensor_updator`、`mqtt_publisher`、`captcha_selenium`、`click_captcha_solver`。

相关关键词：SGCC、State Grid、国家电网、网上国网、95598、Home Assistant、MQTT Discovery、SQLite、Selenium、Chromium、captcha、LLM、electricity、energy。

## 二开来源与重构范围

本项目继承上游能力，并在以下方向做重构：

- 上游已经支持账号密码登录、LLM 视觉验证码、二维码兜底、Vue state 辅助取数、余额、日/月/年用电、峰平谷尖、REST 传感器和可选 SQLite/MySQL。
- 本项目把这些能力拆成更清晰的浏览器、登录、抓取、解析、存储和发布模块。
- 当前版本重点增强：Vue/Vuex Path B 主链路、统一 `AccountData` 模型、规范化 SQLite fact store、MQTT Discovery 发布、启动重发布/缓存恢复、错误现场与脱敏观测。


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
- 本项目是国家电网 / 95598 / Home Assistant 用户社区的非官方桥接项目，与国家电网、95598、腾讯验证码和 Home Assistant 官方无隶属关系。

## 鸣谢

- 上游项目：[`ARC-MX/sgcc_electricity_new`](https://github.com/ARC-MX/sgcc_electricity_new)
- 原作者：renhai-lab
- 感谢 Home Assistant、Selenium、MQTT 与相关开源社区。

## 许可证

本项目遵循 Apache License 2.0。详见 [`LICENSE`](LICENSE) 与 [`NOTICE`](NOTICE)。
