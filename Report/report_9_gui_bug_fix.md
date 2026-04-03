# GUI 音色部分 Bug 修复报告

**报告时间**: 2026-04-04 02:10  
**报告人**: Agent2  
**问题来源**: 用户报告 GUI 运行时错误

---

## 1. 问题描述

用户在运行 GUI 时遇到以下错误：

### 错误 1: AttributeError
```
Traceback (most recent call last):
  File "d:\WorkSpace\AsmrHelper\src\gui.py", line 1244, in preview_voice
    voice = self.single_tts_voice.currentText()
AttributeError: 'MainWindow' object has no attribute 'single_tts_voice'. Did you mean: 'single_tts_vol'?
```

### 错误 2: 布局警告
```
QLayout::addChildLayout: layout QHBoxLayout "" already has a parent
```

---

## 2. 根因分析

### 2.1 AttributeError 根因

在 Agent1 的修复中，GUI 的音色选择从简单的 `QComboBox` 改造为 `QTabWidget` 分类布局：

**改造前**:
```python
self.single_tts_voice = QComboBox()  # 单一音色选择器
```

**改造后**:
```python
self.single_voice_tabs = QTabWidget()      # Tab 容器
self.single_preset_voice = QComboBox()     # Tab 1: 预设音色
self.single_custom_voice = QComboBox()     # Tab 2: 自定义音色
self.single_clone_audio = QLineEdit()      # Tab 3: 克隆音色
```

但 `preview_voice()` 方法仍然引用旧的 `self.single_tts_voice`，导致 AttributeError。

### 2.2 布局警告根因

在批量处理部分的代码中，`engine_layout` 被重复添加到 `tts_layout`：

```python
# 第 698 行 - 第一次添加
engine_layout = QHBoxLayout()
engine_layout.addWidget(self.batch_tts_engine)
tts_layout.addLayout(engine_layout)  # <-- 第一次添加

# ... 中间代码 ...

# 第 791 行 - 错误地重复添加同一个 layout
engine_layout.addWidget(self.batch_asr_model)  # 修改同一个 layout
tts_layout.addLayout(engine_layout)  # <-- 第二次添加（错误！）
```

Qt 不允许将一个 layout 重复添加到多个父 layout 或重复添加到同一个父 layout。

---

## 3. 修复方案

### 3.1 修复 preview_voice 方法

**文件**: `src/gui.py`  
**行号**: 1237-1264

**修复前**:
```python
def preview_voice(self):
    engine = "edge" if self.single_tts_engine.currentText() == "Edge-TTS" else "qwen3"
    voice = self.single_tts_voice.currentText()  # ❌ 属性不存在
    # ...
    self.preview_thread = PreviewWorkerThread(
        engine=engine,
        voice=voice,
        speed=self.single_tts_speed.value() if engine == "qwen3" else 1.0,
        test_text=test_text,
    )
```

**修复后**:
```python
def preview_voice(self):
    engine = "edge" if self.single_tts_engine.currentText() == "Edge-TTS" else "qwen3"
    
    # ✅ 使用 _get_voice_info 获取当前选中的音色
    voice, voice_profile_id = self._get_voice_info(
        self.single_voice_tabs,
        self.single_preset_voice,
        self.single_custom_voice,
        self.single_clone_audio
    )
    # ...
    self.preview_thread = PreviewWorkerThread(
        engine=engine,
        voice=voice,
        voice_profile_id=voice_profile_id,  # ✅ 新增参数
        speed=self.single_tts_speed.value() if engine == "qwen3" else 1.0,
        test_text=test_text,
    )
```

### 3.2 修复 PreviewWorkerThread

**文件**: `src/gui.py`  
**行号**: 110-138

**修复前**:
```python
class PreviewWorkerThread(QThread):
    def __init__(self, engine: str, voice: str, speed: float, test_text: str):
        # ...
        tts_engine = TTSEngine(
            engine=self.engine,
            voice=self.voice,
            speed=self.speed,
        )
```

