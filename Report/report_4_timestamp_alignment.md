# Agent3 架构指导报告 #4 — TTS 时间轴对齐方案

**日期**: 2026-04-03 22:35
**状态**: 最终版
**受众**: Agent1（代码实现）
**前置依赖**: 报告 #3（VTT 智能跳过）已实施

---

## 一、问题诊断：TTS 时间轴为什么对不上？

### 1.1 当前混音逻辑（Mixer）

```python
# src/mixer/__init__.py L105-110
cmd = [
    get_ffmpeg(),
    "-i", str(original_path),    # 原音（整首音频，通常 5-15 分钟）
    "-i", str(tts_path),          # TTS（一段连续音频，通常 1-3 分钟）
    "-filter_complex",
    f"[0:a]volume=0.85[orig];[1:a]volume=XdB,adelay=Yms[tts];[orig][tts]amix=...",
]
```

**当前做法**：将 TTS 整段音频从第 0 秒开始（或延迟 Y 毫秒后）与原音叠加。

### 1.2 为什么完全对不上？

以 VTT 字幕为参考（`#2.千寻的治愈的放松手交.wav.vtt`）：

| VTT 条目 | 时间范围 | 与下一条的间隔 |
|----------|----------|---------------|
| #1 | 24.14s → 29.74s | 0.87s |
| #2 | 30.61s → 32.48s | 0.19s |
| ... | ... | ... |
| #33 | 05:29.71 → 05:33.68s | **16.1s** |
| #34 | 06:01.73 → 06:05.20s | ... |

**核心矛盾**：

1. **TTS 是连续音频**：所有翻译文本被 `"。".join()` 拼成一段，TTS 引擎从头到尾无间断合成。假设 TTS 总时长 90s，那么 TTS 在 0s~90s 连续播放。
2. **原音有大量静默/呼吸**：ASMR 音频中说话只占一部分，其余是呼吸、静默、环境音。
3. **时间轴完全脱钩**：TTS 的第 1 句（对应原音 24s）在 TTS 音频中从 0s 就开始播放，但原音要到 24s 才开始说这句话。

**结果**：听到的效果是 —— TTS 从头开始念，原音在 24s 才开始说第一句，两者完全不同步。

### 1.3 `tts_delay_ms` 为什么不能解决问题？

GUI 有个"TTS 延迟"参数（`tts_delay_ms`），但这是**全局偏移**，只能让整段 TTS 整体提前/延后。

**假设将 delay 设为 24s**：
- TTS 第 1 句 (24.14s) → 延迟后 48.14s，但原音第 1 句在 24.14s → **晚了 24s**
- 即使对齐了第 1 句，第 2 句也会逐渐偏移，因为 TTS 每句话的时长与原音不同

**根本原因**：中文 TTS 每句话的时长与日文原音每句话的时长不同，简单的全局延迟无法解决逐句对齐。

---

## 二、解决方案：逐句时间戳对齐

### 2.1 核心思路

```
原音时间轴:
|--静默24s--|[第1句 5.6s]|[间隔 0.9s]|[第2句 1.9s]|[间隔0.2s]|[第3句 3.1s]|...|--静默16s--|...

TTS 时间轴 (对齐后):
|--静默24s--|[第1句 2.1s]|[间隔 0.9s]|[第2句 0.8s]|[间隔0.2s]|[第3句 1.4s]|...|--静默16s--|...
                ^TTS时长较短            ^自动填充间隔到下一句的start时间
```

**关键**：将每句 TTS 精确放置到原音对应句子的时间位置，中间的间隔保持原音的原始静默。

### 2.2 新流水线设计

```
输入: audio.wav [+ VTT字幕]

Step 1: 人声分离 (Demucs)
  → vocal.wav (人声)

Step 2: 时间戳对齐 (两种来源)
  → 有 VTT: 解析 VTT 时间戳 → [{start, end, text}, ...]
  → 无 VTT: Whisper ASR (已带时间戳) → [{start, end, text}, ...]

Step 3: 翻译 (如需要)
  → [{start, end, text, translation}, ...]
  → 逐句翻译，保留时间戳

Step 4: 逐句 TTS + 时间轴拼装
  → 对每句 translation 单独合成 TTS
  → 按 start 时间放置到时间轴上
  → tts_aligned.wav (与原音等长)

Step 5: 混音
  → vocal.wav + tts_aligned.wav → final_mix.wav
```

### 2.3 逐句 TTS 策略

当前代码将所有翻译拼成一段 `"。".join(translations)` 然后一次合成。改为逐句合成：

