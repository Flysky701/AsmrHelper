# Agent3 架构指导报告 #3 — VTT 智能流水线 & 多线程加速评估

**日期**: 2026-04-03 21:43
**状态**: 最终版
**受众**: Agent1（代码实现）

---

## 一、VTT 逻辑问题诊断

### 1.1 当前行为（BUG）

当检测到 VTT 字幕文件后，当前代码仍然执行**完整的 5 步流程**：

| 步骤 | 操作 | 有 VTT 时是否必要 | 当前行为 |
|------|------|-------------------|----------|
| Step 1 | 人声分离 (Demucs) | **需要** | ✅ 正常执行 |
| Step 2 | ASR 识别 (Whisper) | **不需要** | ❌ 仍在执行（浪费 23s + GPU 资源） |
| Step 3 | 翻译 | **不需要**（VTT 已有翻译文本） | 当前正确跳过，直接加载 VTT |
| Step 4 | TTS 合成 | **需要** | ✅ 正常执行 |
| Step 5 | 混音 | **需要** | ✅ 正常执行 |

**影响范围**：3 个代码入口全部存在此问题：
1. `src/gui.py` → `SingleWorkerThread.run()` (L71-135)
2. `src/gui.py` → `BatchWorkerThread.run()` (L201-269)
3. `scripts/asmr_bilingual.py` → `main()` (L90-155)

### 1.2 VTT 字幕内容语言判断

VTT 文件可能包含：
- **中文字幕**：已是翻译结果，直接用于 TTS
- **日文字幕**：原始台词，需翻译后再 TTS
- **双语字幕**：需提取中文部分

**判断策略**：

```python
def detect_vtt_language(translations: List[str]) -> str:
    """
    检测 VTT 字幕语言
    Returns: "zh" | "ja" | "mixed" | "unknown"
    """
    import re
    zh_chars = 0
    ja_chars = 0
    total_chars = 0
    
    for text in translations:
        if not text.strip():
            continue
        # 统计中文字符（不含日文汉字重叠区）
        zh_chars += len(re.findall(r'[\u4e00-\u9fff]', text))
        # 统计日文假名
        ja_chars += len(re.findall(r'[\u3040-\u309f\u30a0-\u30ff]', text))
        total_chars += len(text)
    
    if total_chars == 0:
        return "unknown"
    
    if ja_chars == 0 and zh_chars / total_chars > 0.3:
        return "zh"
    if zh_chars == 0 and ja_chars / total_chars > 0.3:
        return "ja"
    if ja_chars > 0 and zh_chars > 0:
        return "mixed"
    return "unknown"
```

### 1.3 修复后的智能流水线

根据输入条件自动选择流程：

```
输入: audio.wav + VTT字幕(中文)
→ Step 1: 人声分离
→ Step 2: ASR (跳过)
→ Step 3: 翻译 (跳过，VTT已是中文)
→ Step 4: TTS
→ Step 5: 混音
→ 实际: 3步，节省 ~23s + GPU 资源

输入: audio.wav + VTT字幕(日文)
→ Step 1: 人声分离
→ Step 2: ASR (跳过)
→ Step 3: 翻译 (用 VTT 日文文本 → DeepSeek 翻译为中文)
→ Step 4: TTS
→ Step 5: 混音
→ 实际: 4步，节省 ASR ~23s

输入: audio.wav (无 VTT)
→ Step 1: 人声分离
→ Step 2: ASR
→ Step 3: 翻译 (DeepSeek)
→ Step 4: TTS
→ Step 5: 混音
→ 实际: 5步（完整流程，不变）
```

---

## 二、Agent1 代码修改指导

### 2.1 新增：VTT 语言检测函数

**文件**: `src/core/translate/__init__.py`

在 `load_vtt_translations()` 函数后新增：

```python
import re

def detect_vtt_language(translations: List[str]) -> str:
    """
    检测 VTT 字幕的主语言
    
    Args:
        translations: VTT 解析出的文本列表
        
    Returns:
        "zh" | "ja" | "mixed" | "unknown"
    """
    zh_chars = 0
    ja_kana = 0  # 仅统计假名（排除汉字重叠区）
    total = 0
    
    for text in translations:
        if not text.strip():
            continue
        zh_chars += len(re.findall(r'[\u4e00-\u9fff]', text))
        ja_kana += len(re.findall(r'[\u3040-\u309f\u30a0-\u30ff]', text))
        total += len(text.strip())
    
    if total == 0:
        return "unknown"
    
    # 纯中文：没有假名且汉字占比 > 30%
    if ja_kana == 0 and zh_chars / total > 0.3:
        return "zh"
    # 纯日文：有假名但没有中文（汉字可能是日文汉字）
    if ja_kana > 0 and zh_chars == 0:
        return "ja"
    # 混合：两者都有
    if ja_kana > 0 and zh_chars > 0:
        return "mixed"
    
    return "unknown"
```

