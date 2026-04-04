# ASMR Helper 代码审查报告

**审查日期**: 2026-04-04  
**审查范围**: `src/` 目录下所有 Python 文件  
**审查重点**: 重复代码、潜在 Bug、代码质量问题

---

## 一、重复代码问题

### 1.1 GPU 显存清理代码重复

**位置**:
- `src/core/pipeline/__init__.py` 第 265-269 行、第 333-338 行
- `src/core/vocal_separator/__init__.py` 第 156-168 行
- `src/core/asr/__init__.py` 第 329-341 行
- `src/core/tts/__init__.py` 第 271-275 行

**问题描述**:
多个模块都有类似的 GPU 显存清理逻辑：
```python
if torch.cuda.is_available():
    torch.cuda.empty_cache()
```

**建议**:
统一使用 `GPUManager` 单例的 `clear_cache()` 方法，或创建一个工具函数。

---

### 1.2 模型卸载逻辑重复

**位置**:
- `src/core/vocal_separator/__init__.py` 第 156-168 行
- `src/core/asr/__init__.py` 第 329-341 行

**问题描述**:
两个类都有几乎相同的 `unload()` 方法：
```python
def unload(self):
    if hasattr(self, "model") and self.model is not None:
        del self.model
        self.model = None
        if self.device == "cuda":  # 或 device.startswith("cuda")
            import torch
            torch.cuda.empty_cache()
```

**建议**:
创建一个 `ModelMixin` 基类，统一实现模型加载/卸载逻辑。

---

### 1.3 单例模式实现重复

**位置**:
- `src/config.py` 第 23-30 行
- `src/core/gpu_manager.py` 第 37-48 行
- `src/core/tts/voice_profile.py` 第 45-46 行、第 189-195 行
- `src/core/translate/terminology.py` 第 91-98 行
- `src/core/translate/cache.py` 第 267-275 行

**问题描述**:
多个类都实现了单例模式，但实现方式略有不同：
- 有的使用 `__new__`
- 有的使用全局变量 + 锁
- 有的使用类属性 `_instance`

**建议**:
创建一个通用的单例装饰器或基类：
```python
class SingletonMeta(type):
    _instances = {}
    _lock = threading.Lock()
    
    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            with cls._lock:
                if cls not in cls._instances:
                    cls._instances[cls] = super().__call__(*args, **kwargs)
        return cls._instances[cls]
```

---

### 1.4 VTT 解析逻辑重复

**位置**:
- `src/core/translate/__init__.py` 第 596-657 行 (`load_vtt_translations`)
- `src/core/translate/__init__.py` 第 707-767 行 (`load_vtt_with_timestamps`)

**问题描述**:
两个函数解析 VTT 的逻辑几乎相同，只是返回的数据结构不同。

**建议**:
提取公共的 VTT 解析函数：
```python
def _parse_vtt_entries(vtt_path: str) -> List[Dict]:
    # 公共解析逻辑
    pass

def load_vtt_translations(vtt_path: str) -> List[str]:
    entries = _parse_vtt_entries(vtt_path)
    return [e["text"] for e in entries]

def load_vtt_with_timestamps(vtt_path: str) -> List[dict]:
    return _parse_vtt_entries(vtt_path)
```

---

### 1.5 项目根目录计算重复

**位置**:
- `src/config.py` 第 15 行
- `src/core/tts/qwen3_manager.py` 第 34 行
- `src/core/tts/voice_profile.py` 第 63 行
- `src/core/translate/terminology.py` 第 21 行
- `src/core/translate/cache.py` 第 71 行

**问题描述**:
多处使用 `Path(__file__).parent.parent.parent.parent` 计算项目根目录。

**建议**:
在 `src/__init__.py` 或 `src/utils/__init__.py` 中定义：
```python
PROJECT_ROOT = Path(__file__).parent.parent
```

---

### 1.6 GUI 音色选择代码重复

**位置**:
- `src/gui.py` 第 196-277 行 (单文件处理 Tab)
- `src/gui.py` 第 459-560 行 (批量处理 Tab)

