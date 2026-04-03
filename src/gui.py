"""
ASMR Helper GUI - PySide6 主界面 (支持单文件和批量处理)
"""

import sys
import os
import threading
from pathlib import Path
from typing import Optional, List
from concurrent.futures import ThreadPoolExecutor, as_completed

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit, QFileDialog, QProgressBar,
    QTextEdit, QSlider, QGroupBox, QComboBox, QSpinBox, QDoubleSpinBox,
    QMessageBox, QStyleFactory, QTabWidget, QCheckBox, QListWidget,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QStackedWidget
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QFont, QAction

# 添加项目根目录
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.core import TTSEngine

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
                tts_speed=self.params.get("tts_speed", 1.0),
                original_volume=self.params.get("original_volume", 0.85),
                tts_volume_ratio=self.params.get("tts_ratio", 0.5),
                tts_delay_ms=self.params.get("tts_delay", 0),
                skip_existing=False,
            )

            pipeline = Pipeline(cfg)
            results = pipeline.run(progress_callback=self.progress.emit)

            mix_path = results.get("mix_path", "")
            if mix_path:
                self.finished.emit(True, mix_path)
            else:
                self.finished.emit(False, "流水线未生成混音文件")

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
            # 创建输出目录
            safe_name = "".join(
                c if c.isalnum() or c in " _-()" else "_" for c in Path(input_path).stem
            )
            out_dir = (
                Path(self.output_dir) / safe_name
                if self.output_dir
                else Path(input_path).parent / f"{safe_name}_output"
            )
            out_dir.mkdir(parents=True, exist_ok=True)

            # 检查是否跳过
            final_mix = out_dir / "final_mix.wav"
            if self.params.get("skip_existing", True) and final_mix.exists():
                result["status"] = "skipped"
                result["output"] = str(final_mix)
                return result

            # 自动查找 VTT
            vtt_file = self._find_vtt_file(Path(input_path))

            # 构建 Pipeline 配置
            cfg = PipelineConfig(
                input_path=input_path,
                output_dir=str(out_dir),
                vtt_path=vtt_file if vtt_file and Path(vtt_file).exists() else None,
                vocal_model=self.params.get("vocal_model", "htdemucs"),
                asr_model=self.params.get("asr_model", "large-v3"),
                asr_language="ja",
                tts_engine=self.params.get("tts_engine", "edge"),
                tts_voice=self.params.get("tts_voice", "zh-CN-XiaoxiaoNeural"),
                qwen3_voice=self.params.get("tts_voice", "Vivian"),
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


class MainWindow(QMainWindow):
    """主窗口"""

    def __init__(self):
        super().__init__()
        self.worker = None
        self.batch_worker = None
        self.setup_ui()

    def setup_ui(self):
        """设置UI"""
        self.setWindowTitle("ASMR Helper - 双语双轨处理工具")
        self.setMinimumSize(1000, 750)

        # 菜单栏
        menubar = self.menuBar()
        settings_menu = menubar.addMenu("设置")

        api_action = QAction("API 配置", self)
        api_action.triggered.connect(self.show_api_config)
        settings_menu.addAction(api_action)

        # 中央部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # 主布局
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(15, 15, 15, 15)

        # ===== 标题 =====
        title_label = QLabel("ASMR Helper - 双语双轨处理工具")
        title_font = QFont()
        title_font.setPointSize(16)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(title_label)

        # ===== 标签页 =====
        self.tabs = QTabWidget()
        self.tabs.addTab(self.create_single_tab(), "单文件处理")
        self.tabs.addTab(self.create_batch_tab(), "批量处理")
        main_layout.addWidget(self.tabs)

        # ===== 进度显示 =====
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimumHeight(22)
        self.progress_bar.setFormat("%p%")
        main_layout.addWidget(self.progress_bar)

        self.progress_text = QTextEdit()
        self.progress_text.setMaximumHeight(120)
        self.progress_text.setReadOnly(True)
        self.progress_text.setStyleSheet("""
            QTextEdit {
                background-color: #1e1e1e;
                color: #00ff00;
                font-family: Consolas, monospace;
                font-size: 11px;
                border: 1px solid #333;
            }
        """)
        main_layout.addWidget(self.progress_text)

    def create_single_tab(self) -> QWidget:
        """创建单文件处理标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(12)

        # ===== 输入设置 =====
        input_group = QGroupBox("输入设置")
        input_layout = QVBoxLayout()

        # 文件选择
        file_layout = QHBoxLayout()
        self.single_file_input = QLineEdit()
        self.single_file_input.setPlaceholderText("选择 ASMR 音频文件...")
        file_layout.addWidget(QLabel("音频:"))
        file_layout.addWidget(self.single_file_input)
        browse_btn = QPushButton("浏览...")
        browse_btn.clicked.connect(self.browse_single_file)
        file_layout.addWidget(browse_btn)
        input_layout.addLayout(file_layout)

        # 输出目录
        out_layout = QHBoxLayout()
        self.single_output_input = QLineEdit()
        out_layout.addWidget(QLabel("输出:"))
        out_layout.addWidget(self.single_output_input)
        out_browse_btn = QPushButton("浏览...")
        out_browse_btn.clicked.connect(self.browse_single_output)
        out_layout.addWidget(out_browse_btn)
        input_layout.addLayout(out_layout)

        input_group.setLayout(input_layout)
        layout.addWidget(input_group)

        # ===== 人声分离 + ASR 设置 =====
        vocal_group = QGroupBox("人声分离 / 语音识别设置")
        vocal_layout = QHBoxLayout()
        vocal_layout.addWidget(QLabel("分离模型:"))
        self.single_vocal_model = QComboBox()
        self.single_vocal_model.addItems([
            "htdemucs (默认，4轨道)",
            "htdemucs_ft (微调版，效果更好)",
            "htdemucs_6s (6轨道，含钢琴/人声)",
            "mdx (MDX 模型)",
            "mdx_extra (MDX Extra，兼容性好)",
        ])
        self.single_vocal_model.setToolTip("htdemucs_ft 及以上版本分离效果更好，但需要更多显存")
        vocal_layout.addWidget(self.single_vocal_model)
        vocal_layout.addSpacing(20)
        vocal_layout.addWidget(QLabel("识别模型:"))
        self.single_asr_model = QComboBox()
        self.single_asr_model.addItems([
            "base (快速，精度一般)",
            "small (中等速度和精度)",
            "medium (较高精度)",
            "large-v3 (最高精度，推荐ASMR)",
        ])
        self.single_asr_model.setCurrentIndex(3)  # 默认 large-v3
        self.single_asr_model.setToolTip("large-v3 对轻声/日语识别效果最好（RTX 4070 Ti SUPER 可流畅运行）")
        vocal_layout.addWidget(self.single_asr_model)
        vocal_layout.addStretch()
        vocal_group.setLayout(vocal_layout)
        layout.addWidget(vocal_group)

        # ===== TTS 设置 =====
        tts_group = QGroupBox("TTS 设置")
        tts_layout = QVBoxLayout()

        # 引擎选择
        engine_layout = QHBoxLayout()
        engine_layout.addWidget(QLabel("引擎:"))
        self.single_tts_engine = QComboBox()
        self.single_tts_engine.addItems(["Edge-TTS", "Qwen3-TTS"])
        self.single_tts_engine.currentTextChanged.connect(self.on_single_engine_changed)
        engine_layout.addWidget(self.single_tts_engine)

        # 试音按钮
        self.single_preview_btn = QPushButton("试音")
        self.single_preview_btn.setMinimumWidth(60)
        self.single_preview_btn.clicked.connect(self.preview_voice)
        engine_layout.addWidget(self.single_preview_btn)
        engine_layout.addStretch()
        tts_layout.addLayout(engine_layout)

        # 音色选择（Tab 分类）
        voice_label_layout = QHBoxLayout()
        voice_label_layout.addWidget(QLabel("音色:"))
        voice_label_layout.addStretch()
        tts_layout.addLayout(voice_label_layout)

        # 音色选择容器 (Edge-TTS 和 Qwen3-TTS 切换)
        self.single_voice_container = QStackedWidget()

        # Edge-TTS 音色选择器 (Index 0)
        self.single_edge_voice = QComboBox()
        self.single_edge_voice.addItems([
            "zh-CN-XiaoxiaoNeural (晓晓-女)",
            "zh-CN-YunxiNeural (云希-男)",
            "zh-CN-YunyangNeural (云扬-男)",
            "zh-CN-XiaoyiNeural (小艺-女)",
            "zh-CN-XiaochenNeural (晓晨-女)",
            "ja-JP-NanamiNeural (七海-日语女)",
            "ja-JP-KeigoNeural (圭吾-日语男)",
        ])
        edge_voice_widget = QWidget()
        edge_voice_layout = QVBoxLayout()
        edge_voice_layout.addWidget(self.single_edge_voice)
        edge_voice_layout.addStretch()
        edge_voice_widget.setLayout(edge_voice_layout)
        self.single_voice_container.addWidget(edge_voice_widget)

        # Qwen3-TTS 音色选择器 (Index 1) - 使用 QStackedWidget + QComboBox 替代 QTabWidget
        self.single_qwen3_voice_stack = QStackedWidget()

        # Tab 1: 预设音色
        self.single_preset_voice = QComboBox()
        self.single_preset_voice.addItems([
            "Vivian (A1)", "Serena (A2)", "Uncle_Fu (A3)", "Dylan (A4)",
            "Eric (A5)", "Ryan (A6)", "Ono_Anna (A7)"
        ])
        preset_layout = QVBoxLayout()
        preset_layout.addWidget(self.single_preset_voice)
        preset_layout.addStretch()
        preset_widget = QWidget()
        preset_widget.setLayout(preset_layout)
        self.single_qwen3_voice_stack.addWidget(preset_widget)

        # Tab 2: 自定义音色
        self.single_custom_voice = QComboBox()
        self.single_custom_voice.addItems([
            "治愈大姐姐 (B1)", "娇小萝莉 (B2)", "冷艳女王 (B3)", "温柔暖男 (B4)"
        ])
        custom_layout = QVBoxLayout()
        custom_layout.addWidget(self.single_custom_voice)
        custom_layout.addWidget(QLabel("（需要先运行预生成脚本）"))
        custom_layout.addStretch()
        custom_widget = QWidget()
        custom_widget.setLayout(custom_layout)
        self.single_qwen3_voice_stack.addWidget(custom_widget)

        # Tab 3: 克隆音色
        clone_layout = QVBoxLayout()
        self.single_clone_audio = QLineEdit()
        self.single_clone_audio.setPlaceholderText("选择参考音频...")
        clone_audio_layout = QHBoxLayout()
        clone_audio_layout.addWidget(self.single_clone_audio)
        clone_browse_btn = QPushButton("浏览")
        clone_browse_btn.clicked.connect(lambda: self._browse_clone_audio(self.single_clone_audio))
        clone_audio_layout.addWidget(clone_browse_btn)
        clone_layout.addLayout(clone_audio_layout)
        clone_layout.addWidget(QLabel("（需要先使用 Base 模型生成 prompt）"))
        clone_layout.addStretch()
        clone_widget = QWidget()
        clone_widget.setLayout(clone_layout)
        self.single_qwen3_voice_stack.addWidget(clone_widget)

        # 音色类型选择器 + QStackedWidget
        self.single_voice_type = QComboBox()
        self.single_voice_type.addItems(["预设音色", "自定义音色", "克隆音色"])
        self.single_voice_type.currentIndexChanged.connect(
            self.single_qwen3_voice_stack.setCurrentIndex
        )
        qwen3_voice_layout = QVBoxLayout()
        qwen3_voice_layout.addWidget(self.single_voice_type)
        qwen3_voice_layout.addWidget(self.single_qwen3_voice_stack)
        qwen3_voice_widget = QWidget()
        qwen3_voice_widget.setLayout(qwen3_voice_layout)
        self.single_voice_container.addWidget(qwen3_voice_widget)
        tts_layout.addWidget(self.single_voice_container)

        # 初始化：默认显示 Edge-TTS 音色选择器
        self.single_voice_container.setCurrentIndex(0)

        # Qwen3 语速
        speed_layout = QHBoxLayout()
        self.single_tts_speed_label = QLabel("语速:")
        self.single_tts_speed_label.setVisible(False)
        speed_layout.addWidget(self.single_tts_speed_label)
        self.single_tts_speed = QDoubleSpinBox()
        self.single_tts_speed.setRange(0.5, 2.0)
        self.single_tts_speed.setValue(1.0)
        self.single_tts_speed.setSingleStep(0.1)
        self.single_tts_speed.setSuffix(" x")
        self.single_tts_speed.setVisible(False)
        speed_layout.addWidget(self.single_tts_speed)
        speed_layout.addStretch()
        tts_layout.addLayout(speed_layout)

        tts_group.setLayout(tts_layout)
        layout.addWidget(tts_group)

        # ===== 音量/时间轴设置 =====
        settings_group = QGroupBox("混音设置")
        settings_layout = QVBoxLayout()

        # 音量
        orig_vol_layout = QHBoxLayout()
        orig_vol_layout.addWidget(QLabel("原音音量:"))
        self.single_orig_vol = QSlider(Qt.Horizontal)
        self.single_orig_vol.setRange(0, 100)
        self.single_orig_vol.setValue(85)
        self.single_orig_vol.setTickPosition(QSlider.TicksBelow)
        self.single_orig_vol.setTickInterval(10)
        orig_vol_layout.addWidget(self.single_orig_vol)
        self.single_orig_vol_label = QLabel("85%")
        self.single_orig_vol_label.setMinimumWidth(40)
        orig_vol_layout.addWidget(self.single_orig_vol_label)
        self.single_orig_vol.valueChanged.connect(lambda v: self.single_orig_vol_label.setText(f"{v}%"))
        settings_layout.addLayout(orig_vol_layout)

        tts_vol_layout = QHBoxLayout()
        tts_vol_layout.addWidget(QLabel("配音音量:"))
        self.single_tts_vol = QSlider(Qt.Horizontal)
        self.single_tts_vol.setRange(0, 100)
        self.single_tts_vol.setValue(50)
        self.single_tts_vol.setTickPosition(QSlider.TicksBelow)
        self.single_tts_vol.setTickInterval(10)
        tts_vol_layout.addWidget(self.single_tts_vol)
        self.single_tts_vol_label = QLabel("50%")
        self.single_tts_vol_label.setMinimumWidth(40)
        tts_vol_layout.addWidget(self.single_tts_vol_label)
        self.single_tts_vol.valueChanged.connect(lambda v: self.single_tts_vol_label.setText(f"{v}%"))
        settings_layout.addLayout(tts_vol_layout)

        # 时间轴延迟
        delay_layout = QHBoxLayout()
        delay_layout.addWidget(QLabel("TTS延迟:"))
        self.single_delay = QSpinBox()
        self.single_delay.setRange(-3000, 3000)
        self.single_delay.setValue(0)
        self.single_delay.setSuffix(" ms")
        delay_layout.addWidget(self.single_delay)

        # 延迟调整按钮 (增量模式)
        def adjust_delay(delta):
            new_val = self.single_delay.value() + delta
            new_val = max(-3000, min(3000, new_val))
            self.single_delay.setValue(new_val)

        def reset_delay():
            self.single_delay.setValue(0)

        from functools import partial
        delay_m100_btn = QPushButton("-100ms")
        delay_m100_btn.clicked.connect(partial(adjust_delay, -100))
        delay_layout.addWidget(delay_m100_btn)

        delay_0_btn = QPushButton("Reset")
        delay_0_btn.clicked.connect(reset_delay)
        delay_layout.addWidget(delay_0_btn)

        delay_p100_btn = QPushButton("+100ms")
        delay_p100_btn.clicked.connect(partial(adjust_delay, 100))
        delay_layout.addWidget(delay_p100_btn)

        delay_layout.addStretch()
        settings_layout.addLayout(delay_layout)

        settings_group.setLayout(settings_layout)
        layout.addWidget(settings_group)

        # ===== 按钮 =====
        btn_layout = QHBoxLayout()
        self.single_start_btn = QPushButton("开始处理")
        self.single_start_btn.setMinimumHeight(35)
        self.single_start_btn.setStyleSheet("QPushButton{background-color:#0078d4;color:white;font-weight:bold;border-radius:5px;}")
        self.single_start_btn.clicked.connect(self.start_single)
        btn_layout.addWidget(self.single_start_btn)

        self.single_stop_btn = QPushButton("停止")
        self.single_stop_btn.setMinimumHeight(35)
        self.single_stop_btn.setEnabled(False)
        self.single_stop_btn.clicked.connect(self.stop_single)
        btn_layout.addWidget(self.single_stop_btn)

        layout.addLayout(btn_layout)
        layout.addStretch()

        # 初始化音色列表
        self.on_single_engine_changed("Edge-TTS")

        return widget

    def create_batch_tab(self) -> QWidget:
        """创建批量处理标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(12)

        # ===== 输入设置 =====
        input_group = QGroupBox("批量处理设置")
        input_layout = QVBoxLayout()

        # 目录选择
        dir_layout = QHBoxLayout()
        self.batch_dir_input = QLineEdit()
        self.batch_dir_input.setPlaceholderText("选择包含音频文件的文件夹...")
        dir_layout.addWidget(QLabel("文件夹:"))
        dir_layout.addWidget(self.batch_dir_input)
        dir_btn = QPushButton("浏览...")
        dir_btn.clicked.connect(self.browse_batch_dir)
        dir_layout.addWidget(dir_btn)
        input_layout.addLayout(dir_layout)

        # 输出目录
        out_layout = QHBoxLayout()
        self.batch_output_input = QLineEdit()
        out_layout.addWidget(QLabel("输出:"))
        out_layout.addWidget(self.batch_output_input)
        out_btn = QPushButton("浏览...")
        out_btn.clicked.connect(self.browse_batch_output)
        out_layout.addWidget(out_btn)
        input_layout.addLayout(out_layout)

        # 文件列表
        self.batch_file_list = QListWidget()
        self.batch_file_list.setMaximumHeight(150)
        input_layout.addWidget(QLabel("待处理文件:"))
        input_layout.addWidget(self.batch_file_list)

        # 刷新按钮
        refresh_btn = QPushButton("刷新文件列表")
        refresh_btn.clicked.connect(self.refresh_batch_files)
        input_layout.addWidget(refresh_btn)

        input_group.setLayout(input_layout)
        layout.addWidget(input_group)

        # ===== TTS 设置 =====
        tts_group = QGroupBox("TTS 设置")
        tts_layout = QVBoxLayout()

        engine_layout = QHBoxLayout()
        engine_layout.addWidget(QLabel("引擎:"))
        self.batch_tts_engine = QComboBox()
        self.batch_tts_engine.addItems(["Edge-TTS", "Qwen3-TTS"])
        self.batch_tts_engine.currentTextChanged.connect(self.on_batch_engine_changed)
        engine_layout.addWidget(self.batch_tts_engine)
        engine_layout.addStretch()
        tts_layout.addLayout(engine_layout)

        # 音色选择（Tab 分类）
        voice_label_layout = QHBoxLayout()
        voice_label_layout.addWidget(QLabel("音色:"))
        voice_label_layout.addStretch()
        tts_layout.addLayout(voice_label_layout)

        # 音色选择容器 (Edge-TTS 和 Qwen3-TTS 切换)
        self.batch_voice_container = QStackedWidget()

        # Edge-TTS 音色选择器 (Index 0)
        self.batch_edge_voice = QComboBox()
        self.batch_edge_voice.addItems([
            "zh-CN-XiaoxiaoNeural (晓晓-女)",
            "zh-CN-YunxiNeural (云希-男)",
            "zh-CN-YunyangNeural (云扬-男)",
            "zh-CN-XiaoyiNeural (小艺-女)",
            "zh-CN-XiaochenNeural (晓晨-女)",
            "ja-JP-NanamiNeural (七海-日语女)",
            "ja-JP-KeigoNeural (圭吾-日语男)",
        ])
        edge_voice_widget = QWidget()
        edge_voice_layout = QVBoxLayout()
        edge_voice_layout.addWidget(self.batch_edge_voice)
        edge_voice_layout.addStretch()
        edge_voice_widget.setLayout(edge_voice_layout)
        self.batch_voice_container.addWidget(edge_voice_widget)

        # Qwen3-TTS 音色选择器 (Index 1) - 使用 QStackedWidget + QComboBox 替代 QTabWidget
        self.batch_qwen3_voice_stack = QStackedWidget()

        # Tab 1: 预设音色
        self.batch_preset_voice = QComboBox()
        self.batch_preset_voice.addItems([
            "Vivian (A1)", "Serena (A2)", "Uncle_Fu (A3)", "Dylan (A4)",
            "Eric (A5)", "Ryan (A6)", "Ono_Anna (A7)"
        ])
        preset_layout = QVBoxLayout()
        preset_layout.addWidget(self.batch_preset_voice)
        preset_layout.addStretch()
        preset_widget = QWidget()
        preset_widget.setLayout(preset_layout)
        self.batch_qwen3_voice_stack.addWidget(preset_widget)

        # Tab 2: 自定义音色
        self.batch_custom_voice = QComboBox()
        self.batch_custom_voice.addItems([
            "治愈大姐姐 (B1)", "娇小萝莉 (B2)", "冷艳女王 (B3)", "温柔暖男 (B4)"
        ])
        custom_layout = QVBoxLayout()
        custom_layout.addWidget(self.batch_custom_voice)
        custom_layout.addWidget(QLabel("（需要先运行预生成脚本）"))
        custom_layout.addStretch()
        custom_widget = QWidget()
        custom_widget.setLayout(custom_layout)
        self.batch_qwen3_voice_stack.addWidget(custom_widget)

        # Tab 3: 克隆音色
        clone_layout = QVBoxLayout()
        self.batch_clone_audio = QLineEdit()
        self.batch_clone_audio.setPlaceholderText("选择参考音频...")
        clone_audio_layout = QHBoxLayout()
        clone_audio_layout.addWidget(self.batch_clone_audio)
        clone_browse_btn = QPushButton("浏览")
        clone_browse_btn.clicked.connect(lambda: self._browse_clone_audio(self.batch_clone_audio))
        clone_audio_layout.addWidget(clone_browse_btn)
        clone_layout.addLayout(clone_audio_layout)
        clone_layout.addWidget(QLabel("（需要先使用 Base 模型生成 prompt）"))
        clone_layout.addStretch()
        clone_widget = QWidget()
        clone_widget.setLayout(clone_layout)
        self.batch_qwen3_voice_stack.addWidget(clone_widget)

        # 音色类型选择器 + QStackedWidget
        self.batch_voice_type = QComboBox()
        self.batch_voice_type.addItems(["预设音色", "自定义音色", "克隆音色"])
        self.batch_voice_type.currentIndexChanged.connect(
            self.batch_qwen3_voice_stack.setCurrentIndex
        )
        qwen3_voice_layout = QVBoxLayout()
        qwen3_voice_layout.addWidget(self.batch_voice_type)
        qwen3_voice_layout.addWidget(self.batch_qwen3_voice_stack)
        qwen3_voice_widget = QWidget()
        qwen3_voice_widget.setLayout(qwen3_voice_layout)
        self.batch_voice_container.addWidget(qwen3_voice_widget)
        tts_layout.addWidget(self.batch_voice_container)

        # 初始化：默认显示 Edge-TTS 音色选择器
        self.batch_voice_container.setCurrentIndex(0)

        # Qwen3 语速
        speed_layout = QHBoxLayout()
        self.batch_tts_speed_label = QLabel("语速:")
        self.batch_tts_speed_label.setVisible(False)
        speed_layout.addWidget(self.batch_tts_speed_label)
        self.batch_tts_speed = QDoubleSpinBox()
        self.batch_tts_speed.setRange(0.5, 2.0)
        self.batch_tts_speed.setValue(1.0)
        self.batch_tts_speed.setSingleStep(0.1)
        self.batch_tts_speed.setSuffix(" x")
        self.batch_tts_speed.setVisible(False)
        speed_layout.addWidget(self.batch_tts_speed)
        speed_layout.addStretch()
        tts_layout.addLayout(speed_layout)

        # ASR 和分离模型设置
        model_layout = QHBoxLayout()
        model_layout.addWidget(QLabel("识别模型:"))
        self.batch_asr_model = QComboBox()
        self.batch_asr_model.addItems([
            "base (快速，精度一般)",
            "small (中等速度和精度)",
            "medium (较高精度)",
            "large-v3 (最高精度，推荐ASMR)",
        ])
        self.batch_asr_model.setCurrentIndex(3)  # 默认 large-v3
        model_layout.addWidget(self.batch_asr_model)
        model_layout.addSpacing(20)
        model_layout.addWidget(QLabel("分离模型:"))
        self.batch_vocal_model = QComboBox()
        self.batch_vocal_model.addItems([
            "htdemucs (默认，4轨道)",
            "htdemucs_ft (微调版，效果更好)",
            "htdemucs_6s (6轨道，含钢琴/人声)",
            "mdx (MDX 模型)",
            "mdx_extra (MDX Extra，兼容性好)",
        ])
        self.batch_vocal_model.setToolTip("人声分离使用的 Demucs 模型")
        model_layout.addWidget(self.batch_vocal_model)
        model_layout.addStretch()
        tts_layout.addLayout(model_layout)

        tts_group.setLayout(tts_layout)
        layout.addWidget(tts_group)

        # ===== 混音设置 =====
        mix_group = QGroupBox("混音设置")
        mix_layout = QVBoxLayout()

        orig_vol_layout = QHBoxLayout()
        orig_vol_layout.addWidget(QLabel("原音音量:"))
        self.batch_orig_vol = QSlider(Qt.Horizontal)
        self.batch_orig_vol.setRange(0, 100)
        self.batch_orig_vol.setValue(85)
        orig_vol_layout.addWidget(self.batch_orig_vol)
        self.batch_orig_vol_label = QLabel("85%")
        self.batch_orig_vol_label.setMinimumWidth(40)
        orig_vol_layout.addWidget(self.batch_orig_vol_label)
        self.batch_orig_vol.valueChanged.connect(lambda v: self.batch_orig_vol_label.setText(f"{v}%"))
        mix_layout.addLayout(orig_vol_layout)

        tts_vol_layout = QHBoxLayout()
        tts_vol_layout.addWidget(QLabel("配音音量:"))
        self.batch_tts_vol = QSlider(Qt.Horizontal)
        self.batch_tts_vol.setRange(0, 100)
        self.batch_tts_vol.setValue(50)
        tts_vol_layout.addWidget(self.batch_tts_vol)
        self.batch_tts_vol_label = QLabel("50%")
        self.batch_tts_vol_label.setMinimumWidth(40)
        tts_vol_layout.addWidget(self.batch_tts_vol_label)
        self.batch_tts_vol.valueChanged.connect(lambda v: self.batch_tts_vol_label.setText(f"{v}%"))
        mix_layout.addLayout(tts_vol_layout)

        delay_layout = QHBoxLayout()
        delay_layout.addWidget(QLabel("TTS延迟:"))
        self.batch_delay = QSpinBox()
        self.batch_delay.setRange(-3000, 3000)
        self.batch_delay.setValue(0)
        self.batch_delay.setSuffix(" ms")
        delay_layout.addWidget(self.batch_delay)
        delay_layout.addStretch()
        mix_layout.addLayout(delay_layout)

        # 跳过选项
        self.batch_skip_existing = QCheckBox("跳过已处理的文件")
        self.batch_skip_existing.setChecked(True)
        mix_layout.addWidget(self.batch_skip_existing)

        # 并行度设置
        parallel_layout = QHBoxLayout()
        parallel_layout.addWidget(QLabel("并行处理:"))
        self.batch_parallel = QSpinBox()
        self.batch_parallel.setRange(1, 4)
        self.batch_parallel.setValue(1)
        self.batch_parallel.setToolTip(
            "并行处理文件数。RTX 4070 Ti SUPER 建议设为 1（避免 GPU OOM）\n"
            "使用 Edge-TTS 时可设为 2（不占用 GPU）"
        )
        parallel_layout.addWidget(self.batch_parallel)
        parallel_layout.addWidget(QLabel(" 个文件同时处理"))
        parallel_layout.addStretch()
        mix_layout.addLayout(parallel_layout)

        mix_group.setLayout(mix_layout)
        layout.addWidget(mix_group)

        # ===== 按钮 =====
        btn_layout = QHBoxLayout()
        self.batch_start_btn = QPushButton("开始批量处理")
        self.batch_start_btn.setMinimumHeight(35)
        self.batch_start_btn.setStyleSheet("QPushButton{background-color:#107c10;color:white;font-weight:bold;border-radius:5px;}")
        self.batch_start_btn.clicked.connect(self.start_batch)
        btn_layout.addWidget(self.batch_start_btn)

        self.batch_stop_btn = QPushButton("停止")
        self.batch_stop_btn.setMinimumHeight(35)
        self.batch_stop_btn.setEnabled(False)
        self.batch_stop_btn.clicked.connect(self.stop_batch)
        btn_layout.addWidget(self.batch_stop_btn)

        layout.addLayout(btn_layout)

        # 初始化
        self.on_batch_engine_changed("Edge-TTS")

        return widget

    def browse_single_file(self):
        """选择单文件"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择音频文件", "",
            "音频文件 (*.wav *.mp3 *.flac *.m4a *.ogg);;所有文件 (*.*)"
        )
        if file_path:
            self.single_file_input.setText(file_path)
            if not self.single_output_input.text():
                p = Path(file_path)
                safe_name = "".join(c if c.isalnum() or c in " _-()" else "_" for c in p.stem)
                self.single_output_input.setText(str(p.parent / f"{safe_name}_output"))

    def browse_single_output(self):
        """选择单文件输出目录"""
        dir_path = QFileDialog.getExistingDirectory(self, "选择输出目录", "")
        if dir_path:
            self.single_output_input.setText(dir_path)

    def browse_batch_dir(self):
        """选择批量处理目录"""
        dir_path = QFileDialog.getExistingDirectory(self, "选择包含音频文件的文件夹", "")
        if dir_path:
            self.batch_dir_input.setText(dir_path)
            self.refresh_batch_files()

    def browse_batch_output(self):
        """选择批量处理输出目录"""
        dir_path = QFileDialog.getExistingDirectory(self, "选择输出目录", "")
        if dir_path:
            self.batch_output_input.setText(dir_path)

    def refresh_batch_files(self):
        """刷新批量处理文件列表"""
        dir_path = self.batch_dir_input.text().strip()
        if not dir_path:
            return

        self.batch_file_list.clear()
        for ext in AUDIO_EXTENSIONS:
            for f in Path(dir_path).rglob(f"*{ext}"):
                self.batch_file_list.addItem(str(f))

        count = self.batch_file_list.count()
        self.progress_text.append(f"在 {dir_path} 中找到 {count} 个音频文件")

    def on_single_engine_changed(self, engine: str):
        """单文件 TTS 引擎改变"""
        if engine == "Edge-TTS":
            # Edge-TTS: 显示 Edge 音色选择器
            self.single_voice_container.setCurrentIndex(0)
            self.single_tts_speed_label.setVisible(False)
            self.single_tts_speed.setVisible(False)
        else:
            # Qwen3-TTS: 显示 Qwen3 音色 Tab
            self.single_voice_container.setCurrentIndex(1)
            self.single_tts_speed_label.setVisible(True)
            self.single_tts_speed.setVisible(True)

    def on_batch_engine_changed(self, engine: str):
        """批量处理 TTS 引擎改变"""
        if engine == "Edge-TTS":
            # Edge-TTS: 显示 Edge 音色选择器
            self.batch_voice_container.setCurrentIndex(0)
            self.batch_tts_speed_label.setVisible(False)
            self.batch_tts_speed.setVisible(False)
        else:
            # Qwen3-TTS: 显示 Qwen3 音色 Tab
            self.batch_voice_container.setCurrentIndex(1)
            self.batch_tts_speed_label.setVisible(True)
            self.batch_tts_speed.setVisible(True)

    def _browse_clone_audio(self, line_edit: QLineEdit):
        """浏览克隆参考音频"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择参考音频", "", "音频文件 (*.wav *.mp3 *.flac)"
        )
        if file_path:
            line_edit.setText(file_path)

    def _get_voice_info(self, engine: str, voice_tabs: QTabWidget = None,
                         preset_combo: QComboBox = None, custom_combo: QComboBox = None,
                         clone_line: QLineEdit = None, edge_combo: QComboBox = None) -> tuple:
        """
        从音色选择器获取音色信息

        Args:
            engine: 引擎类型 ("edge" 或 "qwen3")
            voice_tabs: Qwen3 音色 Tab (仅 Qwen3 需要)
            preset_combo: 预设音色下拉框 (仅 Qwen3 需要)
            custom_combo: 自定义音色下拉框 (仅 Qwen3 需要)
            clone_line: 克隆音色输入框 (仅 Qwen3 需要)
            edge_combo: Edge 音色下拉框 (仅 Edge 需要)

        Returns:
            (tts_voice, voice_profile_id)
        """
        if engine == "edge":
            # Edge-TTS: 直接返回选中的音色
            if edge_combo is not None:
                voice_text = edge_combo.currentText()
                return voice_text.split(" ")[0], None  # "zh-CN-XiaoxiaoNeural"
            return "zh-CN-XiaoxiaoNeural", None

        # Qwen3-TTS: 从 voice_type 下拉框获取音色
        # voice_tabs 参数现在代表 voice_type QComboBox
        if voice_tabs is None:
            return "Vivian", "A1"

        tab_index = voice_tabs.currentIndex()
        if tab_index == 0:
            # 预设音色
            voice_text = preset_combo.currentText()
            profile_id = voice_text.split("(")[1].rstrip(")") if "(" in voice_text else None
            return voice_text.split(" ")[0], profile_id
        elif tab_index == 1:
            # 自定义音色
            voice_text = custom_combo.currentText()
            profile_id = voice_text.split("(")[1].rstrip(")") if "(" in voice_text else None
            return voice_text.split(" ")[0], profile_id
        else:
            # 克隆音色
            return clone_line.text(), None

    def get_single_params(self) -> dict:
        """获取单文件处理参数"""
        engine = "edge" if self.single_tts_engine.currentText() == "Edge-TTS" else "qwen3"

        # 解析人声分离模型
        model_map = {
            "htdemucs (默认，4轨道)": "htdemucs",
            "htdemucs_ft (微调版，效果更好)": "htdemucs_ft",
            "htdemucs_6s (6轨道，含钢琴/人声)": "htdemucs_6s",
            "mdx (MDX 模型)": "mdx",
            "mdx_extra (MDX Extra，兼容性好)": "mdx_extra",
        }
        vocal_model = model_map.get(self.single_vocal_model.currentText(), "htdemucs")

        # 解析 ASR 模型
        asr_map = {
            "base (快速，精度一般)": "base",
            "small (中等速度和精度)": "small",
            "medium (较高精度)": "medium",
            "large-v3 (最高精度，推荐ASMR)": "large-v3",
        }
        asr_model = asr_map.get(self.single_asr_model.currentText(), "large-v3")

        # 获取音色信息 (根据引擎类型获取)
        tts_voice, voice_profile_id = self._get_voice_info(
            engine,
            voice_tabs=self.single_voice_type,
            preset_combo=self.single_preset_voice,
            custom_combo=self.single_custom_voice,
            clone_line=self.single_clone_audio,
            edge_combo=self.single_edge_voice
        )

        return {
            "tts_engine": engine,
            "tts_voice": tts_voice,
            "voice_profile_id": voice_profile_id,
            "tts_speed": self.single_tts_speed.value(),
            "original_volume": self.single_orig_vol.value() / 100.0,
            "tts_ratio": self.single_tts_vol.value() / 100.0,
            "tts_delay": self.single_delay.value(),
            "vocal_model": vocal_model,
            "asr_model": asr_model,
        }

    def get_batch_params(self) -> dict:
        """获取批量处理参数"""
        engine = "edge" if self.batch_tts_engine.currentText() == "Edge-TTS" else "qwen3"
        asr_map = {
            "base (快速，精度一般)": "base",
            "small (中等速度和精度)": "small",
            "medium (较高精度)": "medium",
            "large-v3 (最高精度，推荐ASMR)": "large-v3",
        }
        asr_model = asr_map.get(self.batch_asr_model.currentText(), "large-v3")
        vocal_map = {
            "htdemucs (默认，4轨道)": "htdemucs",
            "htdemucs_ft (微调版，效果更好)": "htdemucs_ft",
            "htdemucs_6s (6轨道，含钢琴/人声)": "htdemucs_6s",
            "mdx (MDX 模型)": "mdx",
            "mdx_extra (MDX Extra，兼容性好)": "mdx_extra",
        }
        vocal_model = vocal_map.get(self.batch_vocal_model.currentText(), "htdemucs")

        # 获取音色信息 (根据引擎类型获取)
        tts_voice, voice_profile_id = self._get_voice_info(
            engine,
            voice_tabs=self.batch_voice_type,
            preset_combo=self.batch_preset_voice,
            custom_combo=self.batch_custom_voice,
            clone_line=self.batch_clone_audio,
            edge_combo=self.batch_edge_voice
        )

        return {
            "tts_engine": engine,
            "tts_voice": tts_voice,
            "voice_profile_id": voice_profile_id,
            "tts_speed": self.batch_tts_speed.value(),
            "original_volume": self.batch_orig_vol.value() / 100.0,
            "tts_ratio": self.batch_tts_vol.value() / 100.0,
            "tts_delay": self.batch_delay.value(),
            "skip_existing": self.batch_skip_existing.isChecked(),
            "vocal_model": vocal_model,
            "asr_model": asr_model,
            "max_workers": self.batch_parallel.value(),  # 并行度
        }

    def start_single(self):
        """开始单文件处理"""
        input_file = self.single_file_input.text().strip()
        if not input_file or not Path(input_file).exists():
            QMessageBox.warning(self, "警告", "请选择有效的音频文件！")
            return

        output_dir = self.single_output_input.text().strip()
        if not output_dir:
            p = Path(input_file)
            safe_name = "".join(c if c.isalnum() or c in " _-()" else "_" for c in p.stem)
            output_dir = str(p.parent / f"{safe_name}_output")
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        params = self.get_single_params()
        
        # 查找 VTT 文件
        vtt_path = None
        input_p = Path(input_file)
        possible_vtt_names = [
            f"{input_p.name}.vtt",
            f"{input_p.stem}.vtt",
        ]
        search_dirs = [
            input_p.parent,
            input_p.parent / "ASMR_O",
        ]
        for search_dir in search_dirs:
            if not search_dir.exists():
                continue
            for vtt_name in possible_vtt_names:
                candidate = search_dir / vtt_name
                if candidate.exists():
                    vtt_path = str(candidate)
                    break
            if vtt_path:
                break
        
        self.log(f"开始处理: {input_file}")
        self.log(f"输出目录: {output_dir}")
        if vtt_path:
            self.log(f"VTT字幕: {vtt_path}")
        else:
            self.log(f"VTT字幕: 未找到（将使用API翻译）")
        self.log(f"TTS引擎: {params['tts_engine']}, 音色: {params['tts_voice']}")
        self.log(f"原音音量: {params['original_volume']*100:.0f}%, 配音音量: {params['tts_ratio']*100:.0f}%")
        self.log(f"TTS延迟: {params['tts_delay']}ms\n")

        self.single_start_btn.setEnabled(False)
        self.single_stop_btn.setEnabled(True)
        self.progress_bar.setValue(0)

        self.worker = SingleWorkerThread(input_file, output_dir, params, vtt_path)
        self.worker.progress.connect(self.on_single_progress)
        self.worker.finished.connect(self.on_single_finished)
        self.worker.start()

    def stop_single(self):
        """停止单文件处理"""
        if self.worker and self.worker.isRunning():
            self.worker.terminate()
            self.worker.wait()
        self.log("\n[已停止]")
        self.single_start_btn.setEnabled(True)
        self.single_stop_btn.setEnabled(False)

    def on_single_progress(self, msg: str):
        """单文件进度更新（支持动态步骤数）"""
        import re
        self.log(msg)

        # 动态解析步骤数：支持 [1/3], [2/5], [1/4] 等格式
        match = re.search(r"\[(\d+)/(\d+)\]", msg)
        if match:
            current = int(match.group(1))
            total = int(match.group(2))
            if total > 0:
                # 进度 = 当前步骤 / 总步骤 * 100
                progress = int((current / total) * 100)
                self.progress_bar.setMaximum(100)
                self.progress_bar.setValue(progress)

    def on_single_finished(self, success: bool, message: str):
        """单文件处理完成"""
        self.progress_bar.setValue(100 if success else 0)
        self.single_start_btn.setEnabled(True)
        self.single_stop_btn.setEnabled(False)

        if success:
            self.log(f"\n处理完成!\n输出: {message}")
            QMessageBox.information(self, "完成", f"处理完成！\n\n{message}")
        else:
            self.log(f"\n处理失败: {message}")
            QMessageBox.critical(self, "错误", f"处理失败:\n\n{message}")

    def start_batch(self):
        """开始批量处理"""
        file_count = self.batch_file_list.count()
        if file_count == 0:
            QMessageBox.warning(self, "警告", "没有找到待处理的文件！")
            return

        input_files = [self.batch_file_list.item(i).text() for i in range(file_count)]
        output_dir = self.batch_output_input.text().strip()
        params = self.get_batch_params()
        max_workers = params.pop("max_workers", 1)  # 取出并行度，剩余参数传给 Worker

        self.log(f"开始批量处理 {file_count} 个文件")
        self.log(f"输出目录: {output_dir or '与源文件同目录'}")
        self.log(f"跳过已处理: {params['skip_existing']}")
        self.log(f"并行度: {max_workers}\n")

        self.batch_start_btn.setEnabled(False)
        self.batch_stop_btn.setEnabled(True)
        self.progress_bar.setValue(0)

        self.batch_worker = BatchWorkerThread(input_files, output_dir, params, max_workers=max_workers)
        self.batch_worker.progress.connect(self.log)
        self.batch_worker.file_progress.connect(self.on_batch_file_progress)
        self.batch_worker.finished.connect(self.on_batch_finished)
        self.batch_worker.start()

    def stop_batch(self):
        """停止批量处理"""
        if self.batch_worker and self.batch_worker.isRunning():
            self.batch_worker.terminate()
            self.batch_worker.wait()
        self.log("\n[已停止]")
        self.batch_start_btn.setEnabled(True)
        self.batch_stop_btn.setEnabled(False)

    def on_batch_file_progress(self, current: int, total: int, filename: str):
        """批量处理文件进度"""
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)

    def on_batch_finished(self, results: list):
        """批量处理完成"""
        self.batch_start_btn.setEnabled(True)
        self.batch_stop_btn.setEnabled(False)

        success = sum(1 for r in results if r["status"] == "success")
        skipped = sum(1 for r in results if r["status"] == "skipped")
        failed = sum(1 for r in results if r["status"] == "failed")

        self.log(f"\n{'='*50}")
        self.log(f"批量处理完成!")
        self.log(f"成功: {success}, 跳过: {skipped}, 失败: {failed}")

        if failed > 0:
            self.log("\n失败的文件:")
            for r in results:
                if r["status"] == "failed":
                    self.log(f"  - {r['file']}: {r.get('error', 'Unknown')}")

        QMessageBox.information(
            self, "完成",
            f"批量处理完成!\n\n成功: {success}\n跳过: {skipped}\n失败: {failed}"
        )

    def preview_voice(self):
        """试音功能（使用线程避免阻塞）"""
        # 防止重复点击
        if hasattr(self, 'preview_thread') and self.preview_thread.isRunning():
            return

        engine = "edge" if self.single_tts_engine.currentText() == "Edge-TTS" else "qwen3"

        # 使用 _get_voice_info 获取当前选中的音色
        voice, voice_profile_id = self._get_voice_info(
            engine,
            voice_tabs=self.single_voice_type,
            preset_combo=self.single_preset_voice,
            custom_combo=self.single_custom_voice,
            clone_line=self.single_clone_audio,
            edge_combo=self.single_edge_voice
        )

        if not voice:
            QMessageBox.warning(self, "警告", "请先选择音色！")
            return

        self.log(f"[试音] 引擎: {engine}, 音色: {voice}, profile: {voice_profile_id}")
        self.single_preview_btn.setEnabled(False)
        self.single_preview_btn.setText("试音中...")

        test_text = "你好，这是一段测试语音。"

        # 使用线程执行 TTS，避免阻塞 GUI
        self.preview_thread = PreviewWorkerThread(
            engine=engine,
            voice=voice,
            voice_profile_id=voice_profile_id,
            speed=self.single_tts_speed.value() if engine == "qwen3" else 1.0,
            test_text=test_text,
        )
        self.preview_thread.finished.connect(self._on_preview_finished)
        self.preview_thread.start()

    def _on_preview_finished(self, success: bool, message: str, output_path: str):
        """试音完成回调"""
        self.single_preview_btn.setEnabled(True)
        self.single_preview_btn.setText("试音")

        if success:
            self.log(f"[试音] {message}")
            # 播放音频
            import subprocess
            import platform
            if platform.system() == "Windows":
                subprocess.Popen(["powershell", "-c", f"Start-Process '{output_path}'"])
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", output_path])
            else:
                subprocess.Popen(["xdg-open", output_path])
        else:
            self.log(f"[试音] 失败: {message}")
            QMessageBox.critical(self, "错误", f"试音失败:\n{message}")

    def log(self, msg: str):
        """添加日志"""
        self.progress_text.append(msg)
        self.progress_text.verticalScrollBar().setValue(
            self.progress_text.verticalScrollBar().maximum()
        )

    def show_api_config(self):
        """显示 API 配置对话框"""
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QFormLayout, QLineEdit, QPushButton, QDialogButtonBox
        from src.config import config

        dialog = QDialog(self)
        dialog.setWindowTitle("API 配置")
        dialog.setMinimumWidth(500)

        layout = QVBoxLayout(dialog)

        form = QFormLayout()
        layout.addLayout(form)

        # DeepSeek API Key
        deepseek_key = QLineEdit()
        deepseek_key.setPlaceholderText("输入 DeepSeek API Key")
        deepseek_key.setText(config.deepseek_api_key)
        deepseek_key.setEchoMode(QLineEdit.Password)
        form.addRow("DeepSeek API Key:", deepseek_key)

        # OpenAI API Key
        openai_key = QLineEdit()
        openai_key.setPlaceholderText("输入 OpenAI API Key")
        openai_key.setText(config.openai_api_key)
        openai_key.setEchoMode(QLineEdit.Password)
        form.addRow("OpenAI API Key:", openai_key)

        # 说明
        from PySide6.QtWidgets import QLabel
        info = QLabel("API Key 会保存在 config/config.json 文件中\n优先级: 环境变量 > 配置文件 > 空")
        info.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(info)

        # 按钮
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec():
            # 保存配置
            config.set("api.deepseek_api_key", deepseek_key.text())
            config.set("api.openai_api_key", openai_key.text())
            config.save()
            QMessageBox.information(self, "保存成功", "API 配置已保存！")


def main():
    """入口函数"""
    app = QApplication(sys.argv)
    app.setStyle(QStyleFactory.create("Fusion"))

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
