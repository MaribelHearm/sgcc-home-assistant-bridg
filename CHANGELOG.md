# Changelog

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

[arc-v0.1.0]: https://github.com/MaribelHearm/sgcc-electricity-arc/releases/tag/arc-v0.1.0
