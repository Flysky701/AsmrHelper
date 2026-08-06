# ASMR Helper

ASMR 音频汉化工具，支持人声分离、语音识别、日译中翻译、语音合成和智能混音，输出双语双轨音频。

## 入口说明

- **正式入口**: HTTP API (`/api/v1/*`) - 唯一正式产品接口
- **实验入口**: Desktop 桌面应用 (`desktop/`) 和 CLI (`src/cli.py`) - 仅作为实验性入口保留

## 功能特性

- **人声分离** - 基于 Demucs 从背景音中提取纯净人声
- **语音识别** - Faster-Whisper / Fun-ASR / Qwen3-ASR 高精度日文 ASR
- **翻译引擎** - DeepSeek / OpenAI API，批量翻译 + 质量检测
- **语音合成** - Edge-TTS (免费) / Qwen3-TTS / Kokoro-TTS (高质量)
- **智能混音** - 时间轴对齐 + 音量平衡，输出原声+中文配音双轨
- **HTTP API** - FastAPI RESTful API，支持完整流水线和单步操作
- **工具箱** - 独立的单步工具：音频分离、音频切分、ASR识别、格式转换、字幕生成、字幕翻译

## 系统要求

- **OS**: Windows 10/11
- **Python**: 3.11 或 3.12
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

> 安装脚本会自动并发测速 pypi.org 官方源和国内镜像（清华、阿里），选择延迟最低的源进行安装，哪个快用哪个。如果首选源失败，会自动按延迟顺序回退。

### 2. 下载 AI 模型

下载前**重启Powershell**

```powershell
# 下载 Whisper base 模型 (约 74MB，推荐)
powershell -ExecutionPolicy Bypass -File .\setup.ps1 -Models

# 安装 Qwen3-TTS 模型及独立 qwen_tts 运行环境
powershell -ExecutionPolicy Bypass -File .\setup.ps1 -Models -Engines qwen3

# 下载旧版完整模型集合 (Whisper + Qwen3-TTS，约 25GB+，通常不建议)
powershell -ExecutionPolicy Bypass -File .\setup.ps1 -Models -Full

# 使用国内镜像加速
powershell -ExecutionPolicy Bypass -File .\setup.ps1 -Models -Mirror

# 或直接使用项目虚拟环境中的 Python
.\.venv\Scripts\python.exe scripts\install_models.py                    # Whisper base
.\.venv\Scripts\python.exe scripts\install_models.py --whisper large-v3 # Whisper large-v3
.\.venv\Scripts\python.exe scripts\install_models.py --qwen3            # Qwen3 全部
.\.venv\Scripts\python.exe scripts\install_models.py --all              # 全部
.\.venv\Scripts\python.exe scripts\install_models.py --check            # 检查状态
```

> **注意**: Whisper 模型也可在首次使用时自动下载。Qwen3-TTS 模型需要手动下载（约 8.4GB/个）。

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
│   │   ├── asr/                 # ASR 语音识别 (Faster-Whisper/Fun-ASR/Qwen3-ASR)
│   │   ├── translate/            # 翻译引擎 + 缓存 + 术语库
│   │   ├── tts/                  # TTS (Edge/Qwen3/Kokoro)
│   │   ├── vocal_separator/      # Demucs 人声分离
│   │   ├── orchestration/        # 流水线编排 (PipelineExecutor)
│   │   ├── engines/              # 引擎运行时
│   │   └── resources/            # 模型资源管理
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

- **单文件处理** - 处理单个音频文件，支持完整流程或单步执行
- **批量处理** - 批量处理多个音频文件
- **音色工坊** - Qwen3-TTS 专属功能，支持音色设计、片段预览和试音
- **工具箱** - 独立的单步工具集合

### 工具箱功能

| 工具     | 说明                                |
| -------- | ----------------------------------- |
| 音频分离 | Demucs 人声/伴奏分离                |
| 音频切分 | 按字幕时间轴切分音频                |
| ASR 识别 | 语音转文字 (Faster-Whisper)         |
| 格式转换 | 音频格式互转 (WAV/MP3/FLAC/OGG/M4A) |
| 字幕生成 | 文本/PDF 转字幕 (SRT/VTT/LRC)       |
| 字幕翻译 | 翻译字幕文件 (支持批量)             |

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
.\.venv\Scripts\python.exe scripts/install_models.py --qwen3
```

## 许可证

MIT License

## 架构说明

### 核心模块 (src/core)

- `asr/` - ASR 语音识别，支持 Faster-Whisper、Fun-ASR、Qwen3-ASR
- `translate/` - 翻译引擎，支持 DeepSeek/OpenAI，包含缓存和术语库
- `tts/` - 语音合成，支持 Edge-TTS、Qwen3-TTS、Kokoro-TTS
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

### TODO LIST（优先级从高到低）

#### feat

- Model 审查功能， 通过接入 API 进行循环审查（ASR质量，翻译文本质量等）
- 批量处理 文件夹 分别处理功能

#### model

- 模型配置项，针对不同 本地/API 模型的统一流水线
- 对 ASR API的支持(与MODEL API整合)
- 更多 ASR 支持（Qwen3ASR，FUNASR， MIMOASR）
- 更多 语音合成引擎支持（VoxCPM2，indexTTS等）（同上）
- 添加 本地模型下载页， 不再使用脚本下载（网络配置提醒）

#### 重构

- 前端重构
- 流水线重构
- 后端逻辑重构整合

## DONE LIST

- PDF/TXT台本 转换为 时间轴字幕文件（通过接入Model解决）
- 处理后输出翻译字幕
- GUI 优化和增强
- 添加音频音量预览功能
