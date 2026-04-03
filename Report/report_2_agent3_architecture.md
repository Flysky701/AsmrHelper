# ASMR Helper — Agent3 架构指导报告

**报告编号**: report_2_agent3_architecture  
**出具人**: Agent3（架构评估 & 代码指导）  
**日期**: 2026-04-03  
**对接对象**: Agent1（代码实现）  
**审查基础**: Agent2 的 report_1.txt（Bug 交叉审查报告）+ 全量源码精读

---

## 一、总体可行性评估

### 1.1 现状概述

当前 AsmrHelper 已完成 **核心功能闭环**，各模块在技术选型上是合理的：

| 模块 | 技术选型 | 可行性 | 备注 |
|------|---------|--------|------|
| 人声分离 | Demucs 4.0 / CUDA | ✅ 已验证 | htdemucs, htdemucs_ft 均可用 |
| ASR | Faster-Whisper large-v3 | ✅ 已验证 | GPU float16，~23s/文件 |
| 翻译 | DeepSeek Chat API | ✅ 已验证 | 口语化效果良好 |
| TTS | Edge-TTS / Qwen3-TTS | ✅ 已验证 | 双引擎统一接口 |
| 混音 | ffmpeg filter_complex | ✅ 已验证 | amix 方案通过测试 |
| GUI | PySide6 6.9.2 + QThread | ✅ 已实现 | 单文件 + 批量双标签 |

### 1.2 已存在但尚未实现的功能

以下功能在待办列表中，具备实现条件，本报告将给出具体架构建议：

1. **GPT-SoVITS 语音克隆**（需要外部服务 localhost:9870）
2. **空间音频处理 / HRTF 双耳渲染**（需要 sofar/openAL 等）
3. **ASMR 术语库**（翻译质量强化）

### 1.3 Bug 修复状态（基于 report_1.txt）

经过精读代码，确认以下 Bug **已在当前代码中修复**：

| Bug 编号 | 描述 | 状态 |
|---------|------|------|
| BUG-01 | mixer subprocess 编码 | ✅ 已修复（text=True, encoding='utf-8'）|
| BUG-02 | pipeline translations NameError | ✅ 已修复（跳过时从文件读取）|
| BUG-03 | BatchWorkerThread 无 VTT 支持 | ✅ 已修复（已添加 _find_vtt_file）|
| BUG-04 | no_speech_threshold 方向错误 | ✅ 已修复（改为 0.9）|
| BUG-05 | asyncio.run 重复调用 | ✅ 已修复（改用 gather）|
| BUG-08 | mix_bilingual filter 参数 | ✅ 已修复（改用 amix 串联）|
| BUG-11 | VTT 多行字幕重复 | ✅ 已修复（改用 while loop 收集）|

**尚待确认的 Bug**：

| Bug 编号 | 描述 | 建议 Agent1 处理 |
|---------|------|----------------|
| BUG-06 | batch 的 vocal_model 硬编码 | 已在 BatchWorkerThread 中通过 params 传入，但 get_batch_params() GUI 侧需核查 |
| BUG-07 | VocalSeparator DEBUG 日志 | 代码中未发现 print DEBUG，可能已移除，需 Agent1 确认 |
| BUG-09 | preview_thread GC/重入问题 | 建议增加 isRunning() 检查 |
| BUG-10 | 批量处理 GPU 竞争 | 建议加文档说明 + 限制逻辑 |

---

## 二、架构诊断

### 2.1 当前架构分层图

```
┌─────────────────────────────────────────────┐
│              GUI 层 (src/gui.py)              │
│  MainWindow / SingleWorkerThread              │
│  BatchWorkerThread / PreviewWorkerThread      │
└──────────────┬──────────────────────────────┘
               │ 直接调用
┌──────────────▼──────────────────────────────┐
│            Pipeline 层                        │
│         src/core/pipeline/__init__.py         │
│   PipelineConfig + Pipeline.run()             │
└──────────────┬──────────────────────────────┘
               │ 调用各核心模块
┌──────────────▼──────────────────────────────┐
│            Core 模块层                        │
│  asr/    tts/    translate/    vocal_sep/     │
│  (各自独立，解耦良好)                         │
└──────────────┬──────────────────────────────┘
               │ 调用
┌──────────────▼──────────────────────────────┐
│            基础设施层                         │
│  src/utils/  src/mixer/  src/config.py        │
│  (ffmpeg, ensure_dir, Mixer)                  │
└─────────────────────────────────────────────┘
```

