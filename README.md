# SGCC Home Assistant Bridge

[![License](https://img.shields.io/github/license/MaribelHearm/sgcc-home-assistant-bridg)](LICENSE)
[![Release](https://img.shields.io/github/v/tag/MaribelHearm/sgcc-home-assistant-bridg?label=release)](https://github.com/MaribelHearm/sgcc-home-assistant-bridg/tags)
[![CI and Docker Image](https://github.com/MaribelHearm/sgcc-home-assistant-bridg/actions/workflows/docker-image.yml/badge.svg)](https://github.com/MaribelHearm/sgcc-home-assistant-bridg/actions/workflows/docker-image.yml)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-MQTT%20Discovery-41BDF5)](https://www.home-assistant.io/integrations/mqtt/)

把国家电网 / 网上国网 / 95598 的电费余额、日用电、月度用电、年度用电和峰平谷尖分时电量接入 Home Assistant。

本项目适合已经在用 Home Assistant，希望把国网用电数据放进仪表盘、自动化、长期历史和能源看板的家庭用户。

> 非官方项目。基于 [`ARC-MX/sgcc_electricity_new`](https://github.com/ARC-MX/sgcc_electricity_new) 二次开发，保留 Apache-2.0 License、NOTICE 和上游来源说明。

## 特性

- 抓取电费余额、欠费、日/月/年用电数据。
- 支持峰 / 平 / 谷 / 尖分时电量。
- 使用 SQLite 保存本地事实库，方便重发布和排障。
- 支持 MQTT Discovery 自动生成 Home Assistant 设备和实体。
- 保留 REST states API 兼容发布，方便旧仪表盘迁移。
- 支持 Docker Compose、GHCR 镜像和 Home Assistant OS / Supervised Add-on。
- 默认提供官方 Google Chrome `browser-service` 模式，减少无人值守登录风控概率。
- 验证码识别使用 OpenAI 兼容多模态接口，也兼容火山方舟 / 豆包 `ARK_*` 配置。

## 快速开始

### 1. 准备

你需要：

- 一个可登录的国家电网 / 网上国网账号；
- 一个 Home Assistant MQTT broker，推荐 Mosquitto；
- 一个支持图片输入的 OpenAI 兼容多模态接口。

### 2. 配置环境变量

```bash
cp example.env .env
$EDITOR .env
```

最小配置示例：

```env
PHONE_NUMBER="your-phone-number"
PASSWORD="your-password"

PUBLISHER="mqtt"
MQTT_HOST="127.0.0.1"
MQTT_PORT=1883
MQTT_USERNAME=""
MQTT_PASSWORD=""

LLM_BASE_URL="https://ark.cn-beijing.volces.com/api/v3"
LLM_API_KEY="ark-xxxxxxxx"
LLM_MODEL="ep-xxxxxxxx"
```

### 3. 启动

```bash
docker compose pull
docker compose up -d
```

查看日志：

```bash
docker compose logs -f sgcc_electricity_app
```

如果需要本地构建：

```bash
docker compose build
docker compose up -d
```

Home Assistant OS / Supervised 可以添加 Add-on/App 仓库：

```text
https://github.com/MaribelHearm/sgcc-home-assistant-bridg
```

完整部署说明见 [DOCS.md](DOCS.md)。

## 实体和数据

推荐使用 `PUBLISHER=mqtt`。项目会通过 MQTT Discovery 创建一组设备实体。

| 数据 | 说明 |
| --- | --- |
| 余额 / 欠费 | 电费余额、预付费余额、应交金额。 |
| 日用电 | 最近日用电和独立 `daily_YYYYMMDD` 历史实体。 |
| 月度用电 | 月度用电、月度电费和独立 `monthly_YYYYMM` 历史实体。 |
| 年度用电 | 年度用电、年度电费和独立 `year_YYYY` 历史实体。 |
| 峰平谷尖 | 当前月已抓到日读数汇总后的分时电量。 |
| 曲线数据 | `history` 实体属性里的 `daily` / `monthly` 数组。 |

REST 兼容实体仍可用，主要用于迁移旧仪表盘或自动化。详细实体说明见 [DOCS.md#5-home-assistant-实体](DOCS.md#5-home-assistant-实体)。

## Lovelace 示例

示例和截图在：

```text
examples/
assets/lovelace-cards/
```

常用入口：

- [examples/README.md](examples/README.md)：示例目录索引。
- [examples/lovelace-cards/](examples/lovelace-cards/)：三套内置卡片示例。
- [docs/state-grid-lovelace-migration.md](docs/state-grid-lovelace-migration.md)：`state_grid` 仪表盘字段替换说明。

已有 `state_grid` 仪表盘 YAML 时，不建议让后端兼容另一套实体模型；可以用 `tools/convert_state_grid_lovelace.py` 做离线字段替换。

## 文档

- [DOCS.md](DOCS.md)：完整配置、部署、实体、浏览器模式和排障。
- [example.env](example.env)：环境变量示例。
- [docs/development.md](docs/development.md)：仓库结构和本地开发。
- [docs/release.md](docs/release.md)：版本、镜像和发布流程。
- [examples/README.md](examples/README.md)：示例目录索引。
- [CHANGELOG.md](CHANGELOG.md)：版本记录。
- [NOTICE](NOTICE)：上游来源与版权说明。

## 开发

项目源码在 `sgcc_ha_bridge/`，`scripts/` 只保留 Docker/Add-on shell 入口脚本。

本地验证：

```bash
python -m unittest discover -s tests -v
```

更多说明见 [CONTRIBUTING.md](CONTRIBUTING.md) 和 [docs/development.md](docs/development.md)。

## 许可证

Apache-2.0。详见 [LICENSE](LICENSE)。
