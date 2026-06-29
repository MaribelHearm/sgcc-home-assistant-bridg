# PRD: Add-on 接入官方 Chrome browser-service

## User goal
把当前 RK001 浏览器环境优化方案做成别人可直接用的正式版本：镜像、Add-on、本体配置、文档都落地，不要求用户自己准备宿主机 Google Chrome。

## Requirements
- Docker Compose 默认使用官方 Google Chrome browser-service，而不是容器内 Debian Chromium。
- Compose 普通用户可以直接拉取 app/browser 两个镜像，仍保留本地 build。
- Home Assistant Add-on 用户默认可用，不依赖宿主机桌面、HAOS 里额外安装 Chrome 或常驻完整 Chrome。
- Add-on 单容器内嵌 browser manager，官方 Chrome 按需启动/关闭。
- 配置文件能在 `browser-service`、`local`、`host-cdp/cdp` 之间切换。
- 文档说清 Compose、Add-on、镜像 tag、回滚和 RK001 建议。
- 通过真实构建与 smoke 验证后提交、推送、打版本 tag。

## Constraints
- 不把“人工扫码/缓存免登录”作为方案承诺；国网页面关闭浏览器后登录态不保证可复用。
- 不让普通 Add-on 用户自己备 Google Chrome。
- 保留旧 `local` 模式作为兼容回滚。
- 普通 commit/push/tag 已由用户授权；不做 force push。

## Non-goals
- 不继续堆验证码识别或反自动化启动参数作为主方案。
- 不处理 issue 评论收尾。
- 不承诺所有 SGCC/RK001 风控环境永不命中，只交付浏览器环境优化与可切换配置。

## Acceptance criteria
- Add-on `config.yaml` 版本为 `v0.1.3`，默认 `SGCC_BROWSER_MODE=browser-service`。
- app 镜像内包含官方 Chrome + matching ChromeDriver，支持 Add-on 单容器嵌入 browser-service。
- browser 镜像可作为 Compose sidecar 按需启动/停止 Chrome。
- CI 同时发布 app/browser 镜像。
- 文档覆盖 Add-on 用户和 Docker Compose 用户怎么用。
- 单测、构建、smoke 验证通过。
