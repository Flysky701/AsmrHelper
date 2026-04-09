"""
GUI Worker 线程模块

包含所有后台处理线程：
- SingleWorkerThread: 单文件处理
- PreviewWorkerThread: 试音
- BatchWorkerThread: 批量处理
"""

import threading
from pathlib import Path
from typing import Optional, List

from PySide6.QtCore import QThread, Signal

from src.utils.constants import AUDIO_EXTENSIONS


class SingleWorkerThread(QThread):
    """单个文件处理线程"""
    progress = Signal(str)
    finished = Signal(bool, str)

    def __init__(self, input_path: str, output_dir: str, params: dict, vtt_path: str = None):
        super().__init__()
        self.input_path = input_path
        self.output_dir = output_dir
        self.params = params
        self.vtt_path = vtt_path
        self._cancel_event = threading.Event()

    def cancel(self):
        """请求取消（协作式，安全替代 terminate()）"""
        self._cancel_event.set()

    def _find_subtitle_file(self) -> Optional[str]:
        """查找字幕文件（支持 VTT / SRT / LRC）"""
        from src.utils import find_subtitle_file
        return find_subtitle_file(Path(self.input_path), [Path(self.input_path).parent / "ASMR_O"])

    def run(self):
        try:
            from src.core.pipeline import Pipeline, PipelineConfig

            # 确定字幕路径（用户指定优先，否则自动查找）
            subtitle_path = self.vtt_path or self._find_subtitle_file()

            # 构建 Pipeline 配置
            cfg = PipelineConfig(
                input_path=self.input_path,
                output_dir=self.output_dir,
                vtt_path=subtitle_path,
                vocal_model=self.params.get("vocal_model", "htdemucs"),
                asr_model=self.params.get("asr_model", "large-v3"),
                asr_language="ja",
                tts_engine=self.params.get("tts_engine", "edge"),
                tts_voice=self.params.get("tts_voice", "zh-CN-XiaoxiaoNeural"),
                qwen3_voice=self.params.get("tts_voice", "Vivian"),
                voice_profile_id=self.params.get("voice_profile_id"),
                tts_speed=self.params.get("tts_speed", 1.0),
                original_volume=self.params.get("original_volume", 0.85),
                tts_volume_ratio=self.params.get("tts_ratio", 0.5),
                tts_delay_ms=self.params.get("tts_delay", 0),
                skip_existing=False,
            )

            pipeline = Pipeline(cfg)
            results = pipeline.run(progress_callback=self.progress.emit)

            mix_path = results.get("mix_path", "")
            exported_subtitle = results.get("exported_subtitle", "")

            # 构建完成消息
            msg_parts = []
            if mix_path:
                msg_parts.append(f"成品: {mix_path}")
            if exported_subtitle:
                msg_parts.append(f"字幕: {exported_subtitle}")

            final_msg = "\n".join(msg_parts) if msg_parts else "处理完成"

            self.finished.emit(True, final_msg)

        except Exception as e:
            import traceback
            traceback.print_exc()
            self.finished.emit(False, str(e))


class PreviewWorkerThread(QThread):
    """
    试音线程 - 避免阻塞GUI

    支持三种音色类型的试音：
    1. 预设音色 (voice_profile_id 如 "A1")
    2. 自定义音色 (voice_profile_id 如 "B1")
    3. 克隆音色 (voice_profile_id == "__clone__", voice=音频文件路径)
    """
    finished = Signal(bool, str, str)  # success, message, output_path

    def __init__(self, engine: str, voice: str, voice_profile_id: str, speed: float, test_text: str):
        super().__init__()
        self.engine = engine
        self.voice = voice
        self.voice_profile_id = voice_profile_id
        self.speed = speed
        self.test_text = test_text

    def run(self):
        try:
            import tempfile
            from src.core.tts.voice_designer import VoiceDesigner

            temp_dir = Path(tempfile.gettempdir())
            output_path = temp_dir / "asmr_preview.wav"

            # Edge-TTS: 使用简单路径
            if self.engine == "edge":
                from src.core import TTSEngine
                tts_engine = TTSEngine(
                    engine=self.engine,
                    voice=self.voice,
                    voice_profile_id=self.voice_profile_id,
                    speed=self.speed,
                )
                tts_engine.synthesize(self.test_text, str(output_path))
                self.finished.emit(True, "播放中...", str(output_path))
                return

            # Qwen3-TTS: 根据音色类型选择不同处理方式
            if self.voice_profile_id == "__clone__":
                # 克隆音色：直接使用音频文件克隆
                designer = VoiceDesigner()
                audio_path = designer.clone_and_preview(
                    audio_path=self.voice,  # voice 实际上是音频文件路径
                    text=self.test_text,
                    output_path=str(output_path),
                )
                self.finished.emit(True, "播放中...", audio_path)
            else:
                # 预设/自定义音色：使用 VoiceDesigner.preview_profile
                from src.core.tts.voice_profile import get_voice_manager
                manager = get_voice_manager()
                profile = manager.get_by_id(self.voice_profile_id)
                if not profile:
                    # 回退到 TTSEngine（可能是直接使用预设音色名）
                    from src.core import TTSEngine
                    tts_engine = TTSEngine(
                        engine=self.engine,
                        voice=self.voice,
                        voice_profile_id=self.voice_profile_id,
                        speed=self.speed,
                    )
                    tts_engine.synthesize(self.test_text, str(output_path))
                    self.finished.emit(True, "播放中...", str(output_path))
                    return

                designer = VoiceDesigner()
                audio_path = designer.preview_profile(
                    profile=profile,
                    text=self.test_text,
                    output_path=str(output_path),
                )
                self.finished.emit(True, "播放中...", audio_path)

        except Exception as e:
            import traceback
            traceback.print_exc()
            # 清理可能已创建的临时文件
            if output_path and output_path.exists():
                try:
                    output_path.unlink()
                except Exception:
                    pass
            self.finished.emit(False, str(e), "")


