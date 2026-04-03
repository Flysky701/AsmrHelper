# Report #6: ASMR Helper 项目健壮性与解耦架构设计

> 生成时间: 2026-04-04  
> 分析范围: 全部 28 个 Python 源文件 (~5000 行)  
> 发现问题: 8 类 65+ 个

---

## 一、问题总览

| 风险等级 | 类别 | 问题数 | 典型示例 |
|---------|------|--------|---------|
| 🔴 Critical | 线程安全 | 3 | VoiceProfileManager 无锁保护 |
| 🔴 Critical | 资源泄漏 | 3 | 临时文件异常中断残留 |
| 🔴 High | 上帝类/SRP | 2 | gui.py 1430行、Pipeline 与所有模块紧耦合 |
| 🟡 Medium | 代码重复 | 5 | VTT查找×3, 文件名安全化×5 |
| 🟡 Medium | 错误处理缺失 | 5+ | 翻译失败静默返回空字符串 |
| 🟡 Medium | 硬编码配置 | 6+ | ASR参数、Mixer参数、VTT目录 |
| 🟢 Low | 测试覆盖 | ~30% | Config/GPUManager/VoiceProfile 无测试 |
| 🟢 Low | 开闭原则违反 | 1 | TTS引擎新增需修改TTSEngine类 |

---

## 二、线程安全问题

### 2.1 🔴 VoiceProfileManager 无线程保护

**位置**: `src/core/tts/voice_profile.py:41-61`

```python
class VoiceProfileManager:
    _instance = None  # ❌ 无锁

    def __init__(self):
        self._profiles: Dict[str, VoiceProfile] = {}
        self._load()  # ❌ 无锁

    def get_by_id(self, profile_id):  # ❌ 无锁
        return self._profiles.get(profile_id)

    def save(self):  # ❌ 无锁
        ...
```

**风险**: GUI 线程 + BatchWorkerThread 同时读写时可能数据损坏

**修复方案**:
```python
import threading

class VoiceProfileManager:
    _instance = None
    _instance_lock = threading.Lock()

    def __init__(self):
        self._profiles_lock = threading.RLock()
        self._profiles = {}
        self._load()

    def get_by_id(self, profile_id):
        with self._profiles_lock:
            return self._profiles.get(profile_id)

    def save(self):
        with self._profiles_lock:
            # 保存逻辑
            ...
```

### 2.2 🔴 GPUManager 双重检查锁定不完善

**位置**: `src/core/gpu_manager.py:40-58`

**问题**: `_initialized` 在 Python 中不是 volatile，多线程可能看到不一致的值

**修复**: 使用 `threading.Lock` 保护所有 `__init__` 调用，或改用模块级初始化函数

### 2.3 🟡 BatchWorkerThread 部分操作未加锁

**位置**: `src/gui.py:155, 236, 277`

**问题**: `self.results` 列表有 `_results_lock`，但 `pipeline.results` 读取时未使用锁

**修复**: 统一使用 `with self._results_lock` 包裹所有 results 操作

---

## 三、资源管理问题

### 3.1 🔴 临时文件异常中断残留

**位置**: `src/mixer/__init__.py:258-365`

```python
temp_dir = output_path.parent / "tts_temp"
temp_dir.mkdir(exist_ok=True)

# ... 逐句处理（任何异常都可能中断）...

# 清理在最后
import shutil
shutil.rmtree(temp_dir, ignore_errors=True)  # ✅ 有清理，但异常时可能不执行
```

**修复**: 使用 `try/finally` 或 `tempfile.TemporaryDirectory()`:
```python
import tempfile

with tempfile.TemporaryDirectory(dir=output_path.parent) as temp_dir:
    for i, seg in enumerate(segments):
        temp_tts = Path(temp_dir) / f"tts_{i:04d}.wav"
        tts_engine.synthesize(translation, str(temp_tts))
        ...
    # 退出 with 时自动清理
```

### 3.2 🔴 VocalSeparator / ASRRecognizer 无 unload 方法

**位置**: `src/core/vocal_separator/__init__.py`, `src/core/asr/__init__.py`

**问题**: 模型加载后无卸载接口，Pipeline 中只能 `del separator + empty_cache()`，不优雅且可能遗漏

**修复**: 添加 `unload()` 方法:
```python
class VocalSeparator:
    def unload(self):
        """卸载模型释放显存"""
        if hasattr(self, 'model') and self.model is not None:
            del self.model
            self.model = None
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
```

### 3.3 🟡 subprocess 无超时

