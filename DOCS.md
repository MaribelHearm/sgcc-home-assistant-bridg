# SGCC Electricity ARC Add-on 配置和启动

本项目是基于 [`ARC-MX/sgcc_electricity_new`](https://github.com/ARC-MX/sgcc_electricity_new) 的二开版本，Add-on 仓库地址为：

```text
https://github.com/MaribelHearm/sgcc-electricity-arc
```

## 配置和启动

### 1. 配置

- 安装完成后，点击 “CONFIGURATION” 或 “配置” 标签。
- 填写国家电网账号密码、Home Assistant / MQTT、LLM 验证码接口等参数。
- 推荐保持 `PUBLISHER=both`：MQTT Discovery 自动建实体，REST 路径兼容旧传感器。
- 点击 “SAVE” 或 “保存” 保存配置。

关键配置：

- `PHONE_NUMBER` / `PASSWORD`：国家电网账号密码。
- `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL`：OpenAI 兼容多模态模型，用于点选验证码。
- `MQTT_HOST` / `MQTT_PORT` / `MQTT_USERNAME` / `MQTT_PASSWORD`：Home Assistant MQTT Discovery。
- `HASS_URL` / `HASS_TOKEN`：REST states API 兼容发布。
- `SGCC_DB_PATH`：SQLite 事实库路径，默认 `/data/sgcc.sqlite3`。
- `IGNORE_USER_ID`：需要忽略的户号，多个用英文逗号分隔。

### 2. 启动

- 返回 “Info” 或 “信息” 标签页。
- 点击 “START” 或 “启动” 启动 Add-on。
- 启动后查看 “日志” 标签页。
- 如果抓取失败，优先查看 `/data/errors` 中保存的截图、HTML 和 metadata。

## 常见问题

- 如果无法找到新添加的 Add-on，请刷新 Add-on Store。
- 如果安装失败，检查存储库地址是否为 `https://github.com/MaribelHearm/sgcc-electricity-arc`。
- 如果 MQTT 实体未出现，检查 Home Assistant MQTT 集成是否启用 discovery，以及 `MQTT_DISCOVERY_PREFIX` 是否为 `homeassistant`。
- 如果验证码失败，检查 LLM 接口是否支持图片输入，且 `.env` / Add-on 配置中的 Key 没有留空。