class BatchWorkerThread(QThread):
    """批量处理线程（支持并行处理 + GPU 资源管理）"""
    progress = Signal(str)
    file_progress = Signal(int, int, str)  # current, total, filename
    finished = Signal(list)  # results list

    def __init__(self, input_files: List[str], output_dir: str, params: dict, max_workers: int = 2):
        super().__init__()
        self.input_files = input_files
        self.output_dir = output_dir
        self.params = params
        self.max_workers = max_workers  # 并行度
        self.results = []
        self._results_lock = threading.Lock()  # 保护 results 列表
        self._cancel_event = threading.Event()  # 协作式取消

    def cancel(self):
        """请求取消（协作式，安全替代 terminate()）"""
        self._cancel_event.set()

    def _find_subtitle_file(self, input_path: Path) -> Optional[str]:
        """查找字幕文件（支持 VTT / SRT / LRC）"""
        from src.utils import find_subtitle_file
        return find_subtitle_file(input_path, [input_path.parent / "ASMR_O"])

    def _process_single_file(self, input_path: str) -> dict:
        """处理单个文件（线程安全，使用 GPU 锁）"""
        from src.core.pipeline import Pipeline, PipelineConfig
        from src.core.gpu_manager import get_gpu_lock

        result = {
            "file": input_path,
            "status": "pending",
            "output": None,
            "error": None,
        }

        try:
            # 批量模式：使用 batch_root_dir，Pipeline 内部会分离 Main_Product 和 BY_Product
            batch_root = (
                self.output_dir
                if self.output_dir
                else str(Path(input_path).parent / "output")
            )

            # 自动查找字幕
            subtitle_file = self._find_subtitle_file(Path(input_path))

            # 构建 Pipeline 配置
            cfg = PipelineConfig(
                input_path=input_path,
                output_mode="batch",
                batch_root_dir=batch_root,
                vtt_path=subtitle_file,
                vocal_model=self.params.get("vocal_model", "htdemucs"),
                asr_model=self.params.get("asr_model", "large-v3"),
                asr_language="ja",
                tts_engine=self.params.get("tts_engine", "edge"),
                tts_voice=self.params.get("tts_voice", "zh-CN-XiaoxiaoNeural"),
                qwen3_voice=self.params.get("tts_voice", "Vivian"),
                voice_profile_id=self.params.get("voice_profile_id"),  # 传递音色配置 ID
                tts_speed=self.params.get("tts_speed", 1.0),
                original_volume=self.params.get("original_volume", 0.85),
                tts_volume_ratio=self.params.get("tts_ratio", 0.5),
                tts_delay_ms=self.params.get("tts_delay", 0),
                skip_existing=False,
            )

            # 使用 GPU 锁保护 GPU 操作
            gpu_lock = get_gpu_lock(max_concurrent=1)
            with gpu_lock:
                pipeline = Pipeline(cfg)
                # 无回调，避免线程安全问题
                results = pipeline.run(progress_callback=None)

            mix_path = results.get("mix_path", "")
            if mix_path:
                result["status"] = "success"
                result["output"] = str(mix_path)
            else:
                result["status"] = "failed"
                result["error"] = "流水线未生成混音"

        except Exception as e:
            import traceback
            traceback.print_exc()
            result["status"] = "failed"
            result["error"] = str(e)

        return result

    def run(self):
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from src.core.gpu_manager import get_gpu_lock

        total = len(self.input_files)
        gpu_lock = get_gpu_lock(max_concurrent=1)
        gpu_info = gpu_lock.get_gpu_memory_info()

        # 打印 GPU 状态
        if gpu_info.get("available"):
            self.progress.emit(
                f"开始批量处理 {total} 个文件 (并行度: {self.max_workers}) "
                f"| GPU: {gpu_info['name']} "
                f"| 显存: {gpu_info['free_gb']:.1f}GB 可用"
            )
        else:
            self.progress.emit(f"开始批量处理 {total} 个文件 (并行度: {self.max_workers}, CPU 模式)")

        # 串行处理（并行度为 1 或 GPU 模式）
        if self.max_workers == 1:
            for i, input_path in enumerate(self.input_files, 1):
                self.file_progress.emit(i, total, Path(input_path).name)
                self.progress.emit(f"[{i}/{total}] 处理: {Path(input_path).name}")

                result = self._process_single_file(input_path)

                with self._results_lock:
                    self.results.append(result)

                # 报告结果
                if result["status"] == "skipped":
                    self.progress.emit(f"[{i}/{total}] 跳过: {Path(input_path).name}")
                elif result["status"] == "success":
                    self.progress.emit(f"[{i}/{total}] 完成: {Path(input_path).name}")
                else:
                    self.progress.emit(f"[{i}/{total}] 失败: {Path(input_path).name} - {result.get('error', 'Unknown')}")

        # 并行处理
        else:
            completed = 0
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = {
                    executor.submit(self._process_single_file, f): f
                    for f in self.input_files
                }

                for future in as_completed(futures):
                    input_path = futures[future]
                    completed += 1

                    try:
                        result = future.result()
                    except Exception as e:
                        result = {
                            "file": input_path,
                            "status": "failed",
                            "error": str(e),
                        }

                    with self._results_lock:
                        self.results.append(result)

                    self.file_progress.emit(completed, total, Path(input_path).name)

                    # 报告结果
                    if result["status"] == "skipped":
                        self.progress.emit(f"[{completed}/{total}] 跳过: {Path(input_path).name}")
                    elif result["status"] == "success":
                        self.progress.emit(f"[{completed}/{total}] 完成: {Path(input_path).name}")
                    else:
                        self.progress.emit(
                            f"[{completed}/{total}] 失败: {Path(input_path).name} - {result.get('error', 'Unknown')}"
                        )

        self.finished.emit(self.results)