### 2.2 当前设计的问题

#### 问题 A：GUI 绕过 Pipeline 直接调用 Core

`SingleWorkerThread.run()` 和 `BatchWorkerThread.run()` 中，5个步骤全部直接实例化 Core 模块（`VocalSeparator`、`ASRRecognizer` 等），而**没有复用** `src/core/pipeline/Pipeline` 类。

这导致：
- 同一逻辑重复三份（GUI-单文件 / GUI-批量 / scripts/asmr_bilingual.py）
- 修改一处逻辑需同步修改三处
- 测试覆盖困难

**指导建议 → 见第三节 3.1**

#### 问题 B：TTS 文本合并策略粗糙

当前翻译文本以 `"。".join(translations)` 合并后一次性 TTS，丢失了时间戳信息。如果翻译段落数与 ASR 段落数相差较大，无法实现逐句对齐（时间轴同步）。

**指导建议 → 见第三节 3.2**

#### 问题 C：Qwen3TTS 每次调用都重新加载模型

`Qwen3TTSEngine.synthesize()` 中每次调用 `model = Qwen3TTS()` 都会重新加载模型（8.4GB），严重影响批量处理效率。

**指导建议 → 见第三节 3.3**

#### 问题 D：config.py 单例仅在进程内有效，无持久化通知机制

GUI 修改 API Key 后需要重启才能生效（因为 `Config` 单例已经加载）。

**指导建议 → 见第三节 3.4**

#### 问题 E：scripts/ 与 src/core/ 重复实现

`scripts/asmr_bilingual.py` 中的流水线逻辑与 `src/core/pipeline/__init__.py` 基本重复，后者维护的才是标准路径。

---

## 三、架构改进指导（Agent1 任务清单）

### 3.1 【高优先级】GUI 线程统一走 Pipeline

**目标**：`SingleWorkerThread` 和 `BatchWorkerThread` 不再直接调用 Core，改为委托 `Pipeline` 执行。

**接口设计**：

```python
# src/core/pipeline/__init__.py（改造点）
class Pipeline:
    def run(
        self,
        preset: Optional[str] = None,
        progress_callback: Optional[Callable[[str], None]] = None,  # 新增
    ) -> Dict[str, Any]:
        ...
        # 每步完成后调用回调
        if progress_callback:
            progress_callback(f"[Step {n}/5] 完成: {step_name}")
```

**GUI 侧改造**：

```python
# src/gui.py — SingleWorkerThread.run()
def run(self):
    try:
        from src.core.pipeline import Pipeline, PipelineConfig
        config = PipelineConfig(
            input_path=self.input_path,
            output_dir=self.output_dir,
            **self._params_to_pipeline_config(self.params),
        )
        pipeline = Pipeline(config)
        results = pipeline.run(progress_callback=self.progress.emit)
        
        mix_path = results.get("mix_path", "")
        self.finished.emit(bool(mix_path), mix_path)
    except Exception as e:
        import traceback; traceback.print_exc()
        self.finished.emit(False, str(e))

def _params_to_pipeline_config(self, params: dict) -> dict:
    """将 GUI params 映射为 PipelineConfig 字段名"""
    return {
        "vocal_model": params.get("vocal_model", "htdemucs"),
        "asr_model": params.get("asr_model", "large-v3"),
        "tts_engine": params.get("tts_engine", "edge"),
        "tts_voice": params.get("tts_voice", "zh-CN-XiaoxiaoNeural"),
        "qwen3_voice": params.get("qwen3_voice", "Vivian"),
        "original_volume": params.get("original_volume", 0.85),
        "tts_volume_ratio": params.get("tts_ratio", 0.5),
        "tts_delay_ms": params.get("tts_delay", 0),
    }
```

**健壮性要点**：
- `PipelineConfig` 要支持 `vtt_path: Optional[str]` 字段（当前缺少）
- Pipeline.run() 中 VTT 优先逻辑也要移入（目前只在 GUI 线程里）

---

### 3.2 【中优先级】逐句时间轴对齐 TTS（TimedTTS）

**目标**：按 ASR 时间戳逐句生成 TTS，然后在混音时插入静音对齐时间轴。

**接口设计**（新增 `src/core/tts/timed_tts.py`）：