**问题描述**:
单文件和批量处理的音色选择 UI 代码几乎完全相同，只是变量名不同 (`single_*` vs `batch_*`)。

**建议**:
提取为可复用的组件类：
```python
class VoiceSelectorWidget(QWidget):
    def __init__(self, parent=None):
        # 统一的音色选择 UI
        pass
    
    def get_selected_voice(self) -> str:
        pass
```

---

## 二、潜在 Bug

### 2.1 Pipeline 中 current_step 计数错误

**位置**: `src/core/pipeline/__init__.py` 第 221-291 行

**问题描述**:
当 `has_vtt` 为 True 时，Step 1 人声分离被跳过，但 `current_step` 仍然递增。然而 Step 2 (ASR) 的逻辑在 `has_vtt` 分支中没有递增 `current_step`：

```python
if has_vtt:
    # 使用 VTT 时间戳
    _report(f"[{current_step}/{total_steps}] [跳过] ASR (使用 VTT 字幕时间戳)")
    # 注意：这里没有 current_step += 1
```

这会导致步骤计数错误，显示 `[2/5]` 后直接跳到 `[2/5]` (ASR 显示)。

**建议**:
统一步骤计数逻辑，确保每个步骤块都正确递增 `current_step`。

---

### 2.2 Pipeline 中翻译步骤状态设置不一致

**位置**: `src/core/pipeline/__init__.py` 第 361-367 行

**问题描述**:
中文 VTT 跳过分支中设置了 `skipped: False`：
```python
results["steps"]["translate"] = {
    "duration": 0.0,
    "segments": len(translations),
    "source": "vtt_zh",
    "skipped": False,  # 这里应该是 True？
    "output": str(translated_path),
}
```

但逻辑上是"跳过"了翻译 API 调用，应该设置 `skipped: True`。

---

### 2.3 Mixer.build_aligned_tts 中 shutil 重复导入

**位置**: `src/mixer/__init__.py` 第 277 行、第 411 行

**问题描述**:
```python
import shutil  # 第 277 行
# ...
import shutil  # 第 411 行，重复导入
```

虽然 Python 会处理重复导入，但这是代码质量问题。

---

### 2.4 翻译批量模式结果索引错误

**位置**: `src/core/translate/__init__.py` 第 294-297 行

**问题描述**:
```python
return [
    (batch_indices[i], results_dict[i]["src"] if i in results_dict else batch[i - len(batch_indices)], True)
    for i in range(len(batch))
]
```

这里的 `batch[i - len(batch_indices)]` 逻辑有问题：
- 当 `i = 0` 时，`i - len(batch_indices)` 是负数
- 这会导致索引错误，应该直接使用 `batch[i]`

**建议**:
```python
return [
    (batch_indices[i], results_dict[i]["src"] if i in results_dict else batch[i], True)
    for i in range(len(batch))
]
```

---

### 2.5 GPUManager 中 _active_count 可能为负数

**位置**: `src/core/gpu_manager.py` 第 90-95 行

**问题描述**:
```python
def release(self):
    with self._count_lock:
        if self._active_count > 0:
            self._active_count -= 1
    self._semaphore.release()
```

如果 `release()` 被调用次数多于 `acquire()`，信号量会超过初始值，但 `_active_count` 不会变成负数。这不是严重问题，但可能导致计数不准确。

**建议**:
添加警告或断言来检测这种不匹配情况。

---

### 2.6 翻译缓存未持久化

**位置**: `src/core/translate/cache.py`

**问题描述**:
`TranslationCache` 类提供了 `load()` 和 `save()` 方法，但在实际使用中：
- 缓存只在内存中
- 程序退出后缓存丢失
- `get_cache()` 返回的单例不会自动加载/保存文件

**建议**:
在 `__init__` 中自动加载缓存，在程序退出时自动保存，或提供显式的持久化调用。

---

### 2.7 Qwen3TTSEngine 中 numpy 重复导入

**位置**: `src/core/tts/__init__.py` 第 287 行、第 313 行

**问题描述**:
```python
import numpy as np  # 第 287 行
# ...
import numpy as np  # 第 313 行，重复
```

应该在文件顶部统一导入。

---

