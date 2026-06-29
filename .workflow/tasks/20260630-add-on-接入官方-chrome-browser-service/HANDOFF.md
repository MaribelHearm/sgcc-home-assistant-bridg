# HANDOFF: Add-on 接入官方 Chrome browser-service

## Original objective
把 SGCC Home Assistant Bridge 的 Add-on/镜像完整接入官方 Google Chrome browser-service 模式，更新配置、文档、验证并推送。

## Current status
validating / ready to commit

## Completed
- Docker Compose 支持 app/browser 双镜像，默认 `browser-service`。
- Add-on `v0.1.3` 默认单容器内嵌 browser manager，镜像内含官方 Chrome 和 matching ChromeDriver。
- ChromeDriver 选择按 `local` 与 CDP/browser-service 分流。
- sidecar entrypoint 修复 Xvfb host-network lock 和可选 noVNC helper 退出问题。
- CI 增加 GHCR/ACR browser 镜像发布。
- README、DOCS、Add-on 教程、CHANGELOG、NOTICE、example.env、issue template 已更新。
- 静态检查、单测、Docker build、Compose config、Add-on smoke、sidecar smoke、app→sidecar attach smoke 已通过。

## Pending
- 最终 `git diff --check` / status 复核。
- `git commit -m "✨ feat: 支持 Add-on 官方 Chrome 模式"`。
- `git push origin main`。
- 如果远端不存在 `v0.1.3` tag，则创建并推送。
- 检查 GitHub Actions 发布运行。

## Files changed
- `.github/ISSUE_TEMPLATE/bug_report.yml`
- `.github/workflows/docker-image.yml`
- `CHANGELOG.md`
- `DOCS.md`
- `Dockerfile-for-github-action`
- `Dockerfile.browser`
- `NOTICE`
- `README.md`
- `config.yaml`
- `docker-compose.yml`
- `example.env`
- `ha_addons_doc/Add-on教程.md`
- `scripts/browser-service-entrypoint.sh`
- `scripts/browser.py`
- `scripts/docker-entrypoint.sh`
- `.workflow/tasks/20260630-add-on-接入官方-chrome-browser-service`
- `.workflow/state/current.json`

## Evidence
- `validation.md` 记录完整命令与 smoke 结果。
- `quality-gate.json` 所有 gate 预期 pass。
- 运行时关键证据：Add-on embedded manager ready；sidecar CDP `/json/version` 为 `Chrome/149.0.7827.200`；app attach 后 `release_driver()` 能关闭 Chrome。

## Risks
- 上游 RK001 风控不能由项目保证完全消失；本改动只优化默认浏览器运行环境。
- app/browser 镜像应使用同一 tag，以避免 ChromeDriver 与 Chrome 不匹配。

## Next action
跑最终检查，提交推送，打 `v0.1.3` tag，检查 CI。

## Last user instruction
- “你直接完美处理完 毕竟是给别人用了 处理完后 更新文档 开goal做 包括镜像 啊 addon 本体啊 做好”。
