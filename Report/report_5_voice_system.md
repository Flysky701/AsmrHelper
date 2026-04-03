# Report #5: Qwen3-TTS 音色系统改造架构

> 日期: 2026-04-03
> 状态: 架构设计

---

## 1. 问题诊断

### 1.1 当前 Qwen3-TTS 音色实现

当前 `src/core/tts/__init__.py` 中的 `Qwen3TTSEngine` 存在以下问题：

| 问题 | 说明 |
|------|------|
| **API 调用方式过时** | 使用旧版 `Qwen3TTS().generate()` API，不支持 voice design / voice clone |
| **仅 9 种预设音色** | 使用 CustomVoice 模型，speaker 名称写死（Vivian/Serena 等），无法自定义 |
| **无 Voice Design 能力** | Qwen3-TTS 1.7B-VoiceDesign 模型支持自然语言描述音色，当前完全未集成 |
| **无 instruct 控制** | CustomVoice 模型支持 `instruct` 参数控制语气，当前未暴露 |
| **模型加载极慢** | 单次加载需 30-60s（8.4GB 模型），每次切换引擎都重新加载 |
| **GUI 无音色分类** | Qwen3 和 Edge-TTS 音色混在同一个 ComboBox，没有类型区分 |

### 1.2 Qwen3-TTS 三种音色模式（来自官方 README）

根据官方 README，Qwen3-TTS 提供 **三种音色生成模式**，使用不同的模型：

| 模式 | 模型 | API | 音色来源 | 特点 |
|------|------|-----|---------|------|
| **CustomVoice** | 1.7B-CustomVoice | `generate_custom_voice(text, language, speaker, instruct)` | 9 种预设 speaker | 快速，支持 instruct 控制语气 |
| **VoiceDesign** | 1.7B-VoiceDesign | `generate_voice_design(text, language, instruct)` | 自然语言描述 | 灵活，可描述任意音色 |
| **VoiceClone** | 1.7B-Base | `generate_voice_clone(text, language, ref_audio, ref_text)` | 参考音频 | 克隆任意音色 |
| **Design→Clone** | VoiceDesign + Base | 先 design 生成参考音频 → 再 clone 复用 | 设计后的音色 | **最优方案：兼顾灵活性和速度** |

---

## 2. 架构设计

### 2.1 整体思路

将 TTS 音色系统分为 **三层架构**：

```
┌─────────────────────────────────────────────────┐
│                   GUI 层                         │
│  ┌──────────┐  ┌──────────────┐  ┌────────────┐ │
│  │ 预设音色  │  │ 自定义音色   │  │ 克隆音色   │ │
│  │ (下拉框) │  │ (文本输入)   │  │ (音频上传) │ │
│  └────┬─────┘  └──────┬───────┘  └─────┬──────┘ │
│       └────────┬──────┘                 │        │
├────────────────┼────────────────────────┼────────┤
│                │     VoiceProfile 层    │        │
│  ┌─────────────▼────────────────────────▼──────┐ │
│  │  VoiceProfileManager (音色配置中心)         │ │
│  │  - 预设 profiles (JSON)                     │ │
│  │  - 自定义 instruct → 预生成 prompt          │ │
│  │  - clone prompt 缓存                        │ │
│  └──────────────────┬─────────────────────────┘ │
├─────────────────────┼───────────────────────────┤
│                     │     Engine 层              │
│  ┌──────────────────▼─────────────────────────┐ │
│  │  TTSEngine (统一接口)                       │ │
│  │  ├─ EdgeTTSEngine     (云端)               │ │
│  │  ├─ Qwen3CustomVoice  (本地 GPU, 预设音色) │ │
│  │  ├─ Qwen3VoiceDesign  (本地 GPU, 自定义)   │ │
│  │  └─ Qwen3VoiceClone   (本地 GPU, 克隆)     │ │
│  └────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────┘
```

### 2.2 核心概念：VoiceProfile

引入 `VoiceProfile` 数据结构，统一描述所有音色来源：

