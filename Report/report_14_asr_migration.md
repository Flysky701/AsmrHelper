# Report 14: 语音识别模块对比与迁移分析

> **日期**: 2026-04-04  
> **对比项目**: VoiceTransl vs AsmrHelper  
> **分析范围**: ASR 语音识别 + 人声分离 + 音频预处理  
> **报告编号**: #14

---

## 1. 架构总览

### 1.1 VoiceTransl 语音识别架构

VoiceTransl 的语音识别采用**外部进程调用**模式，不直接集成 Whisper Python API：

```
输入文件 → ffmpeg(重采样16k) → whisper-cli / whisper-faster.exe → .srt → srt2prompt.py → .json
                                    ↑                        ↑
                              外部二进制进程           Silero VAD (whisper.cpp)
                              用户手动放置模型文件
```

**关键文件**:
| 文件 | 作用 |
|------|------|
| `whisper/param.txt` | whisper.cpp 命令行参数模板 |
| `whisper-faster/param.txt` | Faster-Whisper-XXL 命令行参数模板 |
| `srt2prompt.py` | SRT → JSON 时间戳桥接 |
| `prompt2srt.py` | JSON → SRT/LRC 输出 |
| `separate.py` | UVR MDX-Net 人声分离（ONNX Runtime） |

### 1.2 AsmrHelper 语音识别架构

AsmrHelper 采用**Python 库直接集成**模式，完全在进程内运行：

```
输入文件 → (可选: Demucs 人声分离) → Faster-Whisper (Python API) → [{start, end, text}]
                                              ↓
                               ASMR 特化参数:
                               - disable_vad=True (保留轻声)
                               - 多温度重试 [0.0~1.0]
                               - initial_prompt (引导轻声)
                               - no_speech_threshold=0.9
```

**关键文件**:
| 文件 | 作用 |
|------|------|
| `src/core/asr/__init__.py` | Faster-Whisper Python 封装 |
| `src/core/vocal_separator/__init__.py` | Demucs 4.0 人声分离 |
| `src/core/pipeline/__init__.py` | 流水线调度（含 VTT 智能跳过） |

---

## 2. 逐维度对比

### 2.1 Whisper 引擎集成方式

| 维度 | VoiceTransl | AsmrHelper |
|------|-------------|------------|
| **集成模式** | 外部进程 (subprocess) | Python API (ctypes/ONNX) |
| **支持的引擎** | whisper.cpp + Faster-Whisper-XXL | Faster-Whisper |
| **模型管理** | 用户手动放置 .bin/.exe | 自动下载 + 本地缓存 |
| **参数传递** | 命令行模板字符串替换 | Python 函数参数 |
| **输出格式** | .srt → 转换 → .json | 直接 [{start, end, text}] |
| **错误处理** | 检查进程退出码 | Python 异常捕获 |

**分析**: AsmrHelper 的 Python API 集成方式在**可控性、参数精度、错误处理**方面全面优于 VoiceTransl 的外部进程调用。VoiceTransl 使用命令行模板字符串替换（`$whisper_file`, `$language`）的方式脆弱且不安全，但好处是用户可以自由选择任意 whisper.cpp 模型。

### 2.2 ASMR 场景适配

| 维度 | VoiceTransl | AsmrHelper |
|------|-------------|------------|
| **VAD** | Silero VAD (whisper.cpp 内置) | 默认**禁用** (disable_vad=True) |
| **温度策略** | 默认（单温度） | **多温度重试** [0.0, 0.2, 0.4, 0.6, 0.8, 1.0] |
| **初始提示** | 无 | 日文初始提示引导轻声识别 |
| **no_speech_threshold** | 默认 | **0.9**（高阈值保留轻声） |
| **compression_ratio_threshold** | 默认 | **2.4**（过滤重复幻觉） |
| **condition_on_previous_text** | 默认 | **True**（利用上下文） |

**分析**: 这是 AsmrHelper 的**核心优势**。ASMR 音频的特殊性（极低音量、耳语、长时间静默）要求 ASR 引擎针对轻声做特殊适配。AsmrHelper 的五项 ASMR 特化参数是经过实际测试调优的，VoiceTransl 完全没有这方面的适配（它面向的是正常音量的视频/游戏配音）。