### 2.2 新增：VTT 带时间戳解析函数（为后续时间轴对齐 TTS 铺路）

**文件**: `src/core/translate/__init__.py`

```python
def load_vtt_with_timestamps(vtt_path: str) -> List[dict]:
    """
    从 VTT 文件加载翻译文本（带时间戳）
    
    Returns:
        List[dict]: [{start_sec, end_sec, text}, ...]
    """
    entries = []
    
    try:
        with open(vtt_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        lines = content.split("\n")
        i = 0
        
        # 跳过 WEBVTT 头
        while i < len(lines) and "WEBVTT" not in lines[i]:
            i += 1
        i += 1
        
        while i < len(lines):
            line = lines[i].strip()
            
            if not line or line.isdigit():
                i += 1
                continue
            
            if "-->" in line:
                # 解析时间戳
                parts = line.split("-->")
                start_str = parts[0].strip()
                end_str = parts[1].strip()
                start_sec = _parse_vtt_time(start_str)
                end_sec = _parse_vtt_time(end_str)
                
                # 收集文本行
                i += 1
                text_lines = []
                while i < len(lines) and lines[i].strip():
                    text_lines.append(lines[i].strip())
                    i += 1
                
                if text_lines:
                    entries.append({
                        "start": start_sec,
                        "end": end_sec,
                        "text": " ".join(text_lines),
                    })
                continue
            
            i += 1
        
        print(f"[VTT Loader] 加载了 {len(entries)} 条带时间戳翻译: {vtt_path}")
        
    except Exception as e:
        print(f"[VTT Loader] 解析失败: {e}")
    
    return entries


def _parse_vtt_time(time_str: str) -> float:
    """将 VTT 时间格式 '00:00:24.140' 转换为秒数"""
    parts = time_str.strip().replace(",", ".").split(":")
    if len(parts) == 3:
        h, m, s = parts
        return int(h) * 3600 + int(m) * 60 + float(s)
    elif len(parts) == 2:
        m, s = parts
        return int(m) * 60 + float(s)
    return 0.0
```

### 2.3 修改：SingleWorkerThread（GUI 单文件处理）

**文件**: `src/gui.py`