**修复后**:
```python
class PreviewWorkerThread(QThread):
    def __init__(self, engine: str, voice: str, voice_profile_id: str, speed: float, test_text: str):
        # ...
        self.voice_profile_id = voice_profile_id
        # ...
        tts_engine = TTSEngine(
            engine=self.engine,
            voice=self.voice,
            voice_profile_id=self.voice_profile_id,  # ✅ 传递音色配置 ID
            speed=self.speed,
        )
```

### 3.3 修复布局重复添加问题

**文件**: `src/gui.py`  
**行号**: 767-791

**修复前**:
```python
# speed_layout 添加完成
tts_layout.addLayout(speed_layout)

# ❌ 错误：继续使用已添加的 engine_layout
engine_layout.addWidget(QLabel("识别模型:"))  # 修改已有 parent 的 layout
engine_layout.addWidget(self.batch_asr_model)
# ...
tts_layout.addLayout(engine_layout)  # ❌ 重复添加！

# ❌ 错误：重复创建 speed_layout
speed_layout = QHBoxLayout()  # 重复定义
# ...
tts_layout.addLayout(speed_layout)  # 再次添加 speed_layout
```

**修复后**:
```python
# speed_layout 添加完成
tts_layout.addLayout(speed_layout)

# ✅ 创建新的 layout 用于 ASR 和分离模型
model_layout = QHBoxLayout()
model_layout.addWidget(QLabel("识别模型:"))
model_layout.addWidget(self.batch_asr_model)
# ...
tts_layout.addLayout(model_layout)  # ✅ 只添加一次

# ✅ 移除重复的 speed_layout 创建代码
```

---

## 4. 修复验证

### 4.1 修复点汇总

| 问题 | 位置 | 修复方式 |
|------|------|---------|
| `single_tts_voice` 不存在 | `preview_voice()` 方法 | 使用 `_get_voice_info()` 获取音色 |
| `voice_profile_id` 未传递 | `PreviewWorkerThread` | 添加 `voice_profile_id` 参数 |
| `engine_layout` 重复添加 | 批量处理 TTS 设置区 | 新建 `model_layout` 替代 |
| 重复的 `speed_layout` | 批量处理 TTS 设置区 | 移除重复代码 |

### 4.2 代码一致性检查

修复后，以下调用链保持一致：

```
preview_voice()
  └── _get_voice_info()  # 获取音色和 profile_id
  └── PreviewWorkerThread(engine, voice, voice_profile_id, ...)
      └── TTSEngine(engine, voice, voice_profile_id, ...)
          └── Qwen3TTSEngine(voice, voice_profile_id)  # 使用音色配置
```

---

## 5. 后续建议

### 5.1 代码审查建议

1. **重构时注意依赖关系**: 修改 UI 结构时，需要同步更新所有引用该 UI 元素的方法
2. **避免 layout 复用**: Qt 的 layout 一旦添加到 parent，不应再次添加或修改后重复添加
3. **使用统一接口**: `_get_voice_info()` 方法提供了统一的音色获取方式，应在所有需要的地方使用

### 5.2 测试建议

1. 测试三种音色类型的试音功能：
   - 预设音色 (A1-A7)
   - 自定义音色 (B1-B4，需预生成)
   - 克隆音色 (需参考音频)

2. 测试 Edge-TTS 和 Qwen3-TTS 切换时的 UI 状态

3. 测试单文件和批量处理的试音功能

---

## 6. 结论

本次修复解决了 GUI 音色部分的两个关键 Bug：

1. ✅ **AttributeError**: `preview_voice()` 方法现在正确使用 `_get_voice_info()` 获取音色
2. ✅ **布局警告**: 移除重复的 layout 添加，使用独立的 `model_layout`

修复后，试音功能应能正常工作，支持三种音色类型（预设/自定义/克隆）。

---

*报告生成时间: 2026-04-04 02:10*