```python
from dataclasses import dataclass
from typing import List
from pathlib import Path

@dataclass
class TimedSegment:
    start: float    # 起始时间（秒）
    end: float      # 结束时间（秒）
    text: str       # 翻译文本
    audio_path: str = ""  # TTS 合成结果路径

class TimedTTSEngine:
    """
    时间对齐 TTS：根据时间戳逐句合成，保持与原音同步。
    
    策略：
    1. 逐句合成 TTS 片段
    2. 计算每句 TTS 实际时长
    3. 在 Mixer 中用 adelay + concat 按时间戳拼接
    """
    
    def __init__(self, tts_engine: TTSEngine):
        self.tts_engine = tts_engine
    
    def synthesize_segments(
        self,
        segments: List[TimedSegment],
        output_dir: Path,
    ) -> List[TimedSegment]:
        """逐句合成，返回带 audio_path 的 segment 列表"""
        ...
    
    def build_timeline_audio(
        self,
        segments: List[TimedSegment],
        total_duration: float,
        output_path: Path,
    ) -> str:
        """
        将各段 TTS 按时间轴拼接，段间填充静音，
        生成与原音等长的配音轨道。
        """
        ...
```

**Mixer 侧对接**：

混音时传入已对齐的 TTS 轨道，无需额外的 `tts_delay_ms` 参数。

**可行性评估**：  
- Edge-TTS 合成速度快，可并发合成多段  
- 主要风险：TTS 合成时长 > ASR 段落时长时会溢出（需截断或加速处理）  
- 建议先实现"非对齐模式"（当前）+ "对齐模式"（新增），用户在 GUI 中选择

---

### 3.3 【中优先级】Qwen3TTS 模型单例化

**问题**：每次 `synthesize()` 都调用 `Qwen3TTS()` 重新加载约 8.4GB 模型。

**修复方案**：

```python
# src/core/tts/__init__.py
class Qwen3TTSEngine:
    _model_instance = None  # 类级别单例
    
    @classmethod
    def _get_model(cls):
        if cls._model_instance is None:
            from qwen_tts import Qwen3TTS
            cls._model_instance = Qwen3TTS()
            print("[Qwen3TTS] 模型已加载（单例）")
        return cls._model_instance
    
    def synthesize(self, text: str, output_path: str) -> str:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        model = self._get_model()  # 复用已加载模型
        model.generate(
            text,
            voice=self.voice,
            speed=self.speed,
            output_path=str(output_path),
        )
        return str(output_path)
```

**健壮性注意**：
- 若进程内切换 voice/speed，单例不需要重建（`generate()` 的参数每次独立传入）
- 若显存耗尽（与 Demucs/Whisper 同时运行），需 `del cls._model_instance; torch.cuda.empty_cache()`
- 建议在 Pipeline 中实现"模型卸载"接口，供批量处理顺序调用

---

### 3.4 【低优先级】Config 热更新

**问题**：GUI 的 API 配置对话框修改 Key 后，调用 `config.set()` + `config.save()` 虽然写了文件，但运行中的 `Translator` 仍使用旧 Key。

**修复方案**（最小改动）：

```python
# src/core/translate/__init__.py
class Translator:
    def __init__(self, provider, model, api_key=None, ...):
        # 不在 __init__ 中缓存 api_key，每次 translate 时从 config 读取
        self.provider = provider
        self.model = model
        self._api_key_override = api_key

    @property
    def api_key(self) -> str:
        if self._api_key_override:
            return self._api_key_override
        return config.get_api_key(self.provider)
    
    def _get_client(self) -> OpenAI:
        """每次调用都重新构建客户端（保证 key 最新）"""
        return OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
        )
    
    def translate(self, text: str, ...) -> str:
        response = self._get_client().chat.completions.create(...)
        ...
```

---

### 3.5 【新功能】GPT-SoVITS 语音克隆集成

**可行性**：已知需要外部服务 `localhost:9870`（GPT-SoVITS WebUI API）。

**架构建议**：在 `src/core/tts/` 下新增 `gptsovits.py`：

