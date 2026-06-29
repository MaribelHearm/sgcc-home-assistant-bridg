# Design: Add-on 接入官方 Chrome browser-service

## Current state evidence
- 原 `local` 模式是 app 容器内 Debian Chromium + ChromeDriver + Xvfb，容易表现为自动化容器环境。
- 之前已新增 Compose `sgcc_browser` sidecar，但 Add-on 用户仍需要单容器内解决，不能要求 HAOS/NAS 自备 Chrome。
- Add-on 配置由 `/data/options.json` 注入，不能只依赖 Compose `.env`。

## Proposed design
1. **Docker Compose 双容器**
   - `sgcc_browser` 使用 `Dockerfile.browser`，安装官方 `google-chrome-stable`，运行 `browser_service.py`。
   - `sgcc_electricity_app` 使用 app 镜像，通过 `SGCC_BROWSER_SERVICE_URL` 调 `/start`，再用 ChromeDriver CDP attach 到 `SGCC_CDP_ADDRESS`。
   - Chrome 本体按需启动，`release_driver()` 后默认 `/stop`。

2. **Home Assistant Add-on 单容器**
   - `Dockerfile-for-github-action` 同时安装 Debian Chromium/driver（兼容 `local`）和官方 `google-chrome-stable`。
   - 构建时按 `google-chrome --product-version` 下载 Chrome for Testing matching ChromeDriver 到 `/usr/local/bin/chromedriver`。
   - `docker-entrypoint.sh` 读取 `/data/options.json`；Add-on 默认 `browser-service`。
   - Add-on 内启动 Xvfb + `browser_service.py`，但 Chrome 本体仍由 manager 按需启动/关闭。

3. **驱动选择**
   - `local` 模式优先 `/usr/bin/chromedriver` 驱动 Debian Chromium。
   - CDP/browser-service 模式优先 `/usr/local/bin/chromedriver` attach 官方 Google Chrome。
   - `SGCC_CHROMEDRIVER_PATH` 保留显式覆盖。

4. **发布和文档**
   - Compose 支持 `SGCC_APP_IMAGE` / `SGCC_BROWSER_IMAGE` 直接拉 GHCR/ACR 镜像。
   - GitHub Actions 同步构建 app/browser 两个镜像。
   - 文档明确 Add-on 用户无需自备 Chrome，Compose 建议 app/browser 使用同一 tag。

## Affected paths
- `Dockerfile-for-github-action`
- `Dockerfile.browser`
- `scripts/docker-entrypoint.sh`
- `scripts/browser-service-entrypoint.sh`
- `scripts/browser.py`
- `docker-compose.yml`
- `config.yaml`
- `.github/workflows/docker-image.yml`
- `README.md`, `DOCS.md`, `ha_addons_doc/Add-on教程.md`, `CHANGELOG.md`, `NOTICE`, `example.env`

## Flow
- Add-on 启动 → entrypoint 读取 `/data/options.json` → 默认 `browser-service` → 启动 Xvfb + browser manager → main 抓取 → `build_driver()` 调 `/start` → 官方 Chrome 监听 CDP → ChromeDriver attach → 抓取完成 → `release_driver()` 调 `/stop`。
- Compose 启动 → `sgcc_browser` 常驻 Xvfb + browser manager → app 抓取时同样 `/start` + CDP attach → 完成后 `/stop`。

## Risks
- Google Chrome 与 ChromeDriver 主版本/完整版本不一致会导致 CDP attach 失败；通过 app 镜像 matching driver 和文档要求成对 tag 降低风险。
- `network_mode: host` 下 Xvfb `:99` 可能与宿主/其他容器锁冲突；入口脚本使用 `-nolisten tcp -nolisten local -nolock` 并清理 lock。
- RK001 属于对端风控结果，浏览器优化不能保证绝对不出现；文档只写“优先使用默认 browser-service”。

## Rollback
- 配置回滚：设置 `SGCC_BROWSER_MODE=local`，重启容器/Add-on。
- 代码回滚：revert 本次 commit。
- 发布回滚：用户固定到旧镜像 tag；如 tag 发布失败则不覆盖既有 tag、不 force push。

## Alternatives
- 宿主机真实桌面 Chrome profile：对测试机更强，但 Add-on/NAS 普通用户不可依赖。
- 长期常驻完整 Chrome + CDP attach：登录态相对稳，但资源占用不符合用户要求。
- 继续优化验证码识别或 `--disable-blink`：不是本次根因方向。
