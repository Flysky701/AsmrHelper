# ASMR Helper

ASMR 音频汉化工具，支持人声分离、语音识别、日译中翻译、语音合成和智能混音，输出双语双轨音频。

## 入口说明

- **正式产品入口**：Tauri 桌面应用，通过 `GUIRun.bat` 双击启动。
- **后端契约入口**：HTTP API (`/api/v1/*`)，由桌面端和兼容 CLI 共用。
- **兼容入口**：`src/cli.py` 与 `scripts/asmr_bilingual.py`、`scripts/batch_process.py`，不作为 GUI 能力事实源。

## 功能特性

- **人声分离** - 基于 Demucs 从背景音中提取纯净人声
- **语音识别** - Faster-Whisper / Fun-ASR / Qwen3-ASR 高精度日文 ASR
- **翻译引擎** - DeepSeek / OpenAI API，批量翻译 + 质量检测
- **语音合成** - Edge-TTS (免费) / Qwen3-TTS / VoxCPM2 (高质量)
- **智能混音** - 时间轴对齐 + 音量平衡，输出原声+中文配音双轨
- **HTTP API** - FastAPI RESTful API，支持完整流水线和单步操作
- **任务中心** - 统一展示 Pipeline、音频工具、模型安装、音色和台本任务的阶段、错误与产物
- **音频工具** - 人声分离、格式转换、按字幕切分、字幕翻译、音量分析
- **字幕工坊** - 字幕编辑、导出、后台翻译和台本转字幕

## 系统要求