```python
# src/core/tts/gptsovits.py
import requests
from pathlib import Path

class GPTSoVITSEngine:
    """GPT-SoVITS 语音克隆引擎（通过 HTTP API 调用本地服务）"""
    
    DEFAULT_API_URL = "http://localhost:9870"
    
    def __init__(
        self,
        api_url: str = DEFAULT_API_URL,
        ref_audio_path: str = "",   # 参考音频（克隆声线）
        ref_text: str = "",          # 参考音频的文本
        language: str = "zh",
    ):
        self.api_url = api_url
        self.ref_audio_path = ref_audio_path
        self.ref_text = ref_text
        self.language = language
        self._check_service()
    
    def _check_service(self):
        """检查服务是否可用"""
        try:
            resp = requests.get(f"{self.api_url}/", timeout=3)
            resp.raise_for_status()
        except Exception as e:
            raise ConnectionError(
                f"GPT-SoVITS 服务不可用 ({self.api_url})，请先启动服务: {e}"
            )
    
    def synthesize(self, text: str, output_path: str) -> str:
        """调用 GPT-SoVITS API 合成语音"""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        payload = {
            "refer_wav_path": self.ref_audio_path,
            "prompt_text": self.ref_text,
            "prompt_language": "ja",   # 参考音频语言
            "text": text,
            "text_language": self.language,
        }
        
        resp = requests.post(
            f"{self.api_url}/",
            json=payload,
            timeout=60,
        )
        resp.raise_for_status()
        
        output_path.write_bytes(resp.content)
        return str(output_path)
```

**TTSEngine 注册方式**（TTSEngine 统一接口适配）：

```python
# src/core/tts/__init__.py
class TTSEngine:
    ENGINES = {
        "edge": EdgeTTSEngine,
        "qwen3": Qwen3TTSEngine,
        "gptsovits": None,  # 延迟导入，避免服务未启动时报错
    }
    
    def __init__(self, engine="edge", ...):
        if engine == "gptsovits":
            from .gptsovits import GPTSoVITSEngine
            self.engine = GPTSoVITSEngine(
                ref_audio_path=kwargs.get("ref_audio", ""),
                ref_text=kwargs.get("ref_text", ""),
            )
        ...
```

**GUI 侧集成要点**：
- 引擎选择下拉加入 "GPT-SoVITS"
- 选中后显示"参考音频"和"参考文本"输入框
- 启动前做 `_check_service()` 校验，失败弹出提示

---

### 3.6 【新功能】ASMR 术语库（翻译质量强化）

**架构建议**：在 `src/core/translate/` 下新增 `terminology.py`：

```python
# src/core/translate/terminology.py
import json
from pathlib import Path
from typing import Dict, Optional

TERM_DB_PATH = Path(__file__).parent.parent.parent.parent / "config" / "asmr_terms.json"

class TerminologyDB:
    """ASMR 专用术语库，辅助翻译提示词构建"""
    
    _default_terms: Dict[str, str] = {
        # 常见 ASMR 用语
        "ご主人様": "主人",
        "お兄ちゃん": "哥哥",
        "お姉ちゃん": "姐姐",
        "はい": "嗯",
        "ふふ": "呵呵",
        "もふもふ": "毛茸茸的",
    }
    
    def __init__(self):
        self._terms = dict(self._default_terms)
        self._load_user_terms()
    
    def _load_user_terms(self):
        if TERM_DB_PATH.exists():
            try:
                user_terms = json.loads(TERM_DB_PATH.read_text(encoding="utf-8"))
                self._terms.update(user_terms)
            except Exception as e:
                print(f"[TermDB] 加载失败: {e}")
    
    def build_system_prompt(
        self,
        source_lang: str = "日文",
        target_lang: str = "中文",
    ) -> str:
        """构建含术语约束的翻译系统提示词"""
        term_hints = "\n".join(
            f"- {k} → {v}" for k, v in list(self._terms.items())[:20]
        )
        return (
            f"你是一个专业的{source_lang}翻译，专注于 ASMR 音声内容。"
            f"请将{source_lang}翻译成{target_lang}，保持自然流畅、口语化。\n"
            f"以下术语请按约定翻译：\n{term_hints}"
        )
    
    def add_term(self, source: str, target: str):
        self._terms[source] = target
        self._save()
    
    def _save(self):
        TERM_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        TERM_DB_PATH.write_text(
            json.dumps(self._terms, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
```

**Translator 接入**：

```python
# src/core/translate/__init__.py
from .terminology import TerminologyDB

class Translator:
    def __init__(self, ..., use_terminology: bool = True):
        self.term_db = TerminologyDB() if use_terminology else None
    
    def translate_batch(self, texts, source_lang="日文", target_lang="中文", ...):
        system_prompt = (
            self.term_db.build_system_prompt(source_lang, target_lang)
            if self.term_db else
            f"你是专业{source_lang}翻译，请翻译成{target_lang}，口语化。"
        )
        ...
```