```python
@dataclass
class VoiceProfile:
    """音色配置（跨引擎统一描述）"""
    name: str              # 显示名: "温柔大姐姐"
    engine: str            # 引擎类型: "edge" / "qwen3_custom" / "qwen3_design" / "qwen3_clone"
    description: str       # 描述: "温柔、低沉、成熟的女性声线"

    # Edge-TTS 专用
    edge_voice: str = ""   # "zh-CN-XiaoxiaoNeural"

    # Qwen3 CustomVoice 专用
    qwen3_speaker: str = ""    # "Vivian"
    qwen3_instruct: str = ""   # "用温柔的语气说"

    # Qwen3 VoiceDesign 专用
    design_instruct: str = ""  # "温柔成熟的大姐姐声线，音调偏低，语速舒缓"

    # Qwen3 VoiceClone 专用
    clone_ref_audio: str = ""  # 参考音频路径
    clone_ref_text: str = ""   # 参考音频对应的文本
    clone_prompt_path: str = "" # 预生成的 voice_clone_prompt 缓存路径

    # 预生成参考音频（Design→Clone 方案）
    ref_audio_path: str = ""   # 预生成的参考音频 wav 路径
```

### 2.3 音色分类

GUI 中将音色分为 **三类**，使用 Tab 或分组展示：

#### 类型 A：预设音色 (CustomVoice 模型)

内置 Qwen3-TTS 的 9 种预设 speaker，加上 ASMR 场景精选的 instruct 预设：

| 编号 | 音色名 | Speaker | Instruct | 适用场景 |
|------|--------|---------|----------|---------|
| A1 | 甜美少女 | Vivian | (空) | 通用 |
| A2 | 温柔姐姐 | Serena | 用温柔体贴的语气说 | 治愈系 ASMR |
| A3 | 成熟大叔 | Uncle_Fu | (空) | 通用 |
| A4 | 清爽少年 | Dylan | (空) | 通用 |
| A5 | 活力青年 | Eric | 用活泼开朗的语气说 | 轻松系 ASMR |
| A6 | 英文男声 | Ryan | (空) | 英文内容 |
| A7 | 日语少女 | Ono_Anna | (空) | 日文内容 |

#### 类型 B：自定义音色 (VoiceDesign 模型)

用户输入自然语言描述，系统预设 3-5 个 ASMR 专用提示词：

| 编号 | 音色名 | Instruct (自然语言) | 适用场景 |
|------|--------|-------------------|---------|
| B1 | 治愈大姐姐 | 温柔成熟的大姐姐声线，音调偏低，语速舒缓，带有让人安心的气息感 | 治愈系 ASMR |
| B2 | 娇小萝莉 | 撒娇稚嫩的少女声线，音调偏高且起伏明显，语气黏人可爱，带有做作卖萌感 | 萝莉系 ASMR |
| B3 | 冷艳女王 | 冷静优雅的女性声线，音调平稳，语速偏慢，带有压迫感和掌控力 | 女王系 ASMR |
| B4 | 温柔暖男 | 温暖低沉的男性声线，音色圆润厚实，语速舒缓，带有包容感 | 男性 ASMR |
| B5 | 用户自定义 | (用户输入) | 任意 |

#### 类型 C：克隆音色 (VoiceClone 模型)

用户提供参考音频文件，系统克隆该音色。

---

## 3. 模型加载优化

### 3.1 问题：模型启动极慢

Qwen3-TTS 1.7B 模型加载需要 30-60s（含 GPU 加载）。如果用户频繁切换音色，体验极差。

### 3.2 方案：VoiceDesign → VoiceClone 预生成

**核心思路**：VoiceDesign 模型只需运行一次，生成一段参考音频，然后用 VoiceClone 模型快速复用。