**关键发现**: AsmrHelper 禁用 VAD 是正确决策。VAD 会过滤掉 ASMR 中的轻声和气声片段，导致识别遗漏。

### 2.3 音频预处理

| 维度 | VoiceTransl | AsmrHelper |
|------|-------------|------------|
| **重采样** | ffmpeg 强制 16kHz mono | 依赖 Faster-Whisper 内部处理 |
| **人声分离** | UVR MDX-Net (ONNX) | **Demucs 4.0** (PyTorch) |
| **分离精度** | MDX 模型（较好） | htdemucs/htdemucs_ft（业界标杆） |
| **分离速度** | ONNX Runtime (DML/CoreML) | PyTorch CUDA |
| **输出轨** | vocal + instrumental (2轨) | vocals/drums/bass/other (4轨) |
| **GPU 加速** | DirectML / CoreML | CUDA |

**分析**: 
- **预处理**: VoiceTransl 用 ffmpeg 预重采样到 16kHz 是 whisper.cpp 的要求（只接受 16kHz 输入），Faster-Whisper 不需要这一步，AsmrHelper 的做法正确。
- **人声分离**: 两者各有优劣。UVR MDX-Net 通过 ONNX Runtime 可在 AMD GPU (DirectML) 和 Apple Silicon (CoreML) 上运行，硬件兼容性更好。Demucs 4.0 在 CUDA 环境下精度更高。对于 ASMR 场景，人声分离精度更重要（需要干净的人声给 ASR），Demucs 是正确选择。

### 2.4 时间戳与数据格式

| 维度 | VoiceTransl | AsmrHelper |
|------|-------------|------------|
| **中间格式** | .srt → JSON (pysrt解析) | 直接 [{start, end, text}] |
| **桥接转换** | 需要 srt2prompt.py | 不需要 |
| **输出格式** | SRT / LRC | 自定义文本 / VTT |
| **word_timestamps** | 不支持 | 参数可选（当前关闭） |
| **时间精度** | 毫秒级 (SRT 格式) | 2位小数秒 (round(seg.start, 2)) |

**分析**: VoiceTransl 的 SRT → JSON 桥接是历史包袱——因为 whisper.cpp 只输出 SRT 格式。AsmrHelper 直接使用 Faster-Whisper 的 segment 数据结构，更高效。但 AsmrHelper 的时间精度只有 2 位小数（10ms），SRT 支持毫秒级。

### 2.5 输入源支持

| 维度 | VoiceTransl | AsmrHelper |
|------|-------------|------------|
| **本地文件** | 视频文件、音频文件 | 音频文件 |
| **在线下载** | YouTube (yt-dlp)、Bilibili | 无 |
| **SRT 输入** | 支持（跳过 ASR） | 支持（VTT 智能跳过） |
| **批量处理** | 支持 | 支持 |

**分析**: VoiceTransl 的在线下载能力是实用功能，但不属于 ASR 核心能力。AsmrHelper 的 VTT 智能跳过方案更优雅——根据 VTT 语言自动决定执行哪些步骤。

---

## 3. 核心结论：迁移必要性评估

### 3.1 不需要从 VoiceTransl 迁移的部分

| 项目 | 原因 |
|------|------|
| **whisper.cpp 外部进程调用** | AsmrHelper 的 Python API 集成更优 |
| **命令行参数模板** | Python 函数参数更安全可控 |
| **SRT → JSON 桥接** | AsmrHelper 直接使用 segment 数据，无需桥接 |
| **ffmpeg 预重采样** | Faster-Whisper 不需要 |
| **UVR MDX-Net 人声分离** | Demucs 4.0 在 CUDA 环境下精度更高 |
| **Silero VAD** | ASMR 场景需要禁用 VAD |

### 3.2 可以考虑借鉴的部分

| 项目 | 收益 | 优先级 | 工作量 |
|------|------|--------|--------|
| **word_timestamps 开启** | 逐词时间戳可优化 TTS 对齐精度 | P2 | 低 (1个参数) |
| **毫秒级时间精度** | round(seg.start, 3) 替代 round(seg.start, 2) | P3 | 极低 (改1行) |
| **SRT/LRC 输出格式** | 方便外部工具使用 | P3 | 中 |

