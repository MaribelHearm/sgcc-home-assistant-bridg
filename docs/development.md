# 开发与仓库结构

这个仓库按“可发布开源项目”整理：运行代码、部署入口、测试、示例和文档分开存放。

## 目录结构

```text
sgcc_ha_bridge/   核心 Python 包
scripts/          Docker/Add-on shell 入口脚本
tests/            单元测试
tools/            离线辅助脚本
examples/         Home Assistant / Lovelace 示例
docs/             专题文档
assets/           README/docs/examples 使用的图片素材
ha_addons_doc/    Home Assistant Add-on/App 图文说明
.github/          CI 和 PR 模板
```

## Python 入口

业务代码只放在 `sgcc_ha_bridge/`。本地调试和容器入口都使用包模块入口：

```bash
python -m sgcc_ha_bridge.main
python -m sgcc_ha_bridge.browser_service
```

安装为 Python 包后也会提供两个 console script：

```bash
sgcc-ha-bridge
sgcc-browser-service
```

Docker / Add-on 的 shell 包装脚本位于 `scripts/`，只负责读取 Add-on options、选择浏览器模式、启动 Xvfb/browser-service，并最终执行上面的包模块入口。

## 本地验证

标准单测：

```bash
python -m unittest discover -s tests -v
```

如果本机 `.venv` 已安装测试依赖：

```bash
.venv/bin/python -m pytest -q
```

包入口导入检查：

```bash
python - <<'PY'
import importlib
for mod in ["sgcc_ha_bridge.main", "sgcc_ha_bridge.browser_service"]:
    module = importlib.import_module(mod)
    assert hasattr(module, "main")
print("package entrypoints import ok")
PY
```

Dockerfile 静态检查：

```bash
docker build --check -f Dockerfile-for-github-action .
docker build --check -f Dockerfile.browser .
```

Markdown 本地链接检查：

```bash
python tools/check_markdown_links.py
```

## 文档分工

- `README.md`：项目门面、快速开始和文档索引。
- `DOCS.md`：完整配置、部署、实体和排障说明。
- `docs/release.md`：版本、镜像和发布检查清单。
- `docs/`：专题文档。
- `examples/`：可复制示例，不承诺自动安装。
