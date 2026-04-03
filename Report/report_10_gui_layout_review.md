# GUI.py Qwen3-TTS 音色选择布局审阅报告

**审阅时间**: 2026-04-04 02:19  
**审阅人**: Agent2  
**审阅对象**: `src/gui.py` 中 Qwen3-TTS 音色选择相关布局

---

## 1. 执行摘要

经过详细审阅，发现 GUI 的音色选择布局存在**架构级设计缺陷**：

1. **Edge-TTS 音色选择器完全缺失** - 改造后只有 Qwen3-TTS 的音色 Tab，Edge-TTS 没有音色选择 UI
2. **音色获取逻辑不统一** - Edge-TTS 和 Qwen3-TTS 使用相同的 `_get_voice_info`，但返回不兼容的音色格式
3. **隐藏/显示逻辑不完整** - 切换引擎时只隐藏/显示控件，没有切换数据源

**风险等级**: 🔴 **高** - 功能无法正常使用

---

## 2. 详细问题分析

### 问题 1: Edge-TTS 音色选择器缺失 🔴

**位置**: `create_single_tab()` (460-548行), `create_batch_tab()` (687-796行)

**现状**:
```python
# 当前代码结构
engine_layout = QHBoxLayout()
engine_layout.addWidget(QLabel("引擎:"))
self.single_tts_engine = QComboBox()
self.single_tts_engine.addItems(["Edge-TTS", "Qwen3-TTS"])
# ...

# 音色选择（只有 Qwen3-TTS 的 Tab）
self.single_voice_tabs = QTabWidget()
# Tab 1: 预设音色 (Vivian, Serena...)
# Tab 2: 自定义音色 (B1-B4)
# Tab 3: 克隆音色
```

**问题**: 
- 改造后**完全没有 Edge-TTS 的音色选择器**
- 当选择 Edge-TTS 时，`voice_tabs` 被隐藏，用户无法选择任何音色
- 当选择 Qwen3-TTS 时，显示的是 Qwen3 的音色（Vivian, Serena...）

**期望**:
```python
# 应该有两种音色选择器
if engine == "Edge-TTS":
    # 显示 Edge-TTS 音色: zh-CN-XiaoxiaoNeural, zh-CN-YunxiNeural...
else:
    # 显示 Qwen3-TTS 音色 Tab
```

---

### 问题 2: 音色获取逻辑错误 🔴

**位置**: `_get_voice_info()` (968-982行), `get_single_params()` (984-1025行), `get_batch_params()` (1027-1066行)

**现状**:
```python
def _get_voice_info(self, voice_tabs, preset_combo, custom_combo, clone_line):
    tab_index = voice_tabs.currentIndex()
    if tab_index == 0:
        voice_text = preset_combo.currentText()  # "Vivian (A1)"
        return voice_text.split(" ")[0], profile_id  # "Vivian"
    # ...

def get_single_params(self):
    engine = "edge" if self.single_tts_engine.currentText() == "Edge-TTS" else "qwen3"
    # 问题：无论 Edge 还是 Qwen3，都调用 _get_voice_info 获取音色
    tts_voice, voice_profile_id = self._get_voice_info(...)
    # 结果：Edge-TTS 得到 "Vivian"，但 Edge-TTS 需要 "zh-CN-XiaoxiaoNeural"
```

**问题**:
- `_get_voice_info` 始终返回 Qwen3-TTS 格式的音色（如 "Vivian"）
- Edge-TTS 需要完全不同的音色格式（如 "zh-CN-XiaoxiaoNeural"）
- 没有根据引擎类型切换音色获取逻辑

**影响**:
```python
# 当用户选择 Edge-TTS + 默认音色时
tts_voice = "Vivian"  # 错误！Edge-TTS 不认识这个音色
# Edge-TTS 期望: "zh-CN-XiaoxiaoNeural"
```

---

### 问题 3: 引擎切换逻辑不完整 🟡

**位置**: `on_single_engine_changed()` (927-938行), `on_batch_engine_changed()` (940-951行)

**现状**:
```python
def on_single_engine_changed(self, engine: str):
    if engine == "Edge-TTS":
        self.single_voice_tabs.setVisible(False)  # 只是隐藏
        self.single_tts_speed_label.setVisible(False)
        self.single_tts_speed.setVisible(False)
    else:
        self.single_voice_tabs.setVisible(True)   # 只是显示
        self.single_tts_speed_label.setVisible(True)
        self.single_tts_speed.setVisible(True)
```

**问题**:
- 只是简单地隐藏/显示控件
- 没有切换音色数据源
- 没有设置默认音色

---

### 问题 4: 试音功能逻辑错误 🟡

**位置**: `preview_voice()` (1230-1260行)

**现状**:
```python
def preview_voice(self):
    engine = "edge" if self.single_tts_engine.currentText() == "Edge-TTS" else "qwen3"
    # 使用 _get_voice_info 获取音色
    voice, voice_profile_id = self._get_voice_info(...)
    # ...
    PreviewWorkerThread(engine, voice, voice_profile_id, ...)
```