**位置**: `src/mixer/__init__.py:146, 186, 300`

```python
subprocess.run(cmd, capture_output=True, ...)  # ❌ 无 timeout
```

**风险**: ffmpeg 卡死时进程永久挂起

**修复**: 添加 `timeout=300`

---

## 四、上帝类与 SRP 违规

### 4.1 🔴 gui.py (1430 行) — 职责过载

**当前职责**: UI构建 + 文件选择 + 音色管理 + 参数解析 + 任务调度 + 进度显示 + 配置管理

**解耦方案**: 引入 Service 层

```python
# 新建 src/services.py
class AppService:
    """业务逻辑服务层"""

    def __init__(self):
        self.config = Config()
        self.voice_manager = get_voice_manager()

    def process_single(self, input_path, output_dir, params, vtt_path=None):
        """单文件处理"""
        cfg = PipelineConfig(...)
        pipeline = Pipeline(cfg)
        return pipeline.run(progress_callback=...)

    def process_batch(self, files, output_dir, params, max_workers=1):
        """批量处理"""
        ...

    def get_voice_options(self, engine_type):
        """获取音色选项列表"""
        ...

    def preview_voice(self, engine, voice, profile_id, speed, text):
        """试音"""
        ...

# gui.py 简化为纯 UI
class MainWindow(QMainWindow):
    def __init__(self):
        self.service = AppService()
        self.setup_ui()

    def start_single(self):
        params = self._collect_single_params()  # 仅收集 UI 参数
        self.service.process_single(...)
```

### 4.2 🔴 Pipeline — 与所有模块紧耦合

**位置**: `src/core/pipeline/__init__.py:17-22`

```python
from ..vocal_separator import VocalSeparator  # 直接导入
from ..asr import ASRRecognizer
from ..translate import Translator
from ..tts import TTSEngine
from src.mixer import Mixer
```

**解耦方案**: 使用依赖注入

```python
class Pipeline:
    def __init__(self, config, separator=None, recognizer=None, 
                 translator=None, tts_engine=None, mixer=None):
        self.separator = separator or VocalSeparator(...)
        self.recognizer = recognizer or ASRRecognizer(...)
        ...

    @classmethod
    def create_from_config(cls, config):
        """工厂方法，从配置创建（保持向后兼容）"""
        return cls(config=config)
```

---

## 五、代码重复

### 5.1 VTT 文件查找逻辑 ×3

| 位置 | 行数 | 文件 |
|------|------|------|
| `SingleWorkerThread._find_vtt_file()` | 25 行 | gui.py:44-68 |
| `BatchWorkerThread._find_vtt_file()` | 18 行 | gui.py:158-175 |
| `main()` 内联 VTT 搜索 | 24 行 | gui.py:1162-1180 |

**修复**: 提取到 `src/utils.py`:
```python
def find_vtt_file(input_path: Path, extra_dirs=None) -> Optional[Path]:
    """查找匹配的 VTT 字幕文件"""
    possible_names = [f"{input_path.name}.vtt", f"{input_path.stem}.vtt"]
    search_dirs = [input_path.parent, input_path.parent / "ASMR_O"]
    if extra_dirs:
        search_dirs.extend(extra_dirs)
    ...
```

### 5.2 文件名安全化 ×5

```python
# 出现在 gui.py:192, 439, 943, 1154; scripts/asmr_bilingual.py:64; scripts/batch_process.py:81,84
safe_name = "".join(c if c.isalnum() or c in " _-()" else "_" for c in input_path.stem)
```

**修复**: 提取到 `src/utils.py`:
```python
def sanitize_filename(name: str) -> str:
    return "".join(c if c.isalnum() or c in " _-()" else "_" for c in name)
```

### 5.3 模型映射字典 ×2

`get_single_params()` 和 `get_batch_params()` 中重复定义 `model_map` 和 `asr_map`

**修复**: 提取为类常量或模块级常量

### 5.4 统计汇总

| 代码模式 | 重复次数 | 可节省行数 |
|---------|---------|-----------|
| VTT 文件查找 | 3 | 48 |
| 文件名安全化 | 5 | 8 |
| 模型映射字典 | 2 | 15 |
| 批量处理循环 | 2 | 60 |
| GPU 锁获取 | 4 | 8 |
| **合计** | **16** | **139** |

---

## 六、错误处理缺失

### 6.1 🔴 翻译失败静默返回空字符串

**位置**: `src/core/translate/__init__.py:181-183`