```
┌─────────────────────────────────────────────────────────┐
│  用户选择"治愈大姐姐"音色                                │
│           ↓                                             │
│  ① 检查预生成缓存: models/voice_profiles/B1_ref.wav     │
│     ├─ 存在 → 直接加载 voice_clone_prompt (快速!)        │
│     └─ 不存在 → ② 使用 VoiceDesign 模型生成参考音频      │
│                 → 保存到 models/voice_profiles/B1_ref.wav│
│                 → ③ 用 Base 模型创建 voice_clone_prompt  │
│                 → 保存 prompt 序列化文件                  │
│           ↓                                             │
│  ④ 后续所有句子用 VoiceClone + 缓存的 prompt 快速合成     │
└─────────────────────────────────────────────────────────┘
```

### 3.3 模型策略

| 场景 | 使用的模型 | 加载时间 | 合成速度 |
|------|-----------|---------|---------|
| 预设音色 (CustomVoice) | 1.7B-CustomVoice | 首次 30-60s | ~4s/句 |
| 自定义音色 (VoiceDesign) | 1.7B-VoiceDesign + 1.7B-Base | 首次 60-120s（生成参考音频）| ~4s/句（后续用 clone） |
| 自定义音色 (缓存命中) | 1.7B-Base（只用 clone） | 首次 30-60s | ~4s/句 |
| 克隆音色 | 1.7B-Base | 首次 30-60s | ~4s/句 |

### 3.4 模型预加载策略

```python
class Qwen3ModelManager:
    """Qwen3 模型管理器 - 预加载 + 复用"""

    _instances = {}  # 模型单例缓存

    @classmethod
    def get_custom_voice_model(cls):
        """获取 CustomVoice 模型（延迟加载）"""
        if "custom_voice" not in cls._instances:
            model = Qwen3TTSModel.from_pretrained(
                "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice",
                device_map="cuda:0",
                dtype=torch.bfloat16,
            )
            cls._instances["custom_voice"] = model
        return cls._instances["custom_voice"]

    @classmethod
    def get_voice_design_model(cls):
        """获取 VoiceDesign 模型（延迟加载）"""
        if "voice_design" not in cls._instances:
            model = Qwen3TTSModel.from_pretrained(
                "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign",
                device_map="cuda:0",
                dtype=torch.bfloat16,
            )
            cls._instances["voice_design"] = model
        return cls._instances["voice_design"]

    @classmethod
    def get_base_model(cls):
        """获取 Base 模型（延迟加载）"""
        if "base" not in cls._instances:
            model = Qwen3TTSModel.from_pretrained(
                "Qwen/Qwen3-TTS-12Hz-1.7B-Base",
                device_map="cuda:0",
                dtype=torch.bfloat16,
            )
            cls._instances["base"] = model
        return cls._instances["base"]

    @classmethod
    def unload_all(cls):
        """卸载所有模型释放显存"""
        for name, model in cls._instances.items():
            del model
        cls._instances.clear()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
```

### 3.5 显存管理

RTX 4070 Ti SUPER (16GB) 显存预算：

| 组件 | 显存占用 |
|------|---------|
| Demucs (htdemucs) | ~1.5GB |
| Whisper (large-v3) | ~3GB |
| Qwen3-TTS 1.7B (bfloat16) | ~3.5GB |
| **合计最大** | **~8GB** |

策略：Pipeline 同一时刻只需一个 TTS 模型，Demucs/Whisper 用完即卸载。因此 **最多同时加载 1 个 Qwen3 模型 + 1 个分离/识别模型**，显存足够。

但 VoiceDesign → Clone 方案需要同时加载两个模型。解决方案：
- **方案 A（推荐）**: 预生成阶段分两步：先用 VoiceDesign 生成参考音频，卸载后用 Base 创建 prompt。不要求同时加载两个模型。
- **方案 B**: 使用 0.6B 模型做预生成（精度略降但显存占用减半）

---

## 4. 预生成音色系统

### 4.1 目录结构