class VoiceDesignWorker(QThread):
    """
    音色设计 Worker - 在后台执行 VoiceDesign + Base clone

    信号:
        progress(str): 进度消息
        finished(bool, str, str): (success, message, profile_id)
    """

    progress = Signal(str, int)  # message, percent
    finished = Signal(bool, str, str)  # success, message, profile_id

    def __init__(self, name: str, description: str, ref_text: str = None):
        super().__init__()
        self.name = name
        self.description = description
        self.ref_text = ref_text or "你好，今天辛苦了，让我来帮你放松一下吧。"

    def run(self):
        try:
            from src.core.tts.voice_designer import VoiceDesigner

            def progress_callback(msg: str, percent: int):
                self.progress.emit(msg, percent)

            designer = VoiceDesigner()
            profile = designer.design_and_generate(
                description=self.description,
                name=self.name,
                ref_text=self.ref_text,
                progress_callback=progress_callback,
            )

            self.finished.emit(True, f"音色 '{profile.name}' 创建成功!", profile.id)

        except Exception as e:
            import traceback
            traceback.print_exc()
            self.finished.emit(False, f"音色设计失败: {e}", "")


class SegmentAnalysisWorker(QThread):
    """
    片段分析 Worker - 分析音频并返回所有有效片段（用于 GUI 预览选择模式）

    信号:
        progress(str, int): 进度消息, 百分比
        finished(bool, str, dict): (success, message, analysis_result)
            analysis_result 结构见 AudioPreprocessor.analyze_segments()
    """

    progress = Signal(str, int)
    finished = Signal(bool, str, dict)  # success, message, result_dict

    def __init__(self, audio_path: str, subtitle_path: str = None,
                 audio_language: str = "ja", separate_vocals: bool = True):
        super().__init__()
        self.audio_path = audio_path
        self.subtitle_path = subtitle_path
        self.audio_language = audio_language
        self.separate_vocals = separate_vocals

    def run(self):
        try:
            import tempfile
            from src.core.tts.audio_preprocessor import AudioPreprocessor
            from src.core.vocal_separator import separate_vocals as do_separate_vocals

            audio_to_process = self.audio_path

            # Step 1: 分离人声
            if self.separate_vocals:
                self.progress.emit("分离人声中...", 5)
                try:
                    temp_dir = Path(tempfile.gettempdir()) / "asmr_voice_clone"
                    temp_dir.mkdir(parents=True, exist_ok=True)
                    vocal_path = do_separate_vocals(
                        audio_path=self.audio_path,
                        output_dir=str(temp_dir),
                    )
                    if vocal_path and Path(vocal_path).exists():
                        audio_to_process = vocal_path
                        self.progress.emit("人声分离完成!", 15)
                    else:
                        self.progress.emit("人声分离失败，使用原音频", 15)
                except Exception as sep_err:
                    self.progress.emit(f"人声分离失败: {sep_err}，使用原音频", 15)

            # Step 2: 分析片段
            self.progress.emit("分析音频片段...", 20)
            preprocessor = AudioPreprocessor()
            result = preprocessor.analyze_segments(
                audio_path=audio_to_process,
                subtitle_path=self.subtitle_path,
                audio_language=self.audio_language,
                progress_callback=lambda msg, pct: self.progress.emit(msg, 20 + int(pct * 0.75)),
            )

            result["vocal_separated_path"] = audio_to_process
            self.progress.emit(f"分析完成: {result['valid_count']} 个有效片段", 100)
            self.finished.emit(True, f"分析完成: {result['valid_count']} 个有效片段", result)

        except Exception as e:
            import traceback
            traceback.print_exc()
            self.finished.emit(False, f"分析失败: {e}", {})


