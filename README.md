# ASMR Helper - ASMR 音频汉化工具

## 项目概述

基于 pyvideotrans 的改进版 ASMR 音频处理工具，支持：
- 人声分离（Demucs）
- 自动语音识别（Faster-Whisper）
- 多语言翻译（DeepSeek / OpenAI）
- 语音合成（Edge-TTS / Qwen3-TTS）
- 智能混音（双语双轨）

## 项目结构

```
AsmrHelper/
├── src/                    # 核心源代码
│   ├── core/              # 核心处理模块
│   │   ├── asr/          # ASR 语音识别
│   │   ├── translate/     # 翻译引擎
│   │   ├── tts/          # TTS 语音合成
│   │   ├── vocal_separator/  # 人声分离
│   │   └── pipeline/     # 流水线调度
│   ├── mixer/            # 混音处理
│   ├── models/            # 模型管理
│   └── utils/             # 工具函数
├── scripts/              # 独立脚本
├── assets/               # 资源文件
│   ├── f5-tts/          # F5-TTS 参考音频
│   └── voices/           # 预置音色
├── tests/                # 测试文件
└── docs/                 # 文档
```

## 快速开始

```powershell
# 安装依赖
cd d:\WorkSpace\AsmrHelper
uv sync

# 运行 ASMR 双语双轨流程
$env:DEEPSEEK_API_KEY = "your-api-key"
uv run python scripts/asmr_bilingual.py --input "path/to/audio.wav"
```

## 核心流程

1. **Demucs 人声分离** - 从音频中分离出人声
2. **Whisper ASR** - 识别日文语音为文字
3. **DeepSeek 翻译** - 将日文翻译为中文
4. **Qwen3-TTS 合成** - 生成中文配音
5. **ffmpeg 混音** - 合并原音与配音

## 配置

环境变量：
- `DEEPSEEK_API_KEY` - DeepSeek API 密钥
- `OPENAI_API_KEY` - OpenAI API 密钥

## 许可证

MIT License
