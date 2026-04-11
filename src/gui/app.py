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

    

        def _apply_modern_light_theme(self):
            """应用统一浅色主题，提升可读性与层次。"""
            self.setStyleSheet("""
                QMainWindow, QWidget {
                    background: #f5f7fb;
                    color: #1f2937;
                    font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
                    font-size: 12px;
                }
                QGroupBox {
                    background: #ffffff;
                    border: 1px solid #dbe3f1;
                    border-radius: 10px;
                    margin-top: 10px;
                    padding: 12px 10px 10px 10px;
                    font-weight: 600;
                }
                QGroupBox::title {
                    subcontrol-origin: margin;
                    left: 10px;
                    padding: 0 6px;
                    color: #334155;
                }
                QTabWidget::pane {
                    border: 1px solid #dbe3f1;
                    border-radius: 10px;
                    background: #ffffff;
                    top: -1px;
                }
                QTabBar::tab {
                    background: #e8edf8;
                    color: #334155;
                    border: 1px solid #d3dced;
                    border-bottom: none;
                    border-top-left-radius: 8px;
                    border-top-right-radius: 8px;
                    padding: 8px 14px;
                    margin-right: 4px;
                    font-weight: 600;
                }
                QTabBar::tab:selected {
                    background: #ffffff;
                    color: #0f172a;
                }
                QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTextEdit, QListWidget {
                    background: #ffffff;
                    border: 1px solid #cfd8ea;
                    border-radius: 8px;
                    padding: 5px 8px;
                }
                QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QTextEdit:focus, QListWidget:focus {
                    border: 1px solid #3b82f6;
                }
                QPushButton {
                    background: #e5edff;
                    color: #1e3a8a;
                    border: 1px solid #c5d5ff;
                    border-radius: 8px;
                    padding: 6px 12px;
                    font-weight: 600;
                }
                QPushButton:hover {
                    background: #d6e4ff;
                }
                QPushButton:pressed {
                    background: #c6d9ff;
                }
                QPushButton:disabled {
                    background: #eef2f7;
                    color: #94a3b8;
                    border-color: #e2e8f0;
                }
                QProgressBar {
                    background: #e9eef8;
                    border: 1px solid #d0daec;
                    border-radius: 8px;
                    text-align: center;
                    color: #0f172a;
                    font-weight: 700;
                }
                QProgressBar::chunk {
                    background: #3b82f6;
                    border-radius: 7px;
                }
                QCheckBox {
                    spacing: 6px;
                }
            """)

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
