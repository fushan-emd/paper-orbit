# 私人工作区与公开源码隔离

## 三个位置

- 原始开发目录：保留自己的配置、数据库、笔记、凭据、报告与备份；不要整体上传。
- `public-release/PaperOrbit-时间戳`：白名单导出的公开源码快照，只在这里初始化 Git 和提交。没有设置远端，不会自动上传。
- 公开源码目录内的 `private-preview/`：可选独立试用工作区，已被 Git 忽略。测试后也不能整体压缩整个目录公开，应从 Git 跟踪文件生成源码包。

## 创建干净快照

在原始开发目录执行：

```powershell
.venv\Scripts\python.exe scripts/prepare_public_release.py
```

每次生成新的目录，不覆盖以前的版本，不删除私人文件。脚本只复制明确列出的源文件、默认模板、测试和许可材料；拒绝符号链接、数据库、私钥和常见凭据特征。扫描是辅助检查，不能替代提交前人工复核。

导出后会生成文件 SHA-256 清单。可在快照内执行 `python scripts/prepare_public_release.py --check .` 重新核查文件内容与允许范围。新增需要公开的资源时，应先修改脚本白名单。

## 使用与测试

按 README 创建虚拟环境后，用新的 PowerShell 进程运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/start_clean_workspace.ps1
```

默认使用 8010 端口；不连接原个人文献库，也不继承该进程的 DeepSeek、NCBI、OpenAlex 环境变量密钥。不会删除系统凭据或修改系统环境变量。新目录有自己独立的系统凭据命名空间；在预览中自行保存的新密钥只属于该工作区。

显式设置 `LITERATURE_RADAR_ROOT` 会从默认模板创建空工作区，不自动导入旧目录。后续再次使用相同目录会保留该目录自己的数据。此时若要迁移个人数据，请主动使用备份与恢复。

## GitHub 提交前

只在干净快照中检查 `git status --short`、`git diff --cached --stat` 和 `git ls-files`。确认默认模板 `installer/config.toml` 和 `BioinfoLiteratureRadar.spec` 被跟踪，个人 config、backups、private-preview 和所有数据库未被跟踪。不要使用 `git add -f` 绕过忽略规则。

不提交开发者的截图或原始日志。需要截图时使用明确标注的合成测试数据。MIT 仅涵盖代码，不授予第三方论文摘要或全文的再分发许可。

建议先公开源码 Beta。当前独立 Windows 验收、真实 AI 内容质量评审与签名仍有待办；不宣称正式版验收全部完成。不要把较旧安装包当成当前源码构建结果。
