
# ASMR Helper

ASMR 音频汉化工具，支持人声分离、语音识别、日译中翻译、语音合成和智能混音，输出双语双轨音频。

## 功能特性

- **人声分离** - 基于 Demucs 从背景音中提取纯净人声
- **语音识别** - Faster-Whisper 高精度日文 ASR，支持 存在字幕文件时跳过优化
- **翻译引擎** - DeepSeek / OpenAI API，批量翻译 + 质量检测 + 翻译缓存
- **语音合成** - Edge-TTS (免费) / Qwen3-TTS (高质量) / GPT-SoVITS (暂不支持)
- **智能混音** - 时间轴对齐 + 音量平衡，输出原声+中文配音双轨
- **GUI 界面** - PySide6 桌面应用，支持单文件/批量处理/音色工坊/工具箱
- **工具箱** - 独立的单步工具：音频分离、音频切分、ASR识别、格式转换、字幕生成、字幕翻译
- **嵌入式播放器** - 内置音频播放器，支持试音预览和片段播放

## 系统要求

- **OS**: Windows 10/11
- **Python**: 3.10+
- **GPU**: NVIDIA (可选，Qwen3-TTS 需要 CUDA)
- **包管理器**: [uv](https://docs.astral.sh/uv/)

## 快速开始

### 1. 一键配置环境

注意使用**Powershell**

```powershell
# 克隆项目
git clone https://github.com/Flysky701/AsmrHelper.git
cd AsmrHelper

# 基础安装 (ASR + Edge-TTS + Demucs)
.\setup.ps1

# 完整安装 (含 Qwen3-TTS依赖，需要 NVIDIA GPU)
.\setup.ps1 -Full

# 环境完全重建
.\setup.ps1 -CleanReinstall
```

> 安装脚本会自动并发测速 pypi.org 官方源和国内镜像（清华、阿里），选择延迟最低的源进行安装，哪个快用哪个。如果首选源失败，会自动按延迟顺序回退。

### 2. 下载 AI 模型

下载前**重启Powershell**

```powershell
# 下载 Whisper base 模型 (约 74MB，推荐)
.\setup.ps1 -Models

# 下载全部模型 (Whisper + Qwen3-TTS，约 25GB+)
.\setup.ps1 -Models -Full

# 使用国内镜像加速
.\setup.ps1 -Models -Mirror

# 或直接使用 Python 脚本
uv run python scripts/install_models.py                    # Whisper base
uv run python scripts/install_models.py --whisper large-v3 # Whisper large-v3
uv run python scripts/install_models.py --qwen3            # Qwen3 全部
uv run python scripts/install_models.py --all              # 全部
uv run python scripts/install_models.py --check            # 检查状态
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
# 启动 GUI
.\run.bat

# 或命令行处理单文件
uv run python scripts/asmr_bilingual.py --input "path/to/audio.wav"

# 批量处理
uv run python scripts/batch_process.py --input-dir "D:/ASMR"
```

## 项目结构

```
AsmrHelper/
├── src/                          # 核心源代码
│   ├── core/                     # 核心处理模块
│   │   ├── asr/                 # Faster-Whisper ASR 语音识别
│   │   ├── translate/            # 翻译引擎 + 缓存 + 术语库
│   │   ├── tts/                  # TTS (Edge/Qwen3/GPT-SoVITS)
│   │   ├── vocal_separator/      # Demucs 人声分离
│   │   ├── pipeline/             # 统一流水线调度
│   │   ├── subtitle_generator.py # 字幕生成工具
│   │   └── gpu_manager.py        # GPU 管理
│   ├── mixer/                    # 智能混音 + 时间轴对齐
│   ├── utils/                    # 工具模块
│   │   ├── audio_player.py       # 嵌入式音频播放器
│   │   ├── constants.py          # 常量定义
│   │   ├── formatters.py         # 格式化工具
│   │   ├── gpu_context.py        # GPU 上下文
│   │   └── patterns.py           # 正则表达式模式
│   ├── gui/                     # PySide6 GUI 界面 (MVC 架构)
│   │   ├── app.py                # 主应用入口
│   │   ├── views/                # 视图层 (Tab 页面)
│   │   ├── controllers/           # 控制器
│   │   ├── components/            # 通用组件
│   │   ├── services/              # 服务层
│   │   ├── workers/               # 后台工作线程
│   │   └── utils/                 # GUI 工具
│   ├── cli.py                    # Click CLI 入口
│   └── config.py                 # 配置管理
├── config/                       # 配置文件
│   ├── config.example.json       # 配置模板
│   ├── config.json               # 用户配置 (git ignored)
│   ├── asmr_terms.json           # ASMR 术语库
│   ├── voice_profiles.json       # 音色配置 (git ignored)
│   └── voice_profiles.example.json # 音色模板
├── scripts/                      # 独立脚本
│   ├── asmr_bilingual.py         # 双语双轨完整流程
│   ├── batch_process.py          # 批量处理
│   ├── install_models.py         # 模型下载工具
│   ├── verify_env.py             # 环境验证
│   ├── verify_models.py          # 模型验证
│   └── generate_voice_profiles.py # 音色配置文件生成
├── models/                       # 模型文件 (git ignored)
├── tests/                        # 测试
│   ├── test_core.py             # 核心模块测试
│   ├── test_fixes.py            # Bug 修复测试
│   ├── conftest.py              # pytest 配置
│   ├── records/                  # 测试录音
│   ├── scripts/                  # 测试脚本
│   ├── setup/                   # 安装测试
│   └── test_output/              # 测试输出
├── 音色描述词指南.md              # 音色描述词参考
├── setup.ps1                     # 一键环境配置
├── run.bat                       # Windows 启动器
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

| 字段 | 说明 | 默认值 |
|------|------|--------|
| `api.provider` | 翻译服务 (deepseek/openai) | `deepseek` |
| `api.deepseek_api_key` | DeepSeek API Key | |
| `tts.engine` | TTS 引擎 (edge/qwen3/gptsovits) | `edge` |
| `tts.voice` | Edge-TTS 音色 | `zh-CN-XiaoxiaoNeural` |
| `processing.vocal_model` | 人声分离模型 | `htdemucs` |
| `processing.asr_model` | ASR 模型大小 (tiny/base/medium/large-v3) | `base` |

### 环境变量

| 变量 | 说明 |
|------|------|
| `DEEPSEEK_API_KEY` | DeepSeek API 密钥 |
| `OPENAI_API_KEY` | OpenAI API 密钥 |

环境变量优先级高于配置文件。

## TTS 引擎对比

| 引擎 | 质量 | 速度 | GPU | 说明 |
|------|------|------|-----|------|
| `edge` | 一般 | 快 | 不需要 | 微软免费 TTS，适合快速体验 |
| `qwen3` | 高 | 慢 | 需要 CUDA | Qwen3-TTS，支持音色设计/克隆 |

## GUI 界面

### 主界面布局

- **单文件处理** - 处理单个音频文件，支持完整流程或单步执行
- **批量处理** - 批量处理多个音频文件
- **音色工坊** - Qwen3-TTS 专属功能，支持音色设计、片段预览和试音
- **工具箱** - 独立的单步工具集合

### 工具箱功能

| 工具 | 说明 |
|------|------|
| 音频分离 | Demucs 人声/伴奏分离 |
| 音频切分 | 按字幕时间轴切分音频 |
| ASR 识别 | 语音转文字 (Faster-Whisper) |
| 格式转换 | 音频格式互转 (WAV/MP3/FLAC/OGG/M4A) |
| 字幕生成 | 文本/PDF 转字幕 (SRT/VTT/LRC) |
| 字幕翻译 | 翻译字幕文件 (支持批量) |

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
.\setup.ps1 -DevOnly

# 运行测试
uv run pytest

# 运行安装脚本集成测试
uv run pytest tests/test_setup_integration.py -v

# 运行环境验证
uv run python scripts/verify_env.py

# 检查模型状态
uv run python scripts/install_models.py --check

# 下载模型
uv run python scripts/install_models.py --whisper base
uv run python scripts/install_models.py --qwen3
```

## 许可证

MIT License


## 架构说明

### 核心模块 (src/core)
- `asr/` - Faster-Whisper 语音识别，支持 VAD 检测和多语言
- `translate/` - 翻译引擎，支持 DeepSeek/OpenAI，包含缓存和术语库
- `tts/` - 语音合成，支持 Edge-TTS、Qwen3-TTS
- `vocal_separator/` - Demucs 人声分离
- `pipeline/` - 统一处理流水线
- `subtitle_generator.py` - 字幕生成工具

### GUI 架构 (src/gui) - MVC 模式
```
views/       # 视图层：各 Tab 页面 (单文件、批量、音色工坊、工具箱)
controllers/ # 控制器：处理用户交互逻辑
services/    # 服务层：业务逻辑封装
workers/     # 工作线程：后台任务处理，避免 UI 阻塞
components/  # 通用组件：可复用 UI 组件
```

### 工具模块 (src/utils)
- `audio_player.py` - 嵌入式音频播放器
- `constants.py` - 常量定义
- `formatters.py` - 格式化工具
- `gpu_context.py` - GPU 上下文管理
- `patterns.py` - 正则表达式模式库


### TODO LIST
- PDF/TXT台本 转换为 时间轴字幕文件
- VoxCPM2 语音合成

## DONE LIST
- GUI 优化和增强
- 添加音频音量预览功能