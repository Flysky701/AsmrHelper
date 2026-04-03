# Report #6: Agent1 Qwen3-TTS 音色系统执行审查

> 日期: 2026-04-03  
> 审查对象: Agent1 对 report_5_voice_system.md 架构设计的代码实现  
> 审查结果: **严重缺陷 - 功能不完整**

---

## 1. 执行摘要

Agent1 在执行 Qwen3-TTS 音色系统改造时，**仅完成了约 15% 的架构设计内容**，留下了大量关键文件缺失和代码不完整的问题。

---

## 2. 架构设计 vs 实际实现对比

### 2.1 应实现的文件清单

根据 `report_5_voice_system.md`，应创建以下新文件：

| 文件 | 状态 | 问题 |
|------|------|------|
| `src/core/tts/voice_profile.py` | ❌ **缺失** | VoiceProfile 数据类 + VoiceProfileManager 未实现 |
| `src/core/tts/qwen3_manager.py` | ❌ **缺失** | Qwen3ModelManager（模型单例 + 预加载）未实现 |
| `scripts/generate_voice_profiles.py` | ❌ **缺失** | 预生成音色脚本未实现 |
| `config/voice_profiles.json` | ⚠️ **部分完成** | 配置文件已创建，但缺少关键字段 |

### 2.2 应修改的文件

| 文件 | 状态 | 问题 |
|------|------|------|
| `src/core/tts/__init__.py` | ⚠️ **部分完成** | 仅支持 CustomVoice 预设音色，未实现 VoiceDesign/VoiceClone |
| `src/core/pipeline/__init__.py` | ❌ **未修改** | PipelineConfig 未添加 voice_profile_id 字段 |
| `src/gui.py` | ❌ **未修改** | TTS 设置区域仍为单一 ComboBox，无音色分类 Tab |

---

## 3. 发现的具体问题

### 3.1 致命问题：缺少核心模块

**问题**: `src/core/tts/voice_profile.py` 文件不存在

**影响**: 
- `Qwen3TTSEngine` 尝试导入 `from .voice_profile import get_voice_manager` 会失败
- 虽然代码有 try-except 包裹，但音色配置系统完全不可用
- 所有 B1-B4 自定义音色无法使用

**代码位置**:
```python
# src/core/tts/__init__.py:231-240
if voice_profile_id:
    try:
        from .voice_profile import get_voice_manager  # ← 导入失败
        manager = get_voice_manager()
        profile = manager.get_by_id(voice_profile_id)
        ...
    except Exception as e:
        print(f"[Qwen3TTS] 加载音色配置失败: {e}")
```

### 3.2 严重问题：Qwen3-TTS 仅支持 CustomVoice 模式

**问题**: `Qwen3TTSEngine` 仅实现了 CustomVoice 预设音色，未实现 VoiceDesign 和 VoiceClone

**预期实现** (根据架构设计):
```python
class Qwen3TTSEngine:
    def synthesize(self, text: str, output_path: str) -> str:
        if self.profile.category == "preset":
            return self._synthesize_custom_voice(text, output_path)
        elif self.profile.category == "custom":
            return self._synthesize_from_cache(text, output_path)  # ← 缺失
        elif self.profile.category == "clone":
            return self._synthesize_clone(text, output_path)  # ← 缺失
```

**实际实现**:
```python
# 仅支持 CustomVoice 的 generate() 方法
def synthesize(self, text: str, output_path: str) -> str:
    model = self._get_model()
    model.generate(text, voice=self.voice, speed=self.speed, 
                   instruct=self.instruct, output_path=str(output_path))
```

**影响**:
- B1-B4 自定义音色（治愈大姐姐、娇小萝莉等）完全无法使用
- VoiceDesign 功能未实现
- VoiceClone 功能未实现
- 预生成缓存机制未实现

### 3.3 严重问题：GUI 未按设计改造

**预期设计** (report_5_voice_system.md):
```
┌─ TTS 设置 ─────────────────────────────────────────────────────┐
│ 引擎: [Edge-TTS ▾]  [Qwen3-TTS ▾]                             │
│                                                                │
│ ┌─音色选择────────────────────────────────────────────────────┐ │
│ │ [预设音色] [自定义音色] [克隆音色]     ← QTabWidget        │ │
│ │                                                            │ │
│ │ 预设音色 Tab:                                              │ │
│ │ ○ 甜美少女 (Vivian)                                       │ │
│ │ ○ 温柔姐姐 (Serena) + instruct: [用温柔体贴的语气说]       │ │
│ │ ...                                                        │ │
│ └────────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────┘
```

**实际实现**:
```python
# 仍为单一 ComboBox，无 Tab 分类
engine_layout.addWidget(QLabel("音色:"))
self.single_tts_voice = QComboBox()
self.single_tts_voice.setEditable(True)
engine_layout.addWidget(self.single_tts_voice)
```

**影响**:
- 用户无法选择 B1-B4 自定义音色
- 无法使用 VoiceDesign 自然语言描述
- 无法上传参考音频进行克隆
- 无法看到音色分类

### 3.4 中等问题：配置文件字段缺失

**问题**: `config/voice_profiles.json` 中 B1-B4 自定义音色的 `generated` 字段为 `false`，但无生成机制

```json
{
  "id": "B1",
  "name": "治愈大姐姐",
  "category": "custom",
  "engine": "qwen3_clone",
  "ref_audio": "models/voice_profiles/B1_ref.wav",
  "prompt_cache": "models/voice_profiles/B1_prompt.pt",
  "generated": false  // ← 永为 false，无生成脚本
}
```

**影响**: 即使 voice_profile.py 存在，也无法找到预生成的参考音频和 prompt 缓存

### 3.5 中等问题：Pipeline 未集成 voice_profile

