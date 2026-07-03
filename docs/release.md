# 发布与镜像流程

## 版本来源

发布前保持这些位置一致：

- `pyproject.toml`：Python 包版本，例如 `0.1.4`。
- `config.yaml`：Home Assistant Add-on/App 版本，例如 `v0.1.4`。
- `CHANGELOG.md` / `DOCS.md` / `ha_addons_doc/`：对外文档中的版本说明。

## CI 输出

`main` 分支和 `v*` tag 会触发 `.github/workflows/docker-image.yml`：

- 跑单元测试、包入口导入检查和 Markdown 本地链接检查。
- 构建 app 镜像：`Dockerfile-for-github-action`。
- 构建 browser-service 镜像：`Dockerfile.browser`。
- 推送 GHCR；如果配置了 Aliyun ACR secrets，同步推送 ACR。

## 镜像 tag

GHCR 使用两个仓库：

```text
ghcr.io/maribelhearm/sgcc-home-assistant-bridge
ghcr.io/maribelhearm/sgcc-home-assistant-bridge-browser
```

常用 tag：

```text
latest
main
sha-xxxxxxx
v0.1.4
```

Aliyun ACR 使用同一个公开仓库，browser-service 镜像使用 `browser-*` 前缀：

```text
latest
main
sha-xxxxxxx
v0.1.4
browser-latest
browser-main
browser-sha-xxxxxxx
browser-v0.1.4
```

## 发布检查清单

```bash
python -m unittest discover -s tests -v
python -m pytest -q
python tools/check_markdown_links.py
docker build --check -f Dockerfile-for-github-action .
docker build --check -f Dockerfile.browser .
git diff --check
```

确认无误后：

1. 更新版本和 `CHANGELOG.md`。
2. 提交并推送到 `main`。
3. 创建 `v*` tag。
4. 等待 CI 构建并检查 GHCR / ACR 镜像 tag。
5. 对 Add-on/App 做一次安装或重启 smoke test。

## 回滚

- Docker Compose：把 `.env` 的 `SGCC_APP_IMAGE` / `SGCC_BROWSER_IMAGE` 固定回上一个 tag，然后 `docker compose pull && docker compose up -d`。
- Add-on/App：回滚到上一个 `config.yaml` 版本对应的 GHCR tag，或临时使用上一版仓库提交。
