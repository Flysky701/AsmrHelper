# Agent1 TTS 时间轴对齐实现审核报告

**日期**: 2026-04-03 23:00  
**审核者**: Agent2  
**审核对象**: Agent1 根据 report_4_timestamp_alignment.md 完成的 TTS 时间轴对齐功能  

---

## 一、实现概览

### 1.1 核心功能实现状态

| 功能 | 状态 | 实现文件 | 备注 |
|------|------|----------|------|
| `build_aligned_tts()` 逐句合成 | ✅ 100% | `src/mixer/__init__.py` L218-362 | 核心方法完整实现 |
| `_apply_fade()` 淡入淡出 | ✅ 100% | `src/mixer/__init__.py` L19-44 | 独立函数，参数可调 |
| Pipeline 时间戳传递 | ✅ 100% | `src/core/pipeline/__init__.py` L210-343 | `timestamped_segments` 贯穿全程 |
| VTT 带时间戳解析 | ✅ 100% | `src/core/translate/__init__.py` L357-417 | `load_vtt_with_timestamps()` |
| VTT 语言检测 | ✅ 100% | `src/core/translate/__init__.py` L310-354 | `detect_vtt_language()` |
| pytsmod 时间拉伸 | ⚠️ 50% | `src/mixer/__init__.py` L307-321 | 有实现但为可选依赖 |
| Edge-TTS 并发优化 | ❌ 0% | - | 未实现（当前逐句顺序执行） |

### 1.2 架构遵循度

Agent1 完全遵循了 Agent3 报告中的架构设计：

```
报告设计: ASR/VTT → [{start, end, text}] → 翻译保留时间戳 → 逐句TTS → 时间轴拼装
实际实现: 完全一致 ✅
```

---

## 二、详细代码审查

### 2.1 `build_aligned_tts()` - 核心方法

**位置**: `src/mixer/__init__.py` L218-362

**实现亮点**:
1. **时间轴创建**: L257-258 创建与原音等长的静音时间轴
2. **逐句合成**: L267-344 循环处理每句翻译
3. **时长处理**: L303-321 支持 pytsmod 时间拉伸（TTS 过长时）
4. **淡入淡出**: L324 调用 `_apply_fade()`
5. **边界保护**: L331-335 防止超出时间轴
6. **归一化**: L347-350 防止音频溢出

**潜在问题**:

```python
# L292-298: 重采样实现不完整
if tts_sr != sample_rate:
    try:
        import librosa
        tts_data = librosa.resample(tts_data, orig_sr=tts_sr, target_sr=sample_rate)
    except ImportError:
        # 没有 librosa，使用 soundfile 重采样
        pass  # ⚠️ 实际未实现 fallback
```

**建议**: 添加 soundfile 重采样 fallback 或强制要求 librosa。

### 2.2 Pipeline 时间戳传递

**位置**: `src/core/pipeline/__init__.py` L207-343

**数据流验证**:

```python
# Step 2: 时间戳获取 (L207-260)
timestamped_segments = []  # [{start, end, text}, ...]
# - VTT: load_vtt_with_timestamps() → 保留时间戳 ✅
# - ASR: asr_results.copy() → 已有时间戳 ✅

# Step 3: 翻译 (L262-343)
# - 中文 VTT: 直接复制 text 到 translation ✅
# - 日文 VTT: 翻译后 zip 合并 ✅
# - ASR: 翻译后 zip 合并 ✅
# 所有分支都: seg["translation"] = trans ✅

# Step 4: TTS (L346-393)
# mixer.build_aligned_tts(segments=timestamped_segments, ...) ✅
```

**状态**: 时间戳在全程中未断裂，符合设计要求。

### 2.3 VTT 智能跳过

**位置**: `src/core/pipeline/__init__.py` L130-142, L207-219, L266-308

**实现逻辑**:

```python
# L130-142: VTT 预检测
if vtt_path and Path(vtt_path).exists():
    vtt_translations = load_vtt_translations(vtt_path)
    if vtt_translations:
        vtt_lang = detect_vtt_language(vtt_translations)  # ✅ 语言检测
        has_vtt = True
        is_chinese_vtt = vtt_lang == "zh"

# L207-219: 中文/日文 VTT 跳过 ASR
if has_vtt:
    _report(f"... [跳过] ASR (使用 VTT 字幕时间戳)")  # ✅ 跳过 ASR
    vtt_entries = load_vtt_with_timestamps(vtt_path)
    timestamped_segments = [...]

# L266-283: 中文 VTT 跳过翻译
if is_chinese_vtt:
    translations = vtt_translations
    _report(f"... [跳过] 翻译 (VTT 字幕已是中文)")  # ✅ 跳过翻译
```

**流程对比**:

| 场景 | 步骤 | 节省时间 |
|------|------|----------|
| 中文 VTT | 分离 → [跳过ASR] → [跳过翻译] → TTS → 混音 = 3步 | ~51s |
| 日文 VTT | 分离 → [跳过ASR] → 翻译 → TTS → 混音 = 4步 | ~23s |
| 无 VTT | 分离 → ASR → 翻译 → TTS → 混音 = 5步 | - |

**状态**: 完全实现 Agent3 报告中的智能跳过逻辑。

### 2.4 GPU 资源管理器

**位置**: `src/core/gpu_manager.py`

**实现验证**:

```python
# GPU 锁已在 BatchWorkerThread 中使用 (gui.py L228-229)
gpu_lock = get_gpu_lock(max_concurrent=1)
with gpu_lock:
    pipeline.run(...)
```

**状态**: 已实现并集成到批量处理流程。