```python
# 旧方案 (问题)
full_text = "。".join(translations)       # 65句话拼成一段
tts_engine.synthesize(full_text, output)  # 一次合成，结果连续

# 新方案 (修复)
for seg in segments:
    tts_clip = tts_engine.synthesize(seg["translation"], temp_path)
    # 将 tts_clip 放置到 seg["start"] 位置
    timeline.place(tts_clip, start=seg["start"])
```

**TTS 时长 vs 原音时长**：

每句 TTS 的时长可能比原音长或短。处理策略：

| 情况 | 处理方式 |
|------|---------|
| TTS 时长 < 原音间隔 | 自然结束，静默等待下一句 |
| TTS 时长 > 原音间隔 (轻微溢出) | 允许溢出 10-20%，覆盖到下一句前 50ms |
| TTS 时长 > 原音间隔 (严重溢出) | 对 TTS 做时间拉伸 (pytsmod/rubberband)，压缩到适合长度 |

---

## 三、时间戳来源分析

### 3.1 方案 A：Whisper ASR（无 VTT 时）

**已有能力**：`ASRRecognizer.recognize()` 返回的 `asr_results` 已包含时间戳：

```python
# src/core/asr/__init__.py L126-135
result = {
    "start": round(seg.start, 2),   # 精确到 10ms
    "end": round(seg.end, 2),       # 精确到 10ms
    "text": seg.text.strip(),
}
```

**精度**：Faster-Whisper 的 segment 级时间戳精度约 **50-100ms**，对于 ASMR 来说够用。

**可以进一步提升精度**：启用 `word_timestamps=True`，获取词级别时间戳，再取首词 start 和末词 end 作为句子的精确边界，精度可到 **20-50ms**。

### 3.2 方案 B：VTT 字幕（有 VTT 时）

**已有能力**：`load_vtt_with_timestamps()` 已实现（报告 #3 新增）。

VTT 时间戳精度通常为 **10ms**（毫秒级）。

**注意**：VTT 时间戳是人工/半人工标注的，通常比 ASR 更准确。

### 3.3 方案 C：Whisper 强制对齐 (Forced Alignment)

如需更高精度（<10ms），可以用 Whisper 的 forced alignment 功能：

```python
from faster_whisper import WhisperModel

model = WhisperModel("large-v3")
segments, info = model.transcribe(
    audio_path,
    word_timestamps=True,     # 启用词级时间戳
)

for seg in segments:
    for word in seg.words:
        print(f"  {word.word} → {word.start:.3f}s - {word.end:.3f}s")
        # 精度: ~10ms
```

**结论**：方案 A + B 已满足需求。方案 C 作为可选拓展。

---

## 四、Agent1 代码修改指导

### 4.1 新增：时间轴拼装模块

**文件**: `src/mixer/__init__.py`（在 Mixer 类中新增方法）