**问题**: `PipelineConfig` 未添加 `voice_profile_id` 字段

**代码位置**:
```python
# src/gui.py:78-93
# PipelineConfig 构造时未传入 voice_profile_id
cfg = PipelineConfig(
    input_path=self.input_path,
    ...
    tts_voice=self.params.get("tts_voice", "zh-CN-XiaoxiaoNeural"),
    qwen3_voice=self.params.get("tts_voice", "Vivian"),
    # ← voice_profile_id 缺失
)
```

**影响**: 即使 GUI 支持选择音色配置，也无法传递到 Pipeline

### 3.6 轻微问题：音色名称大小写不一致

**问题**: GUI 中 Qwen3 音色列表使用 `Uncle_fu`，但官方 speaker 名称为 `Uncle_Fu`

```python
# src/gui.py:831-832
self.single_tts_voice.addItems([
    "Vivian", "Serena", "Uncle_fu", "Dylan", "Eric", "Ryan", "Aiden"
    #              ↑ 应为 Uncle_Fu
])
```

---

## 4. 功能可用性评估

| 功能 | 设计状态 | 实际状态 | 可用性 |
|------|---------|---------|--------|
| CustomVoice 预设音色 (A1-A7) | 100% | 100% | ✅ 可用 |
| VoiceDesign 自定义音色 (B1-B5) | 100% | 0% | ❌ 不可用 |
| VoiceClone 克隆音色 | 100% | 0% | ❌ 不可用 |
| 预生成缓存机制 | 100% | 0% | ❌ 不可用 |
| GUI 音色分类 Tab | 100% | 0% | ❌ 不可用 |
| 模型单例管理 | 100% | 50% | ⚠️ 部分可用 |
| Pipeline voice_profile 集成 | 100% | 0% | ❌ 不可用 |

**总体完成度: 约 15%**

---

## 5. 修复建议

### 5.1 立即修复（P0）

1. **创建 `src/core/tts/voice_profile.py`**
   - 实现 `VoiceProfile` dataclass
   - 实现 `VoiceProfileManager` 类
   - 实现 `get_voice_manager()` 单例函数

2. **修复 `src/core/tts/__init__.py`**
   - 实现 `_synthesize_from_cache()` 方法
   - 实现 `_synthesize_clone()` 方法
   - 支持从 profile 获取 instruct

### 5.2 高优先级（P1）

3. **创建 `scripts/generate_voice_profiles.py`**
   - 预生成 B1-B4 的参考音频和 prompt 缓存
   - 更新 voice_profiles.json 的 `generated` 字段

4. **创建 `src/core/tts/qwen3_manager.py`**
   - 实现 Qwen3ModelManager 类
   - 支持 CustomVoice/VoiceDesign/Base 三种模型的延迟加载

### 5.3 中优先级（P2）

5. **改造 `src/gui.py`**
   - TTS 设置区域改为 QTabWidget
   - 实现预设音色/自定义音色/克隆音色三个 Tab
   - 添加 VoiceDesign 文本输入框
   - 添加克隆音频上传功能

6. **修改 `src/core/pipeline/__init__.py`**
   - PipelineConfig 添加 voice_profile_id 字段
   - Pipeline 支持传递 voice_profile_id 到 TTSEngine

---

## 6. 结论

Agent1 在执行 Qwen3-TTS 音色系统改造时，**严重偏离了架构设计**：

1. **核心模块缺失**: voice_profile.py、qwen3_manager.py、generate_voice_profiles.py 均未创建
2. **功能不完整**: 仅实现了 CustomVoice 预设音色，VoiceDesign 和 VoiceClone 完全未实现
3. **GUI 未改造**: 仍为单一 ComboBox，无音色分类 Tab
4. **Pipeline 未集成**: voice_profile_id 未添加到配置

**建议**: 需要重新分配任务，完整实现 report_5_voice_system.md 中设计的所有功能。

---

## 7. 附录：缺失文件详细设计

### 7.1 voice_profile.py 应实现内容

```python
@dataclass
class VoiceProfile:
    id: str
    name: str
    category: Literal["preset", "custom", "clone"]
    engine: str
    description: str = ""
    speaker: str = ""          # CustomVoice
    instruct: str = ""         # CustomVoice
    design_instruct: str = ""  # VoiceDesign
    ref_audio: str = ""        # VoiceClone
    prompt_cache: str = ""     # VoiceClone
    generated: bool = False

class VoiceProfileManager:
    def __init__(self, config_path: str = "config/voice_profiles.json")
    def get_by_id(self, profile_id: str) -> Optional[VoiceProfile]
    def get_presets(self) -> List[VoiceProfile]
    def get_customs(self) -> List[VoiceProfile]
    def generate_custom_profile(self, profile_id: str) -> bool  # 预生成参考音频

def get_voice_manager() -> VoiceProfileManager
```

### 7.2 qwen3_manager.py 应实现内容

```python
class Qwen3ModelManager:
    _instances: Dict[str, Any] = {}
    
    @classmethod
    def get_custom_voice_model(cls) -> Any
    @classmethod
    def get_voice_design_model(cls) -> Any
    @classmethod
    def get_base_model(cls) -> Any
    @classmethod
    def unload_all(cls)
```

### 7.3 generate_voice_profiles.py 应实现内容

```python
REF_TEXT = "你好，今天辛苦了，让我来帮你放松一下吧。"
PROFILES = [
    ("B1", "治愈大姐姐", "温柔成熟的大姐姐声线..."),
    ("B2", "娇小萝莉", "撒娇稚嫩的少女声线..."),
    ...
]

def main():
    # Step 1: 用 VoiceDesign 生成参考音频
    # Step 2: 用 Base 模型创建 voice_clone_prompt
    # Step 3: 更新 profiles.json 的 generated 字段
```