### 3.3 AsmrHelper 应该自身优化的部分

这些优化不依赖 VoiceTransl，而是基于 ASMR 场景的自身需求：

| 优化项 | 描述 | 优先级 | 工作量 |
|--------|------|--------|--------|
| **ASR 后处理** | Whisper 输出的日文文本常有标点/空格问题，需要规范化 | **P1** | 中 |
| **轻声/气声检测日志** | 记录被 no_speech_threshold 过滤的片段供审查 | P2 | 低 |
| **多模型 ASR 对比** | 同一音频用 base + large-v3 双模型识别，取长补短 | P3 | 中 |
| **ASR 置信度评分** | 利用 log_prob 过滤低置信度片段 | P2 | 低 |
| **流式 ASR 进度** | 长音频需要实时显示识别进度 | P2 | 中 |

---

## 4. ASMR ASR 后处理规范（建议新增）

基于对 VoiceTransl SRT → JSON 桥接过程和实际 ASMR ASR 输出的分析，建议新增 ASR 后处理步骤：

### 4.1 日文文本规范化

```python
# Whisper 输出常见问题 → 规范化规则
RULES = [
    # 重复标点
    (r'。+', '。'),
    (r'、+', '、'),
    # 全角半角混用
    (r'！', '!'),  # ASMR 中感叹号较少，统一半角
    (r'？', '?'),
    # 多余空格
    (r'\s+', ''),
    # Whisper 幻觉标记
    (r'\[.*?\]', ''),  # 去除 [音乐] [掌声] 等标记
]
```

### 4.2 片段合并策略

Whisper 有时将一句话拆成多个极短片段（<1s），需要合并：

```python
def merge_short_segments(segments, min_gap=0.3, min_duration=1.0):
    """合并间隔 < 0.3s 且单段 < 1s 的片段"""
    merged = []
    for seg in segments:
        if merged and (seg['start'] - merged[-1]['end'] < min_gap):
            if seg['end'] - merged[-1]['start'] < min_duration:
                merged[-1]['end'] = seg['end']
                merged[-1]['text'] += seg['text']
                continue
        merged.append(seg.copy())
    return merged
```

---

## 5. 人声分离方案对比

### 5.1 技术对比

| 维度 | UVR MDX-Net (VoiceTransl) | Demucs 4.0 (AsmrHelper) |
|------|---------------------------|--------------------------|
| **框架** | ONNX Runtime | PyTorch |
| **GPU 支持** | DirectML / CoreML / CPU | CUDA / CPU |
| **模型格式** | .onnx (用户放置) | PyTorch Hub (自动下载) |
| **音频质量** | 44.1kHz 固定 | 自适应（模型 samplerate） |
| **声道要求** | 必须立体声（单声自动复制） | 自动适配 |
| **分离粒度** | 2轨 (vocal/instrumental) | 4轨 (vocals/drums/bass/other) |
| **内存占用** | 较低 (ONNX 优化) | 较高 (PyTorch) |

### 5.2 ASMR 场景评估

**Demucs 4.0 是正确选择**，原因：
1. ASMR 音频以人声为核心，分离精度比速度更重要
2. 4 轨分离可以在混音时灵活调整各音轨比例
3. RTX 4070 Ti SUPER 16GB 显存完全满足 Demucs 需求
4. htdemucs_ft 是当前开源人声分离的 SOTA 模型

**不建议迁移到 UVR MDX-Net**，但可以借鉴其跨平台兼容思路（当未来需要支持 AMD GPU 时）。

---

## 6. 最终建议

### 6.1 迁移优先级总表