### 2.5 Qwen3-TTS 单例化

**位置**: `src/core/tts/__init__.py` L180-264

**实现验证**:

```python
class Qwen3TTSEngine:
    _model_instance = None  # 类级别单例 ✅
    
    @classmethod
    def _get_model(cls):
        if cls._model_instance is None:
            from qwen_tts import Qwen3TTS
            cls._model_instance = Qwen3TTS()  # 仅加载一次 ✅
        return cls._model_instance
```

**状态**: 正确实现，避免重复加载 8.4GB 模型。

---

## 三、Bug 检查

### 3.1 已发现的问题

| 级别 | 问题 | 位置 | 影响 | 修复建议 |
|------|------|------|------|----------|
| P2 | librosa 缺失时无 fallback | mixer L292-298 | 采样率不匹配时可能出错 | 添加 soundfile 重采样或强制依赖 |
| P3 | 临时文件清理不完整 | mixer L356-359 | 残留空目录 | 使用 shutil.rmtree |
| P3 | 并发优化未实现 | - | Edge-TTS 65句顺序执行较慢 | 使用 `_synthesize_all_async` |

### 3.2 代码风格问题

1. **重复导入**: `mixer/__init__.py` L16 和 L250-251 都导入了 `get_ffmpeg` 和 `subprocess`
2. **类型注解**: `build_aligned_tts` 参数 `segments: list` 可改为 `List[Dict[str, Any]]`

### 3.3 边界情况测试

需要测试的场景：
- [ ] TTS 时长 > 原音间隔 * 1.2（触发时间拉伸）
- [ ] 单句翻译为空字符串
- [ ] VTT 时间戳超出音频时长
- [ ] 采样率不匹配（22050 vs 44100）

---

## 四、性能评估

### 4.1 当前性能（预估）

假设 65 句、每句平均 3 秒 TTS：

| 引擎 | 合成方式 | 预估耗时 | 瓶颈 |
|------|----------|----------|------|
| Edge-TTS | 逐句顺序 | ~195s | 网络请求串行 |
| Edge-TTS | 逐句并发（未实现） | ~5s | 网络并发限制 |
| Qwen3-TTS | 逐句顺序 | ~260s | GPU 推理串行 |
| Qwen3-TTS | 整体合成+切割（建议） | ~30s | 单次模型推理 |

### 4.2 优化建议

**Edge-TTS 并发优化**（高优先级）:

```python
# 利用 EdgeTTSEngine 已有的 _synthesize_all_async 方法
# 修改 build_aligned_tts 支持并发模式

async def build_aligned_tts_async(...):
    # 1. 并发合成所有句子
    temp_files = [...]
    await tts_engine._synthesize_all_async(translations, temp_files)
    
    # 2. 按时间戳拼装（无需等待）
    for i, seg in enumerate(segments):
        tts_data, _ = sf.read(str(temp_files[i]))
        # ... 放置到时间轴
```

---

## 五、总体评价

### 5.1 实现质量: A-

| 维度 | 评分 | 说明 |
|------|------|------|
| 功能完整性 | 95% | 核心功能全部实现，仅并发优化缺失 |
| 架构遵循度 | 100% | 完全遵循 Agent3 报告设计 |
| 代码质量 | 85% | 结构清晰，有少量重复导入和边界情况 |
| 文档注释 | 90% | 函数文档完整，关键逻辑有注释 |

### 5.2 与 Agent3 报告对比

| 报告要求 | 实现状态 | 偏差说明 |
|----------|----------|----------|
| `build_aligned_tts()` | ✅ 完全实现 | 无偏差 |
| `_apply_fade()` | ✅ 完全实现 | 无偏差 |
| Pipeline 时间戳传递 | ✅ 完全实现 | 无偏差 |
| Edge-TTS 并发优化 | ❌ 未实现 | 当前逐句顺序执行 |
| pytsmod 时间拉伸 | ⚠️ 部分实现 | 作为可选依赖，有 fallback |
| Qwen3 整体合成+切割 | ❌ 未实现 | 当前逐句执行（慢） |

### 5.3 推荐后续工作

1. **P1 - Edge-TTS 并发优化**: 利用已有 `_synthesize_all_async` 实现 65 句并发
2. **P2 - Qwen3 优化**: 整体合成 + 自动切割对齐（避免 260s 逐句执行）
3. **P2 - 重采样 fallback**: 完善采样率不匹配时的处理
4. **P3 - 测试覆盖**: 添加边界情况单元测试

---

## 六、文件清单

### 修改的文件

| 文件 | 修改类型 | 行数变化 |
|------|----------|----------|
| `src/mixer/__init__.py` | 新增方法 | +217 行 |
| `src/core/pipeline/__init__.py` | 重构 | ~200 行修改 |
| `src/core/translate/__init__.py` | 新增函数 | +125 行 |
| `src/core/gpu_manager.py` | 新增文件 | +67 行 |
| `src/gui.py` | 修改 | ~50 行修改 |

---

## 七、结论

Agent1 高质量完成了 TTS 时间轴对齐功能的核心实现：

1. **架构正确**: 时间戳贯穿整个流程，无断裂
2. **功能完整**: 支持 VTT 智能跳过、时间轴拼装、淡入淡出、时间拉伸
3. **代码质量**: 结构清晰，边界保护到位

**主要不足**:
- Edge-TTS 并发优化未实施（影响性能）
- Qwen3-TTS 逐句执行较慢（建议改为整体合成+切割）

**建议**: 优先实施 Edge-TTS 并发优化，可将 65 句 TTS 从 ~195s 降至 ~5s。
