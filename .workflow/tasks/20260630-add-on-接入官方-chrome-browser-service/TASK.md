# TASK: Add-on 接入官方 Chrome browser-service

## Status
validating

## Objective
把 SGCC Home Assistant Bridge 的 Add-on、Docker Compose 镜像和文档完整接入官方 Google Chrome `browser-service` 模式，供普通用户直接安装使用。

## Scope
- Docker Compose 支持 app/browser 双预构建镜像，默认 `SGCC_BROWSER_MODE=browser-service`。
- Home Assistant Add-on 单容器内嵌 browser manager，镜像内安装官方 `google-chrome-stable` 和匹配 ChromeDriver。
- Chrome 本体按需启动、任务结束后默认关闭；不承诺浏览器关闭后的国网免登录缓存。
- CI 同步发布 app/browser 镜像到 GHCR 和阿里云 ACR。
- README、DOCS、Add-on 教程、CHANGELOG、example.env、issue template 同步更新。

## Acceptance
- Add-on 用户不需要在 HAOS、NAS 或宿主机额外安装 Google Chrome。
- Docker Compose 用户可以直接 `docker compose pull && docker compose up -d` 使用成对镜像。
- `local` 旧 Chromium 模式和 `host-cdp/cdp` 高级模式仍保留为配置切换/回滚路径。
- 单测、YAML/脚本静态检查、Docker build、Add-on smoke、sidecar smoke、app→sidecar CDP attach smoke 通过。
- 提交推送到 `main`，并创建/推送 `v0.1.4` tag 触发镜像发布。

## Current step
执行最终复核、补齐质量门，然后 commit / push / tag。

## Next safest action
跑最终检查命令，确认无无关 diff 和敏感信息，再提交推送。

## Links
- PRD: `prd.md`
- Design: `design.md`
- Implementation: `implement.md`
- Validation: `validation.md`
- Handoff: `HANDOFF.md`
- Ledger: `ledger.jsonl`