class VoiceCloneWorker(QThread):
    """
    音色克隆 Worker - 在后台执行 Base clone (集成 AudioPreprocessor)

    信号:
        progress(str, int): 进度消息, 百分比
        finished(bool, str, str): (success, message, profile_id)

    支持三种模式:
    - 自动模式: 分离人声 + 自动分析选择片段 + 克隆
    - 预选模式: 使用 GUI 分析后用户选中的片段 + 克隆
    - 手动文本模式: 分离人声 + 自动选择 + 使用手动 ref_text
    """

    progress = Signal(str, int)
    finished = Signal(bool, str, str)

    def __init__(self, name: str, audio_path: str, subtitle_path: str = None,
                 audio_language: str = "ja", separate_vocals: bool = True,
                 use_progress_wrapper: bool = False, manual_ref_text: str = None,
                 pre_selected_segments: list = None):
        """
        初始化音色克隆 Worker

        Args:
            name: 音色名称
            audio_path: 参考音频路径
            subtitle_path: 字幕文件路径 (可选)
            audio_language: 音频语言 (默认日语)
            separate_vocals: 是否分离人声后再克隆
            use_progress_wrapper: 是否使用进度映射模式
            manual_ref_text: 手动输入的参考文本 (可选，覆盖 ASR/字幕识别)
            pre_selected_segments: GUI 分析后用户选中的片段列表 (可选，跳过分析)
        """
        super().__init__()
        self.name = name
        self.audio_path = audio_path
        self.subtitle_path = subtitle_path
        self.audio_language = audio_language
        self.separate_vocals = separate_vocals
        self.use_progress_wrapper = use_progress_wrapper
        self.manual_ref_text = manual_ref_text
        self.pre_selected_segments = pre_selected_segments

    def _progress_wrapper(self, start_pct: int, end_pct: int):
        """进度回调包装器：将 0-100 映射到 start_pct-end_pct"""
        def wrapper(msg: str, pct: int):
            scaled_pct = start_pct + int(pct / 100.0 * (end_pct - start_pct))
            self.progress.emit(msg, scaled_pct)
        return wrapper

    def _get_progress_callback(self, start_pct: int = None, end_pct: int = None):
        """获取进度回调函数"""
        if self.use_progress_wrapper and start_pct is not None and end_pct is not None:
            return self._progress_wrapper(start_pct, end_pct)
        return lambda msg, pct: self.progress.emit(msg, pct)

    def run(self):
        clone_result = None
        try:
            import tempfile
            from pathlib import Path
            from src.core.tts.voice_designer import VoiceDesigner
            from src.core.tts.audio_preprocessor import AudioPreprocessor
            from src.core.vocal_separator import separate_vocals as do_separate_vocals

            # ===== 预选模式: 使用 GUI 分析后的选中片段 =====
            if self.pre_selected_segments:
                self.progress.emit("从选中片段构建克隆音频...", 10)
                preprocessor = AudioPreprocessor()
                clone_result = preprocessor.build_from_segments(self.pre_selected_segments)
                ref_text_to_use = clone_result.ref_text
                ref_audio_path_to_use = clone_result.ref_audio_path

                if clone_result.warnings:
                    for w in clone_result.warnings:
                        self.progress.emit(f"警告: {w}", 70)
                self.progress.emit(
                    f"音频构建完成: {clone_result.segments_used} 片段, "
                    f"时长 {clone_result.total_duration:.1f}s", 80)

            else:
                # ===== 自动/手动模式 =====
                audio_to_process = self.audio_path

                # Step 1: 分离人声
                if self.separate_vocals:
                    progress_cb = self._get_progress_callback()
                    progress_cb("分离人声中...", 5)
                    try:
                        temp_dir = Path(tempfile.gettempdir()) / "asmr_voice_clone"
                        temp_dir.mkdir(parents=True, exist_ok=True)
                        vocal_path = do_separate_vocals(
                            audio_path=self.audio_path,
                            output_dir=str(temp_dir),
                        )
                        if vocal_path and Path(vocal_path).exists():
                            audio_to_process = vocal_path
                            progress_cb("人声分离完成!", 10)
                        else:
                            progress_cb("人声分离失败，使用原音频", 10)
                    except Exception as sep_err:
                        progress_cb(f"人声分离失败: {sep_err}", 10)
                        audio_to_process = self.audio_path
                else:
                    progress_cb = self._get_progress_callback()
                    progress_cb("准备克隆音频...", 10)

                # Step 2: 准备克隆音频
                ref_text_to_use = None
                ref_audio_path_to_use = None

                if self.manual_ref_text:
                    self.progress.emit("使用手动输入的参考文本...", 15)
                    preprocessor_cb = self._get_progress_callback(15, 75)
                    preprocessor = AudioPreprocessor()
                    clone_result = preprocessor.prepare_clone_audio(
                        audio_path=audio_to_process,
                        subtitle_path=self.subtitle_path,
                        audio_language=self.audio_language,
                        progress_callback=preprocessor_cb,
                    )
                    ref_text_to_use = self.manual_ref_text
                    ref_audio_path_to_use = clone_result.ref_audio_path
                    self.progress.emit("手动模式: 使用用户提供的参考文本", 80)
                else:
                    preprocessor_cb = self._get_progress_callback(15, 75)
                    self.progress.emit("准备克隆音频 (规格转换/字幕切割/ASR)...", 15)
                    preprocessor = AudioPreprocessor()
                    clone_result = preprocessor.prepare_clone_audio(
                        audio_path=audio_to_process,
                        subtitle_path=self.subtitle_path,
                        audio_language=self.audio_language,
                        progress_callback=preprocessor_cb,
                    )
                    ref_text_to_use = clone_result.ref_text
                    ref_audio_path_to_use = clone_result.ref_audio_path
                    mode_label = "匹配模式" if clone_result.mode == "matched" else "ASR 模式"
                    self.progress.emit(f"{mode_label}: ref_text 与音频内容对应", 80)

            # ===== Step 3: 调用克隆 =====
            clone_cb = self._get_progress_callback(85, 95)
            self.progress.emit("执行音色克隆...", 85)
            designer = VoiceDesigner()
            profile = designer.clone_from_audio(
                audio_path=ref_audio_path_to_use,
                name=self.name,
                ref_text=ref_text_to_use,
                progress_callback=clone_cb,
            )

            self.progress.emit(f"音色 '{self.name}' 克隆完成!", 100)
            self.finished.emit(
                True,
                f"音色 '{profile.name}' 克隆成功! "
                f"(片段: {clone_result.segments_used}, 时长: {clone_result.total_duration:.1f}s)",
                profile.id
            )

        except Exception as e:
            import traceback
            traceback.print_exc()
            self.finished.emit(False, f"音色克隆失败: {e}", "")


