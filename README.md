<div align="center">

# ✧ Paper Orbit

**把文献变成卡片，让阅读通向下一次发现。**

Windows 本地科研工作区 · MIT 开源 · Beta

[快速开始](#快速开始) · [功能预览](#功能预览) · [数据与隐私](#数据与隐私) · [开发与验证](#开发与验证)

</div>

![Paper Orbit 主页：文献搜集、单抽五连十连和统一导航](docs/images/overview.png)

> **截图说明：** 本页所有界面截图均来自隔离测试环境，使用合成文献及模拟 AI 响应，仅展示交互。示例标题、评分和研究内容不应视为真实论文或科学结论；没有使用作者的私人文献库。

## 为什么做 Paper Orbit

论文越存越多，却不一定更容易开始阅读。Paper Orbit 尝试用抽卡的浏览方式降低起步成本：从已经搜集的真实文献中抽取卡片，快速判断兴趣，再回到原文、笔记和研究问题。

它是运行在自己电脑上的阅读管理工具。目前没有云端账户或同步服务，AI 功能使用你自己的服务商配置。

## 功能预览

### 1. 先搜集文献，再抽一组灵感

- 接入 PubMed、bioRxiv、arXiv、OpenAlex；默认方向为生物信息学，可修改关键词与检索式。
- 支持 **单抽、五连抽、十连抽**，在符合条件的文献池中等概率抽取，同一轮不重复。
- 可用文献不足时返回剩余卡片；没有虚构的保底机制。
- 稀有卡带揭晓特效，支持快速揭晓与系统减少动画偏好。

![十连抽的文献卡片，展示评分、摘要和收藏操作](docs/images/cards.png)

| 等级 | AI 分数 / 30 | 如何理解 |
| --- | --- | --- |
| N | 0–9 | 阅读优先级分档 |
| R | 10–17 | 阅读优先级分档 |
| SR | 18–23 | 阅读优先级分档 |
| SSR | 24–27 | 阅读优先级分档 |
| UR | 28–30 | 阅读优先级分档 |

**评级表示对当前研究方向的阅读优先级，不是真实性、科学质量或期刊级别认证。** 仅有规则分析、AI 失败或无有效 AI 评分的文献显示为待评级。分析主要基于标题和摘要。

### 2. 抽到的卡，进入自己的仓库

卡牌仓库保留抽取记录，支持收藏、筛选、阅读状态管理，以及跨页选择组合卡组。文献库同时提供全部搜集结果的搜索、详情阅读与私人笔记。

![卡牌仓库：收藏、状态筛选与组合选卡](docs/images/warehouse.png)

选择 **2–6 张卡**，输入具体研究问题，可在科研想法工作台生成带来源片段的待验证假设，并保留卡组草稿和生成历史。程序会验证引用 ID 和片段是否来自输入材料，但不能替代对证据语义、实验可行性和新颖性的人工判断。

### 3. 配置尽量简单，细节按需展开

基础设置只展示研究偏好、文献来源与范围、AI 配置。检索式、模型参数、期刊与密钥管理放在高级选项中。

![简化后的配置页：三组基础设置与折叠高级选项](docs/images/settings.png)

首次使用有跨页面教程，跟随设置、搜集、抽卡、仓库、科研想法、文献库与数据管理。可以收起、返回、跳过或重新开始；保存设置和刷新不会结束教程。

### 4. 数据和任务有独立管理入口

- SQLite 数据库备份、恢复和 JSON 导出；恢复前先备份当前数据。
- 查看后台搜集与生成任务，主动取消后续处理。
- 查看 AI 请求次数与服务返回的 token 用量，使用本机每日预算保护。
- 所有页面共享主导航，设置、主题和教程位于工具区。

## 快速开始

当前主要支持 **Windows**，开发验证环境为 **Python 3.13**。桌面窗口使用 WebView2；也可用本地浏览器打开。

```powershell
git clone https://github.com/fushan-emd/paper-orbit.git
cd paper-orbit
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-runtime.lock
.venv\Scripts\python.exe desktop_app.py
```

首次启动会从 `installer/config.toml` 创建本地配置，不包含任何 API 密钥。

**第一次使用建议：**

1. 跟随教程检查研究关键词、文献来源和检索范围。
2. 暂不使用 AI 时选择“规则初筛”，先完成文献搜集。
3. 无 AI 评分文献时，取消抽卡页的“仅抽取已有 AI 评分的文献”筛选。
4. 抽取卡片，收藏感兴趣的论文，再打开原文深入阅读。
5. 需要 AI 解读和科研想法时，在设置中填写自己的服务凭据。调用可能产生费用。

希望在完全独立的工作区试用时，在新的 PowerShell 进程中运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/start_clean_workspace.ps1
```

这会以本地浏览器模式启动，默认端口 **8010**，使用仓库内被 Git 忽略的 `private-preview/`，不继承常见 AI/文献源环境变量密钥。再次启动会保留这个独立工作区自己的数据。

## 数据与隐私

| 内容 | 保存或处理位置 |
| --- | --- |
| 文献、收藏、笔记、仓库、想法历史 | 本机工作区数据库 |
| 保存的 API 密钥 | Windows 凭据管理器，按工作区区分 |
| 源码模式默认工作区 | 当前源码目录 |
| 安装版默认工作区 | `%LOCALAPPDATA%/PaperOrbit` |
| AI 文献分析 | 向所配置服务发送必要的文献标题、摘要等信息 |
| AI 科研想法 | 发送所选文献信息与研究问题；不发送个人阅读笔记 |

通过 `LITERATURE_RADAR_ROOT` 可指定独立工作区。显式指定的新目录从默认模板开始，不自动导入原工作区数据。

取消任务不能撤回已经发送的网络请求，可能仍产生费用。数据库恢复不覆盖配置、凭据或用量账本。详细说明见 [PRIVACY.md](PRIVACY.md)。

## 开发与验证

```powershell
# 单元与集成测试：合成数据，不调用真实 AI
.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"

# 浏览器回归：还需要本机 Edge/Chrome 和 Node.js 22+
.venv\Scripts\python.exe tests/browser_check.py
.venv\Scripts\python.exe tests/browser_discovery.py
.venv\Scripts\python.exe tests/browser_workbench.py
```

发布前验证包括 53 项测试、三组浏览器主流程回归，以及独立空白工作区启动。浏览器测试中的采集和模型使用模拟服务；这些结果不等同于真实 AI 内容质量或全平台兼容性验收。

构建说明见 [DESKTOP_APP.md](DESKTOP_APP.md)。私人开发目录与公开源码的隔离流程见 [PUBLIC_RELEASE.md](PUBLIC_RELEASE.md)，白名单导出入口为 `scripts/prepare_public_release.py`。

## 当前状态与已知限制

本仓库为 **Beta 源码发布**，当前不附带新的安装包。既有本地 Beta.2 安装包不代表这里的最新源码。

- 当前主要验证 Windows；干净系统、WebView2 缺失、辅助功能等仍需独立验收。
- 无云同步和团队协作；关闭软件后，正在执行的任务不自动续跑。
- 外部文献源可能限流或暂时不可用，OpenAlex 匿名访问曾遇到 429。
- 真实 AI 联调及独立人工内容评审仍需补齐；输出需要核对来源、证据和可行性。
- 现有安装构建未代码签名，管理页尚未完整英文化。

欢迎通过 [Issues](https://github.com/fushan-emd/paper-orbit/issues) 反馈可复现的问题。请提供系统环境、操作步骤与错误类型，**不要上传 API 密钥、私人研究问题、笔记或完整私人数据库**。

## 许可

本项目代码使用 [MIT License](LICENSE)。第三方组件的许可见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。MIT 不授予第三方论文、摘要、商标或用户内容的再分发权利。
