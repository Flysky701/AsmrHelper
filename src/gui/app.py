"""
ASMR Helper GUI - PySide6 主界面 (支持单文件和批量处理)

模块化结构：
- gui_workers.py: Worker 线程
- gui_services.py: 业务逻辑
"""

import sys
import os
import re
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
from src.gui.workers.pipeline_worker import SingleWorkerThread, PreviewWorkerThread, BatchWorkerThread
from src.gui.services.voice_service import scan_audio_files
from src.gui.utils.validators import validate_batch_params, validate_single_params
from src.utils.constants import AUDIO_EXTENSIONS

class MainWindow(QMainWindow):
    """主窗口"""

    def __init__(self):
        super().__init__()
        self.worker = None
        self.batch_worker = None
        self.setup_ui()

    @property
    def single_custom_voice(self):
        return self.single_tab.single_custom_voice
    
    @property
    def single_edge_voice(self):
        return self.single_tab.single_edge_voice
        
    @property
    def single_preset_voice(self):
        return self.single_tab.single_preset_voice

    @property
    def single_voice_type(self):
        return self.single_tab.single_voice_type
        
    @property
    def single_voice_container(self):
        return self.single_tab.single_voice_container

    @property
    def batch_custom_voice(self):
        return self.batch_tab.batch_custom_voice

    @property
    def batch_edge_voice(self):
        return self.batch_tab.batch_edge_voice
        
    @property
    def batch_preset_voice(self):
        return self.batch_tab.batch_preset_voice

    @property
    def batch_voice_type(self):
        return self.batch_tab.batch_voice_type
        
    @property
    def batch_voice_container(self):
        return self.batch_tab.batch_voice_container

    def _apply_modern_light_theme(self):
        """应用统一浅色主题，提升可读性与视觉层级。"""
        self.setStyleSheet("""
            /* ===== 全局基础 ===== */
            QMainWindow, QWidget {
                background: #f0f2f5;
                color: #303133;
                font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
                font-size: 12px;
            }

            /* ===== 标签文字层级 ===== */
            QLabel {
                color: #303133;
                background: transparent;
            }

            /* ===== 卡片化分组框（带阴影） ===== */
            QGroupBox {
                background: #ffffff;
                border: 1px solid #dcdfe6;
                border-radius: 12px;
                margin-top: 20px;
                padding: 24px 16px 16px 16px;
                font-weight: 600;
                font-size: 13px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 16px;
                margin-left: 8px;
                padding: 0 12px;
                color: #303133;
            }
            QGroupBox:flat {
                border: none;
                border-radius: 12px;
            }

            /* ===== 标签页 ===== */
            QTabWidget::pane {
                border: 1px solid #dcdfe6;
                border-radius: 12px;
                background: #ffffff;
                top: -1px;
            }
            QTabBar::tab {
                background: #e8ecf1;
                color: #606266;
                border: 1px solid #d8dde4;
                border-bottom: none;
                border-top-left-radius: 10px;
                border-top-right-radius: 10px;
                padding: 10px 18px;
                margin-right: 4px;
                font-weight: 600;
                font-size: 13px;
            }
            QTabBar::tab:selected {
                background: #ffffff;
                color: #1e40af;
                border-bottom: 2px solid #3b82f6;
            }
            QTabBar::tab:hover:!selected {
                background: #dde3ea;
                color: #303133;
            }

            /* ===== 按钮层级 ===== */
            /* 主要按钮 - 实心填充蓝色 */
            QPushButton[primary="true"], QPushButton[class="primary"] {
                background: #3b82f6;
                color: #ffffff;
                border: none;
                border-radius: 8px;
                padding: 8px 20px;
                font-weight: 700;
                font-size: 13px;
            }
            QPushButton[primary="true"]:hover, QPushButton[class="primary"]:hover {
                background: #2563eb;
            }
            QPushButton[primary="true"]:pressed, QPushButton[class="primary"]:pressed {
                background: #1d4ed8;
            }
            /* 默认/次要按钮 - 描边样式 */
            QPushButton {
                background: #ffffff;
                color: #303133;
                border: 1.5px solid #dcdfe6;
                border-radius: 8px;
                padding: 7px 16px;
                font-weight: 600;
            }
            QPushButton:hover {
                border-color: #3b82f6;
                color: #3b82f6;
                background: #eff6ff;
            }
            QPushButton:pressed {
                background: #dbeafe;
                border-color: #3b82f6;
                color: #1e40af;
            }
            QPushButton:disabled {
                background: #f5f7fa;
                color: #c0c4cc;
                border-color: #e4e7ed;
            }
            /* 危险/警告按钮 */
            QPushButton[class="danger"] {
                background: #ef4444;
                color: #ffffff;
                border: none;
            }
            QPushButton[class="danger"]:hover {
                background: #dc2626;
            }

            /* ===== 进度条 ===== */
            QProgressBar {
                background: #e4e7ed;
                border: none;
                border-radius: 8px;
                text-align: center;
                color: #303133;
                font-weight: 700;
                min-height: 22px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #3b82f6, stop:1 #60a5fa);
                border-radius: 8px;
            }

            /* ===== 复选框 ===== */
            QCheckBox {
                spacing: 8px;
                color: #606266;
                font-weight: 500;
                outline: none;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border-radius: 4px;
                border: 2px solid #dcdfe6;
                background-color: #ffffff;
            }
            QCheckBox::indicator:checked {
                background-color: #3b82f6;
                border: 2px solid #3b82f6;
                image: url(data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIxMiIgaGVpZ2h0PSIxMiI+PHBhdGggZD0iTTEwLjYzIDMuNDRMNC45NyA5LjAyTDIuMzcgNi40NiIgc3Ryb2tlPSJ3aGl0ZSIgc3Ryb2tlLXdpZHRoPSIyIiBmaWxsPSJub25lIiBzdHJva2UtbGluZWNhcD0icm91bmQiIHN0cm9rZS1saW5lam9pbj0icm91bmQiLz48L3N2Zz4=);
            }
            QCheckBox::indicator:unchecked {
                border: 2px solid #dcdfe6;
                background-color: #ffffff;
            }
            QCheckBox::indicator:hover {
                border-color: #3b82f6;
            }
            QCheckBox:checked {
                color: #1e40af;
                font-weight: 700;
            }

            /* ===== SpinBox 数值调整框 ===== */
            QSpinBox, QDoubleSpinBox {
                padding-right: 20px;
            }
            QSpinBox::up-button, QDoubleSpinBox::up-button {
                border: none;
                width: 16px;
                subcontrol-origin: padding;
                subcontrol-position: right center;
            }
            QSpinBox::down-button, QDoubleSpinBox::down-button {
                border: none;
                width: 16px;
                subcontrol-origin: padding;
                subcontrol-position: right bottom;
            }
            QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {
                image: url(data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIxMiIgaGVpZ2h0PSIxMiIgdmlld0JveD0iMCAwIDEyIDEyIj48cGF0aCBkPSJNNiA0bDMgMyAtMyAzIiBzdHJva2U9IiM2NDM2NDYiIHN0cm9rZS13aWR0aD0iMS41IiBmaWxsPSJub25lIiBzdHJva2UtbGluZWNhcD0icm91bmQiLz48L3N2Zz4=);
                width: 10px;
                height: 10px;
            }
            QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {
                image: url(data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIxMiIgaGVpZ2h0PSIxMiIgdmlld0JveD0iMCAwIDEyIDEyIj48cGF0aCBkPSJNMSA4bDUtNiA1IDYiIHN0cm9rZT0iIzY0MzY0NiIgc3Ryb2tlLXdpZHRoPSIxLjUiIGZpbGw9Im5vbmUiIHN0cm9rZS1saW5lY2FwPSJyb3VuZCIvPjwvc3ZnPg==);
                width: 10px;
                height: 10px;
            }

            /* ===== 滑块 ===== */
            QSlider {
                padding: 8px 0;
            }
            QSlider::groove:horizontal {
                height: 6px;
                background: #e4e7ed;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                width: 18px;
                height: 18px;
                background: #3b82f6;
                border-radius: 9px;
                border: 2px solid #ffffff;
                margin: -6px 0;
            }
            QSlider::handle:horizontal:hover {
                background: #2563eb;
            }
            QSlider::sub-page:horizontal {
                background: #3b82f6;
                border-radius: 3px;
            }

            /* ===== 滚动条 ===== */
            QScrollBar:vertical {
                background: transparent;
                width: 8px;
                margin: 0;
            }
            QScrollBar::handle:vertical {
                background: #c0c4cc;
                border-radius: 4px;
                min-height: 30px;
            }
            QScrollBar::handle:vertical:hover {
                background: #909399;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0;
            }
            QScrollBar:horizontal {
                background: transparent;
                height: 8px;
                margin: 0;
            }
            QScrollBar::handle:horizontal {
                background: #c0c4cc;
                border-radius: 4px;
                min-width: 30px;
            }
            QScrollBar::handle:horizontal:hover {
                background: #909399;
            }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                width: 0;
            }

            /* ===== 菜单栏 ===== */
            QMenuBar {
                background: #ffffff;
                border-bottom: 1px solid #e4e7ed;
                padding: 4px;
            }
            QMenuBar::item {
                background: transparent;
                padding: 6px 12px;
                border-radius: 4px;
            }
            QMenuBar::item:selected {
                background: #e6f0ff;
                color: #1e40af;
            }
            QMenu {
                background: #ffffff;
                border: 1px solid #e4e7ed;
                border-radius: 8px;
                padding: 4px;
            }
            QMenu::item {
                padding: 8px 16px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background: #e6f0ff;
                color: #1e40af;
            }
        """)

    
    def setup_ui(self):
        """设置UI"""
        self.setWindowTitle("ASMR Helper - 双语双轨处理工具")
        self.setMinimumSize(980, 700)
        self._apply_modern_light_theme()

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
        title_font = QFont("Microsoft YaHei UI")
        title_font.setPointSize(16)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(title_label)

        # ===== 标签页 =====
        self.tabs = QTabWidget()
        from src.gui.views.single_tab import SingleTab
        self.single_tab = SingleTab(self)
        self.tabs.addTab(self._wrap_scroll(self.single_tab), "单文件处理")
        from src.gui.views.batch_tab import BatchTab
        self.batch_tab = BatchTab(self)
        self.tabs.addTab(self._wrap_scroll(self.batch_tab), "批量处理")
        from src.gui.views.workshop_tab import VoiceWorkshopTab
        self.workshop_tab = VoiceWorkshopTab(self)
        self.tabs.addTab(self._wrap_scroll(self.workshop_tab), "音色工坊")
        
        from src.gui.views.tools_tab import ToolsTab
        self.tools_tab = ToolsTab(self)
        self.tabs.addTab(self._wrap_scroll(self.tools_tab), "工具箱")
        
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
                background-color: #f7fafc;
                color: #1f2937;
                font-family: Cascadia Mono, Consolas, monospace;
                font-size: 11px;
                border: 1px solid #d1d5db;
                border-radius: 8px;
            }
        """)
        main_layout.addWidget(self.progress_text)

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
        def _parse_voice_text(voice_text: str) -> tuple:
            """从展示文本中提取 voice 与 profile_id（容错不同格式）。"""
            voice_text = (voice_text or "").strip()
            if not voice_text:
                return "", None

            match = re.search(r"\(([^()]+)\)\s*$", voice_text)
            profile_id = match.group(1).strip() if match else None
            voice_name = voice_text.split(" (", 1)[0].strip()
            return voice_name, profile_id

        if engine == "edge":
            # Edge-TTS: 直接返回选中的音色
            if edge_combo is not None:
                voice_text = edge_combo.currentText()
                voice_name, _ = _parse_voice_text(voice_text)
                return voice_name, None
            return "zh-CN-XiaoxiaoNeural", None

        # Qwen3-TTS: 从 voice_type 下拉框获取音色
        # voice_tabs 参数现在代表 voice_type QComboBox
        if voice_tabs is None:
            return "Vivian", "A1"

        tab_index = voice_tabs.currentIndex()
        if tab_index == 0:
            # 预设音色
            voice_text = preset_combo.currentText()
            return _parse_voice_text(voice_text)
        else:
            # 自定义音色 (包含 B/C 系列)
            voice_text = custom_combo.currentText()
            return _parse_voice_text(voice_text)


    def log(self, msg: str, color: Optional[str] = None):
        """添加日志"""
        if color:
            msg = f"<span style=\"color:{color}\">{msg}</span>"
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


    # ==================== 工具 UI 构建器 ====================

    @staticmethod
    
    # ==================== 工具文件浏览槽函数 ====================

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
