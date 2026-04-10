# AsmrHelper 代码库重构计划

> 创建时间: 2026-04-09
> 状态: 进行中（P0/P1 已落地，P2 解耦推进中）

---

## 已完成的修复 ✅

### P0/P1 稳定性修复 (2026-04-10)

| # | 问题 | 文件 | 修复内容 |
|---|------|------|----------|
| 1 | GUI 单文件参数崩溃（single_asr_lang 未初始化） | `src/gui.py` | 单文件页补充 ASR 语言控件初始化并接入参数读取保护 |
| 2 | LRC 时间戳百分秒计算错误 | `src/core/pipeline/__init__.py` | `centiseconds` 改为 `(ms % 1000) // 10` |
| 3 | 翻译写回长度不一致静默截断 | `src/core/pipeline/__init__.py` | 新增 `_attach_translations()` 做补齐/截断与告警 |
| 4 | 无字幕 + skip_existing 时 ASR 时间戳丢失风险 | `src/core/pipeline/__init__.py` | 检测到旧文本时改为重新 ASR，保证下游时间轴完整 |
| 5 | 混音源判定误判 | `src/core/pipeline/__init__.py` | 用 `vocal_path` 与 `input_path` 对比 + source 双条件判定 |
| 6 | GUI 参数缺少统一校验 | `src/gui_validators.py`, `src/gui.py` | 新增单文件/批量参数校验器并在启动前阻断非法参数 |

### 高优先级 BUG 修复 (2026-04-09)

| # | 问题 | 文件 | 修复内容 |
|---|------|------|----------|
| 1 | `PreviewWorkerThread` 变量未定义 | `src/gui_workers.py:109` | 在 try 块前初始化 `output_path = None` |
| 2 | `VoiceCloneWorker` 变量未定义 | `src/gui_workers.py:511` | 在 try 块前初始化 `clone_result = None` |
| 3 | `Qwen3ModelManager.unload()` 内存泄漏 | `src/core/tts/qwen3_manager.py:112` | 先设为 None 再删除键，避免字典残留 |
| 4 | `Config.validate()` 边界检查错误 | `src/config.py:171` | `speed <= 0` 改为 `speed < 0.1` |

---

## 待实施重构计划

### 第一阶段：低风险重构（推荐优先实施）

#### 1. 创建统一的时间戳格式化工具

**问题**: 4处重复定义时间戳格式化函数

| 位置 | 函数名 | 行数 |
|------|--------|------|
| `src/core/asr/__init__.py` | `_format_srt_time()` | 296 |
| `src/core/asr/__init__.py` | `_format_lrc_time()` | 304 |
| `src/core/pipeline/__init__.py` | `_format_timestamp()` | 346 |
| `src/gui_workers.py` | `_fmt_ts()` | 883 |

**实施方案**:
```python
# 新建文件: src/utils/formatters.py
def format_timestamp(seconds: float, fmt: str = "srt") -> str:
    """统一时间戳格式化
    
    Args:
        seconds: 秒数
        fmt: 格式 - "srt"(HH:MM:SS,mmm), "vtt"(HH:MM:SS.mmm), "lrc"([MM:SS.xx])
    
    Returns:
        格式化后的时间字符串
    """
    if fmt == "lrc":
        minutes = int(seconds // 60)
        secs = seconds % 60
        return f"[{minutes:02d}:{secs:05.2f}]"
    
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds - int(seconds)) * 1000)
    
    if fmt == "srt":
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"
    else:  # vtt
        return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"
```

**替换步骤**:
1. 创建 `src/utils/formatters.py`
2. 在 `src/utils/__init__.py` 中添加导出
3. 替换 `asr/__init__.py` 中的两个函数
4. 替换 `pipeline/__init__.py` 中的 `_format_timestamp`
5. 替换 `gui_workers.py` 中的 `_fmt_ts`

---

#### 2. 统一 ffmpeg 路径获取

**问题**: 4种不同的 ffmpeg 获取方式

| 文件 | 当前方式 | 建议 |
|------|----------|------|
| `src/core/tts/__init__.py:92` | `imageio_ffmpeg.get_ffmpeg_exe()` | 使用 `from src.utils import get_ffmpeg` |
| `src/utils/__init__.py:12` | 封装函数 `get_ffmpeg()` | ✅ 保持 |
| `src/mixer/__init__.py:239` | 使用 `get_ffmpeg()` | ✅ 保持 |
| `src/gui_workers.py:984` | 直接调用 `"ffmpeg"` | 改为使用 `get_ffmpeg()` |

**修改点**:
- `src/core/tts/__init__.py:92-95`: 改为 `from src.utils import get_ffmpeg`
- `src/gui_workers.py:984`: 改为使用 `get_ffmpeg()`

---

#### 3. 移除 DEBUG 打印语句

**问题**: `src/core/translate/__init__.py:306-310` 有生产环境不应出现的 DEBUG 输出

```python
# 当前代码（应删除或修改）
print(f"[DEBUG] API 返回字段: {list(first_result.keys())}")
print(f"[DEBUG] 示例数据: {first_result}")
```

**方案**: 直接删除这两行，或改为 `import logging; logging.debug(...)`

---

#### 4. 规范化 import 语句位置

**问题**: 多处方法内部导入模块

| 模块 | 当前位置 | 建议 |
|------|----------|------|
| `time` | `gui_workers.py` 多处方法内 | 移到文件顶部 |
| `re` | `translate/__init__.py:750` 方法内 | 移到文件顶部 |
| `subprocess` | `tts/__init__.py:93` 方法内 | 移到文件顶部 |