class VoicePreviewWorker(QThread):
    """
    音色试音 Worker - 支持所有音色类型和语速调节

    信号:
        finished(bool, str, str): (success, message, audio_path)
    """

    finished = Signal(bool, str, str)

    def __init__(self, profile_id: str, test_text: str = None, speed: float = 1.0):
        super().__init__()
        self.profile_id = profile_id
        self.test_text = test_text or "你好，这是一段测试语音。"
        self.speed = speed

    def run(self):
        try:
            import tempfile
            from src.core.tts.voice_designer import VoiceDesigner
            from src.core.tts.voice_profile import get_voice_manager

            temp_dir = Path(tempfile.gettempdir())
            output_path = temp_dir / f"voice_preview_{self.profile_id}.wav"

            # 获取音色配置
            manager = get_voice_manager()
            profile = manager.get_by_id(self.profile_id)

            if not profile:
                self.finished.emit(False, f"音色不存在: {self.profile_id}", "")
                return

            # 试音
            designer = VoiceDesigner()
            audio_path = designer.preview_profile(
                profile=profile,
                text=self.test_text,
                output_path=str(output_path),
                speed=self.speed,
            )

            self.finished.emit(True, "播放中...", audio_path)

        except Exception as e:
            import traceback
            traceback.print_exc()
            self.finished.emit(False, f"试音失败: {e}", "")