```
models/
├── voice_profiles/           # 预生成音色目录 (新增)
│   ├── profiles.json         # 音色配置文件
│   ├── B1_ref.wav            # "治愈大姐姐" 预生成参考音频
│   ├── B1_prompt.pt          # voice_clone_prompt 缓存
│   ├── B2_ref.wav            # "娇小萝莉" 预生成参考音频
│   ├── B2_prompt.pt          # ...
│   ├── B3_ref.wav            # "冷艳女王"
│   ├── B3_prompt.pt
│   ├── B4_ref.wav            # "温柔暖男"
│   └── B4_prompt.pt
├── qwen3tts/
│   ├── Qwen3-TTS-12Hz-1.7B-CustomVoice/   # (已有)
│   ├── Qwen3-TTS-12Hz-1.7B-VoiceDesign/   # (需下载)
│   └── Qwen3-TTS-12Hz-1.7B-Base/          # (需下载)
└── whisper/
```

### 4.2 profiles.json 格式

```json
{
  "version": 1,
  "profiles": [
    {
      "id": "A1",
      "name": "甜美少女",
      "category": "preset",
      "engine": "qwen3_custom",
      "speaker": "Vivian",
      "instruct": "",
      "description": "甜美、略带俏皮的年轻女声"
    },
    {
      "id": "A2",
      "name": "温柔姐姐",
      "category": "preset",
      "engine": "qwen3_custom",
      "speaker": "Serena",
      "instruct": "用温柔体贴的语气说",
      "description": "温暖、温柔、贴心的年轻女声"
    },
    {
      "id": "B1",
      "name": "治愈大姐姐",
      "category": "custom",
      "engine": "qwen3_clone",
      "design_instruct": "温柔成熟的大姐姐声线，音调偏低，语速舒缓，带有让人安心的气息感",
      "ref_audio": "models/voice_profiles/B1_ref.wav",
      "prompt_cache": "models/voice_profiles/B1_prompt.pt",
      "description": "温柔成熟的大姐姐，治愈系ASMR专用"
    },
    {
      "id": "B2",
      "name": "娇小萝莉",
      "category": "custom",
      "engine": "qwen3_clone",
      "design_instruct": "撒娇稚嫩的少女声线，音调偏高且起伏明显，语气黏人可爱，带有做作卖萌感",
      "ref_audio": "models/voice_profiles/B2_ref.wav",
      "prompt_cache": "models/voice_profiles/B2_prompt.pt",
      "description": "撒娇卖萌的萝莉少女声线"
    },
    {
      "id": "B3",
      "name": "冷艳女王",
      "category": "custom",
      "engine": "qwen3_clone",
      "design_instruct": "冷静优雅的女性声线，音调平稳，语速偏慢，带有压迫感和掌控力",
      "ref_audio": "models/voice_profiles/B3_ref.wav",
      "prompt_cache": "models/voice_profiles/B3_prompt.pt",
      "description": "高贵冷艳的女王声线"
    },
    {
      "id": "B4",
      "name": "温柔暖男",
      "category": "custom",
      "engine": "qwen3_clone",
      "design_instruct": "温暖低沉的男性声线，音色圆润厚实，语速舒缓，带有包容感",
      "ref_audio": "models/voice_profiles/B4_ref.wav",
      "prompt_cache": "models/voice_profiles/B4_prompt.pt",
      "description": "温暖包容的成熟男性声线"
    }
  ]
}
```

### 4.3 预生成脚本

`scripts/generate_voice_profiles.py` - 一键生成所有预设的参考音频和 prompt：