**问题**:
- 当选择 Edge-TTS 时，`voice_tabs` 被隐藏，但 `_get_voice_info` 仍会被调用
- 返回的音色是 Qwen3 格式（如 "Vivian"），但 Edge-TTS 需要 Edge 格式

---

### 问题 5: 布局重复定义（已修复） ✅

**位置**: `create_batch_tab()` (753-794行)

**状态**: 已在 report_9 中修复

**问题**: `speed_layout` 被重复定义和添加

---

## 3. 问题影响矩阵

| 功能场景 | 当前行为 | 期望行为 | 状态 |
|---------|---------|---------|------|
| Edge-TTS 选择音色 | 无音色选择器，使用默认值 | 显示 Edge-TTS 音色列表 | ❌ 损坏 |
| Edge-TTS 试音 | 传入 "Vivian" 导致错误 | 传入 "zh-CN-XiaoxiaoNeural" | ❌ 损坏 |
| Qwen3-TTS 选择预设音色 | 正常显示 Tab | 正常 | ✅ 正常 |
| Qwen3-TTS 选择自定义音色 | 显示但未生成 | 显示并提示预生成 | ⚠️ 部分 |
| Qwen3-TTS 试音 | 正常 | 正常 | ✅ 正常 |

---

## 4. 修复建议

### 方案 A: 添加 Edge-TTS 音色选择器（推荐）

**修改 `create_single_tab()` 和 `create_batch_tab()`**:

```python
# 在音色选择区域添加 Edge-TTS 音色选择器
self.single_edge_voice = QComboBox()
self.single_edge_voice.addItems([
    "zh-CN-XiaoxiaoNeural (晓晓-女)",
    "zh-CN-YunxiNeural (云希-男)",
    "zh-CN-YunyangNeural (云扬-男)",
    "zh-CN-XiaoyiNeural (小艺-女)",
    "ja-JP-NanamiNeural (七海-日语女)",
])

# 将 Edge 音色和 Qwen3 Tab 放在同一个容器中
self.single_voice_container = QStackedWidget()
self.single_voice_container.addWidget(self.single_edge_voice)      # Index 0
self.single_voice_container.addWidget(self.single_voice_tabs)       # Index 1
```

**修改 `on_single_engine_changed()`**:

```python
def on_single_engine_changed(self, engine: str):
    if engine == "Edge-TTS":
        self.single_voice_container.setCurrentIndex(0)  # 显示 Edge 音色
        self.single_tts_speed_label.setVisible(False)
        self.single_tts_speed.setVisible(False)
    else:
        self.single_voice_container.setCurrentIndex(1)  # 显示 Qwen3 Tab
        self.single_tts_speed_label.setVisible(True)
        self.single_tts_speed.setVisible(True)
```

**修改 `_get_voice_info()`**:

```python
def _get_voice_info(self, engine, ...):
    if engine == "edge":
        # 解析 Edge-TTS 音色
        voice_text = self.single_edge_voice.currentText()
        return voice_text.split(" ")[0], None  # "zh-CN-XiaoxiaoNeural"
    else:
        # 解析 Qwen3-TTS 音色（原有逻辑）
        # ...
```

### 方案 B: 简化设计（备选）

如果 Edge-TTS 只是备选方案，可以：
1. 固定 Edge-TTS 使用默认音色 "zh-CN-XiaoxiaoNeural"
2. 不在 GUI 中提供 Edge-TTS 音色选择
3. 在配置文件中允许用户修改默认 Edge 音色

---

## 5. 代码审查清单

### 布局结构
- [x] Qwen3-TTS 音色 Tab 结构正确
- [ ] Edge-TTS 音色选择器缺失
- [x] 语速控制显示/隐藏逻辑正确
- [x] 布局重复添加问题已修复

### 逻辑流程
- [ ] `_get_voice_info` 需要根据引擎类型返回不同格式
- [ ] `get_single_params` 和 `get_batch_params` 需要区分引擎获取音色
- [ ] `preview_voice` 需要根据引擎获取正确的音色

### 初始化
- [x] 默认引擎为 Edge-TTS
- [ ] 但 Edge-TTS 没有默认音色选择器

---

## 6. 结论

GUI 的音色选择布局存在**架构级设计缺陷**，主要问题是：

1. **Edge-TTS 音色选择器完全缺失** - 用户无法选择 Edge-TTS 音色
2. **音色获取逻辑不统一** - 两种引擎使用相同的获取逻辑，但音色格式不兼容

**建议立即修复**，否则 Edge-TTS 功能无法正常使用。

**修复优先级**:
1. 🔴 **P0**: 添加 Edge-TTS 音色选择器
2. 🔴 **P0**: 修复 `_get_voice_info` 根据引擎返回正确音色格式
3. 🟡 **P1**: 统一音色获取逻辑

---

*报告生成时间: 2026-04-04 02:19*