### 2.8 Pipeline 中 mixer 变量可能未定义

**位置**: `src/core/pipeline/__init__.py` 第 541-565 行

**问题描述**:
```python
if config.use_mixer and results.get("tts_path"):
    # ...
    mixer = Mixer(...)  # 这里创建 mixer
    mixer.mix(...)
```

如果 `config.use_mixer` 为 False 但前面 TTS 步骤成功，`results["tts_path"]` 存在，但 `mixer` 变量未定义。不过目前代码逻辑没有问题，因为条件同时检查了两者。

**潜在风险**:
如果后续修改条件逻辑，可能引入 bug。

---

## 三、代码质量问题

### 3.1 未使用的导入

**位置**: `src/core/pipeline/__init__.py` 第 23 行
```python
import soundfile as sf  # 未使用
```

**位置**: `src/core/tts/__init__.py` 第 13 行
```python
import edge_tts  # 实际上使用了，但只在异步方法中
```

---

### 3.2 硬编码值

**位置**: `src/core/pipeline/__init__.py` 第 575-578 行
```python
saved = 23 if is_chinese_vtt else 0
saved += 23 if (has_vtt and not is_chinese_vtt) else 0
```

这里的 `23` 和 `51` 是硬编码的估计值，应该定义为常量：
```python
VTT_SKIP_SAVED_SECONDS = {
    "zh": 51,  # 中文 VTT 节省的时间
    "ja": 23,  # 日文 VTT 节省的时间
}
```

---

### 3.3 异常处理过于宽泛

**位置**: `src/core/tts/voice_profile.py` 第 76-88 行
```python
try:
    with open(self.config_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    # ...
except Exception as e:
    print(f"[VoiceProfileManager] 加载配置文件失败: {e}")
```

应该区分 `FileNotFoundError`、`json.JSONDecodeError` 等不同异常类型。

---

### 3.4 类型注解不完整

**位置**: `src/core/tts/__init__.py` 第 180-208 行

`Qwen3TTSEngine.__init__` 中 `voice_profile_id` 参数没有类型注解：
```python
def __init__(
    self,
    voice: str = "Vivian",
    speed: float = 1.0,
    voice_profile_id: str = None,  # 应该是 Optional[str]
):
```

---

### 3.5 文档字符串与参数不匹配

**位置**: `src/core/tts/__init__.py` 第 395-409 行

`TTSEngine.__init__` 的文档字符串中参数 `voice_profile_id` 描述不完整。

---

### 3.6 魔法数字

**位置**: `src/mixer/__init__.py` 第 356-376 行

多处使用魔法数字：
```python
if tts_duration > original_duration * tts_speed_range[1]:  # 1.2
    target_duration = original_duration * tts_speed_range[1]
```

应该使用命名常量。

---

### 3.7 重复的正则表达式编译

**位置**: `src/core/translate/quality.py` 第 51-56 行

正则表达式在类定义时编译，但如果创建多个 `QualityChecker` 实例，这些正则会被重复编译。虽然当前使用单例模式，但设计上应该考虑：

```python
class QualityChecker:
    # 这些在类加载时编译一次
    HIRAGANA = re.compile(r'[\u3040-\u309f]')
    # ...
```

这是好的实践，但应该添加注释说明这是有意的设计。

---

## 四、架构/设计问题

### 4.1 循环导入风险

**位置**: `src/core/translate/__init__.py` 第 20 行
```python
from src.config import config
```

`src.config` 可能导入 `src.core` 下的模块，如果未来 `config.py` 需要访问翻译模块，会产生循环导入。

**建议**:
使用延迟导入或依赖注入。

---

### 4.2 配置管理分散

项目中有多个配置来源：
- `src/config.py` - 主配置
- `src/core/translate/terminology.py` - 术语库配置
- `src/core/tts/voice_profile.py` - 音色配置
- `src/core/translate/cache.py` - 缓存配置

**建议**:
统一配置管理，或使用配置注册机制。

---

### 4.3 日志系统不一致

项目中混用多种日志方式：
- `print()` 语句
- `warnings.warn()`
- 部分模块没有日志

