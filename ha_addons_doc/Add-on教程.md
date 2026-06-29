# SGCC Home Assistant Bridge Add-on/App 安装教程

本项目是国家电网 / SGCC / 95598 电费与用电数据接入 Home Assistant 的非官方桥接 Add-on/App，基于 [`ARC-MX/sgcc_electricity_new`](https://github.com/ARC-MX/sgcc_electricity_new) Apache-2.0 二开。

仓库地址：

```text
https://github.com/MaribelHearm/sgcc-home-assistant-bridg
```

当前状态：

- 预构建镜像先支持 `amd64`。
- 当前 Add-on 版本 `v0.1.3`，默认使用官方 Google Chrome `browser-service` 模式。
- Add-on 是单容器部署，镜像内已经包含官方 `google-chrome-stable` 和匹配 ChromeDriver；用户不需要在 HAOS、宿主机或 NAS 上另装 Google Chrome。
- 已在 HAOS 18.0 / Supervisor 2026.06.2 上验证仓库添加、识别、安装和启动。
- 真实国网账号抓取、LLM 验证码和 MQTT 发布建议按自己的账号环境再跑一轮。
- 本页截图来自当前项目 `SGCC Home Assistant Bridge` 的 HAOS 测试环境，配置截图已遮挡手机号、密码、Key、Token 等敏感信息。

## 安装步骤

### 1. 添加 Add-on/App 仓库

1. 打开 Home Assistant。
2. 进入 **设置**。
3. 打开 **Add-ons / Apps / 加载项**。
4. 进入 **Add-on Store / App Store / 加载项商店**。
5. 点击右上角三个点，选择 **Repositories / 仓库**。
6. 添加本项目仓库地址：

```text
https://github.com/MaribelHearm/sgcc-home-assistant-bridg
```

7. 保存后刷新 Store。

![添加当前项目 Add-on/App 仓库](img/current/01-add-repository.png)

### 2. 安装 SGCC Home Assistant Bridge

1. 在 Store 中找到 **SGCC Home Assistant Bridge**。
2. 打开详情页。
3. 点击 **Install / 安装**。
4. 等待安装完成。

![Store 中识别到 SGCC Home Assistant Bridge](img/current/02-store-addon.png)

如果列表里没有出现：

- 确认仓库地址没有拼错，仓库名是 `sgcc-home-assistant-bridg`。
- 刷新 Store。
- 确认当前 HAOS / Supervised 主机架构是 `amd64`。

### 3. 配置

安装完成后进入 **Configuration / 配置**，填写常用项：

| 配置项 | 说明 |
| --- | --- |
| `PHONE_NUMBER` | 国家电网 / 网上国网账号手机号。 |
| `PASSWORD` | 国家电网 / 网上国网密码。 |
| `IGNORE_USER_ID` | 需要忽略的户号，多个用英文逗号分隔，可留空。 |
| `LLM_BASE_URL` | OpenAI 兼容多模态接口 Base URL。 |
| `LLM_API_KEY` | OpenAI 兼容多模态接口 Key。 |
| `LLM_MODEL` | 多模态模型名或火山方舟 `ep-...` 接入点 ID。 |
| `PUBLISHER` | 推荐 `mqtt`，只生成 MQTT Discovery 设备实体；需要兼容旧仪表盘/自动化时再改为 `both`。 |
| `MQTT_HOST` | MQTT broker 地址。 |
| `MQTT_PORT` | MQTT broker 端口，通常是 `1883`。 |
| `MQTT_USERNAME` | MQTT 用户名，可留空。 |
| `MQTT_PASSWORD` | MQTT 密码，可留空。 |
| `MQTT_DISCOVERY_PREFIX` | 通常保持 `homeassistant`。 |
| `SGCC_BROWSER_MODE` | 默认 `browser-service`；如需回滚旧 Chromium 模式，可改为 `local`。 |
| `SGCC_BROWSER_SERVICE_STOP_ON_RELEASE` | 默认 `true`；每轮抓取结束后关闭 Chrome 本体，降低常驻资源占用。 |

![Configuration 页面示例，敏感字段已遮挡](img/current/04-configuration-redacted.png)

火山方舟 / 豆包示例：

```text
LLM_BASE_URL = https://ark.cn-beijing.volces.com/api/v3
LLM_API_KEY  = ark-xxxxxxxx
LLM_MODEL    = ep-xxxxxxxx
```

### 4. 启动

1. 保存配置。
2. 回到 **Info / 信息** 页面。
3. 点击 **Start / 启动**。
4. 查看 **Logs / 日志**。

![Add-on/App 详情页](img/current/03-addon-detail.png)

![Add-on/App 运行中状态，页面显示停止和重启按钮](img/current/05-addon-started.png)

启动后程序会：

- 读取 Add-on 配置。
- 启动内置 Xvfb 和轻量 browser manager。
- 默认使用官方 `google-chrome-stable`，在登录/抓取前按需启动 Chrome，通过 CDP attach，任务结束后关闭 Chrome 本体。
- 尝试从 SQLite 缓存恢复数据。
- 缓存不可用时登录国网页面抓取数据。
- 通过 MQTT Discovery / REST 发布到 Home Assistant。

### 5. 查看 Home Assistant 实体

MQTT Discovery 正常后，Home Assistant 会出现类似下面的设备：

```text
国网电费 ****1234
```

常见实体包括：

- 电费余额 / 预付费余额 / 应交金额
- 最近日用电
- 月度用电 / 月度电费
- 年度用电 / 年度电费
- 月度谷/平/峰/尖时电量
- `history` 历史数据实体
- `daily_YYYYMMDD` 日历史实体
- `monthly_YYYYMM` 月历史实体

## 常见问题

### 找不到 Add-on/App

- 检查仓库地址是否为：`https://github.com/MaribelHearm/sgcc-home-assistant-bridg`
- 刷新 Store。
- 确认主机架构是 `amd64`。

### 安装失败

- 检查 HAOS/Supervisor 能否拉取 GHCR 镜像。
- 镜像为：`ghcr.io/maribelhearm/sgcc-home-assistant-bridge:v0.1.3`
- 国内网络如果拉取 GHCR 很慢，可以先确认 HAOS/Supervisor 能访问 GHCR；当前 Add-on 默认使用 GHCR app 镜像。

### 验证码/登录未通过

- 确认 `LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL` 正确。
- 确认模型支持图片输入。
- 火山方舟建议 `LLM_MODEL` 填 `ep-...` 接入点 ID。
- 默认浏览器模式应为 `SGCC_BROWSER_MODE=browser-service`；如需临时回滚旧模式，可改为 `local` 后重启 Add-on。

### MQTT 实体未出现

- 确认 Home Assistant 已配置 MQTT 集成。
- 确认 `MQTT_HOST` 是 Add-on 容器能访问到的 broker 地址。
- 确认 `MQTT_DISCOVERY_PREFIX=homeassistant`。
- 查看 Add-on 日志是否有 MQTT 连接失败。

### 抓取失败

- 查看 Add-on 日志。
- 查看 `/data/errors` 中的错误截图、HTML 和 metadata。
- 如果出现 `RK001`，通常是 95598 / 腾讯验证码风控命中，本项目会停止本轮，避免反复打账号。
- Add-on 和 Docker Compose 默认都使用 `SGCC_BROWSER_MODE=browser-service`。Add-on 内嵌官方 Google Chrome browser manager；Docker Compose 使用官方 Google Chrome sidecar。
- 如果当前环境不适合新模式，可以把 `SGCC_BROWSER_MODE` 改成 `local` 回滚到 Debian Chromium + Xvfb。