```python
"""预生成所有自定义音色的参考音频和 voice_clone_prompt"""

import torch
import soundfile as sf
from pathlib import Path
from qwen_tts import Qwen3TTSModel

# 参考文本（用于生成参考音频和创建 clone prompt）
REF_TEXT = "你好，今天辛苦了，让我来帮你放松一下吧。"

# 音色配置
PROFILES = [
    ("B1", "治愈大姐姐", "温柔成熟的大姐姐声线，音调偏低，语速舒缓，带有让人安心的气息感"),
    ("B2", "娇小萝莉", "撒娇稚嫩的少女声线，音调偏高且起伏明显，语气黏人可爱，带有做作卖萌感"),
    ("B3", "冷艳女王", "冷静优雅的女性声线，音调平稳，语速偏慢，带有压迫感和掌控力"),
    ("B4", "温柔暖男", "温暖低沉的男性声线，音色圆润厚实，语速舒缓，带有包容感"),
]

def main():
    output_dir = Path("models/voice_profiles")
    output_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: 用 VoiceDesign 模型生成参考音频
    print("加载 VoiceDesign 模型...")
    design_model = Qwen3TTSModel.from_pretrained(
        "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign",
        device_map="cuda:0",
        dtype=torch.bfloat16,
    )

    ref_audios = {}
    for profile_id, name, instruct in PROFILES:
        print(f"生成参考音频: {name}...")
        wavs, sr = design_model.generate_voice_design(
            text=REF_TEXT,
            language="Chinese",
            instruct=instruct,
        )
        ref_path = output_dir / f"{profile_id}_ref.wav"
        sf.write(str(ref_path), wavs[0], sr)
        ref_audios[profile_id] = (wavs[0], sr, REF_TEXT)
        print(f"  -> {ref_path}")

    del design_model
    torch.cuda.empty_cache()

    # Step 2: 用 Base 模型创建 voice_clone_prompt
    print("加载 Base 模型...")
    base_model = Qwen3TTSModel.from_pretrained(
        "Qwen/Qwen3-TTS-12Hz-1.7B-Base",
        device_map="cuda:0",
        dtype=torch.bfloat16,
    )

    for profile_id, name, _ in PROFILES:
        wav, sr, ref_text = ref_audios[profile_id]
        print(f"创建 clone prompt: {name}...")

        prompt = base_model.create_voice_clone_prompt(
            ref_audio=(wav, sr),
            ref_text=ref_text,
        )

        # 序列化保存
        prompt_path = output_dir / f"{profile_id}_prompt.pt"
        torch.save(prompt, str(prompt_path))
        print(f"  -> {prompt_path}")

    print("全部完成!")

if __name__ == "__main__":
    main()
```

---

## 5. 代码改造方案

### 5.1 新增文件

| 文件 | 说明 |
|------|------|
| `src/core/tts/voice_profile.py` | VoiceProfile 数据类 + VoiceProfileManager |
| `src/core/tts/qwen3_manager.py` | Qwen3ModelManager（模型单例 + 预加载） |
| `scripts/generate_voice_profiles.py` | 预生成音色脚本 |
| `config/voice_profiles.json` | 预设音色配置文件 |

### 5.2 修改文件

| 文件 | 改动 |
|------|------|
| `src/core/tts/__init__.py` | 重写 Qwen3TTSEngine，支持 3 种模式；TTSEngine 支持 voice_profile 参数 |
| `src/core/pipeline/__init__.py` | PipelineConfig 新增 voice_profile_id 字段 |
| `src/gui.py` | TTS 设置区域重构：音色分类 Tab、自定义 instruct 输入、克隆音频上传 |

### 5.3 `voice_profile.py` 核心设计

```python
# src/core/tts/voice_profile.py

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List
import json

@dataclass
class VoiceProfile:
    """统一音色配置"""
    id: str
    name: str
    category: Literal["preset", "custom", "clone", "edge"]
    engine: str
    description: str = ""

    # CustomVoice 参数
    speaker: str = ""
    instruct: str = ""

    # VoiceDesign 参数
    design_instruct: str = ""

    # VoiceClone 参数
    clone_ref_audio: str = ""
    clone_ref_text: str = ""

    # 预生成缓存
    ref_audio_path: str = ""
    prompt_cache_path: str = ""

    # Edge-TTS 参数
    edge_voice: str = ""


class VoiceProfileManager:
    """音色配置管理器"""

    def __init__(self, config_path: str = None):
        self.config_path = Path(config_path or "config/voice_profiles.json")
        self.profiles: List[VoiceProfile] = []
        self._load()

    def _load(self):
        """加载配置"""
        if not self.config_path.exists():
            self._create_default()
            return

        with open(self.config_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        for p in data.get("profiles", []):
            self.profiles.append(VoiceProfile(**p))

    def get_by_id(self, profile_id: str) -> Optional[VoiceProfile]:
        """按 ID 获取音色"""
        for p in self.profiles:
            if p.id == profile_id:
                return p
        return None

    def get_presets(self) -> List[VoiceProfile]:
        """获取所有预设音色"""
        return [p for p in self.profiles if p.category == "preset"]

    def get_customs(self) -> List[VoiceProfile]:
        """获取所有自定义音色"""
        return [p for p in self.profiles if p.category == "custom"]

    def add_custom(self, profile: VoiceProfile):
        """添加自定义音色"""
        self.profiles.append(profile)
        self._save()

    def _save(self):
        """保存配置"""
        data = {
            "version": 1,
            "profiles": [
                {k: v for k, v in p.__dict__.items() if v}
                for p in self.profiles
            ]
        }
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
```

