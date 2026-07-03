# scripts

这里只保留 Docker / Home Assistant Add-on 使用的 shell 入口脚本。

真实业务代码在 `sgcc_ha_bridge/`，Python 入口统一使用：

```bash
python -m sgcc_ha_bridge.main
python -m sgcc_ha_bridge.browser_service
```

`docker-entrypoint.sh` 用于主镜像和 Add-on；`browser-service-entrypoint.sh` 用于 Docker Compose 的 browser-service sidecar 镜像。