```python
# 在文件头部 import 区域添加
from src.core.translate import load_vtt_translations, detect_vtt_language

class SingleWorkerThread(QThread):
    """单个文件处理线程"""
    progress = Signal(str)
    finished = Signal(bool, str)

    def __init__(self, input_path: str, output_dir: str, params: dict, vtt_path: str = None):
        super().__init__()
        self.input_path = input_path
        self.output_dir = output_dir
        self.params = params
        self.vtt_path = vtt_path

    def _find_vtt_file(self) -> Optional[str]:
        """查找VTT字幕文件（保持不变）"""
        # ... 原有代码不变 ...

    def run(self):
        try:
            # ===== 预检测: VTT 字幕 =====
            vtt_file = self.vtt_path or self._find_vtt_file()
            vtt_translations = None
            vtt_lang = None
            step_count = 5
            current_step = 0
            
            if vtt_file and Path(vtt_file).exists():
                vtt_translations = load_vtt_translations(vtt_file)
                vtt_lang = detect_vtt_language(vtt_translations)
                self.progress.emit(f"[INFO] 检测到 VTT 字幕: {Path(vtt_file).name}")
                self.progress.emit(f"[INFO] 字幕语言: {vtt_lang}, 条数: {len(vtt_translations)}")
            
            # 确定实际需要的步骤数
            has_vtt = vtt_translations is not None
            is_chinese_vtt = vtt_lang == "zh"
            # 有VTT：跳过ASR=省1步；中文VTT：再跳过翻译=省2步
            step_count = 5 - (1 if has_vtt else 0) - (1 if is_chinese_vtt else 0)

            # ===== Step 1: 人声分离 (始终执行) =====
            current_step += 1
            self.progress.emit(f"[{current_step}/{step_count}] 人声分离 (Demucs)...")
            separator = VocalSeparator(model_name=self.params.get("vocal_model", "htdemucs"))
            results = separator.separate(self.input_path, self.output_dir, stems=["vocals"])
            vocal_path = Path(results.get("vocals", ""))

            # ===== Step 2: ASR (有 VTT 时跳过) =====
            if not has_vtt:
                current_step += 1
                self.progress.emit(f"[{current_step}/{step_count}] ASR 语音识别 (Whisper)...")
                recognizer = ASRRecognizer(
                    model_size=self.params.get("asr_model", "base"),
                    language="ja"
                )
                asr_path = Path(self.output_dir) / "asr_result.txt"
                asr_results = recognizer.recognize(str(vocal_path), str(asr_path))
                self.progress.emit(f"  -> 识别到 {len(asr_results)} 段")
            else:
                self.progress.emit(f"[跳过] ASR 识别 (使用 VTT 字幕)")
                asr_results = []

            # ===== Step 3: 翻译 (有中文VTT时跳过，日文VTT需翻译) =====
            trans_path = Path(self.output_dir) / "translated.txt"
            
            if is_chinese_vtt:
                # VTT 已是中文翻译，直接使用
                translations = vtt_translations
                trans_path.write_text("\n".join(translations), encoding="utf-8")
                self.progress.emit(f"[跳过] 翻译 (VTT 字幕已是中文，{len(translations)} 条)")
            elif has_vtt and vtt_lang in ("ja", "mixed"):
                # VTT 是日文/混合，需要翻译
                current_step += 1
                self.progress.emit(f"[{current_step}/{step_count}] 翻译 (VTT 日文 -> DeepSeek)...")
                translator = Translator(provider="deepseek")
                translations = translator.translate_batch(vtt_translations)
                trans_path.write_text("\n".join(translations), encoding="utf-8")
                self.progress.emit(f"  -> 翻译了 {len(translations)} 段")
            else:
                # 无 VTT，正常 ASR + 翻译
                current_step += 1
                self.progress.emit(f"[{current_step}/{step_count}] 翻译 (DeepSeek)...")
                translator = Translator(provider="deepseek")
                texts = [r["text"] for r in asr_results]
                translations = translator.translate_batch(texts)
                trans_path.write_text("\n".join(translations), encoding="utf-8")
                self.progress.emit(f"  -> 翻译了 {len(translations)} 段")

            # ===== Step 4: TTS 合成 (始终执行) =====
            current_step += 1
            self.progress.emit(f"[{current_step}/{step_count}] TTS 合成...")
            tts_engine = TTSEngine(
                engine=self.params.get("tts_engine", "edge"),
                voice=self.params.get("tts_voice", "zh-CN-XiaoxiaoNeural"),
                speed=self.params.get("tts_speed", 1.0),
            )
            full_text = "。".join(translations)
            tts_ext = "wav" if self.params.get("tts_engine") == "qwen3" else "mp3"
            tts_path = Path(self.output_dir) / f"tts_output.{tts_ext}"
            tts_engine.synthesize(full_text, str(tts_path))

            # ===== Step 5: 混音 (始终执行) =====
            current_step += 1
            self.progress.emit(f"[{current_step}/{step_count}] 混音...")
            mixer = Mixer(
                original_volume=self.params.get("original_volume", 0.85),
                tts_volume_ratio=self.params.get("tts_ratio", 0.5),
                tts_delay_ms=self.params.get("tts_delay", 0),
            )
            mix_path = Path(self.output_dir) / "final_mix.wav"
            mixer.mix(str(vocal_path), str(tts_path), str(mix_path))

            self.finished.emit(True, str(mix_path))

        except Exception as e:
            import traceback
            traceback.print_exc()
            self.finished.emit(False, str(e))
```

### 2.4 修改：BatchWorkerThread（GUI 批量处理）

与 SingleWorkerThread 完全相同的逻辑改造，修改 `BatchWorkerThread.run()` 中的内层循环。核心修改点：