### 5.4 `Qwen3TTSEngine` 改造

```python
# src/core/tts/__init__.py (改造后)

class Qwen3TTSEngine:
    """Qwen3-TTS 引擎 - 支持 CustomVoice / VoiceDesign / VoiceClone 三种模式"""

    def __init__(self, voice_profile: VoiceProfile = None, speed: float = 1.0):
        self.profile = voice_profile
        self.speed = speed
        self._clone_prompt = None  # 缓存的 voice_clone_prompt

    def synthesize(self, text: str, output_path: str) -> str:
        """根据 profile 类型选择不同的合成方法"""
        if self.profile.category == "preset":
            return self._synthesize_custom_voice(text, output_path)
        elif self.profile.category == "custom":
            return self._synthesize_from_cache(text, output_path)
        elif self.profile.category == "clone":
            return self._synthesize_clone(text, output_path)

    def _synthesize_custom_voice(self, text, output_path):
        """CustomVoice 模式"""
        model = Qwen3ModelManager.get_custom_voice_model()
        wavs, sr = model.generate_custom_voice(
            text=text,
            language="Chinese",
            speaker=self.profile.speaker,
            instruct=self.profile.instruct,
        )
        sf.write(output_path, wavs[0], sr)
        return output_path

    def _synthesize_from_cache(self, text, output_path):
        """VoiceDesign 预生成 → VoiceClone 快速合成"""
        model = Qwen3ModelManager.get_base_model()

        # 加载预生成的 prompt（首次时自动创建）
        if self._clone_prompt is None:
            prompt_path = Path(self.profile.prompt_cache_path)
            if prompt_path.exists():
                self._clone_prompt = torch.load(str(prompt_path))
            else:
                # 按需生成（触发 VoiceDesign + Base 两步）
                self._generate_ref_and_prompt()

        wavs, sr = model.generate_voice_clone(
            text=text,
            language="Chinese",
            voice_clone_prompt=self._clone_prompt,
        )
        sf.write(output_path, wavs[0], sr)
        return output_path
```

### 5.5 GUI 改造

TTS 设置区域从单一 ComboBox 改为 **分类 Tab**：

