"""
ASMR Helper GUI - PySide6 主界面 (支持单文件和批量处理)

模块化结构：
- gui_workers.py: Worker 线程
- gui_services.py: 业务逻辑
"""

import sys
import os
from pathlib import Path
from typing import Optional, List

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit, QFileDialog, QProgressBar,
    QTextEdit, QSlider, QGroupBox, QComboBox, QSpinBox, QDoubleSpinBox,
    QMessageBox, QStyleFactory, QTabWidget, QCheckBox, QListWidget,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QStackedWidget,
    QScrollArea
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QFont, QAction

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
        main_layout.addWidget(self.tabs)

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

        # ===== 音色克隆设置 (report_17) =====
        clone_group = QGroupBox("音色克隆 (人声分离后自动克隆)")
        clone_layout = QHBoxLayout()
        self.single_clone_voice_check = QCheckBox("分离后人声用于音色克隆")
        self.single_clone_voice_check.setToolTip(
            "勾选后，在人声分离完成后自动用人声作为参考音频克隆音色\n"
            "克隆的音色可在「音色工坊」中查看和管理"
        )
        clone_layout.addWidget(self.single_clone_voice_check)
        clone_layout.addWidget(QLabel("音色名称:"))
        self.single_clone_voice_name = QLineEdit()
        self.single_clone_voice_name.setPlaceholderText("留空自动生成")
        self.single_clone_voice_name.setMaximumWidth(150)
        clone_layout.addWidget(self.single_clone_voice_name)
        clone_layout.addStretch()
        clone_group.setLayout(clone_layout)
        layout.addWidget(clone_group)

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

        # 自动分离人声选项
        self.single_clone_separate_check = QCheckBox("自动分离人声后克隆")
        self.single_clone_separate_check.setChecked(True)  # 默认勾选
        self.single_clone_separate_check.setToolTip(
            "勾选后，将自动分离人声并使用纯净人声进行音色克隆"
        )
        clone_layout.addWidget(self.single_clone_separate_check)

        # 克隆按钮
        self.single_clone_btn = QPushButton("开始克隆音色")
        self.single_clone_btn.clicked.connect(self._clone_voice_only)
        clone_layout.addWidget(self.single_clone_btn)

        clone_layout.addWidget(QLabel("提示: 推荐使用纯净人声音频进行克隆，效果更佳"))
        clone_layout.addStretch()
        clone_widget = QWidget()
        clone_widget.setLayout(clone_layout)
        self.single_qwen3_voice_stack.addWidget(clone_widget)

        # 音色类型选择器 + QStackedWidget（移除克隆音色Tab，C系列已合并到自定义音色下拉框）
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
        self.single_delay.setToolTip("TTS 相对于原音的时间偏移\n正数：TTS 稍慢（晚播放）\n负数：TTS 稍快（早播放）")
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

        # 音色类型选择器 + QStackedWidget（移除克隆音色Tab，C系列已合并到自定义音色下拉框）
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
            # 音色克隆 (report_17)
            "clone_voice_after_separation": self.single_clone_voice_check.isChecked(),
            "clone_voice_name": self.single_clone_voice_name.text().strip() or "",
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
            import platform
            if platform.system() == "Windows":
                os.startfile(output_path)
            elif platform.system() == "Darwin":
                import subprocess
                subprocess.Popen(["open", output_path])
            else:
                import subprocess
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

        # 克隆音色名称
        clone_name_layout = QHBoxLayout()
        clone_name_layout.addWidget(QLabel("音色名称:"))
        self.workshop_clone_name = QLineEdit()
        self.workshop_clone_name.setPlaceholderText("给克隆音色起个名字...")
        clone_name_layout.addWidget(self.workshop_clone_name)
        clone_layout.addLayout(clone_name_layout)

        # 克隆按钮和进度
        clone_btn_layout = QHBoxLayout()
        self.workshop_clone_btn = QPushButton("克隆音色")
        self.workshop_clone_btn.setStyleSheet(
            "QPushButton{background-color:#107c10;color:white;font-weight:bold;border:none;border-radius:5px;padding:8px;}"
        )
        self.workshop_clone_btn.clicked.connect(self._start_voice_clone)
        clone_btn_layout.addWidget(self.workshop_clone_btn)

        self.workshop_clone_progress = QProgressBar()
        self.workshop_clone_progress.setMinimumHeight(20)
        self.workshop_clone_progress.setVisible(False)
        clone_btn_layout.addWidget(self.workshop_clone_progress, stretch=1)
        self.workshop_clone_progress.setFormat("%p%")  # 在addWidget之后
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

    def _open_voice_guide(self):
        """打开音色描述词指南文档"""
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
        """开始音色克隆（支持字幕切分批量克隆）"""
        audio_path = self.workshop_clone_audio.text().strip()
        subtitle_path = self.workshop_subtitle.text().strip()
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

        # 禁用按钮
        self.workshop_clone_btn.setEnabled(False)
        self.workshop_clone_btn.setText("克隆中...")
        self.workshop_clone_progress.setVisible(True)
        self.workshop_clone_progress.setValue(0)

        self.log(f"[音色工坊] 开始克隆音色: {name}")

        # 使用音色克隆Worker，集成 AudioPreprocessor
        from src.gui_workers import VoiceCloneWorker

        self.clone_worker = VoiceCloneWorker(
            name=name,
            audio_path=audio_path,
            subtitle_path=subtitle_path if subtitle_path else None,
            audio_language="ja",  # 默认日语 ASMR
            separate_vocals=True,
            use_progress_wrapper=True,  # 音色工坊使用进度映射模式
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

    def _clone_voice_only(self):
        """单独克隆音色（不进行后续处理）"""
        audio_path = self.single_clone_audio.text().strip()
        if not audio_path:
            QMessageBox.warning(self, "警告", "请先选择参考音频文件!")
            return

        audio_file = Path(audio_path)
        if not audio_file.exists():
            QMessageBox.warning(self, "警告", f"参考音频不存在:\n{audio_path}")
            return

        # 获取音色名称
        voice_name = self.single_clone_voice_name.text().strip()
        if not voice_name:
            voice_name = f"克隆_{audio_file.stem}"

        # 检查是否需要分离人声
        separate_vocals = self.single_clone_separate_check.isChecked()

        self.log(f"[音色克隆] 开始克隆: {voice_name}")
        self.log(f"[音色克隆] 参考音频: {audio_path}")
        if separate_vocals:
            self.log(f"[音色克隆] 将自动分离人声后克隆")
        self.single_clone_btn.setEnabled(False)
        self.single_clone_btn.setText("克隆中...")

        # 使用 VoiceCloneWorker 在后台线程中执行克隆
        # 注意：单独的克隆功能不传递字幕路径，AudioPreprocessor 会使用基础模式
        self.clone_only_worker = VoiceCloneWorker(
            name=voice_name,
            audio_path=audio_path,
            separate_vocals=separate_vocals,
            subtitle_path=None,  # 单独克隆不传字幕
            audio_language="ja",  # 默认日语
        )
        self.clone_only_worker.progress.connect(self._on_clone_only_progress)
        self.clone_only_worker.finished.connect(self._on_clone_only_finished)
        self.clone_only_worker.start()

    def _on_clone_only_progress(self, msg: str, percent: int):
        """克隆进度回调"""
        self.log(f"[音色克隆] {msg}")

    def _on_clone_only_finished(self, success: bool, message: str, profile_id: str):
        """克隆完成回调"""
        self.single_clone_btn.setEnabled(True)
        self.single_clone_btn.setText("开始克隆音色")

        if success:
            self.log(f"[音色克隆] {message}")
            self._refresh_my_voices()  # 刷新音色列表
            QMessageBox.information(self, "成功", message)
        else:
            self.log(f"[音色克隆] 失败: {message}")
            QMessageBox.critical(self, "克隆失败", f"音色克隆失败:\n{message}")

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
            import platform
            if platform.system() == "Windows":
                os.startfile(audio_path)
            elif platform.system() == "Darwin":
                import subprocess
                subprocess.Popen(["open", audio_path])
            else:
                import subprocess
                subprocess.Popen(["xdg-open", audio_path])
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