```python
# 在 BatchWorkerThread.run() 的 for 循环内，每个文件处理时：

# 替换原有的 Step 2 和 Step 3 逻辑：
# Step 2: ASR — 检查是否有 VTT
vtt_file = self._find_vtt_file(Path(input_path))
has_vtt = False
is_chinese_vtt = False

if vtt_file and Path(vtt_file).exists():
    vtt_translations = load_vtt_translations(vtt_file)
    vtt_lang = detect_vtt_language(vtt_translations)
    has_vtt = True
    is_chinese_vtt = (vtt_lang == "zh")
    self.progress.emit(f"  -> VTT 字幕: {Path(vtt_file).name} (语言: {vtt_lang})")

if not has_vtt:
    # 正常执行 ASR
    recognizer = ASRRecognizer(...)
    asr_results = recognizer.recognize(...)
else:
    self.progress.emit(f"  -> 跳过 ASR (使用 VTT)")
    asr_results = []

# Step 3: 翻译
if is_chinese_vtt:
    translations = vtt_translations
    self.progress.emit(f"  -> 跳过翻译 (VTT 已是中文)")
elif has_vtt:
    # 翻译 VTT 日文
    translator = Translator(provider="deepseek")
    translations = translator.translate_batch(vtt_translations)
else:
    # 正常翻译
    translator = Translator(provider="deepseek")
    texts = [r["text"] for r in asr_results]
    translations = translator.translate_batch(texts)
```

### 2.5 修改：CLI 脚本

**文件**: `scripts/asmr_bilingual.py`

在 `main()` 函数中，将 Step 2 和 Step 3 替换为相同的条件判断逻辑。注意 CLI 已经有 VTT 查找代码（L108-133），只需在 Step 2/3 处加入跳过逻辑。

### 2.6 修改：Pipeline 类（可选，建议同步）

**文件**: `src/core/pipeline/__init__.py`

Pipeline 类目前没有 VTT 支持，建议增加 `vtt_path` 参数：

```python
@dataclass
class PipelineConfig:
    # ... 原有字段 ...
    vtt_path: str = ""  # 新增：VTT 字幕路径（为空则自动查找）

class Pipeline:
    def run(self, preset=None):
        # 在 Step 2 之前检测 VTT
        vtt_translations = None
        vtt_lang = None
        if self.config.vtt_path:
            vtt_translations = load_vtt_translations(self.config.vtt_path)
            vtt_lang = detect_vtt_language(vtt_translations)
        elif self.config.input_path:
            # 自动查找 VTT
            input_p = Path(self.config.input_path)
            # ... 查找逻辑（复用 _find_vtt_file） ...
        
        has_vtt = vtt_translations is not None
        is_chinese_vtt = (vtt_lang == "zh")
        
        # Step 2: 有 VTT 时跳过 ASR
        if not has_vtt and config.use_asr:
            # ... 正常 ASR ...
        else:
            print("[跳过] ASR 识别 (VTT 字幕已提供)")
        
        # Step 3: 根据语言决定是否翻译
        # ... 同上 ...
```

---

## 三、多线程/并行加速评估

### 3.1 当前瓶颈分析

基于实测数据（RTX 4070 Ti SUPER, 16GB VRAM）：

| 步骤 | 耗时 | 计算设备 | 是否可并行 |
|------|------|----------|-----------|
| Step 1: Demucs 人声分离 | ~17s | GPU (CUDA) | ❌ GPU 密集 |
| Step 2: Whisper ASR | ~23s | GPU (CUDA) | ❌ GPU 密集 |
| Step 3: DeepSeek 翻译 | ~28s | 网络 (API) | ✅ I/O 等待，可并行 |
| Step 4: TTS 合成 | ~3s (Edge) / ~10s (Qwen3) | 网络/CPU+GPU | ✅ I/O/计算混合 |
| Step 5: ffmpeg 混音 | ~0.4s | CPU | ❌ 极快，无需优化 |

**单文件处理总耗时**: ~71s（完整流程）

### 3.2 单文件内加速（流水线级并行）

#### 方案 A：Step 3（翻译）与 Step 4（TTS）并行 — 可行但收益有限

翻译（DeepSeek API）和 TTS（Edge-TTS/Qwen3）看似可以并行，但存在**数据依赖**：

- Step 4（TTS）需要 Step 3（翻译）的输出作为输入
- 因此这两个步骤**无法并行**

#### 方案 B：预加载模型 — 推荐，立即可做

当前每个步骤都重新实例化模型（Demucs、Whisper、Qwen3TTS），导致：
- Demucs 模型每次重新加载到 GPU
- Whisper 模型每次重新加载
- Qwen3TTS 已有单例优化 ✅

**优化方案**：在 WorkerThread 初始化时预加载所有模型：