```
┌─ TTS 设置 ─────────────────────────────────────────────────────┐
│ 引擎: [Edge-TTS ▾]  [Qwen3-TTS ▾]                             │
│                                                                │
│ ┌─音色选择────────────────────────────────────────────────────┐ │
│ │ [预设音色] [自定义音色] [克隆音色]     ← QTabWidget        │ │
│ │                                                            │ │
│ │ 预设音色 Tab:                                              │ │
│ │ ┌──────────────────────────────────────────────────────┐   │ │
│ │ │ ○ 甜美少女 (Vivian)                                 │   │ │
│ │ │ ○ 温柔姐姐 (Serena) + instruct: [用温柔体贴的语气说] │   │ │
│ │ │ ○ 成熟大叔 (Uncle_Fu)                               │   │ │
│ │ │ ...                                                 │   │ │
│ │ └──────────────────────────────────────────────────────┘   │ │
│ │                                                            │ │
│ │ 自定义音色 Tab:                                            │ │
│ │ ┌──────────────────────────────────────────────────────┐   │ │
│ │ │ ○ 治愈大姐姐 (预生成)                    [试音]       │   │ │
│ │ │ ○ 娇小萝莉 (预生成)                      [试音]       │   │ │
│ │ │ ○ 冷艳女王 (预生成)                      [试音]       │   │ │
│ │ │ ○ 温柔暖男 (预生成)                      [试音]       │   │ │
│ │ │ ○ 自定义:                                           │   │ │
│ │ │   [自然语言描述输入框，如"音调偏高的元气少女声线..."]  │   │ │
│ │ │   [生成参考音频] 按钮                                  │   │ │
│ │ └──────────────────────────────────────────────────────┘   │ │
│ │                                                            │ │
│ │ 克隆音色 Tab:                                              │ │
│ │ ┌──────────────────────────────────────────────────────┐   │ │
│ │ │ 参考音频: [选择文件... (3s以上)]                      │   │ │
│ │ │ 参考文本: [________________]                          │   │ │
│ │ │ [创建克隆] 按钮                                       │   │ │
│ │ └──────────────────────────────────────────────────────┘   │ │
│ └────────────────────────────────────────────────────────────┘ │
│                                                                │
│ 语速: [1.0 ▾ x]          [试音]                               │
└────────────────────────────────────────────────────────────────┘
```

---

## 6. 实施计划

### P0 - 核心功能（优先）

| 任务 | 预估 | 文件 |
|------|------|------|
| 下载 VoiceDesign + Base 模型 | 10min | `models/qwen3tts/` |
| 实现 VoiceProfile + Manager | 1h | `src/core/tts/voice_profile.py` (新建) |
| 实现 Qwen3ModelManager | 1h | `src/core/tts/qwen3_manager.py` (新建) |
| 改造 Qwen3TTSEngine 支持 3 模式 | 2h | `src/core/tts/__init__.py` |
| 创建 voice_profiles.json | 30min | `config/voice_profiles.json` (新建) |
| 预生成脚本 | 1h | `scripts/generate_voice_profiles.py` (新建) |

### P1 - GUI + 集成

| 任务 | 预估 | 文件 |
|------|------|------|
| GUI TTS 区域重构（音色分类 Tab） | 3h | `src/gui.py` |
| Pipeline 集成 voice_profile | 1h | `src/core/pipeline/__init__.py` |
| 试音功能适配新引擎 | 30min | `src/gui.py` |

### P2 - 体验优化

| 任务 | 预估 | 文件 |
|------|------|------|
| GUI 音色预览播放 | 1h | `src/gui.py` |
| 自定义音色即时生成 + 缓存 | 1h | `src/core/tts/voice_profile.py` |
| 模型预加载提示（加载动画） | 30min | `src/gui.py` |

---

## 7. 风险评估

| 风险 | 等级 | 应对 |
|------|------|------|
| 显存不足（同时加载两个 Qwen3 模型） | **高** | 预生成时分步加载，不在同一时刻加载两个模型 |
| VoiceDesign 生成质量不稳定 | 中 | 使用精调的中文 instruct，参考文本选用通用短语 |
| voice_clone_prompt 序列化兼容性 | 低 | 使用 torch.save/load，版本一致即可 |
| 模型下载时间过长（~17GB） | 低 | 支持 ModelScope 镜像，提供手动下载指南 |
| CustomVoice instruct 对日语识别无效 | 低 | ASMR 场景 TTS 目标是中文翻译，instruct 用中文即可 |

---

## 8. 待确认事项

1. **是否需要同时支持 0.6B 和 1.7B 模型？** 0.6B 速度快但质量低，建议默认 1.7B
2. **预设的 CustomVoice instruct 是否需要持久化？** 当前设计保存在 voice_profiles.json 中
3. **克隆音色的参考音频是否支持从 GUI 拖拽上传？** 建议支持
4. **预生成音频的参考文本是否需要可配置？** 当前固定为"你好，今天辛苦了，让我来帮你放松一下吧。"
