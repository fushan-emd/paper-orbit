# Paper Orbit 0.4.0-beta.3

Windows 本地文献工作区，MIT 开源。原项目名 Bioinfo Literature Radar；保留原 EXE 文件名和安装标识以兼容升级。

## 使用与数据

安装 `release/PaperOrbit-0.4.0-beta.3-Setup.exe`，启动后进入抽卡页面。使用 `--page library` 打开文献库。源码启动：`.venv\Scripts\python.exe desktop_app.py`。

安装版工作区默认位于 `%LOCALAPPDATA%/PaperOrbit`，源码版默认项目目录；可用 `LITERATURE_RADAR_ROOT` 指定独立工作区。首次启动会尝试迁移安装目录中的旧数据，已有目标配置时不会覆盖。请先备份旧数据。

密钥保存于 Windows 凭据管理器，可在设置中更新和删除。管理页提供数据库备份、恢复、JSON 导出、任务取消及 AI 用量。恢复前自动备份当前数据库；配置、密钥与用量账本不随数据库恢复。取消不会撤回已经发出的 AI 请求。

## 构建与验证

运行 `powershell -ExecutionPolicy Bypass -File scripts/build_desktop_app.ps1`。构建使用独立 `.release-venv` 和 `requirements-build.lock`，需要 Inno Setup 6。

输出：`dist_release/BioinfoLiteratureRadar/BioinfoLiteratureRadar.exe` 和 `release/PaperOrbit-0.4.0-beta.3-Setup.exe`。安装包不含开发者数据库、密钥或个人配置；默认配置由模板提供。`scripts/verify_artifact.py` 检查打包内容并生成 SHA-256。

当前安装包未签名。已在本机隔离安装标识下测试新装、升级、卸载保留工作区和重装；不代表干净 Windows/WebView2 缺失环境验收。真实 AI 与人工内容评审状态见 PUBLIC_RELEASE.md。

## 首次使用

首次启动会显示可收起的跟随式教程，带你进入设置、搜集、抽卡、仓库、科研想法、文献库与数据管理。点击页面内容、保存设置、刷新和重新启动都会保留进度；只有明确完成或跳过才结束。顶部或右下角问号可重开。引导不会替你发起采集或 AI 请求。
