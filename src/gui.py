"""
ASMR Helper GUI - PySide6 主界面 (支持单文件和批量处理)

模块化结构：
- gui_workers.py: Worker 线程
- gui_services.py: 业务逻辑
"""

import sys
import os
import subprocess
from pathlib import Path
from typing import Optional, List

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QLineEdit, QFileDialog, QProgressBar,
    QTextEdit, QSlider, QGroupBox, QComboBox, QSpinBox, QDoubleSpinBox,
    QMessageBox, QStyleFactory, QTabWidget, QCheckBox, QListWidget,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QStackedWidget,
    QScrollArea
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QFont, QAction, QColor

# 添加项目根目录到 sys.path（支持直接运行脚本）
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# 导入拆分模块
from src.gui_workers import SingleWorkerThread, PreviewWorkerThread, BatchWorkerThread
from src.gui_services import scan_audio_files
from src.utils.constants import AUDIO_EXTENSIONS


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
        self.setMinimumSize(800, 600)

        # 菜单栏
        menubar = self.menuBar()
        settings_menu = menubar.addMenu("设置")

        api_action = QAction("API 配置", self)
        api_action.triggered.connect(self.show_api_config)
        settings_menu.addAction(api_action)

        asr_action = QAction("ASR 模型配置", self)
        asr_action.triggered.connect(self.show_asr_config)
        settings_menu.addAction(asr_action)

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
        title_font.setPointSize(14)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(title_label)

        # ===== 标签页 =====
        self.tabs = QTabWidget()
        self.tabs.addTab(self._wrap_scroll(self.create_single_tab()), "单文件处理")
        self.tabs.addTab(self._wrap_scroll(self.create_batch_tab()), "批量处理")
        self.tabs.addTab(self._wrap_scroll(self.create_voice_workshop_tab()), "音色工坊")
        self.tabs.addTab(self._wrap_scroll(self.create_tools_tab()), "工具箱")
        main_layout.addWidget(self.tabs)

        # ===== 内置音频播放器 =====
        from src.utils.audio_player import AudioPlayerWidget
        self.audio_player = AudioPlayerWidget()
        main_layout.addWidget(self.audio_player)

        # ===== 进度显示 =====
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimumHeight(22)
        main_layout.addWidget(self.progress_bar)
        self.progress_bar.setFormat("%p%")  # 在addWidget之后设置，避免QPainter警告

        self.progress_text = QTextEdit()
        self.progress_text.setMaximumHeight(80)
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
        self._init_vocal_model_combo(self.single_vocal_model)
        self.single_vocal_model.setToolTip("htdemucs_ft 及以上版本分离效果更好，但需要更多显存")
        vocal_layout.addWidget(self.single_vocal_model)
        vocal_layout.addSpacing(20)
        vocal_layout.addWidget(QLabel("识别模型:"))
        self.single_asr_model = QComboBox()
        self._init_asr_model_combo(self.single_asr_model)
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
        # 初始化时从配置加载，稍后由 _refresh_custom_voice_combos() 填充
        custom_layout = QVBoxLayout()
        custom_layout.addWidget(self.single_custom_voice)
        custom_layout.addWidget(QLabel("（需要先运行预生成脚本）"))
        custom_layout.addStretch()
        custom_widget = QWidget()
        custom_widget.setLayout(custom_layout)
        self.single_qwen3_voice_stack.addWidget(custom_widget)

        # 音色类型选择器 + QStackedWidget（克隆音色功能已移至"音色工坊"页面）
        self.single_voice_type = QComboBox()
        self.single_voice_type.addItems(["预设音色", "自定义音色"])
        self.single_voice_type.currentIndexChanged.connect(
            self.single_qwen3_voice_stack.setCurrentIndex
        )
        qwen3_voice_layout = QVBoxLayout()
        qwen3_voice_layout.addWidget(self.single_voice_type)
        qwen3_voice_layout.addWidget(self.single_qwen3_voice_stack, 1)  # 拉伸因子=1
        qwen3_voice_widget = QWidget()
        qwen3_voice_widget.setLayout(qwen3_voice_layout)
        # 不设固定最小高度，让布局自然决定大小，滚动区域负责溢出处理
        self.single_voice_container.addWidget(qwen3_voice_widget)
        # 添加拉伸因子让容器能够正常显示
        tts_layout.addWidget(self.single_voice_container, stretch=1)

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

        # 时间轴偏移 (相对于原音)
        delay_layout = QHBoxLayout()
        delay_layout.addWidget(QLabel("音轨偏移:"))
        self.single_delay = QSpinBox()
        self.single_delay.setRange(-3000, 3000)
        self.single_delay.setValue(0)
        self.single_delay.setSuffix(" ms")
        self.single_delay.setToolTip("TTS 相对于原音的时间偏移\n正数：TTS 延后播放\n负数：TTS 提前播放")
        delay_layout.addWidget(self.single_delay)

        # 偏移调整按钮 (增量模式) - 交换位置并加上提示
        def adjust_delay(delta):
            new_val = self.single_delay.value() + delta
            new_val = max(-3000, min(3000, new_val))
            self.single_delay.setValue(new_val)

        def reset_delay():
            self.single_delay.setValue(0)

        from functools import partial
        # 交换位置：+100ms 在左（稍慢），-100ms 在右（稍快）
        delay_p100_btn = QPushButton("+100ms 稍慢")
        delay_p100_btn.setToolTip("让 TTS 相对于原音稍慢（晚播放）")
        delay_p100_btn.clicked.connect(partial(adjust_delay, 100))
        delay_layout.addWidget(delay_p100_btn)

        delay_0_btn = QPushButton("Reset")
        delay_0_btn.clicked.connect(reset_delay)
        delay_layout.addWidget(delay_0_btn)

        delay_m100_btn = QPushButton("-100ms 稍快")
        delay_m100_btn.setToolTip("让 TTS 相对于原音稍快（早播放）")
        delay_m100_btn.clicked.connect(partial(adjust_delay, -100))
        delay_layout.addWidget(delay_m100_btn)

        delay_layout.addStretch()
        settings_layout.addLayout(delay_layout)

        settings_group.setLayout(settings_layout)
        layout.addWidget(settings_group)

        # ===== 按钮 =====
        btn_layout = QHBoxLayout()
        self.single_start_btn = QPushButton("开始处理")
        self.single_start_btn.setMinimumHeight(30)
        self.single_start_btn.setStyleSheet("QPushButton{background-color:#0078d4;color:white;font-weight:bold;border:none;border-radius:5px;}")
        self.single_start_btn.clicked.connect(self.start_single)
        btn_layout.addWidget(self.single_start_btn)

        self.single_stop_btn = QPushButton("停止")
        self.single_stop_btn.setMinimumHeight(30)
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
        self.batch_file_list.setMaximumHeight(100)
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
        # 初始化时从配置加载，稍后由 _refresh_custom_voice_combos() 填充
        custom_layout = QVBoxLayout()
        custom_layout.addWidget(self.batch_custom_voice)
        custom_layout.addWidget(QLabel("（需要先运行预生成脚本）"))
        custom_layout.addStretch()
        custom_widget = QWidget()
        custom_widget.setLayout(custom_layout)
        self.batch_qwen3_voice_stack.addWidget(custom_widget)

        # 音色类型选择器 + QStackedWidget（克隆音色功能已移至"音色工坊"页面）
        self.batch_voice_type = QComboBox()
        self.batch_voice_type.addItems(["预设音色", "自定义音色"])
        self.batch_voice_type.currentIndexChanged.connect(
            self.batch_qwen3_voice_stack.setCurrentIndex
        )
        qwen3_voice_layout = QVBoxLayout()
        qwen3_voice_layout.addWidget(self.batch_voice_type)
        qwen3_voice_layout.addWidget(self.batch_qwen3_voice_stack, 1)  # 拉伸因子=1
        qwen3_voice_widget = QWidget()
        qwen3_voice_widget.setLayout(qwen3_voice_layout)
        # 不设固定最小高度，让布局自然决定大小
        self.batch_voice_container.addWidget(qwen3_voice_widget)
        # 添加拉伸因子让容器能够正常显示
        tts_layout.addWidget(self.batch_voice_container, stretch=1)

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
        self._init_vocal_model_combo(self.batch_vocal_model)
        self.batch_vocal_model.setToolTip("人声分离使用的 Demucs 模型")
        model_layout.addWidget(self.batch_vocal_model)
        model_layout.addSpacing(20)
        model_layout.addWidget(QLabel("识别语言:"))
        self.batch_asr_lang = QComboBox()
        self._init_asr_lang_combo(self.batch_asr_lang)
        self.batch_asr_lang.setCurrentIndex(0)  # 默认日语
        model_layout.addWidget(self.batch_asr_lang)
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
        self.batch_delay.setToolTip("TTS 相对于原音的时间偏移\n正数：TTS 延后播放\n负数：TTS 提前播放")
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
        self.batch_start_btn.setMinimumHeight(30)
        self.batch_start_btn.setStyleSheet("QPushButton{background-color:#107c10;color:white;font-weight:bold;border:none;border-radius:5px;}")
        self.batch_start_btn.clicked.connect(self.start_batch)
        btn_layout.addWidget(self.batch_start_btn)

        self.batch_stop_btn = QPushButton("停止")
        self.batch_stop_btn.setMinimumHeight(30)
        self.batch_stop_btn.setEnabled(False)
        self.batch_stop_btn.clicked.connect(self.stop_batch)
        btn_layout.addWidget(self.batch_stop_btn)

        layout.addLayout(btn_layout)

        # 初始化
        self.on_batch_engine_changed("Edge-TTS")

        return widget

    @staticmethod
    def _wrap_scroll(widget: QWidget) -> QScrollArea:
        """将 widget 包裹在 QScrollArea 中，支持小屏幕/高缩放比例下滚动"""
        scroll = QScrollArea()
        scroll.setWidget(widget)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        return scroll

    @staticmethod
    def _init_vocal_model_combo(combo: QComboBox):
        """初始化人声分离模型下拉框（使用 setItemData 存储实际值）"""
        vocal_models = [
            ("htdemucs", "htdemucs (默认，4轨道)"),
            ("htdemucs_ft", "htdemucs_ft (微调版，效果更好)"),
            ("htdemucs_6s", "htdemucs_6s (6轨道，含钢琴/人声)"),
            ("mdx", "mdx (MDX 模型)"),
            ("mdx_extra", "mdx_extra (MDX Extra，兼容性好)"),
        ]
        for value, label in vocal_models:
            combo.addItem(label, userData=value)

    @staticmethod
    def _init_asr_lang_combo(combo: QComboBox):
        """初始化ASR识别语言下拉框"""
        lang_options = [
            ("ja", "ja (日语)"),
            ("zh", "zh (中文)"),
            ("en", "en (英语)"),
        ]
        for code, label in lang_options:
            combo.addItem(label, userData=code)

    @staticmethod
    def _init_asr_model_combo(combo: QComboBox):
        """初始化 ASR 识别模型下拉框（使用 setItemData 存储实际值）"""
        asr_models = [
            ("base", "base (快速，精度一般)"),
            ("small", "small (中等速度和精度)"),
            ("medium", "medium (较高精度)"),
            ("large-v3", "large-v3 (最高精度，推荐ASMR)"),
        ]
        for value, label in asr_models:
            combo.addItem(label, userData=value)

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
        else:
            # 自定义音色 (包含 B/C 系列)
            voice_text = custom_combo.currentText()
            profile_id = voice_text.split("(")[1].rstrip(")") if "(" in voice_text else None
            return voice_text.split(" ")[0], profile_id

    def get_single_params(self) -> dict:
        """获取单文件处理参数"""
        engine = "edge" if self.single_tts_engine.currentText() == "Edge-TTS" else "qwen3"

        # 使用 setItemData 存储的模型名
        vocal_model = self.single_vocal_model.currentData() or "htdemucs"
        asr_model = self.single_asr_model.currentData() or "large-v3"

        # 获取音色信息 (根据引擎类型获取)
        tts_voice, voice_profile_id = self._get_voice_info(
            engine,
            voice_tabs=self.single_voice_type,
            preset_combo=self.single_preset_voice,
            custom_combo=self.single_custom_voice,
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
            "asr_language": self.single_asr_lang.currentData() or "ja",
        }

    def get_batch_params(self) -> dict:
        """获取批量处理参数"""
        engine = "edge" if self.batch_tts_engine.currentText() == "Edge-TTS" else "qwen3"
        asr_model = self.batch_asr_model.currentData() or "large-v3"
        vocal_model = self.batch_vocal_model.currentData() or "htdemucs"

        # 获取音色信息 (根据引擎类型获取)
        tts_voice, voice_profile_id = self._get_voice_info(
            engine,
            voice_tabs=self.batch_voice_type,
            preset_combo=self.batch_preset_voice,
            custom_combo=self.batch_custom_voice,
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
            "asr_language": self.batch_asr_lang.currentData() or "ja",
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
        
        # 查找字幕文件 (支持 VTT / SRT / LRC)
        subtitle_path = None
        input_p = Path(input_file)
        search_dirs = [
            input_p.parent,
            input_p.parent / "ASMR_O",
        ]
        from src.utils import find_subtitle_file
        subtitle_path = find_subtitle_file(input_p, search_dirs)
        
        self.log(f"开始处理: {input_file}")
        self.log(f"输出目录: {output_dir}")
        if subtitle_path:
            sub_ext = Path(subtitle_path).suffix.upper().lstrip(".")
            self.log(f"字幕: {Path(subtitle_path).name} ({sub_ext}格式)")
        else:
            self.log(f"字幕: 未找到（将使用API翻译）")
        self.log(f"TTS引擎: {params['tts_engine']}, 音色: {params['tts_voice']}")
        self.log(f"原音音量: {params['original_volume']*100:.0f}%, 配音音量: {params['tts_ratio']*100:.0f}%")
        self.log(f"TTS延迟: {params['tts_delay']}ms\n")

        self.single_start_btn.setEnabled(False)
        self.single_stop_btn.setEnabled(True)
        self.progress_bar.setValue(0)

        self.worker = SingleWorkerThread(input_file, output_dir, params, subtitle_path)
        self.worker.progress.connect(self.on_single_progress)
        self.worker.finished.connect(self.on_single_finished)
        self.worker.start()

    def stop_single(self):
        """停止单文件处理"""
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            # 不调用 wait()：worker 的 finished 信号会自然触发 on_single_finished 回调
            # wait() 会阻塞主线程且可能与 finished 信号回调产生竞态
        else:
            # worker 已结束或为 None，手动恢复按钮状态
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

        # 如果是用户主动取消，不弹窗
        if self.worker and self.worker._cancel_event.is_set():
            self.log("\n[已停止]")
            return

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
            self.batch_worker.cancel()
            # 不调用 wait()：worker 的 finished 信号会自然触发 on_batch_finished 回调
        else:
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

        # 如果是用户主动取消，不弹窗
        if self.batch_worker and self.batch_worker._cancel_event.is_set():
            self.log("\n[已停止]")
            return

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
        if getattr(self, 'preview_thread', None) and self.preview_thread.isRunning():
            return

        engine = "edge" if self.single_tts_engine.currentText() == "Edge-TTS" else "qwen3"

        # 使用 _get_voice_info 获取当前选中的音色
        voice, voice_profile_id = self._get_voice_info(
            engine,
            voice_tabs=self.single_voice_type,
            preset_combo=self.single_preset_voice,
            custom_combo=self.single_custom_voice,
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
            # 使用内置播放器
            self.audio_player.load_and_play(output_path)
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

    def show_asr_config(self):
        """显示 ASR 模型配置对话框"""
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QFormLayout, QComboBox, QDialogButtonBox, QLabel
        from src.config import config

        dialog = QDialog(self)
        dialog.setWindowTitle("ASR 模型配置")
        dialog.setMinimumWidth(400)

        layout = QVBoxLayout(dialog)

        form = QFormLayout()
        layout.addLayout(form)

        # ASR 模型选择
        asr_model = QComboBox()
        asr_model.addItems([
            "tiny",      # 最快，质量一般
            "base",      # 快，质量较好
            "small",     # 中等速度，质量好
            "medium",    # 较慢，质量很好
            "large-v1",  # 慢，最佳质量
            "large-v2",
            "large-v3",  # 默认，最佳质量（推荐）
        ])
        current_model = config.get("processing.asr_model", "large-v3")
        asr_model.setCurrentText(current_model)
        form.addRow("ASR 模型:", asr_model)

        # 说明
        info = QLabel(
            "模型说明:\n"
            "• tiny/base/small: 速度快但识别准确度较低\n"
            "• medium: 平衡速度和质量\n"
            "• large-v3: 最佳准确度（默认，推荐用于音色克隆）\n\n"
            "注意: 更改后下次处理时生效"
        )
        info.setStyleSheet("color: gray; font-size: 11px;")
        info.setWordWrap(True)
        layout.addWidget(info)

        # 按钮
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec():
            # 保存配置
            config.set("processing.asr_model", asr_model.currentText())
            config.save()
            QMessageBox.information(self, "保存成功", "ASR 模型配置已保存！")

    def create_voice_workshop_tab(self) -> QWidget:
        """创建音色工坊标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(15)

        # ===== 音色定制区 =====
        design_group = QGroupBox("音色定制 (自然语言)")
        design_layout = QVBoxLayout()

        # 音色名称
        name_layout = QHBoxLayout()
        name_layout.addWidget(QLabel("音色名称:"))
        self.workshop_name = QLineEdit()
        self.workshop_name.setPlaceholderText("给音色起个名字...")
        self.workshop_name.setMaxLength(50)
        name_layout.addWidget(self.workshop_name)
        design_layout.addLayout(name_layout)

        # 预设模板
        template_layout = QHBoxLayout()
        template_layout.addWidget(QLabel("预设模板:"))
        self.workshop_template = QComboBox()
        self.workshop_template.addItems([
            "-- 选择模板 (可选) --",
            "治愈大姐姐: 温柔成熟的大姐姐声线，音调偏低，语速舒缓",
            "娇小萝莉: 可爱甜美的萝莉音，音调偏高，语速轻快",
            "冷艳女王: 高冷优雅的女王音，音调平稳，语气冷淡",
            "邻家女孩: 亲切自然的邻家女孩声线，音调适中",
            "磁性低音: 低沉磁性的男性声线，音调偏低",
        ])
        self.workshop_template.currentTextChanged.connect(self._on_template_changed)
        template_layout.addWidget(self.workshop_template)
        design_layout.addLayout(template_layout)

        # 音色描述
        desc_layout = QHBoxLayout()
        desc_layout.addWidget(QLabel("音色描述:"))
        desc_layout.addWidget(QLabel("(用自然语言描述你想要的音色)"))
        # 添加参考指南按钮
        self.workshop_guide_btn = QPushButton("参考指南")
        self.workshop_guide_btn.setFixedSize(80, 24)
        self.workshop_guide_btn.setStyleSheet("QPushButton{background-color:#6c757d;color:white;border:none;border-radius:4px;padding:2px;}")
        self.workshop_guide_btn.clicked.connect(self._open_voice_guide)
        desc_layout.addWidget(self.workshop_guide_btn)
        design_layout.addLayout(desc_layout)
        self.workshop_description = QTextEdit()
        self.workshop_description.setPlaceholderText(
            "例如: 温柔成熟的大姐姐声线，音调偏低，语速舒缓，让人感到安心..."
        )
        self.workshop_description.setMaximumHeight(80)
        design_layout.addWidget(self.workshop_description)

        # 生成按钮和进度
        btn_layout = QHBoxLayout()
        self.workshop_design_btn = QPushButton("生成音色")
        self.workshop_design_btn.setStyleSheet(
            "QPushButton{background-color:#0078d4;color:white;font-weight:bold;border:none;border-radius:5px;padding:8px;}"
        )
        self.workshop_design_btn.clicked.connect(self._start_voice_design)
        btn_layout.addWidget(self.workshop_design_btn)

        self.workshop_design_progress = QProgressBar()
        self.workshop_design_progress.setMinimumHeight(20)
        self.workshop_design_progress.setVisible(False)
        btn_layout.addWidget(self.workshop_design_progress, stretch=1)
        self.workshop_design_progress.setFormat("%p%")  # 在addWidget之后
        design_layout.addLayout(btn_layout)

        design_group.setLayout(design_layout)
        layout.addWidget(design_group)

        # ===== 原音频克隆区 =====
        clone_group = QGroupBox("原音频克隆")
        clone_layout = QVBoxLayout()

        # 提示
        hint = QLabel("提示: 支持单音频克隆或多音频片段批量克隆")
        hint.setStyleSheet("color: gray; font-size: 11px;")
        clone_layout.addWidget(hint)

        # 字幕文件（用于切分音频）
        subtitle_layout = QHBoxLayout()
        subtitle_layout.addWidget(QLabel("字幕文件:"))
        self.workshop_subtitle = QLineEdit()
        self.workshop_subtitle.setPlaceholderText("选择字幕文件(可选，用于自动切分音频)")
        subtitle_layout.addWidget(self.workshop_subtitle)
        sub_browse_btn = QPushButton("浏览...")
        sub_browse_btn.clicked.connect(self._browse_workshop_subtitle)
        subtitle_layout.addWidget(sub_browse_btn)
        clone_layout.addLayout(subtitle_layout)

        # 参考音频
        audio_layout = QHBoxLayout()
        audio_layout.addWidget(QLabel("参考音频:"))
        self.workshop_clone_audio = QLineEdit()
        self.workshop_clone_audio.setPlaceholderText("选择参考音频文件...")
        audio_layout.addWidget(self.workshop_clone_audio)
        browse_btn = QPushButton("浏览...")
        browse_btn.clicked.connect(self._browse_workshop_audio)
        audio_layout.addWidget(browse_btn)
        clone_layout.addLayout(audio_layout)

        # 识别语言
        lang_layout = QHBoxLayout()
        lang_layout.addWidget(QLabel("识别语言:"))
        self.workshop_asr_lang = QComboBox()
        self._init_asr_lang_combo(self.workshop_asr_lang)
        self.workshop_asr_lang.setCurrentIndex(0)  # 默认日语
        lang_layout.addWidget(self.workshop_asr_lang)
        lang_layout.addStretch()
        clone_layout.addLayout(lang_layout)

        # 克隆音色名称
        clone_name_layout = QHBoxLayout()
        clone_name_layout.addWidget(QLabel("音色名称:"))
        self.workshop_clone_name = QLineEdit()
        self.workshop_clone_name.setPlaceholderText("给克隆音色起个名字...")
        clone_name_layout.addWidget(self.workshop_clone_name)
        clone_layout.addLayout(clone_name_layout)

        # ===== 手动输入参考文本（高级选项，折叠）=====
        self.manual_ref_text_group = QGroupBox("高级: 手动覆盖 ref_text（可选）")
        self.manual_ref_text_group.setCheckable(True)
        self.manual_ref_text_group.setChecked(False)
        self.manual_ref_text_group.setStyleSheet("""
            QGroupBox {
                font-size: 11px;
                border: 1px solid #666;
                border-radius: 4px;
                margin-top: 8px;
                padding-top: 8px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
        """)
        manual_text_layout = QVBoxLayout()
        manual_hint = QLabel(
            "勾选后将使用此文本覆盖片段拼合后的 ref_text（慎用，需确保文本与音频对应）"
        )
        manual_hint.setStyleSheet("color: gray; font-size: 10px;")
        manual_hint.setWordWrap(True)
        manual_text_layout.addWidget(manual_hint)
        self.workshop_manual_ref_text = QTextEdit()
        self.workshop_manual_ref_text.setPlaceholderText(
            "在此粘贴参考音频对应的原始文本（日语）...\n"
            "留空则使用片段拼合的文本"
        )
        self.workshop_manual_ref_text.setMaximumHeight(50)
        manual_text_layout.addWidget(self.workshop_manual_ref_text)
        self.manual_ref_text_group.setLayout(manual_text_layout)
        clone_layout.addWidget(self.manual_ref_text_group)

        # ===== 分析音频按钮 =====
        analyze_layout = QHBoxLayout()
        self.workshop_analyze_btn = QPushButton("分析音频片段")
        self.workshop_analyze_btn.setStyleSheet(
            "QPushButton{background-color:#6c757d;color:white;font-weight:bold;border:none;border-radius:5px;padding:8px;}"
        )
        self.workshop_analyze_btn.clicked.connect(self._start_segment_analysis)
        analyze_layout.addWidget(self.workshop_analyze_btn)

        self.workshop_analyze_progress = QProgressBar()
        self.workshop_analyze_progress.setMinimumHeight(18)
        self.workshop_analyze_progress.setVisible(False)
        analyze_layout.addWidget(self.workshop_analyze_progress, stretch=1)
        self.workshop_analyze_progress.setFormat("%p%")
        clone_layout.addLayout(analyze_layout)

        # ===== 片段分析结果（初始隐藏）=====
        self.segment_result_group = QGroupBox("片段分析结果")
        self.segment_result_group.setVisible(False)
        segment_result_layout = QVBoxLayout()

        # 信息标签
        self.segment_info_label = QLabel()
        self.segment_info_label.setStyleSheet("color: #333; font-size: 11px;")
        segment_result_layout.addWidget(self.segment_info_label)

        # 片段表格
        self.segment_table = QTableWidget()
        self.segment_table.setColumnCount(5)
        self.segment_table.setHorizontalHeaderLabels(["选择", "#", "时长", "音质", "参考文本"])
        self.segment_table.horizontalHeader().setStretchLastSection(True)
        self.segment_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.segment_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.segment_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.segment_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.segment_table.setColumnWidth(0, 35)
        self.segment_table.setColumnWidth(1, 30)
        self.segment_table.setColumnWidth(2, 55)
        self.segment_table.setColumnWidth(3, 70)
        self.segment_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.segment_table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed)
        self.segment_table.verticalHeader().setVisible(False)
        self.segment_table.setMaximumHeight(200)
        self.segment_table.itemChanged.connect(self._on_segment_table_changed)
        self._updating_table = False  # 防止信号循环
        segment_result_layout.addWidget(self.segment_table)

        # 合成预览
        preview_label = QLabel("合成 ref_text 预览:")
        preview_label.setStyleSheet("font-weight: bold; font-size: 11px;")
        segment_result_layout.addWidget(preview_label)
        self.segment_ref_text_preview = QTextEdit()
        self.segment_ref_text_preview.setReadOnly(True)
        self.segment_ref_text_preview.setMaximumHeight(50)
        self.segment_ref_text_preview.setStyleSheet(
            "QTextEdit { background-color: #f5f5f5; border: 1px solid #ccc; font-size: 12px; }"
        )
        segment_result_layout.addWidget(self.segment_ref_text_preview)

        # 操作按钮行
        seg_btn_layout = QHBoxLayout()
        seg_play_btn = QPushButton("播放选中")
        seg_play_btn.clicked.connect(self._play_selected_segments)
        seg_btn_layout.addWidget(seg_play_btn)
        seg_select_rec_btn = QPushButton("选择推荐")
        seg_select_rec_btn.setToolTip("自动选择质量最高的片段组合")
        seg_select_rec_btn.clicked.connect(self._select_recommended_segments)
        seg_btn_layout.addWidget(seg_select_rec_btn)
        seg_clear_btn = QPushButton("清除选择")
        seg_clear_btn.clicked.connect(self._clear_segment_selection)
        seg_btn_layout.addWidget(seg_clear_btn)
        seg_btn_layout.addStretch()
        segment_result_layout.addLayout(seg_btn_layout)

        self.segment_result_group.setLayout(segment_result_layout)
        clone_layout.addWidget(self.segment_result_group)

        # 克隆按钮和进度
        clone_btn_layout = QHBoxLayout()
        self.workshop_clone_btn = QPushButton("开始克隆")
        self.workshop_clone_btn.setStyleSheet(
            "QPushButton{background-color:#107c10;color:white;font-weight:bold;border:none;border-radius:5px;padding:8px;}"
        )
        self.workshop_clone_btn.clicked.connect(self._start_voice_clone)
        clone_btn_layout.addWidget(self.workshop_clone_btn)

        self.workshop_clone_progress = QProgressBar()
        self.workshop_clone_progress.setMinimumHeight(20)
        self.workshop_clone_progress.setVisible(False)
        clone_btn_layout.addWidget(self.workshop_clone_progress, stretch=1)
        self.workshop_clone_progress.setFormat("%p%")
        clone_layout.addLayout(clone_btn_layout)

        clone_group.setLayout(clone_layout)
        layout.addWidget(clone_group)

        # ===== 我的音色区 =====
        my_voices_group = QGroupBox("我的音色")
        my_voices_layout = QVBoxLayout()

        # 刷新按钮
        refresh_layout = QHBoxLayout()
        refresh_btn = QPushButton("刷新列表")
        refresh_btn.clicked.connect(self._refresh_my_voices)
        refresh_layout.addWidget(refresh_btn)
        refresh_layout.addStretch()
        my_voices_layout.addLayout(refresh_layout)

        # 音色列表
        self.workshop_voice_list = QListWidget()
        self.workshop_voice_list.setMaximumHeight(100)
        my_voices_layout.addWidget(self.workshop_voice_list)

        # 试音文本
        preview_layout = QHBoxLayout()
        preview_layout.addWidget(QLabel("试音文本:"))
        self.workshop_preview_text = QLineEdit()
        self.workshop_preview_text.setText("你好，这是一段测试语音。")
        preview_layout.addWidget(self.workshop_preview_text)
        my_voices_layout.addLayout(preview_layout)

        # 列表操作按钮
        list_btn_layout = QHBoxLayout()
        self.workshop_preview_btn = QPushButton("试音")
        self.workshop_preview_btn.clicked.connect(self._preview_workshop_voice)
        list_btn_layout.addWidget(self.workshop_preview_btn)

        self.workshop_delete_btn = QPushButton("删除")
        self.workshop_delete_btn.setStyleSheet("QPushButton{background-color:#d13438;color:white;border:none;border-radius:4px;padding:2px 8px;}")
        self.workshop_delete_btn.clicked.connect(self._delete_workshop_voice)
        list_btn_layout.addWidget(self.workshop_delete_btn)
        list_btn_layout.addStretch()
        my_voices_layout.addLayout(list_btn_layout)

        my_voices_group.setLayout(my_voices_layout)
        layout.addWidget(my_voices_group)

        # ===== GPU 状态 =====
        gpu_info = self._get_gpu_info()
        gpu_label = QLabel(f"GPU: {gpu_info}")
        gpu_label.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(gpu_label)

        layout.addStretch()

        # 初始化音色列表
        self._refresh_my_voices()

        return widget

    def create_tools_tab(self) -> QWidget:
        """创建工具箱标签页 - 提供独立的单步工具功能"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(15)

        # ===== 工具选择区 =====
        tool_group = QGroupBox("工具选择")
        tool_layout = QVBoxLayout()

        select_row = QHBoxLayout()
        select_row.addWidget(QLabel("选择工具:"))
        self.tools_combo = QComboBox()
        self.tools_combo.addItems([
            "-- 请选择工具 --",
            "音频分离 (Demucs 人声/伴奏分离)",
            "音频切分 (按字幕时间轴切分音频)",
            "ASR 识别 (语音转文字)",
            "格式转换 (音频格式互转)",
            "字幕生成 (文本/PDF转字幕)",
            "字幕翻译 (翻译字幕文件)",
        ])
        self.tools_combo.currentIndexChanged.connect(self._on_tool_changed)
        select_row.addWidget(self.tools_combo, 1)
        tool_layout.addLayout(select_row)

        # 工具说明
        self.tools_desc_label = QLabel("请从上方下拉框选择要使用的工具，然后填写参数并运行。")
        self.tools_desc_label.setStyleSheet("color: gray; font-size: 11px;")
        self.tools_desc_label.setWordWrap(True)
        tool_layout.addWidget(self.tools_desc_label)

        tool_group.setLayout(tool_layout)
        layout.addWidget(tool_group)

        # ===== 参数输入区（动态切换）=====
        self.tools_param_stack = QStackedWidget()

        # --- Page 0: 空占位 ---
        empty_page = QWidget()
        empty_layout = QVBoxLayout(empty_page)
        empty_layout.addStretch()
        hint_label = QLabel("← 请先选择一个工具")
        hint_label.setAlignment(Qt.AlignCenter)
        hint_label.setStyleSheet("color: #999; font-size: 13px;")
        empty_layout.addWidget(hint_label)
        empty_layout.addStretch()
        self.tools_param_stack.addWidget(empty_page)  # Index 0

        # --- Page 1: 音频分离 ---
        sep_page, self._sep_params = self._build_separation_tool_ui()
        self.tools_param_stack.addWidget(sep_page)  # Index 1

        # --- Page 2: 音频切分 ---
        split_page, self._split_params = self._build_split_tool_ui()
        self.tools_param_stack.addWidget(split_page)  # Index 2

        # --- Page 3: ASR 识别 ---
        asr_page, self._asr_params = self._build_asr_tool_ui()
        self.tools_param_stack.addWidget(asr_page)  # Index 3

        # --- Page 4: 格式转换 ---
        convert_page, self._convert_params = self._build_convert_tool_ui()
        self.tools_param_stack.addWidget(convert_page)  # Index 4

        # --- Page 5: 字幕生成 ---
        subgen_page, self._subgen_params = self._build_subtitle_gen_ui()
        self.tools_param_stack.addWidget(subgen_page)  # Index 5

        # --- Page 6: 字幕翻译 ---
        subtrans_page, self._subtrans_params = self._build_subtitle_translate_ui()
        self.tools_param_stack.addWidget(subtrans_page)  # Index 6

        self.tools_param_stack.setCurrentIndex(0)
        layout.addWidget(self.tools_param_stack, stretch=1)

        # ===== 运行按钮行 =====
        btn_layout = QHBoxLayout()
        self.tools_run_btn = QPushButton("▶ 运行")
        self.tools_run_btn.setMinimumHeight(32)
        self.tools_run_btn.setMinimumWidth(100)
        self.tools_run_btn.setEnabled(False)
        self.tools_run_btn.setStyleSheet(
            "QPushButton{background-color:#0078d4;color:white;font-weight:bold;"
            "border:none;border-radius:6px;font-size:13px;}"
            "QPushButton:hover{background-color:#1a86dd;}"
            "QPushButton:disabled{background-color:#555;color:#aaa;}"
        )
        self.tools_run_btn.clicked.connect(self._start_tool_run)
        btn_layout.addWidget(self.tools_run_btn)

        self.tools_stop_btn = QPushButton("停止")
        self.tools_stop_btn.setMinimumHeight(32)
        self.tools_stop_btn.setEnabled(False)
        self.tools_stop_btn.clicked.connect(self._stop_tool_run)
        btn_layout.addWidget(self.tools_stop_btn)

        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        layout.addStretch()

        return widget

    # ==================== 工具 UI 构建器 ====================

    @staticmethod
    def _make_file_input_row(label_text: str, placeholder: str,
                              browse_slot, parent_widget) -> tuple:
        """创建文件输入行 (QLineEdit + 浏览按钮)，返回 (layout, line_edit)"""
        row = QHBoxLayout()
        row.addWidget(QLabel(label_text))
        line_edit = QLineEdit()
        line_edit.setPlaceholderText(placeholder)
        row.addWidget(line_edit, 1)
        browse_btn = QPushButton("浏览...")
        browse_btn.setMaximumWidth(70)
        browse_btn.clicked.connect(browse_slot)
        row.addWidget(browse_btn)
        return row, line_edit

    def _build_separation_tool_ui(self) -> tuple:
        """构建音频分离工具的参数面板"""
        page = QWidget()
        form = QGridLayout(page)
        form.setSpacing(10)

        # 输入音频
        r0, self.sep_input = self._make_file_input_row(
            "输入音频:", "选择要分离的音频文件...",
            self._browse_sep_input, self
        )
        form.addLayout(r0, 0, 0, 1, 3)

        # 输出目录
        r1, self.sep_output = self._make_file_input_row(
            "输出目录:", "分离结果保存位置...",
            self._browse_sep_output, self
        )
        form.addLayout(r1, 1, 0, 1, 3)

        # 模型选择
        form.addWidget(QLabel("分离模型:"), 2, 0)
        self.sep_model = QComboBox()
        self._init_vocal_model_combo(self.sep_model)
        form.addWidget(self.sep_model, 2, 1, 1, 2)

        # 分离轨道（多选）
        form.addWidget(QLabel("提取轨道:"), 3, 0)
        stems_layout = QHBoxLayout()
        self.sep_stem_vocals = QCheckBox("vocals (人声)")
        self.sep_stem_vocals.setChecked(True)
        self.sep_stem_no_vocals = QCheckBox("no_vocals (伴奏)")
        self.sep_stem_drums = QCheckBox("drums (鼓声)")
        self.sep_stem_bass = QCheckBox("bass (贝斯)")
        self.sep_stem_piano = QCheckBox("piano (钢琴)")
        self.sep_stem_other = QCheckBox("other (其他)")
        stems_layout.addWidget(self.sep_stem_vocals)
        stems_layout.addWidget(self.sep_stem_no_vocals)
        stems_layout.addWidget(self.sep_stem_drums)
        stems_layout.addWidget(self.sep_stem_bass)
        stems_layout.addWidget(self.sep_stem_piano)
        stems_layout.addWidget(self.sep_stem_other)
        stems_layout.addStretch()
        form.addLayout(stems_layout, 3, 1, 1, 2)

        params = {
            "input": self.sep_input,
            "output": self.sep_output,
            "model": self.sep_model,
        }

        form.setRowStretch(4, 1)
        return page, params

    def _build_split_tool_ui(self) -> tuple:
        """构建音频切分工具的参数面板"""
        page = QWidget()
        form = QGridLayout(page)
        form.setSpacing(10)

        r0, self.split_audio = self._make_file_input_row(
            "输入音频:", "选择要切分的音频文件...",
            self._browse_split_audio, self
        )
        form.addLayout(r0, 0, 0, 1, 3)

        r1, self.split_subtitle = self._make_file_input_row(
            "字幕文件:", "选择用于切分的字幕文件 (VTT/SRT/LRC)...",
            self._browse_split_subtitle, self
        )
        form.addLayout(r1, 1, 0, 1, 3)

        r2, self.split_output = self._make_file_input_row(
            "输出目录:", "切分后的片段保存位置...",
            self._browse_split_output, self
        )
        form.addLayout(r2, 2, 0, 1, 3)

        # 切分模式
        form.addWidget(QLabel("切分模式:"), 3, 0)
        self.split_mode = QComboBox()
        self.split_mode.addItems(["按时间轴逐句切分", "按固定时长等分"])
        form.addWidget(self.split_mode, 3, 1, 1, 2)

        params = {
            "audio": self.split_audio,
            "subtitle": self.split_subtitle,
            "output": self.split_output,
            "mode": self.split_mode,
        }

        form.setRowStretch(4, 1)
        return page, params

    def _build_asr_tool_ui(self) -> tuple:
        """构建 ASR 识别工具的参数面板"""
        page = QWidget()
        form = QGridLayout(page)
        form.setSpacing(10)

        r0, self.asr_tool_input = self._make_file_input_row(
            "输入音频:", "选择要识别的音频文件...",
            self._browse_asr_tool_input, self
        )
        form.addLayout(r0, 0, 0, 1, 3)

        r1, self.asr_tool_output = self._make_file_input_row(
            "输出文件:", "识别结果保存位置 (如 result.txt)...",
            self._browse_asr_tool_output, self
        )
        form.addLayout(r1, 1, 0, 1, 3)

        form.addWidget(QLabel("识别模型:"), 2, 0)
        self.asr_tool_model = QComboBox()
        self._init_asr_model_combo(self.asr_tool_model)
        self.asr_tool_model.setCurrentIndex(3)  # large-v3
        form.addWidget(self.asr_tool_model, 2, 1, 1, 2)

        form.addWidget(QLabel("识别语言:"), 3, 0)
        self.asr_tool_lang = QComboBox()
        self.asr_tool_lang.addItems(["ja (日语)", "zh (中文)", "en (英语)"])
        form.addWidget(self.asr_tool_lang, 3, 1, 1, 2)

        # 导出选项
        self.asr_export_subtitle = QCheckBox("同时导出为字幕文件 (.srt)")
        self.asr_export_subtitle.setChecked(True)
        form.addWidget(self.asr_export_subtitle, 4, 0, 1, 3)

        params = {
            "input": self.asr_tool_input,
            "output": self.asr_tool_output,
            "model": self.asr_tool_model,
            "lang": self.asr_tool_lang,
            "export_subtitle": self.asr_export_subtitle,
        }
        form.setRowStretch(5, 1)
        return page, params

    def _build_convert_tool_ui(self) -> tuple:
        """构建格式转换工具的参数面板"""
        page = QWidget()
        form = QGridLayout(page)
        form.setSpacing(10)

        r0, self.conv_input = self._make_file_input_row(
            "输入文件:", "选择要转换的音频文件...",
            self._browse_conv_input, self
        )
        form.addLayout(r0, 0, 0, 1, 3)

        r1, self.conv_output_dir = self._make_file_input_row(
            "输出目录:", "转换后文件保存位置...",
            self._browse_conv_output_dir, self
        )
        form.addLayout(r1, 1, 0, 1, 3)

        form.addWidget(QLabel("目标格式:"), 2, 0)
        self.conv_format = QComboBox()
        self.conv_format.addItems(["WAV (无损)", "MP3 (压缩)", "FLAC (无损)", "OGG", "M4A (AAC)"])
        form.addWidget(self.conv_format, 2, 1, 1, 2)

        # 音质设置
        form.addWidget(QLabel("采样率:"), 3, 0)
        self.conv_sr = QComboBox()
        self.conv_sr.addItems(["保持原样", "44100 Hz", "48000 Hz", "22050 Hz"])
        self.conv_sr.setCurrentIndex(0)
        form.addWidget(self.conv_sr, 3, 1, 1, 2)

        params = {
            "input": self.conv_input,
            "output_dir": self.conv_output_dir,
            "format": self.conv_format,
            "sr": self.conv_sr,
        }
        form.setRowStretch(4, 1)
        return page, params

    def _build_subtitle_gen_ui(self) -> tuple:
        """构建字幕生成工具的参数面板（文本/PDF → SRT/VTT/LRC）

        增强：
        - Q1: PDF 多脚本自动检测与选择器
        - Q2: 动作描述过滤选项
        - Q3: ASR 对齐预览表格（运行后展示匹配结果）
        """
        page = QWidget()
        form = QGridLayout(page)
        form.setSpacing(10)

        row = 0

        # ===== 模式选择 =====
        form.addWidget(QLabel("生成模式:"), row, 0)
        self.subgen_mode = QComboBox()
        self.subgen_mode.addItems([
            "纯文本均分（按字符比例分配时间轴）",
            "ASR 对齐模式（配对音频文件，ASR获取真实时间轴）",
        ])
        self.subgen_mode.currentIndexChanged.connect(self._on_subgen_mode_changed)
        form.addWidget(self.subgen_mode, row, 1, 1, 2)
        row += 1

        # ===== 语言选择 =====
        form.addWidget(QLabel("语言:"), row, 0)
        self.subgen_lang = QComboBox()
        self._init_asr_lang_combo(self.subgen_lang)
        self.subgen_lang.setCurrentIndex(1)
        form.addWidget(self.subgen_lang, row, 1, 1, 2)
        row += 1

        # ===== 输入源：PDF 或 纯文本 =====
        form.addWidget(QLabel("输入源:"), row, 0)
        self.subgen_source = QComboBox()
        self.subgen_source.addItems(["纯文本文件 (.txt)", "PDF 文档 (.pdf)"])
        self.subgen_source.currentIndexChanged.connect(self._on_subgen_source_changed)
        form.addWidget(self.subgen_source, row, 1, 1, 2)
        row += 1

        # ===== 输入文件路径 =====
        r_input, self.subgen_input = self._make_file_input_row(
            "输入文件:", "选择文本或 PDF 文件...",
            self._browse_subgen_input, self
        )
        form.addLayout(r_input, row, 0, 1, 3)
        row += 1

        # ===== 配对音频 =====
        r_audio, self.subgen_audio = self._make_file_input_row(
            "配对音频:", "选择用于获取时长的音频文件...",
            self._browse_subgen_audio, self
        )
        form.addLayout(r_audio, row, 0, 1, 3)
        row += 1

        # ===== Q1: PDF 脚本选择器（默认隐藏）=====
        script_row = QHBoxLayout()
        script_row.addWidget(QLabel("选择脚本:"))
        self.subgen_script_combo = QComboBox()
        self.subgen_script_combo.addItem("-- 加载PDF后自动检测 --")
        self.subgen_script_combo.setMinimumWidth(200)
        script_row.addWidget(self.subgen_script_combo, 1)
        self.subgen_script_label = QLabel()
        self.subgen_script_label.setStyleSheet("color:#888; font-size:11px;")
        script_row.addWidget(self.subgen_script_label)
        self.subgen_script_widget = script_row
        form.addLayout(script_row, row, 0, 1, 3)
        self.subgen_script_row_idx = row
        row += 1

        # ===== 参数行 =====
        param_row = QHBoxLayout()
        param_row.addWidget(QLabel("输出格式:"))
        self.subgen_fmt = QComboBox()
        self.subgen_fmt.addItems(["SRT", "VTT", "LRC"])
        param_row.addWidget(self.subgen_fmt)
        param_row.addStretch()
        form.addLayout(param_row, row, 0, 1, 3)
        row += 1

        # 输出文件
        r_out, self.subgen_output = self._make_file_input_row(
            "输出文件:", "生成的字幕保存位置...",
            self._browse_subgen_output, self
        )
        form.addLayout(r_out, row, 0, 1, 3)
        row += 1

        # ===== Q3: ASR对齐结果预览表格 (默认隐藏) =====
        preview_group = QGroupBox("ASR 对齐预览")
        preview_layout = QVBoxLayout()

        self.subgen_align_table = QTableWidget()
        self.subgen_align_table.setColumnCount(5)
        self.subgen_align_table.setHorizontalHeaderLabels([
            "#", "用户台词", "匹配的ASR文本", "置信度", "时间轴"
        ])
        header = self.subgen_align_table.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.subgen_align_table.setMinimumHeight(120)
        self.subgen_align_table.setSelectionBehavior(QTableWidget.SelectRows)
        preview_layout.addWidget(self.subgen_align_table)

        align_hint = QLabel(
            "提示：在 ASR 对齐模式下运行后会显示匹配详情。\n"
            "可手动编辑台词内容后重新生成以改善对齐效果。"
        )
        align_hint.setStyleSheet("color:#888; font-size:11px;")
        preview_layout.addWidget(align_hint)

        preview_group.setLayout(preview_layout)
        form.addWidget(preview_group, row, 0, 1, 3)
        self.subgen_align_row_idx = row
        self.subgen_align_visible = False
        row += 1

        params = {
            "source": self.subgen_source,
            "input": self.subgen_input,
            "fmt": self.subgen_fmt,
            "output": self.subgen_output,
            "mode": self.subgen_mode,
            "lang": self.subgen_lang,
            "audio": self.subgen_audio,
            "script_combo": self.subgen_script_combo,
        }

        form.setRowStretch(row, 1)
        return page, params

    def _build_subtitle_translate_ui(self) -> tuple:
        """构建字幕翻译工具的参数面板"""
        page = QWidget()
        form = QGridLayout(page)
        form.setSpacing(10)

        # 输入字幕文件
        r0, self.subtrans_input = self._make_file_input_row(
            "字幕文件:", "选择要翻译的字幕文件 (SRT/VTT/LRC)...",
            self._browse_subtrans_input, self
        )
        form.addLayout(r0, 0, 0, 1, 3)

        # 输出文件
        r1, self.subtrans_output = self._make_file_input_row(
            "输出文件:", "翻译后的字幕保存路径...",
            self._browse_subtrans_output, self
        )
        form.addLayout(r1, 1, 0, 1, 3)

        # 语言设置
        lang_row = QHBoxLayout()
        lang_row.addWidget(QLabel("源语言:"))
        self.subtrans_source_lang = QComboBox()
        self._init_asr_lang_combo(self.subtrans_source_lang)
        self.subtrans_source_lang.setCurrentIndex(0)  # 默认日语
        lang_row.addWidget(self.subtrans_source_lang)

        lang_row.addWidget(QLabel("目标语言:"))
        self.subtrans_target_lang = QComboBox()
        self._init_asr_lang_combo(self.subtrans_target_lang)
        self.subtrans_target_lang.setCurrentIndex(1)  # 默认中文
        lang_row.addWidget(self.subtrans_target_lang)
        lang_row.addStretch()
        form.addLayout(lang_row, 2, 0, 1, 3)

        # 输出格式
        fmt_row = QHBoxLayout()
        fmt_row.addWidget(QLabel("输出格式:"))
        self.subtrans_fmt = QComboBox()
        self.subtrans_fmt.addItems(["SRT", "VTT", "LRC"])
        fmt_row.addWidget(self.subtrans_fmt)
        fmt_row.addStretch()
        form.addLayout(fmt_row, 3, 0, 1, 3)

        params = {
            "input": self.subtrans_input,
            "output": self.subtrans_output,
            "source_lang": self.subtrans_source_lang,
            "target_lang": self.subtrans_target_lang,
            "fmt": self.subtrans_fmt,
        }
        form.setRowStretch(4, 1)
        return page, params

    def _on_tool_changed(self, index: int):
        """切换工具时更新参数面板"""
        descriptions = {
            0: "请从上方下拉框选择要使用的工具，然后填写参数并运行。",
            1: "使用 Demucs 模型将音频分离为人声、伴奏、乐器等独立轨道。"
                "\n支持 htdemucs / htdemucs_ft / mdx 等多种模型。",
            2: "根据字幕文件中的时间戳信息，将长音频按句子边界切分为多个短片段。"
                "\n常用于音色克隆前的音频预处理。",
            3: "使用 Faster-Whisper 模型将语音内容转换为文字。"
                "\n支持导出为纯文本或带时间戳的字幕文件。",
            4: "在多种常见音频格式之间进行互相转换。"
                "\n可调整采样率、比特率等参数。",
            5: "从 PDF 文档或纯文本中提取台词，自动生成带时间轴的字幕文件。"
                "\n支持纯文本均分模式（按字符比例分配）和 ASR 对齐模式（配对音频获取真实时间轴）。\n支持 SRT/VTT/LRC 输出格式。",
            6: "将字幕文件翻译为目标语言，输出双语对照字幕。"
                "\n支持 DeepSeek / OpenAI 翻译引擎。",
        }
        desc = descriptions.get(index, "")
        self.tools_desc_label.setText(desc)
        self.tools_param_stack.setCurrentIndex(index)
        # index > 0 时启用运行按钮
        self.tools_run_btn.setEnabled(index > 0)

    def _start_tool_run(self):
        """启动选中的工具"""
        tool_index = self.tools_combo.currentIndex()
        if tool_index <= 0:
            QMessageBox.warning(self, "警告", "请先选择要运行的工具！")
            return

        # 收集当前工具的参数
        params = self._collect_tool_params(tool_index)
        if not params:
            return  # 用户已收到错误提示

        self.log(f"[工具箱] 启动工具: {self.tools_combo.currentText()}")

        self.tools_run_btn.setEnabled(False)
        self.tools_stop_btn.setEnabled(True)
        self.progress_bar.setValue(0)

        from src.gui_workers import ToolsWorkerThread
        self.tools_worker = ToolsWorkerThread(
            tool_id=tool_index,
            params=params,
        )
        self.tools_worker.progress.connect(self.log)
        self.tools_worker.finished.connect(self._on_tool_finished)
        # Q3: ASR对齐预览信号
        self.tools_worker.alignment_ready.connect(self._on_alignment_preview_ready)
        self.tools_worker.start()

    def _stop_tool_run(self):
        """停止工具执行"""
        if hasattr(self, 'tools_worker') and self.tools_worker and self.tools_worker.isRunning():
            self.tools_worker.cancel()
        else:
            self.tools_run_btn.setEnabled(True)
            self.tools_stop_btn.setEnabled(False)

    def _on_tool_finished(self, success: bool, message: str):
        """工具执行完成回调"""
        self.tools_run_btn.setEnabled(True)
        self.tools_stop_btn.setEnabled(False)
        self.progress_bar.setValue(100 if success else 0)

        if success:
            self.log(f"[工具箱] 完成: {message}")
            QMessageBox.information(self, "完成", f"工具执行完成！\n\n{message}")
        else:
            self.log(f"[工具箱] 失败: {message}")
            QMessageBox.critical(self, "错误", f"工具执行失败:\n{message}")

    def _on_alignment_preview_ready(self, align_data: list):
        """Q3: ASR对齐结果预览 - 填充表格"""
        if not hasattr(self, 'subgen_align_table'):
            return
        table = self.subgen_align_table
        table.setRowCount(len(align_data))

        # 置信度颜色映射
        conf_colors = {
            "high": "#2d7d2d",
            "medium": "#c4a000",
            "low": "#c43b3b",
            "none": "#666666",
        }

        for row, item in enumerate(align_data):
            # 序号
            idx_item = QTableWidgetItem(str(item["index"]))
            idx_item.setTextAlignment(Qt.AlignCenter)
            table.setItem(row, 0, idx_item)

            # 用户台词
            text_item = QTableWidgetItem(item["text"][:60] + ("..." if len(item["text"]) > 60 else ""))
            text_item.setToolTip(item["text"])
            table.setItem(row, 1, text_item)

            # 匹配的ASR文本
            asr_text = item.get("asr_text", "") or "(未匹配/估算)"
            asr_item = QTableWidgetItem(asr_text[:40] + ("..." if len(asr_text) > 40 else ""))
            asr_item.setToolTip(asr_text or "ASR未匹配到此句")
            table.setItem(row, 2, asr_item)

            # 置信度
            conf = item.get("confidence", "none")
            conf_label = conf.upper()
            score = item.get("score", 0)
            if score > 0:
                conf_label = f"{conf} ({score:.0%})"
            conf_item = QTableWidgetItem(conf_label)
            color = QColor(conf_colors.get(conf, "#888"))
            conf_item.setForeground(color)
            conf_item.setTextAlignment(Qt.AlignCenter)
            table.setItem(row, 3, conf_item)

            # 时间轴
            ts = f"{item['start']:.1f}s ~ {item['end']:.1f}s"
            ts_item = QTableWidgetItem(ts)
            ts_item.setTextAlignment(Qt.AlignCenter)
            table.setItem(row, 4, ts_item)

        # 显示对齐预览区（如果还没显示）
        if hasattr(self, 'subgen_align_table'):
            align_parent = self.subgen_align_table.parent()
            if align_parent and not align_parent.isVisible():
                align_parent.setVisible(True)

    def _collect_tool_params(self, tool_index: int) -> Optional[dict]:
        """收集当前选中工具的参数，返回 None 表示校验失败"""
        if tool_index == 1:
            # 音频分离
            audio = self.sep_input.text().strip()
            output = self.sep_output.text().strip()
            if not audio or not Path(audio).exists():
                QMessageBox.warning(self, "警告", "请选择有效的输入音频文件！")
                return None
            if not output:
                output = str(Path(audio).parent / "separated")

            model = self.sep_model.currentData() or "htdemucs"
            selected_stems = []
            if self.sep_stem_vocals.isChecked():
                selected_stems.append("vocals")
            if self.sep_stem_no_vocals.isChecked():
                selected_stems.append("no_vocals")
            if self.sep_stem_drums.isChecked():
                selected_stems.append("drums")
            if self.sep_stem_bass.isChecked():
                selected_stems.append("bass")
            if self.sep_stem_piano.isChecked():
                selected_stems.append("piano")
            if self.sep_stem_other.isChecked():
                selected_stems.append("other")
            if not selected_stems:
                selected_stems = ["vocals"]  # 默认至少提取人声

            return {"tool": "separate", "input_path": audio, "output_dir": output,
                    "model": model, "selected_stems": selected_stems}

        elif tool_index == 2:
            # 音频切分
            audio = self.split_audio.text().strip()
            subtitle = self.split_subtitle.text().strip()
            output = self.split_output.text().strip()
            if not audio or not Path(audio).exists():
                QMessageBox.warning(self, "警告", "请选择有效的输入音频文件！")
                return None
            if not subtitle or not Path(subtitle).exists():
                QMessageBox.warning(self, "警告", "请选择有效的字幕文件！")
                return None
            if not output:
                output = str(Path(audio).parent / "split_segments")

            mode = "timestamp" if self.split_mode.currentIndex() == 0 else "fixed_duration"
            return {"tool": "split", "audio_path": audio, "subtitle_path": subtitle,
                    "output_dir": output, "mode": mode}

        elif tool_index == 3:
            # ASR 识别
            audio = self.asr_tool_input.text().strip()
            output = self.asr_tool_output.text().strip()
            if not audio or not Path(audio).exists():
                QMessageBox.warning(self, "警告", "请选择有效的输入音频文件！")
                return None
            if not output:
                output = str(Path(audio).parent / f"{Path(audio).stem}_asr.txt")

            model = self.asr_tool_model.currentData() or "large-v3"
            lang_code = self.asr_tool_lang.currentText().split(" ")[0]
            export_sub = self.asr_export_subtitle.isChecked()

            return {"tool": "asr", "input_path": audio, "output_path": output,
                    "model": model, "language": lang_code, "export_subtitle": export_sub}

        elif tool_index == 4:
            # 格式转换
            inp = self.conv_input.text().strip()
            outdir = self.conv_output_dir.text().strip()
            if not inp or not Path(inp).exists():
                QMessageBox.warning(self, "警告", "请选择有效的输入文件！")
                return None
            if not outdir:
                outdir = str(Path(inp).parent)

            fmt_map = {
                "WAV (无损)": "wav", "MP3 (压缩)": "mp3",
                "FLAC (无损)": "flac", "OGG": "ogg", "M4A (AAC)": "m4a",
            }
            target_fmt = fmt_map.get(self.conv_format.currentText(), "wav")
            sr_val = self.conv_sr.currentText()
            sr = None if "原样" in sr_val else int(sr_val.split(" ")[0])

            return {"tool": "convert", "input_path": inp, "output_dir": outdir,
                    "format": target_fmt, "sample_rate": sr}

        elif tool_index == 5:
            # 字幕生成
            inp = self.subgen_input.text().strip()
            if not inp:
                QMessageBox.warning(self, "警告", "请选择输入文件！")
                return None

            output = self.subgen_output.text().strip()
            if not output:
                QMessageBox.warning(self, "警告", "请指定输出文件路径！")
                return None

            gen_mode = "asr_align" if self.subgen_mode.currentIndex() == 1 else "text"
            lang_code = self.subgen_lang.currentData() or "zh"
            fmt = self.subgen_fmt.currentText().lower()

            # Q1: PDF 脚本选择
            script_index = 0
            if hasattr(self, 'subgen_script_combo') and self.subgen_script_combo.isVisible():
                idx_data = self.subgen_script_combo.currentData()
                if idx_data is not None:
                    script_index = int(idx_data)

            result = {"tool": "subtitle_gen",
                       "input_path": inp,
                       "fmt": fmt,
                       "output_path": output,
                       "mode": gen_mode,
                       "lang": lang_code,
                       # Q1 参数
                       "script_index": script_index}

            # ASR 对齐模式需要配对音频
            if gen_mode == "asr_align":
                audio_path = self.subgen_audio.text().strip()
                if not audio_path or not Path(audio_path).exists():
                    QMessageBox.warning(self, "警告", "ASR 对齐模式需要选择有效的配对音频文件！")
                    return None
                result["audio_path"] = audio_path

            return result

        elif tool_index == 6:
            # 字幕翻译
            input_file = self.subtrans_input.text().strip()
            if not input_file or not Path(input_file).exists():
                QMessageBox.warning(self, "警告", "请选择有效的字幕文件！")
                return None

            output = self.subtrans_output.text().strip()
            if not output:
                base = Path(input_file)
                output = str(base.parent / f"{base.stem}_translated{base.suffix}")

            source_lang_code = self.subtrans_source_lang.currentData() or "ja"
            target_lang_code = self.subtrans_target_lang.currentData() or "zh"
            fmt = self.subtrans_fmt.currentText().lower()

            return {"tool": "subtitle_translate",
                    "input_path": input_file,
                    "output_path": output,
                    "source_lang": source_lang_code,
                    "target_lang": target_lang_code,
                    "format": fmt}

        return None

    # ==================== 工具文件浏览槽函数 ====================

    def _browse_sep_input(self):
        fp, _ = QFileDialog.getOpenFileName(self, "选择音频文件",
                                            "", "音频文件 (*.wav *.mp3 *.flac *.m4a *.ogg);;所有文件 (*)")
        if fp:
            self.sep_input.setText(fp)
            if not self.sep_output.text():
                self.sep_output.setText(str(Path(fp).parent / "separated"))

    def _browse_sep_output(self):
        d = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if d:
            self.sep_output.setText(d)

    def _browse_split_audio(self):
        fp, _ = QFileDialog.getOpenFileName(self, "选择音频文件",
                                            "", "音频文件 (*.wav *.mp3 *.flac *.m4a);;所有文件 (*)")
        if fp:
            self.split_audio.setText(fp)
            if not self.split_output.text():
                self.split_output.setText(str(Path(fp).parent / "split"))

    def _browse_split_subtitle(self):
        fp, _ = QFileDialog.getOpenFileName(self, "选择字幕文件",
                                            "", "字幕文件 (*.vtt *.srt *.lrc);;所有文件 (*)")
        if fp:
            self.split_subtitle.setText(fp)

    def _browse_split_output(self):
        d = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if d:
            self.split_output.setText(d)

    def _browse_subgen_input(self):
        source_idx = self.subgen_source.currentIndex()
        if source_idx == 0:  # 纯文本
            fp, _ = QFileDialog.getOpenFileName(
                self, "选择文本文件", "",
                "文本文件 (*.txt);;所有文件 (*)"
            )
        else:  # PDF
            fp, _ = QFileDialog.getOpenFileName(
                self, "选择 PDF 文件", "",
                "PDF 文件 (*.pdf);;所有文件 (*)"
            )
        if fp:
            self.subgen_input.setText(fp)
            # PDF模式下自动检测脚本
            try:
                if fp.lower().endswith(".pdf"):
                    from src.core.subtitle_generator import SubtitleGenerator
                    # Q1: 检测多脚本并填充选择器
                    scripts = SubtitleGenerator.extract_pdf_scripts(fp)
                    self._populate_pdf_script_selector(scripts)
                else:
                    # 非PDF时隐藏脚本选择器
                    if hasattr(self, 'subgen_script_widget'):
                        self.subgen_script_widget.setVisible(False)
            except Exception as e:
                self.log(f"[字幕生成] 加载文件失败: {e}")

    def _populate_pdf_script_selector(self, scripts: list):
        """Q1: 填充 PDF 脚本选择下拉框"""
        self.subgen_script_combo.clear()
        if not scripts or len(scripts) <= 1:
            self.subgen_script_combo.addItem("仅一个脚本")
            self.subgen_script_label.setText("")
            self.subgen_script_widget.setVisible(False)
            return

        for s in scripts:
            title = f"[{s['index']+1}] {s['title']}"
            page_info = f"P.{s.get('page_start', '?')+1}-{s.get('page_end', '?')+1}" \
                        if 'page_start' in s else ""
            display = f"{title} {page_info}".strip()
            self.subgen_script_combo.addItem(display, userData=s["index"])

        self.subgen_script_label.setText(f"检测到 {len(scripts)} 个脚本段落")
        self.subgen_script_widget.setVisible(True)

        # 切换脚本时重新加载文本
        try:
            self.subgen_script_combo.currentIndexChanged.disconnect(self._on_script_changed)
        except (TypeError, RuntimeError):
            pass
        self.subgen_script_combo.currentIndexChanged.connect(self._on_script_changed)
        # 缓存脚本列表供切换使用
        self._pdf_scripts_cache = scripts

    def _browse_subgen_output(self):
        fp, _ = QFileDialog.getSaveFileName(self, "选择输出文件",
                                             "subtitle.srt",
                                             "SRT 文件 (*.srt);;VTT 文件 (*.vtt);;LRC 文件 (*.lrc)")
        if fp:
            self.subgen_output.setText(fp)
            ext = Path(fp).suffix.lstrip(".").lower()
            idx = self.subgen_fmt.findText(ext.upper())
            if idx >= 0:
                self.subgen_fmt.setCurrentIndex(idx)

    def _browse_subgen_audio(self):
        fp, _ = QFileDialog.getOpenFileName(self, "选择配对音频",
                                            "", "音频文件 (*.wav *.mp3 *.flac *.m4a *.ogg);;所有文件 (*)")
        if fp:
            self.subgen_audio.setText(fp)

    def _on_subgen_mode_changed(self, index: int):
        """切换字幕生成模式时显示/隐藏对齐预览"""
        is_asr_mode = (index == 1)
        # Q3: 对齐预览表格 - 通过父 GroupBox 控制
        if hasattr(self, 'subgen_align_table'):
            align_parent = self.subgen_align_table.parent()
            if align_parent:
                align_parent.setVisible(is_asr_mode)

    def _on_subgen_source_changed(self, index: int):
        """切换输入源时显示/隐藏脚本选择器"""
        is_pdf = (index == 1)
        if hasattr(self, 'subgen_script_widget') and self.subgen_script_widget is not None:
            # subgen_script_widget 是 QHBoxLayout，用 setEnabled 控制可见性
            # 通过遍历其子 widget 设置
            for i in range(self.subgen_script_widget.count()):
                w = self.subgen_script_widget.itemAt(i).widget()
                if w:
                    w.setVisible(is_pdf)

    def _browse_subtrans_input(self):
        fp, _ = QFileDialog.getOpenFileName(self, "选择字幕文件",
                                            "", "字幕文件 (*.vtt *.srt *.lrc);;所有文件 (*)")
        if fp:
            self.subtrans_input.setText(fp)
            if not self.subtrans_output.text():
                base = Path(fp)
                self.subtrans_output.setText(str(base.parent / f"{base.stem}_translated{base.suffix}"))

    def _browse_subtrans_output(self):
        fp, _ = QFileDialog.getSaveFileName(self, "选择输出文件",
                                             "translated.srt",
                                             "SRT 文件 (*.srt);;VTT 文件 (*.vtt);;LRC 文件 (*.lrc)")
        if fp:
            self.subtrans_output.setText(fp)

    def _browse_asr_tool_input(self):
        fp, _ = QFileDialog.getOpenFileName(self, "选择音频文件",
                                            "", "音频文件 (*.wav *.mp3 *.flac *.m4a);;所有文件 (*)")
        if fp:
            self.asr_tool_input.setText(fp)
            if not self.asr_tool_output.text():
                self.asr_tool_output.setText(str(Path(fp).parent / f"{Path(fp).stem}_asr.txt"))

    def _browse_asr_tool_output(self):
        fp, _ = QFileDialog.getSaveFileName(self, "选择输出文件",
                                             "result.txt", "文本文件 (*.txt);;所有文件 (*)")
        if fp:
            self.asr_tool_output.setText(fp)

    def _browse_conv_input(self):
        fp, _ = QFileDialog.getOpenFileName(self, "选择音频文件",
                                            "", "音频文件 (*.wav *.mp3 *.flac *.m4a *.ogg);;所有文件 (*)")
        if fp:
            self.conv_input.setText(fp)
            if not self.conv_output_dir.text():
                self.conv_output_dir.setText(str(Path(fp).parent))

    def _browse_conv_output_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if d:
            self.conv_output_dir.setText(d)

    def _open_voice_guide(self):
        import os
        import subprocess
        from pathlib import Path

        guide_path = Path(__file__).parent.parent / "音色描述词指南.md"
        if guide_path.exists():
            try:
                os.startfile(str(guide_path))
            except Exception:
                self.log(f"[音色工坊] 无法打开指南: {guide_path}")
        else:
            self.log(f"[音色工坊] 指南文件不存在: {guide_path}")

    def _on_template_changed(self, text: str):
        """选择预设模板时自动填入描述"""
        if text.startswith("--"):
            return  # 跳过 "-- 选择模板 --" 选项

        if text:
            # 提取模板名称和描述
            if ": " in text:
                _, description = text.split(": ", 1)
                self.workshop_description.setText(description)

    def _start_voice_design(self):
        """开始音色设计"""
        name = self.workshop_name.text().strip()
        description = self.workshop_description.toPlainText().strip()

        if not name:
            QMessageBox.warning(self, "警告", "请输入音色名称!")
            return

        if not description:
            QMessageBox.warning(self, "警告", "请输入音色描述!")
            return

        # 禁用按钮
        self.workshop_design_btn.setEnabled(False)
        self.workshop_design_btn.setText("生成中...")
        self.workshop_design_progress.setVisible(True)
        self.workshop_design_progress.setValue(0)

        self.log(f"[音色工坊] 开始生成音色: {name}")

        # 导入 Worker
        from src.gui_workers import VoiceDesignWorker

        self.design_worker = VoiceDesignWorker(
            name=name,
            description=description,
        )
        self.design_worker.progress.connect(self._on_design_progress)
        self.design_worker.finished.connect(self._on_design_finished)
        self.design_worker.start()

    def _on_design_progress(self, msg: str, percent: int):
        """音色设计进度回调"""
        self.workshop_design_progress.setValue(percent)
        self.log(f"[音色工坊] {msg}")

    def _on_design_finished(self, success: bool, message: str, profile_id: str):
        """音色设计完成回调"""
        # 恢复按钮
        self.workshop_design_btn.setEnabled(True)
        self.workshop_design_btn.setText("生成音色")
        self.workshop_design_progress.setVisible(False)

        if success:
            self.log(f"[音色工坊] {message}")
            QMessageBox.information(self, "成功", message)
            # 清空输入
            self.workshop_name.clear()
            self.workshop_description.clear()
            self.workshop_template.setCurrentIndex(0)
            # 刷新音色列表
            self._refresh_my_voices()
        else:
            self.log(f"[音色工坊] 失败: {message}")
            QMessageBox.critical(self, "错误", message)

    def _browse_workshop_audio(self):
        """浏览音色工坊的参考音频"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择参考音频",
            "",
            "音频文件 (*.wav *.mp3 *.flac *.m4a);;所有文件 (*.*)"
        )
        if file_path:
            self.workshop_clone_audio.setText(file_path)
            # 自动填入文件名作为音色名称
            if not self.workshop_clone_name.text():
                import os
                name = os.path.splitext(os.path.basename(file_path))[0]
                self.workshop_clone_name.setText(f"克隆_{name[:20]}")

    def _start_segment_analysis(self):
        """开始分析音频片段"""
        audio_path = self.workshop_clone_audio.text().strip()
        subtitle_path = self.workshop_subtitle.text().strip()

        if not audio_path:
            QMessageBox.warning(self, "警告", "请先选择参考音频!")
            return
        if not Path(audio_path).exists():
            QMessageBox.critical(self, "错误", f"参考音频不存在:\n{audio_path}")
            return

        self.workshop_analyze_btn.setEnabled(False)
        self.workshop_analyze_btn.setText("分析中...")
        self.workshop_analyze_progress.setVisible(True)
        self.workshop_analyze_progress.setValue(0)
        self.segment_result_group.setVisible(False)
        self.workshop_clone_btn.setEnabled(False)

        self.log(f"[音色工坊] 开始分析音频片段: {Path(audio_path).name}")

        from src.gui_workers import SegmentAnalysisWorker
        self.segment_analysis_worker = SegmentAnalysisWorker(
            audio_path=audio_path,
            subtitle_path=subtitle_path if subtitle_path else None,
            audio_language=self.workshop_asr_lang.currentData() or "ja",
            separate_vocals=True,
        )
        self.segment_analysis_worker.progress.connect(self._on_segment_analysis_progress)
        self.segment_analysis_worker.finished.connect(self._on_segment_analysis_finished)
        self.segment_analysis_worker.start()

    def _on_segment_analysis_progress(self, msg: str, percent: int):
        """片段分析进度回调"""
        self.workshop_analyze_progress.setValue(percent)
        self.log(f"[音色工坊] {msg}")

    def _on_segment_analysis_finished(self, success: bool, message: str, result: dict):
        """片段分析完成回调"""
        self.workshop_analyze_btn.setEnabled(True)
        self.workshop_analyze_btn.setText("重新分析")
        self.workshop_analyze_progress.setVisible(False)

        if not success:
            self.log(f"[音色工坊] 分析失败: {message}")
            QMessageBox.critical(self, "分析失败", message)
            return

        # 保存分析结果
        self._analysis_result = result
        self._segment_table_data = [dict(s) for s in result["segments"]]  # 深拷贝

        # 更新信息标签
        mode_label = "字幕匹配" if result["mode"] == "matched" else "ASR 识别"
        self.segment_info_label.setText(
            f"模式: {mode_label} | "
            f"原始片段: {result['total_raw']} | "
            f"有效: {result['valid_count']} | "
            f"推荐: {len(result['recommended_indices'])} | "
            f"音频时长: {result['audio_info']['original_duration']:.1f}s"
        )

        # 填充表格
        self._populate_segment_table(result["segments"], result["recommended_indices"])

        # 显示片段组
        self.segment_result_group.setVisible(True)
        self.workshop_clone_btn.setEnabled(True)

        self.log(f"[音色工坊] {message}")

        # 警告提示
        for w in result.get("warnings", []):
            self.log(f"[音色工坊] 警告: {w}")

    def _populate_segment_table(self, segments: list, recommended_indices: list):
        """填充片段表格"""
        self._updating_table = True
        self.segment_table.setRowCount(len(segments))

        for i, seg in enumerate(segments):
            duration = seg.get("duration", 0)
            score = seg.get("quality_score", 0)
            label = seg.get("quality_label", "")
            text = seg.get("text", "")
            rms = seg.get("rms", 0)

            # 列0: 选择复选框
            check_item = QTableWidgetItem()
            check_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            check_item.setCheckState(Qt.CheckState.Checked if i in recommended_indices else Qt.CheckState.Unchecked)
            self.segment_table.setItem(i, 0, check_item)

            # 列1: 序号
            idx_item = QTableWidgetItem(f"#{i + 1}")
            idx_item.setFlags(idx_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            idx_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.segment_table.setItem(i, 1, idx_item)

            # 列2: 时长
            dur_item = QTableWidgetItem(f"{duration:.1f}s")
            dur_item.setFlags(dur_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            dur_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.segment_table.setItem(i, 2, dur_item)

            # 列3: 音质评分（带颜色）
            qual_item = QTableWidgetItem(f"{score} {label}")
            qual_item.setFlags(qual_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            qual_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if score >= 90:
                qual_item.setBackground(QColor(200, 255, 200))  # 浅绿
            elif score >= 75:
                qual_item.setBackground(QColor(200, 230, 255))  # 浅蓝
            elif score >= 60:
                qual_item.setBackground(QColor(255, 255, 200))  # 浅黄
            else:
                qual_item.setBackground(QColor(255, 210, 210))  # 浅红
            self.segment_table.setItem(i, 3, qual_item)

            # 列4: 参考文本（可编辑）
            text_item = QTableWidgetItem(text)
            text_item.setToolTip(f"RMS: {rms:.4f} | 双击可编辑")
            self.segment_table.setItem(i, 4, text_item)

        self._updating_table = False
        self._update_ref_text_preview()

    def _on_segment_table_changed(self, item):
        """表格内容变化时更新预览"""
        if self._updating_table:
            return

        row = item.row()
        col = item.column()

        # 更新数据
        if row < len(self._segment_table_data):
            if col == 0:
                # 复选框变化
                pass
            elif col == 4:
                # 文本编辑
                self._segment_table_data[row]["text"] = item.text()

        self._update_ref_text_preview()

    def _update_ref_text_preview(self):
        """更新 ref_text 合成预览"""
        if not hasattr(self, '_segment_table_data'):
            return

        selected_texts = []
        for i in range(self.segment_table.rowCount()):
            if i >= len(self._segment_table_data):
                break
            check_item = self.segment_table.item(i, 0)
            if check_item and check_item.checkState() == Qt.CheckState.Checked:
                text_item = self.segment_table.item(i, 4)
                if text_item:
                    text = text_item.text().strip()
                    if text:
                        selected_texts.append(text)

        selected_count = sum(
            1 for i in range(self.segment_table.rowCount())
            if self.segment_table.item(i, 0)
            and self.segment_table.item(i, 0).checkState() == Qt.CheckState.Checked
        )
        total_duration = sum(
            self._segment_table_data[i].get("duration", 0)
            for i in range(min(selected_count, len(self._segment_table_data)))
            if self.segment_table.item(i, 0)
            and self.segment_table.item(i, 0).checkState() == Qt.CheckState.Checked
        ) if hasattr(self, '_segment_table_data') else 0

        # 计算选中片段的真实总时长
        real_total = 0.0
        for i in range(self.segment_table.rowCount()):
            if i < len(self._segment_table_data):
                check_item = self.segment_table.item(i, 0)
                if check_item and check_item.checkState() == Qt.CheckState.Checked:
                    real_total += self._segment_table_data[i].get("duration", 0)

        preview_text = " ".join(selected_texts) if selected_texts else "(未选择任何片段)"
        self.segment_ref_text_preview.setPlainText(preview_text)

    def _get_selected_segments(self) -> list:
        """获取用户选中的片段列表"""
        if not hasattr(self, '_segment_table_data'):
            return []

        selected = []
        for i in range(self.segment_table.rowCount()):
            if i >= len(self._segment_table_data):
                break
            check_item = self.segment_table.item(i, 0)
            if check_item and check_item.checkState() == Qt.CheckState.Checked:
                seg = dict(self._segment_table_data[i])
                # 更新表格中编辑过的文本
                text_item = self.segment_table.item(i, 4)
                if text_item:
                    seg["text"] = text_item.text().strip()
                selected.append(seg)
        return selected

    def _select_recommended_segments(self):
        """选择推荐的片段"""
        if not hasattr(self, '_analysis_result'):
            return

        self._updating_table = True
        recommended = self._analysis_result.get("recommended_indices", [])
        for i in range(self.segment_table.rowCount()):
            item = self.segment_table.item(i, 0)
            if item:
                item.setCheckState(Qt.CheckState.Checked if i in recommended else Qt.CheckState.Unchecked)
        self._updating_table = False
        self._update_ref_text_preview()
        self.log(f"[音色工坊] 已选择 {len(recommended)} 个推荐片段")

    def _clear_segment_selection(self):
        """清除所有选择"""
        self._updating_table = True
        for i in range(self.segment_table.rowCount()):
            item = self.segment_table.item(i, 0)
            if item:
                item.setCheckState(Qt.CheckState.Unchecked)
        self._updating_table = False
        self._update_ref_text_preview()

    def _play_selected_segments(self):
        """播放选中片段的合成音频"""
        selected = self._get_selected_segments()
        if not selected:
            QMessageBox.warning(self, "警告", "请先选择要播放的片段!")
            return

        self.log(f"[音色工坊] 拼合 {len(selected)} 个片段用于预览...")

        try:
            from src.core.tts.audio_preprocessor import AudioPreprocessor
            import tempfile

            preprocessor = AudioPreprocessor()
            result = preprocessor.build_from_segments(selected)
            self.log(f"[音色工坊] 预览音频: {result.total_duration:.1f}s")

            # 使用嵌入式播放器播放音频
            self.audio_player.load_and_play(result.ref_audio_path)

        except Exception as e:
            self.log(f"[音色工坊] 播放失败: {e}")
            QMessageBox.critical(self, "错误", f"播放失败: {e}")

    def _browse_workshop_subtitle(self):
        """浏览音色工坊的字幕文件"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择字幕文件",
            "",
            "字幕文件 (*.vtt *.srt *.lrc);;所有文件 (*.*)"
        )
        if file_path:
            self.workshop_subtitle.setText(file_path)

    def _start_voice_clone(self):
        """开始音色克隆（支持预选片段模式）"""
        audio_path = self.workshop_clone_audio.text().strip()
        name = self.workshop_clone_name.text().strip()

        if not audio_path:
            QMessageBox.warning(self, "警告", "请选择参考音频!")
            return
        if not name:
            QMessageBox.warning(self, "警告", "请输入音色名称!")
            return
        if not Path(audio_path).exists():
            QMessageBox.critical(self, "错误", f"参考音频不存在:\n{audio_path}")
            return

        # 检查是否有分析结果（预选模式）
        pre_selected_segments = None
        manual_ref_text = None

        if hasattr(self, '_analysis_result') and self._analysis_result:
            pre_selected_segments = self._get_selected_segments()
            if not pre_selected_segments:
                QMessageBox.warning(self, "警告", "请至少选择一个音频片段!")
                return

            # 检查是否启用手动覆盖 ref_text
            if self.manual_ref_text_group.isChecked():
                manual_ref_text = self.workshop_manual_ref_text.toPlainText().strip()
                if manual_ref_text:
                    self.log(f"[音色工坊] 使用手动覆盖的 ref_text ({len(manual_ref_text)} 字符)")
        else:
            # 未分析模式：使用旧的直接克隆流程
            subtitle_path = self.workshop_subtitle.text().strip()
            if self.manual_ref_text_group.isChecked():
                manual_ref_text = self.workshop_manual_ref_text.toPlainText().strip()

        # 禁用按钮
        self.workshop_clone_btn.setEnabled(False)
        self.workshop_clone_btn.setText("克隆中...")
        self.workshop_clone_progress.setVisible(True)
        self.workshop_clone_progress.setValue(0)

        self.log(f"[音色工坊] 开始克隆音色: {name}")
        if pre_selected_segments:
            self.log(f"[音色工坊] 预选模式: {len(pre_selected_segments)} 个片段")

        from src.gui_workers import VoiceCloneWorker

        # 根据是否有预选片段选择不同的参数
        if pre_selected_segments:
            # 预选模式：跳过分析和分离（已在分析步骤完成）
            self.clone_worker = VoiceCloneWorker(
                name=name,
                audio_path=audio_path,
                separate_vocals=False,  # 分析时已分离
                use_progress_wrapper=True,
                pre_selected_segments=pre_selected_segments,
                manual_ref_text=manual_ref_text,
                audio_language=self.workshop_asr_lang.currentData() or "ja",
            )
        else:
            # 传统模式
            subtitle_path = self.workshop_subtitle.text().strip()
            self.clone_worker = VoiceCloneWorker(
                name=name,
                audio_path=audio_path,
                subtitle_path=subtitle_path if subtitle_path else None,
                audio_language=self.workshop_asr_lang.currentData() or "ja",
                separate_vocals=True,
                use_progress_wrapper=True,
                manual_ref_text=manual_ref_text,
            )

        self.clone_worker.progress.connect(self._on_clone_progress)
        self.clone_worker.finished.connect(self._on_clone_finished)
        self.clone_worker.start()

    def _on_clone_progress(self, msg: str, percent: int):
        """音色克隆进度回调"""
        self.workshop_clone_progress.setValue(percent)
        self.log(f"[音色工坊] {msg}")

    def _on_clone_finished(self, success: bool, message: str, profile_id: str):
        """音色克隆完成回调"""
        # 恢复按钮
        self.workshop_clone_btn.setEnabled(True)
        self.workshop_clone_btn.setText("克隆音色")
        self.workshop_clone_progress.setVisible(False)

        if success:
            self.log(f"[音色工坊] {message}")
            QMessageBox.information(self, "成功", message)
            # 清空输入
            self.workshop_clone_audio.clear()
            self.workshop_clone_name.clear()
            # 刷新音色列表
            self._refresh_my_voices()
        else:
            self.log(f"[音色工坊] 失败: {message}")
            QMessageBox.critical(self, "错误", message)

    def _refresh_my_voices(self):
        """刷新我的音色列表"""
        from src.core.tts.voice_profile import get_voice_manager

        self.workshop_voice_list.clear()
        manager = get_voice_manager()

        # 显示自定义音色 (B 系列)
        for profile in manager.get_customs():
            self.workshop_voice_list.addItem(
                f"{profile.name} (自定义, {profile.id})"
            )

        # 显示克隆音色 (C 系列)
        for profile in manager.get_clones():
            self.workshop_voice_list.addItem(
                f"{profile.name} (克隆, {profile.id})"
            )

        if self.workshop_voice_list.count() == 0:
            self.workshop_voice_list.addItem("(暂无自定义音色)")

        # 同时刷新单文件和批量处理的下拉框
        self._refresh_custom_voice_combos()

    def _refresh_custom_voice_combos(self):
        """刷新单文件和批量处理中的自定义音色下拉框"""
        from src.core.tts.voice_profile import get_voice_manager
        manager = get_voice_manager()

        # 保存当前选中项
        current_single = self.single_custom_voice.currentText() if self.single_custom_voice.count() > 0 else ""
        current_batch = self.batch_custom_voice.currentText() if self.batch_custom_voice.count() > 0 else ""

        def populate_combo(combo: QComboBox):
            combo.clear()
            # 自定义音色 (B 系列)
            customs = list(manager.get_customs())
            if customs:
                combo.addItem("--- 自定义音色 ---")
                combo.model().item(combo.count() - 1).setEnabled(False)
                for profile in customs:
                    combo.addItem(f"{profile.name} ({profile.id})")
            # 克隆音色 (C 系列)
            clones = list(manager.get_clones())
            if clones:
                combo.addItem("--- 克隆音色 ---")
                combo.model().item(combo.count() - 1).setEnabled(False)
                for profile in clones:
                    combo.addItem(f"{profile.name} ({profile.id})")
            # 如果没有音色，添加提示
            if not customs and not clones:
                combo.addItem("(暂无自定义音色)")

        # 刷新单文件和批量处理
        populate_combo(self.single_custom_voice)
        populate_combo(self.batch_custom_voice)

        # 恢复选中项（如果存在）
        if current_single and self.single_custom_voice.findText(current_single) >= 0:
            self.single_custom_voice.setCurrentText(current_single)
        if current_batch and self.batch_custom_voice.findText(current_batch) >= 0:
            self.batch_custom_voice.setCurrentText(current_batch)

    def _preview_workshop_voice(self):
        """试音我的音色"""
        current_item = self.workshop_voice_list.currentItem()
        if not current_item:
            QMessageBox.warning(self, "警告", "请先选择一个音色!")
            return

        text = current_item.text()
        # 格式: "名称 (类型, ID)" → 直接提取最后的 ID
        import re
        match = re.search(r'\(([^)]+)\)$', text)
        if not match:
            QMessageBox.warning(self, "警告", "无法解析音色 ID!")
            return

        profile_id = match.group(1).split(", ")[-1]  # 取最后一个元素即 ID

        test_text = self.workshop_preview_text.text().strip()
        if not test_text:
            test_text = "你好，这是一段测试语音。"

        self.log(f"[音色工坊] 试音: {profile_id}")
        self.workshop_preview_btn.setEnabled(False)

        from src.gui_workers import VoicePreviewWorker

        self.preview_worker = VoicePreviewWorker(
            profile_id=profile_id,
            test_text=test_text,
        )
        self.preview_worker.finished.connect(self._on_workshop_preview_finished)
        self.preview_worker.start()

    def _on_workshop_preview_finished(self, success: bool, message: str, audio_path: str):
        """试音完成回调"""
        self.workshop_preview_btn.setEnabled(True)

        if success:
            self.log(f"[音色工坊] {message}")
            # 使用嵌入式播放器播放音频
            self.audio_player.load_and_play(audio_path)
        else:
            self.log(f"[音色工坊] 试音失败: {message}")
            QMessageBox.critical(self, "错误", message)

    def _delete_workshop_voice(self):
        """删除音色"""
        current_item = self.workshop_voice_list.currentItem()
        if not current_item:
            QMessageBox.warning(self, "警告", "请先选择一个音色!")
            return

        text = current_item.text()

        # 解析 profile_id
        import re
        match = re.search(r'\(([^)]+)\)$', text)
        if not match:
            QMessageBox.warning(self, "警告", "无法解析音色!")
            return

        # 确认删除
        reply = QMessageBox.question(
            self,
            "确认删除",
            f"确定要删除音色 \"{text}\" 吗？\n\n注意：预设音色不可删除。",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        # 解析并删除 - 直接取最后一个元素即为 profile_id
        profile_id = match.group(1).split(", ")[-1].strip()

        from src.core.tts.voice_profile import get_voice_manager
        manager = get_voice_manager()

        if manager.delete_profile(profile_id):
            self.log(f"[音色工坊] 已删除: {text}")
            self._refresh_my_voices()
            QMessageBox.information(self, "成功", "音色已删除!")
        else:
            QMessageBox.critical(self, "错误", "删除失败或该音色不可删除!")

    def _get_gpu_info(self) -> str:
        """获取 GPU 信息"""
        try:
            import torch
            if torch.cuda.is_available():
                props = torch.cuda.get_device_properties(0)
                mem_total = props.total_memory / 1024**3
                return f"{props.name} ({mem_total:.1f}GB)"
            return "无 GPU (CPU 模式)"
        except Exception:
            return "未知"


def main():
    """入口函数"""
    app = QApplication(sys.argv)
    app.setStyle(QStyleFactory.create("Fusion"))

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
