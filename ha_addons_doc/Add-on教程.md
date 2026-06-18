# SGCC Electricity ARC Add-on 安装教程

本项目是基于 [`ARC-MX/sgcc_electricity_new`](https://github.com/ARC-MX/sgcc_electricity_new) 的 Apache-2.0 二开版本，当前 Add-on 仓库地址为：

```text
https://github.com/MaribelHearm/sgcc-electricity-arc
```

## 安装步骤

### 1. 添加 Add-on 存储库

- 打开 Home Assistant。
- 进入设置页面，点击 “Add-ons” 或 “加载项”。
  ![进入Add-ons页面](./img/addons-page.png)
- 点击右下角的 “ADD-ON STORE” 或 “加载项商店”。
  ![打开Add-on商店](./img/addon-store.png)
- 点击右上角的三个点菜单。
- 选择 “Repositories” 或 “仓库”。
  ![添加存储库入口](./img/repositories-menu.png)
- 在弹出的对话框中输入本项目仓库地址：

```text
https://github.com/MaribelHearm/sgcc-electricity-arc
```

- 点击 “ADD” 或 “添加” 确认添加。
  ![添加存储库地址](./img/add-repository.png)

### 2. 安装 Add-on

- 点击右上角的三个点菜单。
- 选择 “Refresh” 或 “检查更新”。
  ![检查更新](./img/refresh.png)
- 在列表中找到 “SGCC Electricity ARC”。
- 点击 Add-on。
- 点击 “INSTALL” 或 “安装” 开始安装。
  ![安装Add-on](./img/install-addon.png)
- 等待安装完成。
  ![安装完成](./img/installation-complete.png)

### 3. 配置和启动

- 安装完成后，点击 “CONFIGURATION” 或 “配置” 标签。
- 填写国家电网账号密码、Home Assistant / MQTT、LLM 验证码接口等参数。
- 推荐保持 `PUBLISHER=both`，优先使用 MQTT Discovery 自动建实体，同时保留 REST 兼容发布。
- 如需忽略某些户号，填写 `IGNORE_USER_ID`，多个户号用英文逗号分隔。
- 点击 “SAVE” 或 “保存” 保存配置。
- 返回 “Info” 或 “信息” 标签页。
- 点击 “START” 或 “启动” 启动 Add-on。
- 启动后，点击 “日志” 标签页查看运行状态。

## 常见问题

- 如果无法找到新添加的 Add-on，请尝试刷新 Add-on Store。
- 如果安装失败，检查存储库地址是否正确。
- 如果验证码失败，检查 `LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL` 是否正确，且模型支持图片输入。
- 如果 MQTT 实体未出现，检查 Home Assistant MQTT 集成和 discovery 配置。
- 如果抓取失败，查看 `/data/errors` 中的错误现场文件。