```python
import soundfile as sf
import numpy as np

class Mixer:
    # ... 原有代码 ...

    def build_aligned_tts(
        self,
        segments: List[dict],
        tts_engine,
        output_path: str,
        reference_duration: float,
        sample_rate: int = 44100,
        tts_speed_range: tuple = (0.8, 1.2),
    ) -> str:
        """
        逐句合成 TTS 并按时间戳拼装到时间轴上

        Args:
            segments: 带时间戳的段落 [{start, end, translation}, ...]
            tts_engine: TTS 引擎实例
            output_path: 输出文件路径
            reference_duration: 参考音频总时长（秒）
            sample_rate: 采样率
            tts_speed_range: TTS 语速允许范围（超出则自动调速）

        Returns:
            str: 输出文件路径
        """
        from pathlib import Path
        import tempfile
        import os

        output_path = Path(output_path)
        ensure_dir(output_path.parent)

        # 创建空的时间轴（与原音等长的静音）
        total_samples = int(reference_duration * sample_rate)
        timeline = np.zeros(total_samples, dtype=np.float32)

        temp_dir = output_path.parent / "tts_temp"
        temp_dir.mkdir(exist_ok=True)

        print(f"[Mixer] 逐句合成 TTS ({len(segments)} 句)...")

        for i, seg in enumerate(segments):
            translation = seg.get("translation", "")
            if not translation.strip():
                continue

            start_sec = seg["start"]
            end_sec = seg["end"]
            original_duration = end_sec - start_sec

            # 1. 合成单句 TTS
            temp_tts = temp_dir / f"tts_{i:04d}.mp3"
            try:
                tts_engine.synthesize(translation, str(temp_tts))
            except Exception as e:
                print(f"  [WARN] 第 {i+1} 句 TTS 失败: {e}")
                continue

            # 2. 读取 TTS 音频
            tts_data, tts_sr = sf.read(str(temp_tts))
            if tts_sr != sample_rate:
                # 重采样
                import librosa
                tts_data = librosa.resample(tts_data, orig_sr=tts_sr, target_sr=sample_rate)
            tts_duration = len(tts_data) / sample_rate

            # 3. 处理时长差异
            if tts_duration > original_duration * tts_speed_range[1]:
                # TTS 太长，需要加速
                target_duration = original_duration * tts_speed_range[1]
                speed_factor = tts_duration / target_duration
                try:
                    import pytsmod
                    tts_data = pytsmod.time_stretch(
                        tts_data, sample_rate, target_rate=speed_factor
                    )
                    tts_duration = len(tts_data) / sample_rate
                    print(f"  [{i+1}] 加速 {speed_factor:.2f}x: {tts_duration:.1f}s → {target_duration:.1f}s")
                except ImportError:
                    print(f"  [WARN] 第 {i+1} 句 TTS 过长 ({tts_duration:.1f}s > {original_duration:.1f}s)，请安装 pytsmod")

            # 4. 放置到时间轴
            start_sample = int(start_sec * sample_rate)
            end_sample = start_sample + len(tts_data)

            # 边界保护
            if end_sample > total_samples:
                end_sample = total_samples
                tts_data = tts_data[:end_sample - start_sample]

            # 叠加（如与下一句重叠，淡出处理）
            if end_sample > total_samples:
                continue
            timeline[start_sample:end_sample] += tts_data.astype(np.float32)

            # 清理临时文件
            temp_tts.unlink(missing_ok=True)

        # 5. 归一化（防止溢出）
        max_val = np.max(np.abs(timeline))
        if max_val > 0.95:
            timeline = timeline * 0.95 / max_val

        # 6. 保存
        sf.write(str(output_path), timeline, sample_rate)

        # 清理临时目录
        try:
            temp_dir.rmdir()
        except:
            pass

        print(f"[Mixer] 时间轴拼装完成: {output_path.name}")
        return str(output_path)
```

### 4.2 修改：Pipeline 时间戳传递

**文件**: `src/core/pipeline/__init__.py`

关键改动：**在整个流程中保持时间戳信息不断裂**。

```python
def run(self, preset=None, progress_callback=None):
    # ...

    # ===== Step 2: ASR / VTT 时间戳 =====
    # 当前问题: asr_results 有 start/end，但 translations 只剩纯文本
    # 修复: 合并为 timestamped_segments，贯穿后续流程

    timestamped_segments = []  # [{start, end, text, translation}, ...]

    if has_vtt:
        # 使用 VTT 时间戳
        vtt_entries = load_vtt_with_timestamps(vtt_path)
        timestamped_segments = [
            {"start": e["start"], "end": e["end"], "text": e["text"]}
            for e in vtt_entries
        ]
    elif config.use_asr:
        # 使用 ASR 时间戳（已有 start/end）
        timestamped_segments = asr_results  # [{start, end, text}, ...]

    # ===== Step 3: 翻译（保留时间戳）=====
    if is_chinese_vtt:
        # VTT 已是中文
        for seg in timestamped_segments:
            seg["translation"] = seg["text"]
    elif has_vtt and vtt_lang in ("ja", "mixed"):
        # VTT 日文 → 翻译
        translator = Translator(provider=config.translate_provider, model=config.translate_model)
        texts = [s["text"] for s in timestamped_segments]
        translations = translator.translate_batch(texts, source_lang="日文", target_lang="中文")
        for seg, trans in zip(timestamped_segments, translations):
            seg["translation"] = trans
    elif config.use_translate and timestamped_segments:
        # ASR 结果 → 翻译
        translator = Translator(provider=config.translate_provider, model=config.translate_model)
        texts = [s["text"] for s in timestamped_segments]
        translations = translator.translate_batch(texts, source_lang=config.source_lang, target_lang=config.target_lang)
        for seg, trans in zip(timestamped_segments, translations):
            seg["translation"] = trans

    # ===== Step 4: 逐句 TTS + 时间轴拼装 =====
    tts_aligned_path = task_dir / "tts_aligned.wav"

    if config.use_tts and timestamped_segments:
        tts_engine = TTSEngine(
            engine=config.tts_engine,
            voice=config.tts_voice if config.tts_engine == "edge" else config.qwen3_voice,
            speed=config.tts_speed,
        )

        # 获取参考音频时长
        import soundfile as sf
        ref_info = sf.info(str(results["vocal_path"]))
        ref_duration = ref_info.duration

        mixer = Mixer(
            original_volume=config.original_volume,
            tts_volume_ratio=config.tts_volume_ratio,
            tts_delay_ms=config.tts_delay_ms,
        )
        mixer.build_aligned_tts(
            segments=timestamped_segments,
            tts_engine=tts_engine,
            output_path=str(tts_aligned_path),
            reference_duration=ref_duration,
        )

    # ===== Step 5: 混音 =====
    # 使用 tts_aligned.wav 替代原来的 tts_output.mp3
    mixer.mix(
        results["vocal_path"],
        str(tts_aligned_path),
        str(mix_path),
        adjust_tts_volume=True,
    )
```