```python
class SingleWorkerThread(QThread):
    def __init__(self, ...):
        # ...
        self._separator = None
        self._recognizer = None
        self._tts_engine = None
    
    def _ensure_models_loaded(self):
        """延迟加载所有模型（在 run() 中调用一次）"""
        if self._separator is None:
            self._separator = VocalSeparator(
                model_name=self.params.get("vocal_model", "htdemucs")
            )
        if self._recognizer is None:
            self._recognizer = ASRRecognizer(
                model_size=self.params.get("asr_model", "base"),
                language="ja"
            )
        if self._tts_engine is None:
            self._tts_engine = TTSEngine(
                engine=self.params.get("tts_engine", "edge"),
                voice=self.params.get("tts_voice", "zh-CN-XiaoxiaoNeural"),
                speed=self.params.get("tts_speed", 1.0),
            )
```

**预估收益**：减少重复模型加载，单文件节省约 3-5s。

#### 方案 C：VTT 智能跳过（本文档第一节） — 推荐，立即可做

有中文 VTT 时：跳过 ASR (23s) + 跳过翻译 (28s) = **节省 51s**
有日文 VTT 时：跳过 ASR (23s) = **节省 23s**

**这是目前收益最大的优化**。

### 3.3 批量文件间并行（文件级并行）

#### 现状

`BatchWorkerThread` 是串行处理：文件1 → 文件2 → 文件3 → ...

#### 方案 D：多文件并行处理 — 收益显著

使用 `concurrent.futures.ThreadPoolExecutor` 并行处理多个文件：

```
                    ┌─ File1: [Demucs→ASR→Translate→TTS→Mix]  ~71s
ThreadPool(2) ──────┤
                    └─ File2: [Demucs→ASR→Translate→TTS→Mix]  ~71s
                    
8 个文件串行: 8 × 71s = 568s (9.5min)
8 个文件并行(2): 4 × 71s = 284s (4.7min) — 快 2x
```

**关键约束**：

1. **GPU 显存限制**（RTX 4070 Ti SUPER, 16GB）：
   - Demucs htdemucs: ~1.5GB VRAM
   - Whisper large-v3: ~3GB VRAM
   - 同时运行 Demucs + Whisper: ~4.5GB（安全）
   - **推荐并行度: 2**（两个文件同时分别在不同步骤）
   - 保守并行度: 1（避免 OOM 风险）

2. **GPU 互斥访问**：
   - Demucs 和 Whisper 不能同时在 GPU 上运行（显存可能不够）
   - 但 Demucs 和 DeepSeek 翻译可以并行（翻译用网络）
   - Demucs 和 Edge-TTS 可以并行（TTS 用网络）

3. **文件 I/O**：
   - 大文件读写（50MB+ WAV）可能成为瓶颈
   - SSD: 基本无影响
   - HDD: 可能限制并行效果

#### Agent1 实现方案

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

class BatchWorkerThread(QThread):
    progress = Signal(str)
    file_progress = Signal(int, int, str)  # current, total, filename
    finished = Signal(list)
    
    def __init__(self, input_files, output_dir, params, max_workers=2):
        super().__init__()
        self.input_files = input_files
        self.output_dir = output_dir
        self.params = params
        self.max_workers = max_workers  # 新增
        self.results = []
        self._lock = threading.Lock()  # 保护 results 列表
    
    def _process_single_file(self, input_path: str) -> dict:
        """处理单个文件（线程安全）"""
        # ... 与 SingleWorkerThread.run() 相同逻辑 ...
        # 注意：每个线程需要独立的模型实例（或使用锁保护共享模型）
        pass
    
    def run(self):
        total = len(self.input_files)
        self.progress.emit(f"开始批量处理 {total} 个文件 (并行度: {self.max_workers})...")
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(self._process_single_file, f): f
                for f in self.input_files
            }
            
            completed = 0
            for future in as_completed(futures):
                input_path = futures[future]
                completed += 1
                
                try:
                    result = future.result()
                    with self._lock:
                        self.results.append(result)
                    self.file_progress.emit(completed, total, Path(input_path).name)
                except Exception as e:
                    with self._lock:
                        self.results.append({
                            "file": input_path, "status": "failed", "error": str(e)
                        })
                    self.file_progress.emit(completed, total, Path(input_path).name)
        
        self.finished.emit(self.results)
```

### 3.4 GPU 资源管理策略

由于 GPU 是最稀缺的资源，需要智能调度：

```
时间轴:
───────────────────────────────────────────────────────
File1: [Demucs(GPU)] → [ASR(GPU)] → [翻译(网络)] → [TTS] → [混音(CPU)]
File2:                [Demucs(GPU)] → [ASR(GPU)] → [翻译(网络)] → [TTS] → [混音(CPU)]
                         ↑ 错开 GPU 使用
