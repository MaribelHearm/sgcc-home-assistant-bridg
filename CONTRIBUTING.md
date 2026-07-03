# Contributing

感谢你愿意改进 SGCC Home Assistant Bridge。这个项目主要围绕 Home Assistant、MQTT Discovery、Docker/Add-on 部署和国网页面适配维护。

## 提交前请先确认

- 不要提交真实 `.env`、国网账号、Home Assistant Token、MQTT 密码、LLM API Key。
- 涉及登录、验证码、浏览器模式、实体字段、Docker/Add-on 的改动，请尽量附带复现说明和验证命令。
- 文档或示例变更请同步更新相关链接。

## 本地开发

```bash
python -m unittest discover -s tests -v
```

如果使用本仓库的虚拟环境：

```bash
.venv/bin/python -m pytest -q
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

## 目录约定

- `sgcc_ha_bridge/`：核心 Python 包。
- `scripts/`：Docker/Add-on shell 入口脚本。
- `tests/`：单元测试。
- `tools/`：离线辅助工具。
- `examples/`：可复制的 Home Assistant / Lovelace 示例。
- `docs/`：专题文档。

更多结构说明见 [docs/development.md](docs/development.md)。

## Issue 和 PR

提交 issue 时请尽量提供：

- 部署方式：Docker Compose / Add-on / 其他；
- 发布方式：`PUBLISHER=mqtt` / `rest` / `both`；
- 关键日志，注意先脱敏；
- Home Assistant、镜像版本或 commit；
- 期望行为和实际行为。

PR 建议保持范围清晰：一个 PR 只解决一个问题或一组强相关问题。