### 4.3 修改：Mixer.mix() 适配

**文件**: `src/mixer/__init__.py`

现有 `mix()` 方法中的 `adelay` 可以保留作为微调手段，但由于时间轴已在 `build_aligned_tts()` 中对齐，`tts_delay_ms` 的作用变为**全局微调**（补偿 TTS 引擎固有延迟）。

建议默认值改为 `0`，GUI 上的范围缩小到 `[-500ms, 500ms]`。

### 4.4 优化：逐句 TTS 性能

逐句合成最大的问题是 **TTS 引擎调用次数多**（65 句 = 65 次调用）。

#### Edge-TTS 优化（异步并发）

```python
async def _synthesize_all_async(self, sentences: List[str], temp_files: List[Path]):
    """并发合成所有句子"""
    tasks = [
        self.synthesize_async(sent, str(tf))
        for sent, tf in zip(sentences, temp_files)
        if sent.strip()
    ]
    await asyncio.gather(*tasks)  # 65 句并发，约 3-5s 完成
```

EdgeTTSEngine 已有此方法（L84-91）。只需在 `build_aligned_tts()` 中利用即可。

**预估耗时**：65 句 Edge-TTS 并发 → ~5s（与当前整体合成几乎相同）

#### Qwen3-TTS 优化（顺序执行）

Qwen3-TTS 使用本地 GPU，无法并发。65 句顺序执行：
- 每句约 2-4s → 总计 130-260s（不可接受）

**解决方案**：Qwen3-TTS 仍然用整体合成，然后手动切割并时间拉伸对齐。

```python
if tts_engine.engine_type == "qwen3":
    # Qwen3: 整体合成 + 自动切割对齐
    full_text = "。".join(seg["translation"] for seg in segments)
    tts_engine.synthesize(full_text, str(temp_full_path))
    # 用 librosa 或 pydub 检测每句的边界，然后拉伸对齐
    aligned_clips = auto_align_tts(temp_full_path, segments)
else:
    # Edge-TTS: 逐句合成（并发）
    aligned_clips = per_sentence_tts(segments, tts_engine)
```

或者，更简单的做法：**Qwen3 也逐句合成，但限制并发为 1**，接受更长的处理时间。

---

## 五、关键技术细节

### 5.1 时间戳精度对比

| 来源 | 精度 | 获取方式 |
|------|------|---------|
| VTT 字幕 | ~10ms | 解析 VTT 文件（已有） |
| Whisper segment 级 | ~50-100ms | `seg.start`, `seg.end`（已有） |
| Whisper word 级 | ~20-50ms | `word_timestamps=True`（需启用） |

**建议**：
- 有 VTT → 直接用 VTT 时间戳（最精确）
- 无 VTT → Whisper segment 级即可（ASMR 语速慢，50-100ms 偏差不明显）

### 5.2 TTS 时长不匹配的处理

中文和日文的语速天然不同。示例：

| 日文原文 | 原音时长 | 中文翻译 | 预计 TTS 时长 | 差异 |
|---------|---------|---------|-------------|------|
| 主人、您露出了放松的表情呢 | 5.6s | 主人，您露出了放松的表情呢 | ~2.5s | TTS 短 3.1s |
| はい、少しだけ主人を癒せれば | 5.3s | 是的，哪怕能稍微治愈一下主人也好 | ~3.0s | TTS 短 2.3s |

**中文 TTS 通常比日文原音短 30-50%**，因为：
1. 中文字符信息密度高于日语假名
2. TTS 引擎（Edge-TTS）语速较快

这意味着大部分情况下不需要压缩 TTS，只需在正确时间点插入即可。

### 5.3 时间拉伸（TTS 过长时）

当 TTS 时长超过原音间隔时（少数情况），可用 `pytsmod` 进行时间拉伸：

