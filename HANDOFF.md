# Fly-PC 接手入口（2026-10-12）

下次先从主仓库 **`E:\Projects\AsmrHelper`** 的 **`RUNGUI.bat`** 启动；它使用现有 `.venv` 和 `scripts/desktop_local.py`。运行环境、模型和构建缓存均保留，无需重新安装或下载。当前没有新功能待实施。

## 当前版本

- 发布源码：**v1.0.0 / `d54affdaa9974822b40e22e25e626b686d9e8862`**，已正常快进合入远端默认分支 `master`。本机保留 `sync/pc-integrated-20261009`，未为收尾盲切分支。
- 本说明作为独立 docs 提交同步后，master 会多出交接文档提交；程序源码仍与 v1.0.0 一致。发布标签、安装包和历史分支未重写。
- [正式 Release、安装包、校验和及中文 QuickStart](https://github.com/Flysky701/AsmrHelper/releases/tag/v1.0.0)。本地发布副本：`C:\Users\Fly\Documents\Codex\2026-10-12\task\github-v1.0.0-publication\assets\AsmrHelper-1.0.0-windows-x64-setup.exe`。
- 安装包 153105861 字节，SHA256：`7ee729e6f81f6ff5f50a97f7f07e43b9c9703332c23501b80c73871f86ed6bad`。原始构建和缓存保留在 `.cache\release-1.0`。
- 隔离回归：Python 996 通过、1 跳过；前端 46 通过；TypeScript/Vite 构建通过。仓库没有配置 CI 工作流或状态检查。

## 尚未解决的事项

- PC 开发环境和已安装包的 Edge TTS 均遇到 WebSocket HTTP 403，原因未定，未生成真实 Edge WAV；未改代理、VPN、防火墙、证书或依赖来规避。
- 新任务 shell、文件写读及回复链可用，不能据此断言旧会话已修复。本任务 GUI 工具曾报 `node_repl kernel exited unexpectedly` / Windows 平台目录错误，原生视觉验收和首次目录选择尚未完成。安装、启动、重启已验证；升级和卸载未完整重测。
- 旧 `.pytest-tmp-dispatcher-review` 权限警告仍在，未改 ACL。`C:\Users\Fly\AppData\Local\Temp\AH100-9d320080` 是已注册的隔离测试安装，连同测试工作区保留，未卸载；不要当普通静态临时目录删除。

## laptop 和学习资料

FLY-Laptop：`D:\WorkSpace\AsmrHelper`。今日曾通过 UU 将 laptop 的源码修改同步到 PC；**没有核验 laptop 已更新到本次发布或交接提交**。下次同步前先保存其 `git status`、diff、未跟踪源文件并备份/提交原改动，再合并，避免覆盖未提交内容。模型、私密配置、凭据和个人素材不在源码同步范围。

`D:\Lesson` 只读核对：本地及远端默认 `main` 均为 `472608ba9a4e483f7550c41096fb916c27d7a5e1`，没有后续提交，可读工作树为空；本次未修改或重跑学习资料。

## 今日收尾与恢复

本机证据根目录：`C:\Users\Fly\Documents\Codex\2026-10-12\task`。必要备份和证据保留，重点见 `release-1.0-delivery-report.md`、`github-v1.0.0-publication\publication-report.md`、`main-merge-evidence\result.json`、`cleanup-evidence\cleanup-report.md`。

28 个一次性脚本已逐字节核验归档为 `cleanup-evidence\today-automation-scripts.zip`。已完成测试的生成夹具、脚本原文件及会话哨兵共 38 项、2695 文件、127647258 字节，仅送入系统回收站并逐文件核验恢复数据；未永久删除、未清空回收站。原路径/哈希见 `cleanup-evidence\recycle-plan.json`，回收数据位置见 `recycle-actions.json`，需要时在回收站选择“还原”。

含 Git 的隔离检出/模拟导出测试、有效环境、构建缓存、发布安装包/说明/校验和、必要证据、模型/config/keys/声音素材/真实输入输出均保留。未发现仍需结束的本轮测试或预览进程；没有结束用户应用、其他 Codex、UU 或浏览器。
