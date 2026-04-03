"""
AppService - 业务逻辑服务层

将 GUI 中的业务逻辑抽离出来，实现 UI 与业务逻辑的解耦。
GUI 只负责 UI 渲染和用户交互，业务逻辑统一由 AppService 处理。
"""

import time
from pathlib import Path
from typing import Optional, List, Dict, Any, Callable, Literal

from src.config import config
from src.core.pipeline import Pipeline, PipelineConfig
from src.core.tts import TTSEngine
from src.core.translate import Translator
from src.core.tts.voice_profile import get_voice_manager
from src.utils import find_vtt_file, sanitize_filename, ensure_dir


class AppService:
    """
    应用服务层

    职责：
    1. 业务流程编排（单文件处理、批量处理）
    2. 参数配置管理
    3. 音色选项获取
    4. 试音功能
    """

    # TTS 引擎选项
    TTS_ENGINES = ["Edge-TTS", "Qwen3-TTS"]

    # Edge-TTS 音色列表
    EDGE_VOICES = [
        "zh-CN-XiaoxiaoNeural",
        "zh-CN-YunxiNeural",
        "zh-CN-YunyangNeural",
        "zh-CN-XiaoyiNeural",
        "zh-CN-XiaochenNeural",
        "ja-JP-NanamiNeural",
        "ja-JP-KeigoNeural",
    ]

    # Edge-TTS 音色显示名称映射
    EDGE_VOICE_NAMES = {
        "zh-CN-XiaoxiaoNeural": "晓晓（女）",
        "zh-CN-YunxiNeural": "云希（男）",
        "zh-CN-YunyangNeural": "云扬（男）",
        "zh-CN-XiaoyiNeural": "小艺（女）",
        "zh-CN-XiaochenNeural": "晓晨（女）",
        "ja-JP-NanamiNeural": "七海（日语女）",
        "ja-JP-KeigoNeural": "圭吾（日语男）",
    }

    # ASR 模型选项
    ASR_MODELS = ["large-v3", "large-v2", "large", "medium", "small", "base"]

    # Vocal 模型选项
    VOCAL_MODELS = ["htdemucs", "htdemucs_ft", "htdemucs_6s", "hdemucs_mmi"]

    def __init__(self):
        """初始化服务"""
        self.voice_manager = get_voice_manager()

    # ==================== 参数获取 ====================

    def get_edge_voice_options(self) -> List[str]:
        """获取 Edge-TTS 音色选项（带显示名称）"""
        return [f"{v} ({self.EDGE_VOICE_NAMES.get(v, v)})" for v in self.EDGE_VOICES]

    def get_qwen3_voice_options(self) -> Dict[str, List[str]]:
        """获取 Qwen3-TTS 音色选项（按类别分组）"""
        presets = self.voice_manager.get_presets()
        customs = self.voice_manager.get_customs()
        clones = self.voice_manager.get_clones()

        return {
            "preset": [f"{p.name} ({p.id})" for p in presets if p.is_available()],
            "custom": [f"{p.name} ({p.id})" for p in customs if p.is_available()],
            "clone": [f"{p.name} ({p.id})" for p in clones if p.is_available()],
        }

    def get_tts_engine_voices(self, engine: str) -> List[str]:
        """获取指定引擎的音色列表"""
        if engine == "Edge-TTS":
            return self.get_edge_voice_options()
        elif engine == "Qwen3-TTS":
            opts = self.get_qwen3_voice_options()
            all_voices = opts.get("preset", []) + opts.get("custom", []) + opts.get("clone", [])
            return all_voices
        return []

    # ==================== 试音 ====================

    def preview_voice(
        self,
        engine: str,
        voice: str,
        voice_profile_id: Optional[str] = None,
        speed: float = 1.0,
        text: str = "你好，我是ASMR助手。",
        output_dir: str = None,
    ) -> str:
        """
        试音功能

        Args:
            engine: TTS 引擎 ("Edge-TTS" 或 "Qwen3-TTS")
            voice: 音色名称
            voice_profile_id: Qwen3 音色配置 ID
            speed: 语速
            text: 试音文本
            output_dir: 输出目录

        Returns:
            生成的音频文件路径
        """
        if output_dir is None:
            output_dir = Path(__file__).parent.parent.parent / "output"
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # 确定内部引擎类型
        engine_type = "edge" if engine == "Edge-TTS" else "qwen3"

        # 生成安全的文件名
        safe_engine = sanitize_filename(engine)
        safe_voice = sanitize_filename(voice.split("(")[0].strip() if "(" in voice else voice)
        timestamp = int(time.time())
        output_path = output_dir / f"preview_{safe_engine}_{safe_voice}_{timestamp}.wav"

        # Edge-TTS 使用完整音色名
        if engine_type == "edge":
            tts_voice = voice.split(" ")[0] if " " in voice else voice
        else:
            tts_voice = voice.split(" ")[0] if voice else "Vivian"

        # 创建 TTS 引擎
        tts_engine = TTSEngine(
            engine=engine_type,
            voice=tts_voice,
            speed=speed,
            voice_profile_id=voice_profile_id,
        )

        # 合成
        tts_engine.synthesize(text, str(output_path))

        return str(output_path)

    # ==================== 单文件处理 ====================

    def process_single(
        self,
        input_path: str,
        output_dir: str,
        params: Dict[str, Any],
        vtt_path: str = None,
        progress_callback: Callable[[str], None] = None,
        mix_output_dir: str = None,
    ) -> Dict[str, Any]:
        """
        单文件处理

        Args:
            input_path: 输入音频路径
            output_dir: 输出目录（中间文件放这里）
            params: 处理参数
            vtt_path: 字幕文件路径
            progress_callback: 进度回调
            mix_output_dir: 成品混音输出目录（默认同 output_dir）

        Returns:
            处理结果
        """
        # 构建流水线配置
        pipeline_config = self._build_pipeline_config(
            input_path, output_dir, params, vtt_path, mix_output_dir
        )

        # 创建流水线
        pipeline = Pipeline(config=pipeline_config)

        # 运行
        return pipeline.run(
            preset=params.get("preset", "asmr_bilingual"),
            progress_callback=progress_callback,
        )

    def _build_pipeline_config(
        self,
        input_path: str,
        output_dir: str,
        params: Dict[str, Any],
        vtt_path: str = None,
        mix_output_dir: str = None,
    ) -> PipelineConfig:
        """从参数构建流水线配置"""
        engine = params.get("tts_engine", "Edge-TTS")
        engine_type = "edge" if engine == "Edge-TTS" else "qwen3"

        # 解析音色
        tts_voice, voice_profile_id = self._parse_voice(params.get("tts_voice", ""), engine_type)

        # 构建配置
        return PipelineConfig(
            input_path=str(input_path),
            output_dir=str(output_dir),
            vtt_path=str(vtt_path) if vtt_path else None,
            mix_output_dir=str(mix_output_dir) if mix_output_dir else None,

            # 人声分离
            use_vocal_separator=params.get("use_vocal_separator", True),
            vocal_model=params.get("vocal_model", "htdemucs"),

            # ASR
            use_asr=params.get("use_asr", True),
            asr_model=params.get("asr_model", "large-v3"),
            asr_language=params.get("asr_language", "ja"),

            # 翻译
            use_translate=params.get("use_translate", True),
            translate_provider=params.get("translate_provider", "deepseek"),
            translate_model=params.get("translate_model", "deepseek-chat"),
            source_lang=params.get("source_lang", "日文"),
            target_lang=params.get("target_lang", "中文"),

            # TTS
            use_tts=params.get("use_tts", True),
            tts_engine=engine_type,
            tts_voice=tts_voice,
            qwen3_voice=tts_voice,
            voice_profile_id=voice_profile_id,
            tts_speed=params.get("tts_speed", 1.0),

            # 混音
            use_mixer=params.get("use_mixer", True),
            original_volume=params.get("original_volume", 0.85),
            tts_volume_ratio=params.get("tts_volume_ratio", 0.5),
            tts_delay_ms=params.get("tts_delay_ms", 0),

            # 高级
            skip_existing=params.get("skip_existing", False),
        )

    def _parse_voice(self, voice_str: str, engine_type: str) -> tuple:
        """
        解析音色字符串

        Args:
            voice_str: 音色字符串
            engine_type: 引擎类型

        Returns:
            (voice, voice_profile_id)
        """
        if engine_type == "edge":
            # Edge-TTS: 直接返回音色名
            voice = voice_str.split(" ")[0] if voice_str else "zh-CN-XiaoxiaoNeural"
            return voice, None
        else:
            # Qwen3-TTS: 解析 ID
            if "(" in voice_str and ")" in voice_str:
                name = voice_str.split("(")[0].strip()
                voice_id = voice_str.split("(")[1].rstrip(")")
                return name, voice_id
            return voice_str or "Vivian", None

    # ==================== 批量处理 ====================

    def process_batch(
        self,
        input_paths: List[str],
        output_dir: str,
        params: Dict[str, Any],
        max_workers: int = 1,
        progress_callback: Callable[[str], None] = None,
    ) -> Dict[str, Any]:
        """
        批量处理

        输出结构:
        - output_dir/
          - product/           # 所有成品混音文件
          - <name1>_outcome/   # 中间文件（人声、翻译、TTS等）
          - <name2>_outcome/
          - ...

        Args:
            input_paths: 输入文件列表
            output_dir: 输出目录
            params: 处理参数
            max_workers: 最大并发数
            progress_callback: 进度回调

        Returns:
            批量处理结果
        """
        # 成品输出目录
        product_dir = Path(output_dir) / "product"
        ensure_dir(product_dir)

        results = []
        total = len(input_paths)

        for i, input_path in enumerate(input_paths):
            input_p = Path(input_path)
            if progress_callback:
                progress_callback(f"[{i+1}/{total}] 处理: {input_p.name}")

            # 查找 VTT
            vtt_path = find_vtt_file(input_p)
            if vtt_path:
                if progress_callback:
                    progress_callback(f"  找到字幕: {vtt_path.name}")

            # 处理单个文件
            # 中间文件放在 output_dir/<name>_outcome/
            # 成品放在 output_dir/product/
            try:
                result = self.process_single(
                    input_path=input_path,
                    output_dir=output_dir,  # 中间文件的根目录
                    params=params,
                    vtt_path=str(vtt_path) if vtt_path else None,
                    mix_output_dir=str(product_dir),  # 成品放这里
                )
                results.append({
                    "input": input_path,
                    "success": True,
                    "result": result,
                })
            except Exception as e:
                results.append({
                    "input": input_path,
                    "success": False,
                    "error": str(e),
                })

        if progress_callback:
            progress_callback(f"批量处理完成: {sum(1 for r in results if r.get('success'))}/{total} 成功")

        return {
            "total": total,
            "success": sum(1 for r in results if r.get("success")),
            "failed": sum(1 for r in results if not r.get("success")),
            "results": results,
        }

    # ==================== VTT 查找 ====================

    def find_vtt_for_audio(self, audio_path: str, extra_dirs: List[str] = None) -> Optional[str]:
        """为音频文件查找对应的 VTT 字幕"""
        vtt_path = find_vtt_file(Path(audio_path), extra_dirs)
        return str(vtt_path) if vtt_path else None

    # ==================== 配置管理 ====================

    def get_default_params(self) -> Dict[str, Any]:
        """获取默认参数"""
        return {
            "use_vocal_separator": True,
            "vocal_model": "htdemucs",
            "use_asr": True,
            "asr_model": "large-v3",
            "asr_language": "ja",
            "use_translate": True,
            "translate_provider": "deepseek",
            "translate_model": "deepseek-chat",
            "source_lang": "日文",
            "target_lang": "中文",
            "use_tts": True,
            "tts_engine": "Edge-TTS",
            "tts_voice": self.EDGE_VOICES[0],
            "tts_speed": 1.0,
            "use_mixer": True,
            "original_volume": 0.85,
            "tts_volume_ratio": 0.5,
            "tts_delay_ms": 0,
            "skip_existing": False,
        }

    def validate_params(self, params: Dict[str, Any]) -> tuple:
        """
        验证参数

        Returns:
            (is_valid, error_message)
        """
        if not params.get("input_path"):
            return False, "请选择输入文件"

        if not Path(params["input_path"]).exists():
            return False, f"输入文件不存在: {params['input_path']}"

        if params.get("translate_provider") == "deepseek":
            if not config.deepseek_api_key:
                return False, "请在设置中配置 DeepSeek API Key"

        return True, None


# 单例
_app_service: Optional[AppService] = None


def get_app_service() -> AppService:
    """获取 AppService 单例"""
    global _app_service
    if _app_service is None:
        _app_service = AppService()
    return _app_service
