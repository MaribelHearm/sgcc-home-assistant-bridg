# Changelog

## [Unreleased]

### Added

- 每日定时抓取在持续运行期间会为下一天重新抽取 `SGCC_DAILY_JITTER_MINUTES` 偏移；每天两次任务仍共用当天偏移并保持 12 小时间隔。
- 新增可配置的 `phone-code,qrcode` 人工登录兜底顺序，以及 Telegram Bot 二维码通知、短信验证码回复和结果通知。
- 新增统一的 `SGCC_LOGIN_FALLBACK_UNATTENDED` 安全开关；默认定时任务不等待人工响应，旧 `SGCC_QRCODE_FALLBACK_UNATTENDED` 保持兼容。
- 新增默认关闭的 `SGCC_RISK_FALLBACK_OVERRIDE`；只有本次任务原本允许 fallback 时，才可在 RK001 后尝试一次已配置的限时人工接管，失败仍进入冷却。

## [v0.1.5] - 2026-07-03

### Changed

- 整理仓库结构：移除 `scripts/` Python 兼容 wrapper，Docker/Add-on/镜像入口统一使用 `sgcc_ha_bridge` 包模块。
- 整理 examples、开发文档和发布文档，补充 Markdown 本地链接检查。

### CI

- 补充包入口导入检查、Markdown 本地链接检查和 Dockerfile 静态检查，文档与示例变更也会触发 CI。

## [v0.1.4] - 2026-06-30

### Fixed

- 修正阿里云 ACR browser-service 镜像发布方式：browser 镜像改为发布到已公开的 `sgcc_ha:browser-*` tag，避免新建 `sgcc_ha_browser` 仓库匿名拉取失败。
- Add-on 版本更新到 `v0.1.4`。

### Docs

- 更新 Docker Compose 国内镜像示例，app 使用 `sgcc_ha:*`，browser 使用 `sgcc_ha:browser-*`。

## [v0.1.3] - 2026-06-30

### Added

- Docker Compose 新增官方 Google Chrome browser-service sidecar 镜像，默认 `SGCC_BROWSER_MODE=browser-service`，主程序通过 CDP attach，Chrome 按需启动并在任务结束后关闭。
- Home Assistant Add-on 默认接入单容器内嵌 browser-service，镜像内安装官方 `google-chrome-stable` 和匹配 ChromeDriver；Add-on 用户不需要另装 Google Chrome。
- CI 同时发布 app 镜像和 browser-service 镜像到 GHCR / 阿里云 ACR。

### Changed

- Add-on 版本更新到 `v0.1.3`。
- `docker-compose.yml` 支持通过 `SGCC_APP_IMAGE` / `SGCC_BROWSER_IMAGE` 直接拉取预构建镜像，也保留本地 build。

### Docs

- 补充 `browser-service` / `local` / `host-cdp` 三种浏览器模式说明，以及 Docker Compose、Add-on 和 RK001 场景下的配置切换方式。

## [v0.1.2] - 2026-06-27

### Fixed

- 修复多户号账号只抓到部分户号的问题：Path B 现在会先抓当前户号，再遍历所有可切换下拉项，并按真实户号去重，避免当前户号被下拉组件隐藏/禁用或同名民用户号被文本去重折叠。

### Changed

- Add-on 版本更新到 `v0.1.2`。

## [v0.1.1] - 2026-06-19

### Added

- 日用电抓取会尽量切换到国网页面近 30 天范围，并把更多日历史发布到 HA/MQTT。
- 新增无人值守登录风控熔断：RK001、操作频繁、验证码通过后仍失败等情况会进入冷却，避免立即重试反复打账号。
- 新增 `SGCC_DAILY_RUNS`、`RISK_COOLDOWN_MINUTES`、`SGCC_LOGIN_COOLDOWN_ENABLED`、`SGCC_QRCODE_FALLBACK_UNATTENDED` 等运行参数。

### Changed

- 无人值守默认每日一次真实登录；二维码兜底默认不用于定时无人值守任务。
- 浏览器启动时补充语言、timezone 与 webdriver 显性特征一致性设置，减少误判风险。

## [arc-v0.1.0] - 2026-06-18

第一版 SGCC Home Assistant Bridge 二开发布。

### Added

- 真实浏览器账号密码登录，支持多模态 LLM 点选验证码。
- Path B 抓取 SGCC Vue2/Vuex store 与组件数据。
- 规范化 SQLite 本地事实源：账户、余额、日/月/年用电、运行记录、会话检查、发布状态。
- Home Assistant MQTT Discovery 自动创建设备和实体，并保留 REST states API 兼容发布。
- 日用电、月度、年度、峰/平/谷/尖分时数据的缓存恢复与重发布。
- 错误现场保存与日志脱敏。

### Changed

- 保留上游 Home Assistant / Docker 部署外壳，重写核心抓取、解析、存储和发布链路。
- 项目元数据、README、Add-on repository 信息改为 SGCC Home Assistant Bridge。

[arc-v0.1.0]: https://github.com/MaribelHearm/sgcc-home-assistant-bridg/releases/tag/arc-v0.1.0