---

### 3.7 【新功能】空间音频/HRTF 双耳渲染

**可行性评估**：

空间音频处理对 ASMR 场景有意义，但实现复杂度高，依赖专业库。建议分两期：

**一期（简单实现）**：

使用 ffmpeg `pan` 滤镜模拟左右耳定向效果：

```python
# src/mixer/__init__.py 新增方法
def apply_3d_panning(
    self,
    audio_path: str,
    output_path: str,
    pan_position: float = 0.0,   # -1.0 (全左) ~ 1.0 (全右)
) -> str:
    """
    简单声像定位（非真实 HRTF）
    pan_position: -1.0=全左耳, 0.0=中央, 1.0=全右耳
    """
    left_gain = 1.0 - max(0, pan_position)
    right_gain = 1.0 + min(0, pan_position)
    
    cmd = [
        get_ffmpeg(),
        "-i", audio_path,
        "-filter_complex",
        f"[0:a]pan=stereo|c0={left_gain:.2f}*c0|c1={right_gain:.2f}*c1[out]",
        "-map", "[out]",
        output_path, "-y",
    ]
    ...
```

**二期（真实 HRTF）**：  
依赖 `soundfile` + `scipy` 卷积 HRTF IR 数据集（如 CIPIC），计算量大，建议后续专项任务。

---

## 四、代码解耦原则与健壮性规范

Agent1 在后续开发中必须遵守以下原则：

### 4.1 模块职责单一原则（SRP）

```
src/core/asr/          → 只负责语音识别，不写文件以外的逻辑
src/core/tts/          → 只负责语音合成
src/core/translate/    → 只负责文本翻译
src/core/vocal_sep/    → 只负责人声分离
src/mixer/             → 只负责音频混合
src/core/pipeline/     → 只负责编排上述模块，不含业务逻辑
src/gui.py             → 只负责 UI 交互，通过 Pipeline 调用业务
scripts/               → 只负责 CLI 入口，通过 Pipeline 调用业务
```

**禁止行为**：
- GUI 线程直接 `import VocalSeparator` 并手写完整流程
- Pipeline 中直接操作 ffmpeg subprocess（应委托 Mixer）
- 任何模块直接调用 `config.save()` 以外的全局副作用

### 4.2 错误处理规范

```python
# 推荐模式：异常分层，每层只处理自己能处理的
class ASRRecognizer:
    def recognize(self, audio_path: str, ...) -> List[dict]:
        if not Path(audio_path).exists():
            raise FileNotFoundError(f"音频文件不存在: {audio_path}")
        try:
            segments, info = self.model.transcribe(...)
        except Exception as e:
            raise RuntimeError(f"ASR 识别失败: {e}") from e
        ...

class Pipeline:
    def run(self, ...) -> Dict[str, Any]:
        try:
            ...
        except FileNotFoundError as e:
            raise  # 直接传递给调用方，不吞异常
        except RuntimeError as e:
            # 记录日志，并在 results 中标记失败步骤
            results["error"] = str(e)
            raise

# GUI 层捕获所有异常，格式化显示
class SingleWorkerThread(QThread):
    def run(self):
        try:
            results = pipeline.run(...)
            self.finished.emit(True, results.get("mix_path", ""))
        except Exception as e:
            import traceback; traceback.print_exc()
            self.finished.emit(False, str(e))
```

### 4.3 Windows 编码规范

所有 `subprocess.run()` 调用必须包含：

```python
subprocess.run(
    cmd,
    capture_output=True,
    text=True,
    encoding="utf-8",
    errors="replace",
    check=True,   # 或手动检查 returncode
)
```

所有文件读写必须显式指定 `encoding="utf-8"`。

### 4.4 GPU 资源管理规范

```python
# 批量处理时，模型按"用完即卸"模式管理
class Pipeline:
    def run(self, ...):
        # 人声分离完成后释放 Demucs 模型
        separator = VocalSeparator(model_name=config.vocal_model)
        sep_results = separator.separate(...)
        del separator
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        
        # ASR 完成后释放 Whisper 模型
        recognizer = ASRRecognizer(...)
        asr_results = recognizer.recognize(...)
        del recognizer
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        
        # Qwen3TTS 批量处理前主动加载，处理后卸载
        ...
```

