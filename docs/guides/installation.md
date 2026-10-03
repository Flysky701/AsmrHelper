# 安装与运行

## 环境

- Windows 10/11、PowerShell 5.1+。
- 安装脚本默认通过 uv 使用项目内 Python 3.12；显式 `-PythonPath` 支持已有 Python 3.11/3.12，不继承其他项目的 Conda 环境。
- 前端依赖安装需要 Node.js 22+ 和 npm。Tauri 开发或 release 构建还需要 Rust/Cargo 与匹配的 Windows 编译工具链；WebView2 用于桌面渲染。
- 已构建 release 仍依赖本项目 Python 后端和配置，并非携带所有模型的独立 exe。仅运行新鲜的现成构建无需再次执行前端编译。

## 安装

在项目根目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1
```

脚本初始化缺失的配置，保留已有配置；按 `uv.lock` 同步 Python 依赖，运行 `npm ci`，选择并验证 CPU/CUDA 配置，最后执行环境验证。基础依赖包含 FFmpeg（`imageio-ffmpeg`），不因混音页面打开而下载或安装工具。默认安装不下载模型权重。

| 参数 | 实际作用 |
| --- | --- |
| `-Models` | 增加本地音频依赖并下载默认 Whisper 模型；指定 `-Engines` 时安装相应目录模型 |
| `-Full` | 增加本地音频依赖；只有同时传 `-Models` 才下载其扩展模型集合 |
| `-DevOnly` | 增加开发检查工具，仍保留 API 所需运行依赖 |
| `-SkipFrontend` | 跳过 `npm ci`，适用于只准备后端或前端已就绪 |
| `-Compute auto/cpu/cuda` | 明确运行策略；CUDA 验证失败报错，不偷偷降级 |
| `-PythonPath <python.exe>` | 使用明确指定的受支持解释器 |
| `-SkipInstall` | 跳过 Python 依赖同步，计算环境改为检查；不代表跳过前端或显式模型安装 |
| `-CleanReinstall` | 删除并重建主 `.venv`；仅用于明确修复，不清除模型、声音或任务数据 |

Qwen、Fun-ASR、VoxCPM 等引擎的依赖使用各自的 `.runtimes/` 隔离环境，不应手工将互相冲突的 extras 全装进主 `.venv`。

## 按需安装模型

优先在“引擎与资源”选择实际需要的模型。命令行使用同一资源目录：

```powershell
.\.venv\Scripts\python.exe scripts\install_models.py --list
.\.venv\Scripts\python.exe scripts\install_models.py --model faster-whisper-base
.\.venv\Scripts\python.exe scripts\install_models.py --model qwen3-base
```

`--model` 可重复；`--provider` 会选择该引擎全部可安装模型，不适合只需一个模型时使用。不要把 `-Models -Full` 当作所有用户的安装前提。模型已下载、环境可执行和真实推理成功是不同状态。

`-Mirror` 只为模型下载传入 Hugging Face 镜像，不修改 Python 包源。`-Offline` 约束 uv 与计算环境安装，要求已有 Python 和包缓存；它不自动约束 `npm ci` 或显式的 `-Models` 下载。离线准备应使用 `-SkipFrontend`、不传 `-Models`，并事先具备 uv、解释器和所需缓存。

## 启动和更新

```powershell
.\GUIRun.bat              # 新鲜 release / 源码变化时重建 / 无 release 时开发模式
.\GUIRun.bat --installed  # 只启动已有 release
.\GUIRun.bat --dev        # 当前前端源码的开发模式
.\GUIRun.bat --release    # 构建无安装包的 release 并启动
.\run.bat api             # 仅后端，127.0.0.1:8000
.\run.bat test            # 环境检查，不是完整回归测试
```

`GUIRun.bat` 检查本机 `/health`，复用同项目健康后端；源码过时且桌面已经关闭时才重启旧后端。关闭本次启动的桌面后，启动器清理自己创建的后端。端口被其他程序占用时报告错误，不应手工终止所有 Python 进程。

前端构建产物位于 `desktop/dist/`，exe 位于 `desktop/src-tauri/target/release/asmr-helper.exe`。`--release` 调用 `npm run tauri -- build --no-bundle`，不是安装包发布。源码更新后应保存所有草稿、结束活动任务并关闭窗口，再启动更新；不要清 WebView 目录来“刷新”界面。

脚本识别项目内 `.runtimes/node-*-win-x64`、`.runtimes/cargo`、`.runtimes/rustup` 及匹配的 LLVM-MinGW 工具链；明确设置的 `ASMR_HELPER_NODE_HOME`、`CARGO_HOME`、`RUSTUP_HOME`、`RUSTUP_TOOLCHAIN` 优先。

## 配置和诊断

翻译连接与语音连接在对应设置中管理，语音配置使用命名连接，不从旧全局 TTS 字段猜测。`DEEPSEEK_API_KEY`、`OPENAI_API_KEY` 可作为翻译环境配置；环境变量覆盖文件值。不要把凭据写入流水线预设、提交日志或截图。

```powershell
.\.venv\Scripts\python.exe scripts\verify_env.py
.\.venv\Scripts\python.exe scripts\configure_compute.py --existing
.\.venv\Scripts\python.exe scripts\configure_compute.py --existing --check
```

首个命令检查基础环境和 FFmpeg，后两个分别查看计算环境计划和验证。只有明确执行 `--apply --compute cpu` 或 `--apply --compute cuda` 才应用相应计算环境安装。启动日志为 `logs/backend.log`。

模型环境检查不加载权重，不等于真实推理验收。探测缓存位于 `.cache/runtime-probes/`；依赖修复后可通过模型“验证”强制更新。成功、缺依赖和超时未知分别显示，不能把未知当作就绪。

## 数据与备份

| 位置 | 内容 |
| --- | --- |
| `config/`、`config/voice_lab/` | 配置、连接与凭据、参考录音、音色修订、试听及自定义流程；不可作为普通缓存清除 |
| `models/`、`.runtimes/`、`.venv/` | 模型与运行环境；删除将影响可执行能力 |
| `output/` 或用户设置目录 | 处理结果；任务历史只是索引，不代替音频文件 |
| `%LOCALAPPDATA%\AsmrHelper\state.sqlite3` | 默认任务、批次、产物和恢复信息；可由 `ASMR_HELPER_STATE_DB` 改变位置 |
| `%LOCALAPPDATA%\com.asmrhelper.desktop` | WebView 用户数据，含工作台持久草稿；声音库部分草稿只在当前会话中 |
| `.cache/`、`desktop/node_modules/`、`desktop/dist/`、Rust `target/` | 可重建缓存或构建输出；正在运行的 exe 和唯一有效构建仍须保护 |

Git 只保护已提交文件，不能代替上述用户数据的备份。做一致备份时先保存草稿、停止任务并正常退出应用，再复制数据库、配置、音频及 WebView 数据；运行中的 SQLite 应使用 SQLite backup API，不只复制主文件而遗漏 WAL。回退代码不自动回退数据格式，当前流程目录的备份与冲突规则见 [兼容边界](../contracts/compatibility.md)。
