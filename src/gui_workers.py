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

# 支持的音频格式
AUDIO_EXTENSIONS = {".wav", ".mp3", ".flac", ".m4a", ".ogg", ".aac"}


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

    def _find_vtt_file(self) -> Optional[str]:
        """查找VTT字幕文件"""
        input_p = Path(self.input_path)

        # 可能的VTT文件名
        possible_vtt_names = [
            f"{input_p.name}.vtt",   # audio.wav.vtt
            f"{input_p.stem}.vtt",   # audio.vtt
        ]

        # 搜索目录
        search_dirs = [
            input_p.parent,                    # 同目录
            input_p.parent / "ASMR_O",         # ASMR_O 子目录
        ]

        for search_dir in search_dirs:
            if not search_dir.exists():
                continue
            for vtt_name in possible_vtt_names:
                vtt_path = search_dir / vtt_name
                if vtt_path.exists():
                    return str(vtt_path)

        return None

    def run(self):
        try:
            from src.core.pipeline import Pipeline, PipelineConfig

            # 确定 VTT 路径（用户指定优先，否则自动查找）
            vtt_path = self.vtt_path or self._find_vtt_file()

            # 构建 Pipeline 配置
            cfg = PipelineConfig(
                input_path=self.input_path,
                output_dir=self.output_dir,
                vtt_path=vtt_path,
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
                # 音色克隆 (report_17)
                clone_voice_after_separation=self.params.get("clone_voice_after_separation", False),
                clone_voice_name=self.params.get("clone_voice_name", ""),
            )

            pipeline = Pipeline(cfg)
            results = pipeline.run(progress_callback=self.progress.emit)

            mix_path = results.get("mix_path", "")
            cloned_profile_id = results.get("cloned_profile_id")

            # 构建完成消息
            msg_parts = []
            if mix_path:
                msg_parts.append(f"成品: {mix_path}")
            if cloned_profile_id:
                msg_parts.append(f"克隆音色: {cloned_profile_id}")
                msg_parts.append("(可在音色工坊中查看和管理)")

            final_msg = "\n".join(msg_parts) if msg_parts else "处理完成"

            self.finished.emit(True, final_msg)

        except Exception as e:
            import traceback
            traceback.print_exc()
            self.finished.emit(False, str(e))


class PreviewWorkerThread(QThread):
    """试音线程 - 避免阻塞GUI"""
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
            from src.core import TTSEngine

            temp_dir = Path(tempfile.gettempdir())
            ext = "wav" if self.engine == "qwen3" else "mp3"
            output_path = temp_dir / f"asmr_preview.{ext}"

            tts_engine = TTSEngine(
                engine=self.engine,
                voice=self.voice,
                voice_profile_id=self.voice_profile_id,
                speed=self.speed,
            )
            tts_engine.synthesize(self.test_text, str(output_path))
            self.finished.emit(True, "播放中...", str(output_path))
        except Exception as e:
            import traceback
            traceback.print_exc()
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

    def _find_vtt_file(self, input_path: Path) -> Optional[str]:
        """查找 VTT 字幕文件"""
        possible_vtt_names = [
            f"{input_path.name}.vtt",
            f"{input_path.stem}.vtt",
        ]
        search_dirs = [
            input_path.parent,
            input_path.parent / "ASMR_O",
        ]
        for search_dir in search_dirs:
            if not search_dir.exists():
                continue
            for vtt_name in possible_vtt_names:
                vtt_path = search_dir / vtt_name
                if vtt_path.exists():
                    return str(vtt_path)
        return None

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

            # 自动查找 VTT
            vtt_file = self._find_vtt_file(Path(input_path))

            # 构建 Pipeline 配置
            cfg = PipelineConfig(
                input_path=input_path,
                output_mode="batch",
                batch_root_dir=batch_root,
                vtt_path=vtt_file if vtt_file and Path(vtt_file).exists() else None,
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
                pipeline.run(progress_callback=None)

            mix_path = pipeline.results.get("mix_path", "")
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


class VoiceCloneWorker(QThread):
    """
    音色克隆 Worker - 在后台执行 Base clone

    信号:
        progress(str, int): 进度消息, 百分比
        finished(bool, str, str): (success, message, profile_id)
    """

    progress = Signal(str, int)
    finished = Signal(bool, str, str)

    def __init__(self, name: str, audio_path: str, ref_text: str = None):
        super().__init__()
        self.name = name
        self.audio_path = audio_path
        self.ref_text = ref_text or "你好，今天辛苦了，让我来帮你放松一下吧。"

    def run(self):
        try:
            from src.core.tts.voice_designer import VoiceDesigner

            def progress_callback(msg: str, percent: int):
                self.progress.emit(msg, percent)

            designer = VoiceDesigner()
            profile = designer.clone_from_audio(
                audio_path=self.audio_path,
                name=self.name,
                ref_text=self.ref_text,
                progress_callback=progress_callback,
            )

            self.finished.emit(True, f"音色 '{profile.name}' 克隆成功!", profile.id)

        except Exception as e:
            import traceback
            traceback.print_exc()
            self.finished.emit(False, f"音色克隆失败: {e}", "")


class VoicePreviewWorker(QThread):
    """
    音色试音 Worker - 支持所有音色类型

    信号:
        finished(bool, str, str): (success, message, audio_path)
    """

    finished = Signal(bool, str, str)

    def __init__(self, profile_id: str, test_text: str = None):
        super().__init__()
        self.profile_id = profile_id
        self.test_text = test_text or "你好，这是一段测试语音。"

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
            )

            self.finished.emit(True, "播放中...", audio_path)

        except Exception as e:
            import traceback
            traceback.print_exc()
            self.finished.emit(False, f"试音失败: {e}", "")
