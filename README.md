# ASMR Helper

Windows 桌面音频处理工具，支持人声分离、语音识别、字幕翻译、语音合成、时间轴校准和混音。工作台使用已保存的节点流水线；用户选择素材、节点和交付结果，程序检查依赖，不自动补跑未选节点。

## 开始使用

需要 Windows 10/11、PowerShell 5.1+。安装脚本默认使用项目内的 Python 3.12；桌面开发与构建另需 Node.js 22+、Rust/Cargo 及对应 Windows 编译工具链。模型和 GPU 要求取决于所选引擎。

```powershell
git clone https://github.com/Flysky701/AsmrHelper.git
cd AsmrHelper
powershell -ExecutionPolicy Bypass -File .\setup.ps1
.\GUIRun.bat
```

基础安装包含 API、语音服务客户端和 FFmpeg，不下载全部模型。本地模型从“引擎与资源”按需安装；外部服务在那里保存连接与凭据。详细选项、离线边界和修复方式见 [安装与运行](docs/guides/installation.md)。

日常双击 `RUNGUI.bat` 或桌面“ASMR Helper 主项目”快捷方式，打开免安装的本机桌面窗口，使用主项目现有 Python、模型和配置。`GUIRun.bat` 无参数也是同一桌面入口。修改 Python 后重启窗口；修改前端或 Rust 后，先保存草稿、结束任务并关闭窗口，再执行 `RUNGUI.bat --build` 离线增量构建。工具缺失会报错，不自动下载。详见[开发与验证](docs/guides/development.md)。

## 使用入口

| 页面 | 用途 |
| --- | --- |
| [工作台](docs/guides/workbench.md) | 选择流水线，添加音频或字幕，绑定素材并提交单组或批次 |
| [流水线编辑](docs/guides/workflow-graph-v2.md) | 定义节点、连线、输入槽和交付结果，保存为可复用预设 |
| [声音与音色](docs/guides/voice-lab-v2.md) | 编辑参考录音、保存音色规则、试听并复用高级参数 |
| 任务中心 | 查看任务与批次、错误归属、最终结果及中间产物，按可用条件取消、重试或恢复 |
| 字幕工坊 / 音频工具 | 编辑字幕、处理台本、分离、转换音频及按字幕切分 |
| 引擎与资源 / 设置 | 按需安装模型、检查环境、管理命名连接、流水线预设和路径 |

只包含目标语言字幕与 TTS 的流水线可直接配音，无需分离、ASR 或翻译。语言、时间轴、配对关系与引擎输入必须满足要求；检查配置或构建成功不等于真实音频验收通过。

## Fish 远程克隆

在“声音与音色 → Fish 远程克隆”选择已保存的参考片段、服务连接和目标名称；常驻摘要会显示上传对象、素材和原文，点击“上传片段并创建音色”即提交创建。请仅使用自己有权克隆的声音素材。该操作会将所选片段和原文发送到 Fish Audio，创建私有持久音色，计费与额度按 Fish 当前规则执行；`s2.1-pro-free` 推理免费不保证创建音色免费。凭据仍在外部服务连接入口填写。

结果就绪后可保存为本地音色，用于试音和工作台；网页端的云端音色管理仍由 Fish 提供。结果未知时先到 Fish 网页核查，不要重复创建。“删除本地记录”只隐藏结果，可用“撤销上次删除”恢复，不删除云端音色、已保存音色或参考素材；处理中记录需先更新状态。详见 [Fish 克隆指南](docs/guides/fish-cloning.md)。

## 开发与数据

- [文档索引](docs/README.md)：当前使用指南和接口契约。
- [开发与验证](docs/guides/development.md)：目录职责、检查命令和构建入口。
- [TTS 指南](docs/guides/tts.md)：能力、命名连接、参数和任务快照。
- [分支与发布](docs/guides/branch-workflow.md)：`dev` 集成、`master` 发布，提交和发布分开进行。

用户配置在 `config/`，声音数据在 `config/voice_lab/`；模型、运行环境和输出目录不是构建缓存。Windows 任务数据库默认在 `%LOCALAPPDATA%\AsmrHelper\state.sqlite3`，桌面草稿位于 WebView 用户数据中。清理或回退前保留这些数据，详见安装指南的[数据与备份](docs/guides/installation.md#数据与备份)。

项目许可：MIT（见项目元数据）。