class ToolsWorkerThread(QThread):
    """
    工具箱 Worker - 独立执行各工具模块的功能

    支持的工具：
    1. separate   - 音频分离 (Demucs)
    2. split      - 音频切分 (按字幕时间轴)
    3. subtitle_merge - 字幕合并
    4. asr        - ASR 语音识别
    5. convert    - 格式转换

    信号:
        progress(str): 进度消息
        finished(bool, str): (success, message)
    """

    progress = Signal(str)
    finished = Signal(bool, str)

    def __init__(self, tool_id: int, params: dict):
        """
        Args:
            tool_id: 工具 ID (1-5，对应 tools_combo 的索引)
            params: 工具参数字典（由 GUI _collect_tool_params 收集）
        """
        super().__init__()
        self.tool_id = tool_id
        self.params = params
        self._cancel_event = threading.Event()

    def cancel(self):
        self._cancel_event.set()

    def run(self):
        try:
            tool_name = self.params.get("tool", "unknown")
            self.progress.emit(f"[工具箱] 开始执行: {tool_name}")

            if tool_name == "separate":
                result_msg = self._run_separate()
            elif tool_name == "split":
                result_msg = self._run_split()
            elif tool_name == "subtitle_merge":
                result_msg = self._run_submerge()
            elif tool_name == "asr":
                result_msg = self._run_asr()
            elif tool_name == "convert":
                result_msg = self._run_convert()
            elif tool_name == "subtitle_gen":
                result_msg = self._run_subtitle_gen()
            else:
                raise ValueError(f"未知工具: {tool_name}")

            if self._cancel_event.is_set():
                self.finished.emit(False, "已取消")
            else:
                self.progress.emit(f"[工具箱] 执行完成")
                self.finished.emit(True, result_msg)

        except Exception as e:
            import traceback
            traceback.print_exc()
            self.finished.emit(False, str(e))

    # ==================== 各工具实现 ====================

    def _run_separate(self) -> str:
        """音频分离"""
        from src.core.vocal_separator import VocalSeparator
        from pathlib import Path
        import time

        input_path = self.params["input_path"]
        output_dir = self.params["output_dir"]
        model = self.params["model"]
        stem = self.params["stem"]
        export_all = self.params.get("export_all", False)

        Path(output_dir).mkdir(parents=True, exist_ok=True)

        self.progress.emit("[工具箱] 加载 Demucs 分离模型...")
        t0 = time.time()
        separator = VocalSeparator(model_name=model)

        # 全部轨道 or 单轨道
        all_stems = ["vocals", "no_vocals", "drums", "bass", "piano", "other"]
        target_stems = all_stems if export_all else [stem]

        self.progress.emit(f"[工具箱] 正在分离 (目标轨道: {', '.join(target_stems)})...")
        results = separator.separate(input_path, output_dir, stems=target_stems)

        elapsed = time.time() - t0

        # 构建结果报告：列出所有输出文件及大小
        lines = [f"分离完成！", f"耗时: {elapsed:.1f}s", ""]
        total_size = 0
        for s in target_stems:
            fpath = results.get(s, "")
            if fpath and Path(fpath).exists():
                size_mb = Path(fpath).stat().st_size / (1024 * 1024)
                total_size += size_mb
                size_str = f"{size_mb:.1f} MB"
                # 简短名称映射
                name_map = {
                    "vocals": "人声", "no_vocals": "伴奏", "drums": "鼓声",
                    "bass": "贝斯", "piano": "钢琴", "other": "其他",
                }
                lines.append(f"  [{name_map.get(s, s)}] {Path(fpath).name}  ({size_str})")
            else:
                lines.append(f"  [{s}] 未生成")
        lines.append(f"\n总计大小: {total_size:.1f} MB")
        lines.append(f"输出目录: {output_dir}")

        return "\n".join(lines)

    def _run_split(self) -> str:
        """按字幕时间轴切分音频"""
        from src.core.tts.audio_preprocessor import AudioPreprocessor
        from pathlib import Path
        import soundfile as sf
        import time

        audio_path = self.params["audio_path"]
        subtitle_path = self.params["subtitle_path"]
        output_dir = self.params["output_dir"]

        Path(output_dir).mkdir(parents=True, exist_ok=True)

        # 加载字幕时间戳
        self.progress.emit("[工具箱] 解析字幕时间戳...")
        from ..translate import load_subtitle_with_timestamps
        entries = load_subtitle_with_timestamps(subtitle_path)
        if not entries:
            raise RuntimeError("无法从字幕文件中解析出有效的时间戳条目")

        # 读取音频信息
        info = sf.info(audio_path)
        sample_rate = info.samplerate

        self.progress.emit(f"[工具箱] 切分 {len(entries)} 个片段...")
        t0 = time.time()
        data, sr = sf.read(audio_path, always_2d=False)

        saved_count = 0
        for i, entry in enumerate(entries):
            if self._cancel_event.is_set():
                break

            start_sample = int(entry["start"] * sr)
            end_sample = int(entry["end"] * sr)
            segment_data = data[start_sample:end_sample]

            out_path = Path(output_dir) / f"segment_{i+1:03d}.wav"
            sf.write(str(out_path), segment_data, sr)
            saved_count += 1
            self.progress.emit(f"[{i+1}/{len(entries)}] {out_path.name} ({entry['text'][:20]}...)")

        elapsed = time.time() - t0
        return f"切分完成！\n保存片段数: {saved_count}\n输出目录: {output_dir}\n耗时: {elapsed:.1f}s"

    def _run_submerge(self) -> str:
        """合并多语言字幕文件"""
        from ..translate import (
            load_subtitle_with_timestamps,
            detect_subtitle_language,
            load_subtitle_translations,
        )
        from pathlib import Path
        import time

        files = self.params["files"]
        output_path = self.params["output_path"]
        fmt = self.params["format"]

        if not output_path:
            raise ValueError("请指定输出文件路径")

        out_p = Path(output_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)

        self.progress.emit(f"[工具箱] 合并 {len(files)} 个字幕文件...")
        t0 = time.time()

        all_segments = []
        for fp in files:
            self.progress.emit(f"  读取: {Path(fp).name}")
            entries = load_subtitle_with_timestamps(fp)
            lang = detect_subtitle_language(load_subtitle_translations(fp))
            for e in entries:
                seg = dict(e)
                seg["_source"] = Path(fp).name
                seg["_lang"] = lang or "?"
                all_segments.append(seg)

        if not all_segments:
            raise RuntimeError("所有字幕文件均无有效内容")

        # 按起始时间排序
        all_segments.sort(key=lambda x: x["start"])

        # 构建输出内容
        if fmt == "srt":
            lines = []
            for i, seg in enumerate(all_segments, 1):
                start = self._fmt_ts(seg["start"], fmt="srt")
                end = self._fmt_ts(seg["end"], fmt="srt")
                lines.append(f"{i}")
                lines.append(f"{start} --> {end}")
                lines.append(seg["text"])
                lines.append("")
            content = "\n".join(lines)
        elif fmt == "vtt":
            lines = ["WEBVTT", ""]
            for seg in all_segments:
                start = self._fmt_ts(seg["start"], fmt="vtt")
                end = self._fmt_ts(seg["end"], fmt="vtt")
                lines.append(f"{start} --> {end}")
                lines.append(seg["text"])
                lines.append("")
            content = "\n".join(lines)
        elif fmt == "lrc":
            lines = []
            for seg in all_segments:
                ms = int(seg["start"] * 1000)
                m = ms // 60000
                s = (ms % 60000) // 1000
                cs = ms % 1000
                ts = f"[{m:02d}:{s:02d}.{cs:02d}]"
                lines.append(f"{ts}{seg['text']}")
            content = "\n".join(lines)
        else:
            raise ValueError(f"不支持的格式: {fmt}")

        out_p.write_text(content, encoding="utf-8")
        elapsed = time.time() - t0
        return f"合并完成！\n输出: {output_path}\n总条目: {len(all_segments)}\n耗时: {elapsed:.1f}s"

    @staticmethod
    def _fmt_ts(seconds: float, fmt: str = "srt") -> str:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s_val = int(seconds % 60)
        ms = int((seconds - int(seconds)) * 1000)
        if fmt == "srt":
            return f"{h:02d}:{m:02d}:{s_val:02d},{ms:03d}"
        else:
            return f"{h:02d}:{m:02d}:{s_val:02d}.{ms:03d}"

    def _run_asr(self) -> str:
        """ASR 语音识别"""
        from src.core.asr import ASRRecognizer
        from pathlib import Path
        import time

        input_path = self.params["input_path"]
        output_path = self.params["output_path"]
        model = self.params["model"]
        language = self.params["language"]
        export_sub = self.params.get("export_subtitle", False)
        sub_fmt = self.params.get("sub_format", "srt")
        disable_vad = self.params.get("disable_vad", True)

        out_p = Path(output_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)

        self.progress.emit(f"[工具箱] 加载 Whisper 模型 ({model})...")
        t0 = time.time()
        recognizer = ASRRecognizer(
            model_size=model, language=language,
            disable_vad=disable_vad
        )

        self.progress.emit("[工具箱] 正在识别...")
        results = recognizer.recognize(input_path, output_path)

        elapsed = time.time() - t0

        msg_lines = [
            f"识别完成！",
            f"输出文本: {output_path}",
            f"识别条目: {len(results)}",
            f"耗时: {elapsed:.1f}s",
        ]

        if export_sub and results:
            sub_path = out_p.with_suffix(f".{sub_fmt}")
            sub_lines = []
            if sub_fmt == "srt":
                for i, r in enumerate(results, 1):
                    text = r.get("text", "")
                    start = r.get("start", 0)
                    end = r.get("end", start + 2)
                    srt_start = self._fmt_ts(start, "srt")
                    srt_end = self._fmt_ts(end, "srt")
                    sub_lines.append(f"{i}\n{srt_start} --> {srt_end}\n{text}\n")
            elif sub_fmt == "vtt":
                sub_lines.append("WEBVTT\n")
                for r in results:
                    text = r.get("text", "")
                    start = r.get("start", 0)
                    end = r.get("end", start + 2)
                    vtt_start = self._fmt_ts(start, "vtt")
                    vtt_end = self._fmt_ts(end, "vtt")
                    sub_lines.append(f"{vtt_start} --> {vtt_end}\n{text}\n")
            elif sub_fmt == "lrc":
                for r in results:
                    text = r.get("text", "")
                    start = r.get("start", 0)
                    ms = int(start * 1000)
                    m = ms // 60000
                    s = (ms % 60000) // 1000
                    cs = ms % 1000
                    ts = f"[{m:02d}:{s:02d}.{cs:02d}]"
                    sub_lines.append(f"{ts}{text}")
            else:
                # 默认 SRT
                for i, r in enumerate(results, 1):
                    text = r.get("text", "")
                    start = r.get("start", 0)
                    end = r.get("end", start + 2)
                    srt_start = self._fmt_ts(start, "srt")
                    srt_end = self._fmt_ts(end, "srt")
                    sub_lines.append(f"{i}\n{srt_start} --> {srt_end}\n{text}\n")
            sub_path.write_text("\n".join(sub_lines), encoding="utf-8")
            msg_lines.append(f"字幕文件: {sub_path}")

        return "\n".join(msg_lines)

    def _run_subtitle_gen(self) -> str:
        """字幕生成（文本/PDF → SRT/VTT/LRC）"""
        from src.core.subtitle_generator import SubtitleGenerator
        from pathlib import Path
        import time

        text = self.params["text"]
        duration = self.params.get("duration", 600.0)
        fmt = self.params.get("fmt", "srt")
        output_path = self.params["output_path"]

        out_p = Path(output_path)

        self.progress.emit("[工具箱] 正在生成字幕...")
        t0 = time.time()

        entries = SubtitleGenerator.generate_from_text(
            text=text,
            total_duration=duration,
            fmt=fmt,
            lang="zh",
        )

        SubtitleGenerator.save(entries, output_path, fmt)

        elapsed = time.time() - t0
        size_kb = out_p.stat().st_size / 1024 if out_p.exists() else 0

        return (
            f"字幕生成完成！\n"
            f"输出: {output_path}\n"
            f"条目数: {len(entries)}\n"
            f"文件大小: {size_kb:.1f} KB\n"
            f"耗时: {elapsed:.1f}s"
        )

    def _run_convert(self) -> str:
        """音频格式转换"""
        from pathlib import Path
        import subprocess
        import time
        import soundfile as sf

        input_path = self.params["input_path"]
        output_dir = self.params["output_dir"]
        target_fmt = self.params["format"]
        sample_rate = self.params.get("sample_rate")

        Path(output_dir).mkdir(parents=True, exist_ok=True)

        inp_p = Path(input_path)
        out_filename = f"{inp_p.stem}_converted.{target_fmt}"
        out_path = Path(output_dir) / out_filename

        self.progress.emit(f"[工具箱] 格式转换: {inp_p.suffix} -> .{target_fmt}")
        t0 = time.time()

        # 使用 soundfile 进行基础格式转换
        data, sr = sf.read(input_path)
        target_sr = sample_rate or sr

        # 根据目标格式选择子类型
        subtype_map = {
            "wav": "PCM_16",
            "mp3": "MPEG_LAYER_III",
            "flac": "PCM_24",
            "ogg": "VORBIS",
            "m4a": None,  # m4a 需要 ffmpeg
        }

        if target_fmt == "m4a":
            # m4a 不被 soundfile 直接支持，尝试 ffmpeg
            try:
                cmd = [
                    "ffmpeg", "-y", "-i", input_path,
                    "-ar", str(target_sr), "-ac", "2",
                    "-c:a", "aac", "-b:a", "192k",
                    str(out_path),
                ]
                subprocess.run(cmd, check=True, capture_output=True)
            except FileNotFoundError:
                raise RuntimeError("需要 ffmpeg 来转换为 M4A 格式。请确保 ffmpeg 已安装并添加到 PATH 中。")
        else:
            sf.write(str(out_path), data, target_sr, format=target_fmt,
                     subtype=subtype_map.get(target_fmt))

        elapsed = time.time() - t0
        size_mb = out_path.stat().st_size / (1024 * 1024)
        return f"转换完成！\n输出: {out_path}\n文件大小: {size_mb:.1f} MB\n采样率: {target_sr} Hz\n耗时: {elapsed:.1f}s"