```python
except Exception as e:
    print(f"  翻译失败 [{i+1}]: {e}")
    results.append("")  # ❌ 用户不知道翻译失败了
```

**影响**: 空字符串进入 TTS → 产出无声片段 → 用户困惑

**修复**:
```python
except Exception as e:
    print(f"  翻译失败 [{i+1}]: {e}")
    results.append(text)  # 降级：保留原文
    # 或者记录失败索引供后续处理
```

### 6.2 🔴 Pipeline 无统一异常处理

**位置**: `src/core/pipeline/__init__.py:174-427`

**问题**: 任何步骤失败都直接崩溃，无法部分恢复

**修复**: 每步用 try-except 包装，记录到 results:
```python
try:
    separator = VocalSeparator(...)
    sep_results = separator.separate(...)
except Exception as e:
    results["steps"]["vocal_separator"] = {"error": str(e)}
    results["vocal_path"] = str(input_path)  # 降级：使用原音
    _report(f"[WARN] 人声分离失败，使用原音: {e}")
```

### 6.3 🟡 自定义异常类缺失

**修复**: 新建 `src/exceptions.py`:
```python
class ASMRHelperError(Exception):
    """基础异常"""
    pass

class ModelLoadError(ASMRHelperError):
    """模型加载失败"""
    pass

class ASRError(ASMRHelperError):
    """ASR 识别失败"""
    pass

class TranslationError(ASMRHelperError):
    """翻译失败（含原文和索引）"""
    def __init__(self, message, original_text="", index=-1):
        super().__init__(message)
        self.original_text = original_text
        self.index = index

class TTSError(ASMRHelperError):
    """TTS 合成失败"""
    pass

class MixerError(ASMRHelperError):
    """混音失败"""
    pass
```

---

## 七、硬编码配置

### 7.1 应移至 config.json 的值

| 硬编码值 | 位置 | 建议配置键 |
|---------|------|-----------|
| `initial_prompt="これはASMR音声です..."` | asr/__init__.py:118 | `processing.asr_initial_prompt` |
| `beam_size=5, temperature=[0.0,...,1.0]` | asr/__init__.py:114-116 | `processing.asr_beam_size` 等 |
| `vad_parameters={min_silence:500}` | asr/__init__.py:109-112 | `processing.asr_vad_min_silence` |
| `sample_rate=44100` | mixer/__init__.py:222 | `processing.output_sample_rate` |
| `fade_in_ms=30, fade_out_ms=50` | mixer/__init__.py:223-224 | `processing.fade_in_ms, fade_out_ms` |
| `tts_speed_range=(0.8, 1.2)` | mixer/__init__.py:223 | `processing.tts_speed_range` |
| `ASMR_O` 目录名 | gui.py:57, batch_process.py:116 | `paths.vtt_search_subdir` |
| `speed = max(0.5, min(2.0, ...))` | tts/__init__.py:224 | `tts.speed_range` |

---

## 八、TTS 引擎工厂重构（开闭原则）

### 8.1 当前问题

`TTSEngine.__init__` 使用 if-elif 分发，新增引擎需修改此类:
```python
if engine == "edge":
    self.engine = EdgeTTSEngine(...)
elif engine == "qwen3":
    self.engine = Qwen3TTSEngine(...)
elif engine == "gptsovits":
    from .gptsovits import GPTSoVITSEngine
    self.engine = GPTSoVITSEngine(...)
else:
    raise ValueError(...)  # ❌ 每加一个引擎都要改这里
```

### 8.2 修复: 注册式工厂

```python
class TTSEngine:
    _registry = {}

    @classmethod
    def register(cls, name: str, engine_class):
        """注册新 TTS 引擎（开闭原则）"""
        cls._registry[name] = engine_class

    @classmethod
    def available_engines(cls):
        return list(cls._registry.keys())

    def __init__(self, engine="edge", **kwargs):
        if engine not in self._registry:
            raise ValueError(f"未知引擎: {engine}，可用: {list(self._registry.keys())}")
        self.engine_type = engine
        self.engine = self._registry[engine](**kwargs)

    def synthesize(self, text, output_path):
        return self.engine.synthesize(text, output_path)

# 注册内置引擎
TTSEngine.register("edge", EdgeTTSEngine)
TTSEngine.register("qwen3", Qwen3TTSEngine)
TTSEngine.register("gptsovits", GPTSoVITSEngine)

# 扩展新引擎（无需修改 TTSEngine）
# TTSEngine.register("cosyvoice", CosyVoiceEngine)
```

