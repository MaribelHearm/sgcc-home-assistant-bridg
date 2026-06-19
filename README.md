# SGCC Home Assistant Bridge

[![License](https://img.shields.io/github/license/MaribelHearm/sgcc-home-assistant-bridg)](LICENSE)
[![Release](https://img.shields.io/github/v/tag/MaribelHearm/sgcc-home-assistant-bridg?label=release)](https://github.com/MaribelHearm/sgcc-home-assistant-bridg/tags)
[![CI and Docker Image](https://github.com/MaribelHearm/sgcc-home-assistant-bridg/actions/workflows/docker-image.yml/badge.svg)](https://github.com/MaribelHearm/sgcc-home-assistant-bridg/actions/workflows/docker-image.yml)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-MQTT%20Discovery-41BDF5)](https://www.home-assistant.io/integrations/mqtt/)

把国家电网 / 网上国网 / 95598 的电费余额、日用电、月度用电、年度用电和峰平谷尖分时电量接入 Home Assistant。

适合已经在用 Home Assistant，希望把国网用电数据放进仪表盘、自动化、长期历史和能源看板的家庭用户。

> 非官方项目。基于 [`ARC-MX/sgcc_electricity_new`](https://github.com/ARC-MX/sgcc_electricity_new) 二次开发，保留 Apache-2.0 License、NOTICE 和上游来源说明。

## 能做什么

- 抓取国家电网账号下的余额、欠费、日/月/年用电数据。
- 支持峰 / 平 / 谷 / 尖分时电量。
- 用 SQLite 保存本地事实库，便于重发布和排障。
- 通过 MQTT Discovery 在 Home Assistant 自动生成设备和实体。
- 保留 REST states API 兼容发布。
- 支持 Docker Compose、GHCR 预构建镜像和 Home Assistant OS/Supervised Add-on。
- LLM 验证码调用保持 OpenAI 兼容接口，也兼容火山方舟 / 豆包 `ARK_*` 配置写法。

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

PUBLISHER="both"
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

或使用 GHCR 镜像，把 `docker-compose.yml` 中的 `build` 改成：

```yaml
image: ghcr.io/maribelhearm/sgcc-home-assistant-bridge:latest
```

固定版本：

```yaml
image: ghcr.io/maribelhearm/sgcc-home-assistant-bridge:v0.1.0
```

国内网络访问 GHCR 慢时，可以把 `image:` 换成阿里云 ACR 镜像：

```yaml
image: crpi-uqxz2jxgnrieto82.cn-hangzhou.personal.cr.aliyuncs.com/maribelhearm/sgcc_ha:latest
```

查看日志：

```bash
docker compose logs -f sgcc_electricity_app
```

Home Assistant OS / Supervised 也可以直接添加 Add-on/App 仓库：

```text
https://github.com/MaribelHearm/sgcc-home-assistant-bridg
```

当前 Add-on 预构建镜像先支持 `amd64`，已在 HAOS 18.0 / Supervisor 2026.06.2 验证安装和启动。详细步骤见 [Add-on 安装教程](ha_addons_doc/Add-on教程.md)。

### 4. 去 Home Assistant 看实体

MQTT Discovery 正常后，HA 会出现一个类似 `国网电费 ****1234` 的设备，下面自动挂传感器。

## 数据和实体概览

| 数据 | HA 表达 | 说明 |
| --- | --- | --- |
| 余额 | 电费余额、预付费余额、应交金额 | 当前账户金额状态。 |
| 日用电 | 最近日用电、`daily_YYYYMMDD` | 日历史数量以国网页面实际返回为准。 |
| 月度用电 | 月度用电、月度电费、`monthly_YYYYMM` | 月度历史数量以国网页面实际返回为准。 |
| 年度用电 | 年度用电、年度电费、`year_YYYY` | 年度汇总。 |
| 峰平谷尖 | 月度谷/平/峰/尖时电量 | 由当前月已抓到的日读数汇总。 |
| 曲线数据 | `history` 实体属性 | `daily` / `monthly` 数组适合给 ApexCharts 画图。 |

Lovelace 示例在：

```text
examples/lovelace-sgcc-electricity.yaml
```

它只是示例视图，不会自动安装；曲线部分依赖 HACS 的 `apexcharts-card`。

## 常见问题

**RK001 是什么？**

通常不像普通网络超时，更像 95598 / 腾讯验证码风控命中。项目会保存错误现场，避免无意义反复打账号。

**一直识别成 slider 怎么办？**

很多时候是隐藏验证码 DOM 被误判，或登录页资源没加载完整。本项目做了可见弹窗判断和登录页完整加载处理。

**HA 没有实体？**

先检查 MQTT broker、MQTT 集成 discovery、`MQTT_DISCOVERY_PREFIX=homeassistant`，再看容器日志。

**日历史、月历史不完整？**

正常。不同地区、账号和页面状态返回的数据范围可能不同，本项目只发布国网页面实际返回的数据。

**验证码模型怎么填？**

火山方舟建议 `LLM_BASE_URL=https://ark.cn-beijing.volces.com/api/v3`，`LLM_API_KEY` 填 Ark Key，`LLM_MODEL` 填 `ep-...` 接入点 ID。

## 详细文档

- [DOCS.md](DOCS.md)：完整配置、实体、架构、故障排查和上游关系。
- [example.env](example.env)：环境变量示例。
- [Lovelace 示例](examples/lovelace-sgcc-electricity.yaml)：HA 仪表盘示例视图。
- [CHANGELOG.md](CHANGELOG.md)：版本记录。
- [NOTICE](NOTICE)：上游来源与版权说明。

## 项目状态

- 已在个人 Home Assistant 场景完成真实账号抓取验证。
- CI 会运行单测并构建 / 发布 GHCR 镜像。
- 国网页面、腾讯验证码和账号风控可能变化；失败时优先查看 `/data/errors` 中的现场文件。
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