```

**推荐实现**：使用信号量 (Semaphore) 控制 GPU 访问：

```python
import threading

class GPUManager:
    """GPU 资源管理器"""
    
    def __init__(self, max_concurrent=1):
        self._semaphore = threading.Semaphore(max_concurrent)
    
    def __enter__(self):
        self._semaphore.acquire()
        return self
    
    def __exit__(self, *args):
        self._semaphore.release()

# 全局实例
gpu_lock = GPUManager(max_concurrent=1)

# 在 _process_single_file 中使用:
with gpu_lock:
    # Step 1: Demucs (GPU)
    separator.separate(...)
    
with gpu_lock:
    # Step 2: ASR (GPU)
    recognizer.recognize(...)

# Step 3: 翻译 (网络，不需要 GPU 锁)
# Step 4: TTS (网络/本地，可能需要 GPU 锁 for Qwen3)
if self.params.get("tts_engine") == "qwen3":
    with gpu_lock:
        tts_engine.synthesize(...)
else:
    tts_engine.synthesize(...)  # Edge-TTS 不需要 GPU
```

### 3.5 并行加速收益预估

| 场景 | 文件数 | 串行耗时 | 并行(2)耗时 | 加速比 |
|------|--------|---------|------------|--------|
| 完整流程 | 8 | ~9.5min | ~4.7min | 2.0x |
| 完整流程 | 20 | ~23.7min | ~11.8min | 2.0x |
| 有中文VTT | 8 | ~3.0min | ~1.5min | 2.0x |
| 有中文VTT | 20 | ~7.5min | ~3.8min | 2.0x |
| 有日文VTT | 8 | ~4.0min | ~2.0min | 2.0x |

---

## 四、实施优先级

| 优先级 | 任务 | 收益 | 工作量 | 风险 |
|--------|------|------|--------|------|
| **P0** | VTT 智能跳过（跳过 ASR + 条件跳过翻译） | 节省 23-51s/文件 | 小 | 低 |
| **P1** | 多文件并行处理 (ThreadPoolExecutor) | 批量处理 2x 加速 | 中 | 中 (OOM 风险) |
| **P2** | GPU 资源管理器 (Semaphore) | 防止 OOM | 小 | 低 |
| **P2** | 模型预加载/复用 | 节省 3-5s/文件 | 小 | 低 |
| **P3** | VTT 带时间戳解析 | 为时间轴对齐 TTS 铺路 | 小 | 无 |

### 建议实施顺序

1. **先做 P0**（VTT 智能跳过）— 改动最小，收益最大
2. **再做 P2**（GPU 管理器）— 为并行铺路
3. **然后做 P1**（多文件并行）— 需要在 GPU 管理器基础上
4. **最后做 P2+P3**（模型复用 + VTT 时间戳）— 锦上添花

---

## 五、GUI 适配说明

进度条需要适配动态步骤数：

```python
# 原有硬编码:
if "[1/5]" in msg: self.progress_bar.setValue(20)
elif "[2/5]" in msg: self.progress_bar.setValue(40)
# ...

# 改为动态解析:
import re
match = re.search(r'\[(\d+)/(\d+)\]', msg)
if match:
    current = int(match.group(1))
    total = int(match.group(2))
    self.progress_bar.setMaximum(total)
    self.progress_bar.setValue(current)
```

---

## 六、完整修改清单

| 文件 | 修改类型 | 说明 |
|------|----------|------|
| `src/core/translate/__init__.py` | 新增 | `detect_vtt_language()` 函数 |
| `src/core/translate/__init__.py` | 新增 | `load_vtt_with_timestamps()` + `_parse_vtt_time()` |
| `src/gui.py` → `SingleWorkerThread` | 修改 | VTT 智能跳过逻辑 |
| `src/gui.py` → `BatchWorkerThread` | 修改 | VTT 智能跳过 + 并行处理 |
| `src/gui.py` → `MainWindow.on_single_progress()` | 修改 | 动态进度条解析 |
| `src/gui.py` → `MainWindow.create_batch_tab()` | 修改 | 新增"并行度"控件 (QSpinBox, 1-4) |
| `scripts/asmr_bilingual.py` | 修改 | VTT 智能跳过逻辑 |
| `src/core/pipeline/__init__.py` | 修改 | 增加 `vtt_path` 配置项 |
| `src/core/gpu_manager.py` | **新建** | GPU 资源管理器 (Semaphore) |