| 优先级 | 项目 | 来源 | 工作量 | 收益 |
|--------|------|------|--------|------|
| **P1** | ASR 后处理（文本规范化 + 片段合并） | 自身优化 | 1-2天 | 提升翻译输入质量 |
| **P2** | 开启 word_timestamps | 参数调整 | 1行 | TTS 对齐优化 |
| **P2** | ASR 置信度过滤 | 自身优化 | 半天 | 减少误识别 |
| **P2** | 流式 ASR 进度显示 | 自身优化 | 半天 | 用户体验 |
| **P3** | 毫秒级时间精度 | 自身优化 | 1行 | 精度提升 |
| **P3** | SRT/LRC 输出格式 | 参考 VoiceTransl | 1天 | 兼容外部工具 |
| **不迁移** | whisper.cpp 外部调用 | — | — | Python API 更优 |
| **不迁移** | UVR MDX-Net | — | — | Demucs 更适合 |
| **不迁移** | ffmpeg 预重采样 | — | — | 不需要 |
| **不迁移** | Silero VAD | — | — | ASMR 需禁用 VAD |

### 6.2 核心结论

> **VoiceTransl 的 ASR 模块对 AsmrHelper 没有迁移价值。**

原因：
1. VoiceTransl 面向**正常音量视频/游戏配音**的 ASR 场景，与 ASMR 的**轻声/气声/低信噪比**场景需求完全不同
2. VoiceTransl 使用外部进程调用 whisper.cpp，是技术选型上的妥协（为了跨平台），AsmrHelper 的 Python API 集成更先进
3. AsmrHelper 在 ASMR ASR 领域已经有 5 项特化调优（多温度、禁用 VAD、高阈值、初始提示、上下文关联），VoiceTransl 一项都没有

**真正的优化方向不在迁移，而在自身 ASMR 场景的深度优化**——特别是 ASR 后处理（文本规范化、短片段合并、置信度过滤），这些是目前缺失的关键环节。

---

## 附录 A: VoiceTransl ASR 参数模板

### whisper.cpp (whisper/param.txt)
```
whisper/whisper-cli -m whisper/$whisper_file -osrt -l $language $input_file.wav -of $input_file --vad --vad-model whisper/ggml-silero-v5.1.2.bin
```

### Faster-Whisper-XXL (whisper-faster/param.txt)
```
Whisper-Faster/whisper-faster.exe --beep_off --verbose True --model $whisper_file --model_dir Whisper-Faster --task transcribe --language $language --output_format srt --output_dir $output_dir $input_file.wav --compute_type float16
```

### 参数对比

| 参数 | VoiceTransl | AsmrHelper | 说明 |
|------|-------------|------------|------|
| `--vad` | 开启 | **禁用** | ASMR 需保留轻声 |
| `--language` | 用户指定 | 配置文件 | 一致 |
| `--model` | 用户放置 | 自动下载 | AsmrHelper 更方便 |
| `--compute_type` | float16 | float16/int8 | 一致（CPU 用 int8） |
| `beam_size` | 未指定(默认5) | 5 | 一致 |
| `best_of` | 未指定(默认5) | 5 | 一致 |
| `temperature` | 未指定(默认) | **[0.0~1.0] 6档** | AsmrHelper 更激进 |
| `initial_prompt` | 无 | **日文引导** | AsmrHelper 特化 |
| `no_speech_threshold` | 默认(~0.6) | **0.9** | AsmrHelper 特化 |

## 附录 B: 数据流对比图

### VoiceTransl
```
[视频/音频] → ffmpeg → [16k.wav] → whisper.cpp/faster-whisper → [.srt]
                                                                    ↓
                                                              srt2prompt.py
                                                                    ↓
                                                              [project/gt_input/*.json]
                                                                    ↓
                                                              GalTransl 翻译
                                                                    ↓
                                                              prompt2srt.py
                                                                    ↓
                                                              [输出.srt / .lrc]
```

### AsmrHelper
```
[音频] → (Demucs分离) → [vocal.wav] → Faster-Whisper → [{start,end,text}]
                                                                ↓
                                                    (VTT智能跳过: 直接用VTT)
                                                                ↓
                                                         DeepSeek 翻译
                                                                ↓
                                                    [{start,end,text,translation}]
                                                                ↓
                                                         Qwen3-TTS 逐句合成
                                                                ↓
                                                         时间轴对齐 → 混音
                                                                ↓
                                                         [成品_mix.wav]
```

**关键差异**: AsmrHelper 的全链路 Python 集成使得中间数据格式统一（dict/list），无需任何格式转换桥接。