- **OS**: Windows 10/11
- **Python**: 项目内 UV Python 3.12（默认位于 `.runtimes/python`）
- **GPU**: NVIDIA (可选，Qwen3-TTS 需要 CUDA)
- **包管理器**: [uv](https://docs.astral.sh/uv/)

## 快速开始

### 1. 一键配置环境

注意使用**Powershell**

```powershell
# 克隆项目
git clone https://github.com/Flysky701/AsmrHelper.git
cd AsmrHelper

#如果后续关闭了powershell 需要CD到对应文件夹内

# 基础安装（默认 Python 3.12，含 API、桌面端与测试依赖）
powershell -ExecutionPolicy Bypass -File .\setup.ps1

# 安装本地音频引擎和默认模型（含 Faster-Whisper / Demucs）
powershell -ExecutionPolicy Bypass -File .\setup.ps1 -Models

# 完整主环境（API + 本地音频链路；隔离 Provider 不装入主环境）
powershell -ExecutionPolicy Bypass -File .\setup.ps1 -Full

# 环境完全重建
powershell -ExecutionPolicy Bypass -File .\setup.ps1 -CleanReinstall
```

默认安装使用项目内由 UV 管理的 Python 3.12，位置为 `.runtimes/python`，不会继承当前终端中其他项目的 Conda 环境。只有明确需要复用已有 Python 3.11/3.12 时才传入 `-PythonPath`；Python 3.13/3.14 不在当前依赖支持范围内。离线重建要求项目内 UV Python 和 `.uv-cache` 已经准备完成。

> Python 依赖由 UV 按当前 UV/Python 索引配置安装；`-Mirror` 只把 Hugging Face 模型下载切换到 `https://hf-mirror.com`，不会隐式改写 Python 包索引。

### 2. 下载 AI 模型

下载前**重启Powershell**

```powershell
# 下载 Whisper base 模型 (约 74MB，推荐)
powershell -ExecutionPolicy Bypass -File .\setup.ps1 -Models

# 使用国内镜像加速
powershell -ExecutionPolicy Bypass -File .\setup.ps1 -Models -Mirror

# 查看模型目录或只安装明确选择的模型
.\.venv\Scripts\python.exe scripts\install_models.py --list
.\.venv\Scripts\python.exe scripts\install_models.py --model qwen3-custom-voice

# 默认 Faster-Whisper Base
.\.venv\Scripts\python.exe scripts\install_models.py                    # Whisper base
.\.venv\Scripts\python.exe scripts\install_models.py --whisper large-v3 # Whisper large-v3
.\.venv\Scripts\python.exe scripts\install_models.py --check            # 检查状态
```

> 不建议默认下载所有 Whisper/Qwen 变体。Qwen3-TTS、Qwen3-ASR 和 Fun-ASR 使用各自隔离运行时，应从“引擎与资源”页面或 `--model <model-id>` 按需安装；模型存在不等于当前环境可执行或已真实验收。

### 3. 配置 API Key

编辑 `config/config.json` 填入翻译 API Key，或设置环境变量：

```powershell
$env:DEEPSEEK_API_KEY = "your-deepseek-api-key"
```

也可以在 GUI 的 **设置 > API 配置** 中填写。

### 4. 运行

```powershell
# 双击/正常启动：优先使用已构建的 release，无 release 时进入开发模式
.\GUIRun.bat

# 强制使用当前前端源码
.\GUIRun.bat --dev

# 重新构建 release 后启动
.\GUIRun.bat --release

# 仅启动 HTTP API
.\run.bat api

# 或命令行处理单文件
.\.venv\Scripts\python.exe scripts\asmr_bilingual.py --input "path/to/audio.wav"

# 批量处理
.\.venv\Scripts\python.exe scripts\batch_process.py --input-dir "D:/ASMR"
```

桌面启动器会隐藏启动后端并在 APP 退出时清理本次创建的后端进程。后端启动、请求和异常日志保存在 `logs/backend.log`，启动失败时窗口会显示日志尾部，不再只留下闪退现象。开发模式需要 Node.js 与 Rust；已有 release 的普通启动不要求这两套构建工具。

## 项目结构

```
AsmrHelper/
├── src/                          # 核心源代码
│   ├── core/                     # 核心处理模块
│   │   ├── engines/              # ASR/TTS/LLM/Separator 引擎
│   │   ├── orchestration/        # Pipeline 与工具编排
│   │   ├── tasks/                # Task Registry、Dispatcher 与状态机
│   │   ├── runtime/              # 隔离运行时与短生命周期 Worker
│   │   ├── artifacts/            # 任务产物索引
│   │   ├── subtitles/            # 字幕、台本处理领域
│   │   └── resources/            # 模型目录、安装与状态
│   ├── api/                      # HTTP API (FastAPI)
│   │   └── http/                 # RESTful API 路由和服务
│   ├── app/                      # 应用层服务
│   │   ├── services/             # 业务服务
│   │   ├── dto/                  # 数据传输对象
│   │   └── errors/               # 错误定义
│   ├── mixer/                    # 智能混音 + 时间轴对齐
│   ├── cli.py                    # Click CLI 入口 (实验性)
│   └── config.py                 # 配置管理
├── desktop/                      # Tauri + React + Vite 桌面应用
├── config/                       # 配置文件
│   ├── models.yaml               # 模型配置
│   ├── config.example.json       # 配置模板
│   └── config.json               # 用户配置 (git ignored)
├── tests/                        # 测试
├── pyproject.toml                # 项目依赖
└── uv.lock                       # 依赖锁定文件
```

## 配置说明

### config.json

从模板创建配置文件：

```powershell
cp config/config.example.json config/config.json
```

主要配置项：

| 字段                       | 说明                                     | 默认值                   |
| -------------------------- | ---------------------------------------- | ------------------------ |
| `api.provider`           | 翻译服务 (deepseek/openai)               | `deepseek`             |
| `api.deepseek_api_key`   | DeepSeek API Key                         |                          |
| `tts.engine`             | TTS 引擎 (edge/qwen3)                    | `edge`                 |
| `tts.voice`              | Edge-TTS 音色                            | `zh-CN-XiaoxiaoNeural` |
| `processing.vocal_model` | 人声分离模型                             | `htdemucs`             |
| `processing.asr_model`   | ASR 模型大小 (tiny/base/medium/large-v3) | `base`                 |

### 环境变量

| 变量                 | 说明              |
| -------------------- | ----------------- |
| `DEEPSEEK_API_KEY` | DeepSeek API 密钥 |
| `OPENAI_API_KEY`   | OpenAI API 密钥   |

环境变量优先级高于配置文件。

## TTS 引擎对比

| 引擎      | 质量 | 速度 | GPU       | 说明                         |
| --------- | ---- | ---- | --------- | ---------------------------- |
| `edge`  | 一般 | 快   | 不需要    | 微软免费 TTS，适合快速体验   |
| `qwen3` | 高   | 慢   | 需要 CUDA | Qwen3-TTS，支持音色设计/克隆 |

## GUI 界面

### 主界面布局

- **工作台** - 一个或多个输入分别创建独立 Pipeline Task
- **批量处理** - 扫描目录并创建持久 BatchRun，支持总进度、整批取消和失败项重提
- **任务中心** - 查看进度、失败阶段、结构化错误、取消、重提与产物
- **字幕工坊** - 编辑、导出、后台翻译和台本转字幕
- **音色实验室** - Qwen3-TTS 专属的设计、克隆、片段分析和试音
- **音频工具** - 五项独立 Tool Task
- **引擎与资源 / 设置** - 查看 installed、executable、缺失依赖与凭据

### 工具箱功能

| 工具     | 说明                                |
| -------- | ----------------------------------- |
| 音频分离 | Demucs 人声/伴奏分离                |
| 按字幕切分 | 按字幕时间轴切分音频              |
| 格式转换 | 音频格式互转 (WAV/MP3/FLAC/OGG)    |
| 字幕翻译 | 翻译字幕并保留时间轴               |
| 音量分析 | 分析 RMS 并给出混音比例建议         |

### 嵌入式音频播放器

主界面底部集成音频播放器，支持：

- 播放/暂停、停止控制
- 可拖拽进度条
- 当前时间/总时长显示

用于试音预览和音色工坊片段播放。

## 核心处理流程

```
输入音频 (.wav/.mp3/.flac)
    |
    v
[1] VTT 字幕检测 (有则跳过人声分离)
    |
    v
[2] Demucs 人声分离
    |
    v
[3] Faster-Whisper ASR (日文 -> 日语文字)
    |
    v
[4] LLM 翻译 (日文 -> 中文)
    |
    v
[5] TTS 合成 (中文文字 -> 语音)
    |
    v
[6] 时间轴对齐 + 智能混音
    |
    v
输出: 双语双轨音频 + SRT 字幕
```

## 开发

```powershell
# 安装开发工具
powershell -ExecutionPolicy Bypass -File .\setup.ps1 -DevOnly

# 运行测试
.\.venv\Scripts\python.exe -m pytest

# 运行安装脚本集成测试
.\.venv\Scripts\python.exe -m pytest tests/test_setup_integration.py -v

# 运行环境验证
.\.venv\Scripts\python.exe scripts/verify_env.py

# 检查模型状态
.\.venv\Scripts\python.exe scripts/install_models.py --check

# 下载模型
.\.venv\Scripts\python.exe scripts/install_models.py --whisper base
.\.venv\Scripts\python.exe scripts/install_models.py --model qwen3-custom-voice
```

## 许可证

MIT License

## 架构说明

### 核心模块 (src/core)

- `asr/` - ASR 语音识别，支持 Faster-Whisper、Fun-ASR、Qwen3-ASR
- `engines/llm/` - 翻译引擎，支持 DeepSeek/OpenAI，包含缓存和术语库
- `tts/` - 语音合成，支持 Edge-TTS、Qwen3-TTS、VoxCPM2
- `vocal_separator/` - Demucs 人声分离
- `orchestration/` - 流水线编排，使用 PipelineExecutor 执行
- `engines/` - 引擎运行时，统一管理各引擎生命周期
- `resources/` - 模型资源管理，支持模型安装和状态查询

### HTTP API (src/api/http)

FastAPI RESTful API，提供以下端点：
- `/api/v1/pipeline/*` - 流水线执行
- `/api/v1/asr/*` - 语音识别
- `/api/v1/llm/*` - LLM 翻译
- `/api/v1/tts/*` - 语音合成
- `/api/v1/models/*` - 模型管理
- `/api/v1/tasks/*` - 任务管理
- `/api/v1/artifacts/*` - 产物管理

### 应用层 (src/app)

- `services/` - 业务服务层，封装核心功能
- `dto/` - 数据传输对象，定义 API 契约
- `errors/` - 错误定义和处理

### 项目状态

README 只保留安装、启动和使用入口，不再维护容易失真的 TODO/DONE 双清单。当前能力、验收范围与剩余边界统一记录在：

- [总体进度状态](docs/roadmap/overall-progress-status.md)
- [后端能力事实清单](docs/roadmap/backend-capability-baseline.md)
- [当前源码基线](docs/roadmap/current-source-baseline.md)
- [文档索引](docs/README.md)

历史计划和已执行检查表已移入 `docs/archived/`，不再作为当前开发入口。