### 4.5 进度回调解耦

Pipeline 不应依赖 Qt（保证 CLI 可用性）：

```python
# 正确：通用回调
from typing import Callable, Optional

class Pipeline:
    def run(
        self,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, Any]:
        def _report(msg: str):
            print(msg)  # 默认打印
            if progress_callback:
                progress_callback(msg)
        
        _report("[1/5] 人声分离...")
        ...
```

---

## 五、推荐实现顺序（Agent1 执行路线图）

```
阶段 1（修复 & 重构，1~2天）
├── [P0] 修复 BUG-06: GUI get_batch_params 读取 vocal_model 控件
├── [P0] 修复 BUG-09: preview_thread.isRunning() 防重入
├── [P1] 将 GUI 线程改为委托 Pipeline（3.1 节）
└── [P1] Qwen3TTS 模型单例化（3.3 节）

阶段 2（新功能，3~5天）
├── [F1] ASMR 术语库（3.6 节）—— 独立模块，不影响现有流程
├── [F2] GPT-SoVITS 引擎接入（3.5 节）—— 可选依赖，服务不可用时优雅降级
└── [F3] Config 热更新（3.4 节）—— 小改动

阶段 3（增强，1周）
├── [E1] TimedTTS 时间轴对齐（3.2 节）
└── [E2] 空间音频一期：pan 定向（3.7 节）
```

---

## 六、文件变更清单

Agent1 根据以上指导进行以下文件操作：

| 操作 | 文件 | 说明 |
|------|------|------|
| 修改 | `src/gui.py` | SingleWorkerThread/BatchWorkerThread 委托 Pipeline；preview 防重入 |
| 修改 | `src/core/pipeline/__init__.py` | 添加 progress_callback 参数；添加 vtt_path 支持；添加 GPU 释放 |
| 修改 | `src/core/tts/__init__.py` | Qwen3TTSEngine 模型单例化 |
| 修改 | `src/core/translate/__init__.py` | 接入 TerminologyDB |
| 新增 | `src/core/tts/gptsovits.py` | GPT-SoVITS 引擎 |
| 新增 | `src/core/translate/terminology.py` | ASMR 术语库 |
| 修改 | `config/asmr_terms.json` | 创建默认术语文件 |
| 修改 | `scripts/batch_process.py` | 添加 GPU 竞争警告与限制注释 |

---

## 七、附：当前代码结构参考图（完整）

```
AsmrHelper/
├── src/
│   ├── core/
│   │   ├── asr/__init__.py          # ASRRecognizer（已修复 no_speech_threshold）
│   │   ├── tts/__init__.py          # EdgeTTSEngine + Qwen3TTSEngine + TTSEngine
│   │   ├── tts/gptsovits.py         # [待新增] GPT-SoVITS 引擎
│   │   ├── translate/__init__.py    # Translator + load_vtt_translations（VTT已修复）
│   │   ├── translate/terminology.py # [待新增] ASMR 术语库
│   │   ├── vocal_separator/__init__.py  # VocalSeparator（Demucs 4.0）
│   │   └── pipeline/__init__.py     # Pipeline + PipelineConfig（主编排器）
│   ├── mixer/__init__.py            # Mixer（ffmpeg amix, 已修复 bilingual filter）
│   ├── utils/                       # get_ffmpeg, ensure_dir 等
│   ├── config.py                    # Config 单例
│   ├── gui.py                       # PySide6 主界面 [待重构委托 Pipeline]
│   └── cli.py                       # CLI 入口
├── scripts/
│   ├── asmr_bilingual.py            # 单文件 CLI（依赖 Pipeline）
│   └── batch_process.py             # 批量 CLI
├── config/
│   ├── config.json                  # 用户配置
│   └── asmr_terms.json              # [待新增] ASMR 术语库
├── models/
│   ├── whisper/                     # faster-whisper-large-v3
│   └── qwen3tts/                    # Qwen3-TTS 模型
└── Report/
    ├── report_1.txt                 # Agent2 交叉审查报告
    └── report_2_agent3_architecture.md  # 本报告
```

---

**报告结束**

*Agent3 已完成可行性评估与架构指导，本报告可直接作为 Agent1 代码实现的执行依据。如 Agent1 在实现过程中遇到接口歧义，优先参考第三节的代码示例；遇到新的设计决策，请反馈至 Agent3 进行评估。*
