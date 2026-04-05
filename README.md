# ASMR Helper

ASMR 音频汉化工具，支持人声分离、语音识别、日译中翻译、语音合成和智能混音，输出双语双轨音频。

## 功能特性

- **人声分离** - 基于 Demucs 从背景音中提取纯净人声
- **语音识别** - Faster-Whisper 高精度日文 ASR，支持 VTT 字幕跳过优化
- **翻译引擎** - DeepSeek / OpenAI API，批量翻译 + 质量检测 + 翻译缓存
- **语音合成** - Edge-TTS (免费) / Qwen3-TTS (高质量) / GPT-SoVITS (声音克隆)
- **智能混音** - 时间轴对齐 + 音量平衡，输出原声+中文配音双轨
- **GUI 界面** - PySide6 桌面应用，支持单文件/批量处理

## 系统要求

- **OS**: Windows 10/11
- **Python**: 3.10+
- **GPU**: NVIDIA (可选，Qwen3-TTS 需要 CUDA)
- **包管理器**: [uv](https://docs.astral.sh/uv/)

## 快速开始

### 1. 一键配置环境

```powershell
# 克隆项目
git clone https://github.com/Flysky701/AsmrHelper.git
cd AsmrHelper

# 基础安装 (ASR + Edge-TTS + Demucs)
.\setup.ps1

# 完整安装 (含 Qwen3-TTS，需要 NVIDIA GPU)
.\setup.ps1 -Full
```

> 安装脚本会自动并发测速 pypi.org 官方源和国内镜像（清华、阿里），选择延迟最低的源进行安装，哪个快用哪个。如果首选源失败，会自动按延迟顺序回退。

### 2. 下载 AI 模型

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
│   ├── core/
│   │   ├── asr/                  # Faster-Whisper ASR 语音识别
│   │   ├── translate/            # 翻译引擎 + 缓存 + 术语库
│   │   ├── tts/                  # TTS (Edge/Qwen3/GPT-SoVITS)
│   │   ├── vocal_separator/      # Demucs 人声分离
│   │   └── pipeline/             # 统一流水线调度
│   ├── mixer/                    # 智能混音 + 时间轴对齐
│   ├── config.py                 # 配置管理
│   ├── cli.py                    # Click CLI 入口
│   ├── gui.py                    # PySide6 GUI 界面
│   ├── gui_workers.py            # GUI 后台工作线程
│   └── gui_services.py           # GUI 服务层
├── config/                       # 配置文件
│   ├── config.example.json       # 配置模板 (复制为 config.json)
│   ├── config.json               # 用户配置 (git ignored)
│   ├── asmr_terms.json           # ASMR 术语库
│   └── voice_profiles.json       # 音色配置 (git ignored)
├── scripts/                      # 独立脚本
│   ├── asmr_bilingual.py         # 双语双轨完整流程
│   ├── batch_process.py          # 批量处理
│   ├── install_models.py         # 模型下载工具
│   ├── verify_env.py             # 环境验证
│   └── verify_models.py          # 模型验证
├── models/                       # 模型文件 (git ignored, 首次运行自动下载)
├── tests/                        # 测试
├── setup.ps1                     # 一键环境配置
├── run.bat                       # Windows 启动器
└── pyproject.toml                # 项目依赖
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
| `gptsovits` | 高 | 快 | 需要 | GPT-SoVITS，需单独部署服务 |

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
[3] Faster-Whisper ASR (日文 -> 文字)
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