---

## 九、测试覆盖提升方案

### 9.1 当前覆盖情况

| 模块 | 覆盖 | 缺失测试 |
|------|------|---------|
| Config | ❌ | 单例、热更新、验证 |
| GPUManager | ❌ | 并发争用、信号量 |
| VoiceProfileManager | ❌ | CRUD、持久化、并发 |
| VocalSeparator | ⚠️ | 仅初始化 |
| ASRRecognizer | ⚠️ | 仅初始化 |
| Translator | ⚠️ | 初始化 + 翻译 |
| TTSEngine | ⚠️ | 仅初始化 |
| Mixer | ✅ | 初始化 + detect_volume |
| Pipeline | ⚠️ | 配置 + 预设 |

### 9.2 优先补充测试

**P0 — 关键路径**:
```python
# tests/test_exceptions.py
def test_translation_fallback():
    """翻译失败时降级返回原文"""

# tests/test_gpu_manager.py
def test_concurrent_access():
    """多线程并发 GPU 锁"""
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(acquire_and_hold, gpu_lock) for _ in range(3)]
        # 验证同一时刻只有 1 个持有锁

# tests/test_voice_profile.py
def test_concurrent_read_write():
    """多线程同时读写音色配置"""

# tests/test_utils.py
def test_find_vtt_file():
def test_sanitize_filename():
```

---

## 十、重构路线图

### Phase 1 — 紧急修复（1-2 天）

| 任务 | 文件 | 影响 |
|------|------|------|
| VoiceProfileManager 加锁 | voice_profile.py | 消除并发数据损坏 |
| 新建 `src/exceptions.py` | exceptions.py | 统一错误处理 |
| 提取 utils 函数 | utils/__init__.py | 消除 5 处代码重复 |
| 翻译失败降级 | translate/__init__.py | 避免无声片段 |
| Pipeline 步骤级 try-except | pipeline/__init__.py | 单步失败不崩溃 |

### Phase 2 — 架构优化（3-5 天）

| 任务 | 文件 | 影响 |
|------|------|------|
| 新建 `src/services.py` AppService | services.py | 解耦 GUI 业务逻辑 |
| gui.py 调用 AppService | gui.py | gui.py 从 1430→~800 行 |
| Pipeline 依赖注入 | pipeline/__init__.py | 松耦合 |
| TTS 引擎工厂注册 | tts/__init__.py | 开闭原则 |
| 硬编码值迁移到 config | config.py, config.json | 可配置化 |
| 新建 `scripts/generate_voice_profiles.py` 临时文件保护 | generate_voice_profiles.py | 防止残留 |

### Phase 3 — 质量保障（3-5 天）

| 任务 | 影响 |
|------|------|
| VocalSeparator/ASR 添加 unload() | 资源管理规范 |
| subprocess 统一 timeout | 防止进程挂起 |
| 补充测试覆盖到 70%+ | 回归安全 |
| Config 添加 validate() | 配置错误前置发现 |

---

## 十一、文件修改清单

```
新建:
  src/exceptions.py              # 自定义异常类
  src/services.py                # AppService 业务逻辑层

修改:
  src/core/tts/voice_profile.py  # 添加线程锁
  src/core/gpu_manager.py        # 完善双重检查锁定
  src/core/translate/__init__.py # 翻译失败降级
  src/core/pipeline/__init__.py  # 依赖注入 + 步骤级错误处理
  src/core/tts/__init__.py       # 引擎工厂注册
  src/utils/__init__.py           # 提取 VTT查找 + 文件名安全化
  src/gui.py                     # 调用 AppService，大幅精简
  config/config.json              # 新增配置项

新增测试:
  tests/test_exceptions.py
  tests/test_gpu_manager.py
  tests/test_voice_profile.py
  tests/test_utils.py
  tests/test_pipeline_steps.py
```

---

## 十二、风险评估

| 不修复的风险 | 概率 | 影响 | 紧急度 |
|-------------|------|------|--------|
| VoiceProfileManager 并发损坏 | 中 | 音色配置丢失 | 🔴 高 |
| Pipeline 一步失败全崩 | 高 | 用户体验差 | 🔴 高 |
| 翻译失败产生无声片段 | 中 | 输出质量差 | 🟡 中 |
| GUI 代码膨胀难维护 | 高 | 开发效率低 | 🟡 中 |
| 临时文件残留 | 低 | 磁盘空间 | 🟢 低 |
| 硬编码值不可调 | 中 | 灵活性差 | 🟢 低 |
