# Desktop Agent App 中文说明

这是一个桌面端智能体 MVP，可在 Windows 和 macOS 上运行。

项目能力：

- 使用 `tkinter` 提供本地图形界面
- 使用 `pyautogui` 执行鼠标、键盘和截图操作
- 使用兼容 OpenAI API 的模型进行任务规划、执行和校验
- 采用 `planner -> executor/supervisor -> verifier -> loop` 的运行方式

## 安装

```bash
cd desktop_agent_app
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 运行

```bash
python .\app.py
```

首次运行前，你可以将 `config.example.json` 复制为 `config.json`，也可以先启动程序，再通过 `Config` 弹窗填写配置。

## 主要文件

- `app.py`：跨平台桌面 GUI
- `config.py`：配置持久化，使用本地 `config.json`
- `computer_control.py`：本地鼠标、键盘、截图控制层
- `llm_client.py`：兼容 OpenAI API 的模型调用封装
- `agent_core.py`：任务规划与执行循环核心逻辑
- `run_history.py`：本地运行历史记录

## 浏览器动作能力

项目内置了面向浏览器场景的高层动作：

- `open_browser`
- `focus_address_bar`
- `open_url`
- `search_text`
- `paste_text`

这些动作可以减少模型依赖底层点击和按键组合来完成浏览器任务。

## 运行架构

整体流程如下：

1. `planner` 根据用户任务生成步骤列表
2. 每一轮执行时：
   - 截取当前屏幕
   - 将任务、计划、当前步骤、近期动作历史和截图发送给模型
   - 由 `executor/supervisor` 选择执行一次 UI 动作，或给出重规划、阻塞等控制信号
   - 动作完成后再次截图，并由 `verifier` 判断当前步骤或任务是否完成
3. 循环直到任务完成、需要重规划，或进入阻塞状态

## 配置说明

仓库中提供了 `config.example.json` 作为开源发布用的样例配置文件。
你本地真实使用的 `config.json` 应仅保留在本地，不要上传到 GitHub。

可配置项包括：

- `provider`：`openai` / `openrouter` / `doubao`
- `model`：默认主模型
- `planner_model`：规划模型，可留空
- `executor_model`：执行模型，可留空
- `verifier_model`：校验模型，可留空
- `api_key_env`：保存 API Key 的环境变量名
- `api_base`：兼容 OpenAI API 的服务地址

Provider 说明：

- OpenAI：
  - `api_base`：通常为 `https://api.openai.com/v1`
  - `api_key_env`：通常为 `OPENAI_API_KEY`
- OpenRouter：
  - `api_base`：通常为 `https://openrouter.ai/api/v1`
  - `api_key_env`：通常为 `OPENROUTER_API_KEY`
- Doubao / Ark：
  - `api_base`：通常为 `https://ark.cn-beijing.volces.com/api/v3`
  - `api_key_env`：通常为 `ARK_API_KEY`

## 界面功能

- 任务输入框
- 配置弹窗
- 发送 / 停止按钮
- 实时日志输出
- 最新截图预览
- 本地运行历史列表
- 支持将历史任务重新载入输入框

## 多模型分工

你可以分别为以下角色配置独立模型：

- `planner`
- `executor`
- `verifier`

如果留空，则默认回退到主模型。

## 开源发布说明

- `.gitignore` 已排除 `config.json`
- `history.json` 也建议仅保留在本地
- 提交仓库时建议只保留 `config.example.json` 作为示例

## 注意事项

- 这是一个会控制真实鼠标和键盘的桌面智能体，使用时请保持可人工中断
- 建议先从打开应用、页面导航、搜索、截图等安全任务开始测试
- 在 macOS 上通常需要授予辅助功能和屏幕录制权限