```python
import pytsmod

# 将 TTS 从 4.0s 拉伸到 3.0s（加速 1.33x，但不变调）
stretched = pytsmod.time_stretch(audio, sr, target_rate=4.0/3.0)
```

**依赖**: `pip install pytsmod`（基于 phase vocoder，音质可接受）

**替代方案**: `librosa.effects.time_stretch()`（更简单但音质稍差）

### 5.4 淡入淡出处理

为避免 TTS 片段之间的突兀切换，建议添加短淡入淡出：

```python
def _apply_fade(audio, sample_rate, fade_in_ms=30, fade_out_ms=50):
    """应用淡入淡出"""
    fade_in_samples = int(fade_in_ms * sample_rate / 1000)
    fade_out_samples = int(fade_out_ms * sample_rate / 1000)

    # 淡入
    if fade_in_samples > 0 and len(audio) > fade_in_samples:
        audio[:fade_in_samples] *= np.linspace(0, 1, fade_in_samples)

    # 淡出
    if fade_out_samples > 0 and len(audio) > fade_out_samples:
        audio[-fade_out_samples:] *= np.linspace(1, 0, fade_out_samples)

    return audio
```

---

## 六、数据流对比

### 6.1 旧流程（时间轴断裂）

```
ASR → [{start, end, text}]     ← 有时间戳
  ↓ 提取 text
翻译 → [translation_1, ..., translation_n]   ← 时间戳丢失！
  ↓ join
TTS → "翻译1。翻译2。...翻译n"    ← 连续音频，无时间信息
  ↓ 整体叠加
混音 → 原音 + TTS → 完全不对齐
```

### 6.2 新流程（时间轴贯穿）

```
ASR/VTT → [{start, end, text}]     ← 有时间戳
  ↓ 逐句翻译，保留时间戳
翻译 → [{start, end, text, translation}]   ← 时间戳保留
  ↓ 逐句合成，按 start 放置
TTS → 与原音等长的时间轴音频        ← 时间戳对齐
  ↓ 整体叠加
混音 → 原音 + TTS_aligned → 精确对齐
```

---

## 七、实施优先级与文件清单

### 7.1 修改清单

| 文件 | 修改类型 | 说明 |
|------|----------|------|
| `src/mixer/__init__.py` | **新增方法** | `build_aligned_tts()` — 逐句 TTS + 时间轴拼装 |
| `src/mixer/__init__.py` | **新增函数** | `_apply_fade()` — 淡入淡出 |
| `src/core/pipeline/__init__.py` | **修改** | Step 2~5 改为传递 `timestamped_segments` |
| `src/core/asr/__init__.py` | **可选修改** | 启用 `word_timestamps=True` 提升精度 |
| `src/gui.py` | **修改** | `SingleWorkerThread` / `BatchWorkerThread` 适配新流程 |
| `scripts/asmr_bilingual.py` | **修改** | CLI 适配新流程 |
| `pyproject.toml` | **新增依赖** | `pytsmod`（时间拉伸，可选） |

### 7.2 实施步骤

| 步骤 | 内容 | 预估工作量 |
|------|------|-----------|
| 1 | 实现 `build_aligned_tts()` 核心方法 | 1-2h |
| 2 | 修改 Pipeline，保持时间戳传递 | 30min |
| 3 | Edge-TTS 逐句合成 + 并发优化 | 30min |
| 4 | GUI / CLI 适配 | 30min |
| 5 | 测试 + 微调（淡入淡出、时间拉伸参数） | 1h |

### 7.3 实施优先级

| 优先级 | 任务 | 收益 | 风险 |
|--------|------|------|------|
| **P0** | `build_aligned_tts()` + Pipeline 改造 | 解决时间轴对齐核心问题 | 低 |
| **P1** | Edge-TTS 逐句并发合成 | 65 句 ~5s 完成 | 低 |
| **P2** | pytsmod 时间拉伸（TTS 过长时） | 处理边缘情况 | 低 |
| **P2** | 淡入淡出处理 | 音质提升 | 低 |
| **P3** | Whisper word_timestamps 精度提升 | 无 VTT 时更精确 | 低 |

---

## 八、预期效果

修复前：
```
原音: |--24s静默--[日文第1句]--1s间隔--[日文第2句]--...
TTS:  |--[中文第1句]--[中文第2句]--...--|  (从0s开始连续播放)
效果: 完全不对齐，TTS和原音各说各的
```

修复后：
```
原音: |--24s静默--[日文第1句]--1s间隔--[日文第2句]--...
TTS:  |--24s静默--[中文第1句]--1s间隔--[中文第2句]--...
效果: 中文配音与日文原音精确同步，双语双轨效果达成
```