**修改文件**:
- `src/gui_workers.py`: 在顶部添加 `import time`
- `src/core/translate/__init__.py`: 在顶部添加 `import re`
- `src/core/tts/__init__.py`: 在顶部添加 `import subprocess`

---

### 第二阶段：中风险重构

#### 5. 统一字幕加载函数

**问题**: `src/core/translate/__init__.py` 中有6组几乎相同的字幕加载函数（约400行重复代码）

| 函数名 | 行数范围 | 功能 |
|--------|----------|------|
| `load_vtt_translations()` | 670-731 | 加载VTT文本 |
| `load_vtt_with_timestamps()` | 781-841 | 加载VTT带时间戳 |
| `load_srt_translations()` | 863-921 | 加载SRT文本 |
| `load_srt_with_timestamps()` | 924-982 | 加载SRT带时间戳 |
| `load_lrc_translations()` | 999-1038 | 加载LRC文本 |
| `load_lrc_with_timestamps()` | 1041-1092 | 加载LRC带时间戳 |

**方案**: 新建 `src/utils/subtitle_loader.py`

```python
from typing import List, Dict, Union
from pathlib import Path

def load_subtitle(
    subtitle_path: str,
    fmt: str = "auto",  # "auto", "vtt", "srt", "lrc"
    with_timestamps: bool = False
) -> Union[List[str], List[Dict]]:
    """统一字幕加载函数
    
    Args:
        subtitle_path: 字幕文件路径
        fmt: 格式，auto自动检测
        with_timestamps: 是否包含时间戳信息
    
    Returns:
        with_timestamps=False: List[str] 文本列表
        with_timestamps=True: List[Dict] [{"text": str, "start": float, "end": float}, ...]
    """
    pass  # 实现统一的解析逻辑
```

**替换步骤**:
1. 创建 `src/utils/subtitle_loader.py`
2. 实现统一的 VTT/SRT/LRC 解析逻辑
3. 删除 `translate/__init__.py` 中的6个旧函数
4. 更新所有调用点使用新函数

---

### 第三阶段：高风险重构（需谨慎）

#### 6. TTSEngine 注册表机制简化

**问题**: `src/core/tts/__init__.py:408-527` 的 `_registry` 字典存储默认参数但未被实际使用

**分析**:
- `_registry` 字典存储了引擎默认参数
- `get_engine_class()` 方法从未被调用
- `available_engines()` 方法仅在 CLI presets 命令中使用
- 实际只有 3 个 if-elif 分支，注册式工厂设计过度

**方案A（推荐）**: 移除注册表，简化为简单工厂
**方案B**: 让 `__init__` 实际读取注册表参数

**影响范围**: `src/core/tts/__init__.py` 中的 `TTSEngine` 类

---

#### 7. Pipeline.run() 方法拆分

**问题**: `run()` 方法约600行（`src/core/pipeline/__init__.py:358-959`），包含完整流水线逻辑

**方案**: 提取为独立步骤方法

```python
def run(self, preset=None, progress_callback=None):
    """运行流水线"""
    results = {}
    
    # Step 1: 人声分离
    if self.config.enable_vocal_separator:
        results['vocal'] = self._step_vocal_separator(progress_callback)
    
    # Step 2: ASR 识别
    if self.config.enable_asr:
        results['asr'] = self._step_asr(progress_callback)
    
    # Step 3: 翻译
    if self.config.enable_translate:
        results['translate'] = self._step_translate(progress_callback)
    
    # Step 4: TTS 合成
    if self.config.enable_tts:
        results['tts'] = self._step_tts(progress_callback)
    
    # Step 5: 混音
    if self.config.enable_mixer:
        results['mixer'] = self._step_mixer(progress_callback)
    
    return results
```

**影响**: 需要仔细测试每个步骤的边界条件

---

## 实施建议

### 推荐顺序

1. **第一阶段**（低风险，可立即实施）:
    - [x] 1. 统一时间戳格式化
    - [x] 2. 统一 ffmpeg 路径
    - [x] 3. 移除 DEBUG 打印
    - [x] 4. 规范化 import

2. **第二阶段**（中风险，需测试）:
    - [x] 5. 统一字幕加载函数（已提供统一入口，旧函数清理持续中）

3. **第三阶段**（高风险，需充分测试）:
    - [ ] 6. TTSEngine 注册表简化
    - [ ] 7. Pipeline.run() 拆分（已抽离 PathPlanner/StepResolver/SubtitleStrategy，StepExecutor/ArtifactCollector 待完成）

### 测试建议

- 每个重构后运行 `python -m pytest tests/`（如有测试）
- 手动测试核心功能：音色克隆、批量处理、字幕加载
- 检查日志输出是否正常

---

## 相关文件清单

### 需要修改的文件

| 文件路径 | 修改类型 | 优先级 |
|----------|----------|--------|
| `src/utils/formatters.py` | 新建 | 高 |
| `src/utils/subtitle_loader.py` | 新建 | 中 |
| `src/utils/__init__.py` | 修改导出 | 高 |
| `src/core/asr/__init__.py` | 修改 | 高 |
| `src/core/pipeline/__init__.py` | 修改 | 高 |
| `src/gui_workers.py` | 修改 | 高 |
| `src/core/tts/__init__.py` | 修改 | 高 |
| `src/core/translate/__init__.py` | 修改 | 中 |

### 参考文件（了解上下文）

- `src/core/tts/voice_profile.py` - 音色管理
- `src/core/tts/qwen3_manager.py` - 模型管理
- `src/config.py` - 配置验证

---

## 备注

- 所有路径均相对于项目根目录 `d:/WorkSpace/AsmrHelper/`
- 重构前建议创建分支或备份
- 如有疑问，参考已修复的 BUG 模式
