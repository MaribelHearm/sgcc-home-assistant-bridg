# SGCC Home Assistant Bridge

[![License](https://img.shields.io/github/license/MaribelHearm/sgcc-home-assistant-bridg)](LICENSE)
[![Release](https://img.shields.io/github/v/tag/MaribelHearm/sgcc-home-assistant-bridg?label=release)](https://github.com/MaribelHearm/sgcc-home-assistant-bridg/tags)
[![CI and Docker Image](https://github.com/MaribelHearm/sgcc-home-assistant-bridg/actions/workflows/docker-image.yml/badge.svg)](https://github.com/MaribelHearm/sgcc-home-assistant-bridg/actions/workflows/docker-image.yml)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-MQTT%20Discovery-41BDF5)](https://www.home-assistant.io/integrations/mqtt/)

把国家电网 / 网上国网 / 95598 的电费余额、日用电、月度用电、年度用电和峰平谷尖分时电量接入 Home Assistant。

适合已经在用 Home Assistant，希望把国网用电数据放进仪表盘、自动化、长期历史和能源看板的家庭用户。

> 非官方项目。基于 [`ARC-MX/sgcc_electricity_new`](https://github.com/ARC-MX/sgcc_electricity_new) 二次开发，保留 Apache-2.0 License、NOTICE 和上游来源说明。

## 能做什么

- 抓取国家电网账号下的余额、欠费、日/月/年用电数据；日用电会尽量切到国网页面近 30 天范围。
- 支持峰 / 平 / 谷 / 尖分时电量。
- 用 SQLite 保存本地事实库，便于重发布和排障。
- 通过 MQTT Discovery 在 Home Assistant 自动生成设备和实体。
- 保留 REST states API 兼容发布。
- 支持 Docker Compose、GHCR 预构建镜像和 Home Assistant OS/Supervised Add-on。
- Docker Compose 和 Home Assistant Add-on 默认提供官方 Google Chrome `browser-service` 模式，减少 Debian Chromium + Xvfb 指纹带来的 RK001 风险。
- LLM 验证码调用保持 OpenAI 兼容接口，也兼容火山方舟 / 豆包 `ARK_*` 配置写法。
- 无人值守模式默认每日一次真实登录；命中 RK001/验证码风控时会熔断冷却，避免连续重试打账号。

## 5 分钟快速开始

### 1. 准备依赖

- 一个可登录的国家电网 / 网上国网账号。
- Home Assistant MQTT broker，推荐 Mosquitto。
- 一个支持图片输入的 OpenAI 兼容多模态接口。火山方舟 / 豆包免费额度方案可用。

### 2. 配置 `.env`

```bash
cp example.env .env
$EDITOR .env
```

最小常用配置示例：

```env
PHONE_NUMBER="your-phone-number"
PASSWORD="your-password"

# 推荐 mqtt：只生成 MQTT Discovery 设备实体。
# 如需兼容旧仪表盘/自动化，可改为 both 同时发布旧 REST 实体。
PUBLISHER="mqtt"
MQTT_HOST="127.0.0.1"
MQTT_PORT=1883
MQTT_USERNAME=""
MQTT_PASSWORD=""

LLM_BASE_URL="https://ark.cn-beijing.volces.com/api/v3"
LLM_API_KEY="ark-xxxxxxxx"
LLM_MODEL="ep-xxxxxxxx"
```

如果只沿用上游火山方舟写法，也可以用：

```env
ARK_API_KEY="ark-xxxxxxxx"
ARK_MODEL="ep-xxxxxxxx"
```

同时存在时 `LLM_*` 优先。

### 3. 启动

本地构建：

```bash
docker compose build
docker compose up -d
```

或直接使用预构建 GHCR 镜像：

```bash
docker compose pull
docker compose up -d
```

`docker-compose.yml` 默认使用两套镜像：

```env
SGCC_APP_IMAGE=ghcr.io/maribelhearm/sgcc-home-assistant-bridge:latest
SGCC_BROWSER_IMAGE=ghcr.io/maribelhearm/sgcc-home-assistant-bridge-browser:latest
```

固定版本：

```env
SGCC_APP_IMAGE=ghcr.io/maribelhearm/sgcc-home-assistant-bridge:v0.1.4
SGCC_BROWSER_IMAGE=ghcr.io/maribelhearm/sgcc-home-assistant-bridge-browser:v0.1.4
```

国内网络访问 GHCR 慢时，可以换成阿里云 ACR 镜像：

```env
SGCC_APP_IMAGE=crpi-uqxz2jxgnrieto82.cn-hangzhou.personal.cr.aliyuncs.com/maribelhearm/sgcc_ha:latest
SGCC_BROWSER_IMAGE=crpi-uqxz2jxgnrieto82.cn-hangzhou.personal.cr.aliyuncs.com/maribelhearm/sgcc_ha:browser-latest
```

`latest` 跟随 GitHub `main` 分支发布；也可以使用 `main`、`sha-xxxxxxx` 或版本 tag 固定到一次构建。阿里云 ACR 为了保证匿名拉取稳定，app 和 browser 共用公开仓库：app 使用普通 tag，browser 使用 `browser-*` tag，例如 `sgcc_ha:v0.1.4` 搭配 `sgcc_ha:browser-v0.1.4`。

Compose 使用 `browser-service` 时，`SGCC_APP_IMAGE` 和 `SGCC_BROWSER_IMAGE` 建议固定到同一次发布的 tag，避免 app 内 ChromeDriver 与 sidecar Chrome 版本不一致。

查看日志：

```bash
docker compose logs -f sgcc_electricity_app
```

Home Assistant OS / Supervised 也可以直接添加 Add-on/App 仓库：

```text
https://github.com/MaribelHearm/sgcc-home-assistant-bridg
```

当前 Add-on 预构建镜像先支持 `amd64`，版本 `v0.1.4` 默认内置官方 Google Chrome `browser-service` 模式；Add-on 用户不需要在宿主机或 HAOS 上另装 Google Chrome。已在 HAOS 18.0 / Supervisor 2026.06.2 验证仓库添加、安装和启动流程。详细步骤见 [Add-on 安装教程](ha_addons_doc/Add-on教程.md)。

### 4. 浏览器模式

Docker Compose 和 Home Assistant Add-on 默认使用 `browser-service`：

```env
SGCC_BROWSER_MODE=browser-service
SGCC_CDP_ADDRESS=127.0.0.1:19222
SGCC_BROWSER_SERVICE_URL=http://127.0.0.1:39222
SGCC_BROWSER_SERVICE_STOP_ON_RELEASE=true
```

Docker Compose 默认启动两个服务：

- `sgcc_browser`：sidecar 容器，安装官方 `google-chrome-stable`，负责按需启动/停止 Chrome。
- `sgcc_electricity_app`：主程序容器，运行登录、抓取、解析和 HA/MQTT 发布，通过 CDP 连接 sidecar Chrome。

Home Assistant Add-on 不能启动 Compose 双容器，所以在 Add-on 单容器内嵌同一个轻量 browser manager，并在同一个 Add-on 镜像内安装官方 `google-chrome-stable` 和匹配 ChromeDriver；Chrome 本体仍然是按需启动、任务结束后关闭。

| 模式 | 适用场景 | 行为 |
|---|---|---|
| `browser-service` | 推荐；Docker Compose / Home Assistant Add-on 默认 | 官方 Google Chrome；抓取时按需启动 Chrome，app 通过 CDP attach，用完关闭 Chrome |
| `local` | 兼容旧部署 / 回滚测试 | app 容器内 Debian Chromium + Xvfb + ChromeDriver |
| `host-cdp` / `cdp` | 高级调试或真实桌面测试 | app 连接外部已启动的 Chrome CDP 地址，不负责启动/关闭 Chrome |

`browser-service` 不是让完整 Chrome 长期常驻：常驻的是轻量 browser manager 和 Xvfb；Google Chrome 本体在登录/抓取前启动，任务结束后默认关闭。Docker Compose 的 profile 默认挂载到 `${SGCC_BROWSER_SERVICE_PROFILE_HOST:-/data/sgcc-browser-profile}`，Add-on 默认使用 `/data/sgcc-browser-profile`。国网页面关闭浏览器后不保证免登录。

默认 Compose 使用 `network_mode: host`。如果你改成自定义 Docker network，并希望 app 通过 `sgcc_browser` 这类服务名访问 sidecar，需要显式启用小范围高级开关：

```env
SGCC_BROWSER_SERVICE_HOST=0.0.0.0
SGCC_BROWSER_SERVICE_URL=http://sgcc_browser:39222
SGCC_BROWSER_CDP_HOST=0.0.0.0
SGCC_BROWSER_CDP_PORT=19222
SGCC_BROWSER_CDP_INTERNAL_PORT=19223
SGCC_BROWSER_CDP_FORWARD_ENABLED=true
SGCC_CDP_ADDRESS=sgcc_browser:19222
```

新版 Chrome 可能强制 DevTools/CDP 只监听 `127.0.0.1`。启用 `SGCC_BROWSER_CDP_FORWARD_ENABLED` 后，browser-service 会启动一个内置 CDP 代理，把服务名访问转发到 Chrome 的内部 loopback 端口；默认关闭，普通 host network 部署不需要开启。

遇到 RK001 时，优先确认已切到 `browser-service` 并重建/更新后启动：

```bash
docker compose build
docker compose up -d
```

如果新模式不适合当前环境，可以回滚：

```env
SGCC_BROWSER_MODE=local
```

### 5. 去 Home Assistant 看实体

MQTT Discovery 正常后，HA 会出现一个类似 `国网电费 ****1234` 的设备，下面自动挂传感器。

### 关于新旧实体

推荐使用：

```env
PUBLISHER="mqtt"
```

此模式只通过 MQTT Discovery 生成实体，实体会挂在“国网电费 ****后四位”设备下。

如果设置为：

```env
PUBLISHER="both"
```

程序会同时发布：

- MQTT Discovery 实体：推荐的新实体，挂在“国网电费 ****后四位”设备下。
- REST 兼容实体：沿用旧项目命名，例如 `sensor.electricity_charge_balance_xxxx`、`sensor.month_electricity_usage_xxxx`。

REST 兼容实体主要用于迁移旧仪表盘或自动化。如果不需要兼容旧实体，建议使用 `PUBLISHER=mqtt`。

如果升级后 Home Assistant 里仍残留旧的 `unavailable` / `unknown` 实体，可以在 HA 的“设置 → 设备与服务 → 实体”中手动删除旧实体，或清理旧 MQTT retained discovery。

## 数据和实体概览

| 数据 | HA 表达 | 说明 |
| --- | --- | --- |
| 余额 | 电费余额、预付费余额、应交金额 | 当前账户金额状态。 |
| 日用电 | 最近日用电、`daily_YYYYMMDD` | 默认尝试读取近 30 天；最终数量以国网页面实际返回为准。 |
| 月度用电 | 月度用电、月度电费、`monthly_YYYYMM` | 月度历史数量以国网页面实际返回为准。 |
| 年度用电 | 年度用电、年度电费、`year_YYYY` | 年度汇总。 |
| 峰平谷尖 | 月度谷/平/峰/尖时电量 | 由当前月已抓到的日读数汇总。 |
| 曲线数据 | `history` 实体属性 | `daily` / `monthly` 数组适合给 ApexCharts 画图。 |

Lovelace 示例在：

```text
examples/lovelace-cards/
```

内置当前项目自用卡片示例，不会自动安装。已有 `state_grid` 仪表盘 YAML 可用 `tools/convert_state_grid_lovelace.py` 做字段替换。

## 常见问题

**RK001 是什么？**

通常不像普通网络超时，更像 95598 / 腾讯验证码风控命中。项目会保存错误现场；无人值守任务会停止本轮重试并进入冷却，避免无意义反复打账号。Docker Compose 和 Add-on 部署都建议先使用默认的 `SGCC_BROWSER_MODE=browser-service`。

**一直识别成 slider 怎么办？**

很多时候是隐藏验证码 DOM 被误判，或登录页资源没加载完整。本项目做了可见弹窗判断和登录页完整加载处理。

**HA 没有实体？**

先检查 MQTT broker、MQTT 集成 discovery、`MQTT_DISCOVERY_PREFIX=homeassistant`，再看容器日志。

**日历史、月历史不完整？**

正常。项目会尝试切换到国网页面近 30 天日用电范围，但不同地区、账号和页面状态返回的数据范围可能不同，本项目只发布国网页面实际返回的数据。

**验证码模型怎么填？**

火山方舟建议 `LLM_BASE_URL=https://ark.cn-beijing.volces.com/api/v3`，`LLM_API_KEY` 填 Ark Key，`LLM_MODEL` 填 `ep-...` 接入点 ID。

## 详细文档

- [DOCS.md](DOCS.md)：完整配置、实体、架构、故障排查和上游关系。
- [example.env](example.env)：环境变量示例。
- [Lovelace 示例](examples/lovelace-cards/)：HA 自用卡片示例。
- [state_grid Lovelace 迁移说明](docs/state-grid-lovelace-migration.md)：把已有 `state_grid` 仪表盘 YAML 做字段替换。
- [CHANGELOG.md](CHANGELOG.md)：版本记录。
- [NOTICE](NOTICE)：上游来源与版权说明。

## 项目状态

- 已在个人 Home Assistant 场景完成真实账号抓取验证。
- GitHub 默认分支为 `main`；CI 会运行单测并发布 GHCR 与阿里云 ACR 镜像。
- 国网页面、腾讯验证码和账号风控可能变化；失败时优先查看 `/data/errors` 中的现场文件和 `/data/sgcc_login_cooldown.json` 冷却状态。
- 本项目与国家电网、95598、腾讯验证码和 Home Assistant 官方无隶属关系。

## 社区链接

- LINUX DO 社区：[`linux.do`](https://linux.do)
- LINUX DO 开源推广帖：[`SGCC Home Assistant Bridge`](https://linux.do/t/topic/2431381)

## 鸣谢

- 上游项目：[`ARC-MX/sgcc_electricity_new`](https://github.com/ARC-MX/sgcc_electricity_new)
- 原作者：renhai-lab
- 感谢 Home Assistant、Selenium、MQTT 与相关开源社区。

## 许可证

Apache License 2.0。详见 [LICENSE](LICENSE) 与 [NOTICE](NOTICE)。