**建议**:
统一使用 Python 的 `logging` 模块。

---

### 4.4 错误处理策略不一致

不同模块对错误的处理方式不同：
- 有的抛出异常
- 有的返回空值
- 有的打印警告继续执行

**建议**:
定义统一的错误处理策略和异常层次结构。

---

## 五、性能问题

### 5.1 音频文件重复读取

**位置**: `src/mixer/__init__.py` 第 97-103 行、第 134-138 行

`detect_volume()` 方法每次调用都会重新读取音频文件：
```python
def detect_volume(self, audio_path: str) -> float:
    data, sr = sf.read(audio_path)  # 重复读取
```

在 `mix()` 方法中，原音和 TTS 音频各读取一次，如果音频很大会有性能问题。

**建议**:
考虑缓存音频数据或使用流式读取。

---

### 5.2 翻译缓存未使用文件缓存

**位置**: `src/core/translate/cache.py`

虽然实现了 `load()` 和 `save()` 方法，但 `get_cache()` 返回的单例不会自动持久化缓存到文件。

---

## 六、安全/健壮性问题

### 6.1 文件路径未验证

多处直接使用用户输入的文件路径，没有验证：
- 路径遍历攻击风险
- 特殊字符处理

**建议**:
使用 `pathlib.Path.resolve()` 验证路径。

---

### 6.2 临时文件清理不完全

**位置**: `src/mixer/__init__.py` 第 306-399 行

`build_aligned_tts` 方法中，如果中途发生异常，临时文件可能不会被清理。

**建议**:
使用 `try...finally` 或上下文管理器确保清理。

---

### 6.3 subprocess 命令未完全验证

多处使用 `subprocess.run()` 执行外部命令，参数拼接可能存在注入风险。

---

## 七、建议修复优先级

### 🔴 高优先级 (Bug)
1. **Pipeline 步骤计数错误** - ✅ 已修复 (commit f464dcc)
2. **翻译批量模式索引错误** - ✅ 已修复 (commit f464dcc)
3. **翻译缓存未持久化** - ✅ 已修复 (commit f464dcc)
4. ⚠️ **翻译API返回字段错误** - ✅ 已修复 (commit 63d9138) **[新发现严重Bug]**

### 🟡 中优先级 (代码质量)
1. 提取重复的 GPU 清理逻辑
2. 统一单例模式实现
3. 提取 VTT 解析公共函数
4. GUI 音色选择组件化

### 🟢 低优先级 (优化)
1. 统一日志系统
2. 完善类型注解
3. 添加更多单元测试

---

## 八、修复记录

| 日期 | Bug | Commit | 修复人 |
|------|-----|--------|--------|
| 2026-04-04 | 2.1 Pipeline 步骤计数错误 | f464dcc | AI |
| 2026-04-04 | 2.2 翻译步骤状态不一致 | f464dcc | AI |
| 2026-04-04 | 2.3 Mixer shutil 重复导入 | f464dcc | AI |
| 2026-04-04 | 2.4 翻译批量模式索引错误 | f464dcc | AI |
| 2026-04-04 | 2.6 翻译缓存未持久化 | f464dcc | AI |
| 2026-04-04 | 2.7 Qwen3TTSEngine numpy | f464dcc | AI |
| 2026-04-04 | 翻译API返回dst字段错误 | 63d9138 | AI |

---

## 九、附录：代码统计

| 模块 | 文件数 | 代码行数 | 主要问题 |
|------|--------|----------|----------|
| core/pipeline | 1 | ~600 | 步骤计数错误、硬编码值 |
| core/translate | 4 | ~1000 | 重复解析逻辑、缓存未持久化 |
| core/tts | 3 | ~700 | 重复导入、类型注解不完整 |
| core/asr | 2 | ~400 | 良好 |
| core/vocal_separator | 1 | ~180 | 良好 |
| mixer | 1 | ~440 | 重复导入、临时文件清理 |
| gui.py | 1 | ~1430 | 大量重复UI代码 |
| config.py | 1 | ~194 | 良好 |

---

*报告生成时间: 2026-04-04*  
*审查工具: 人工代码审查*
