from pathlib import Path
from typing import Optional
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QPushButton, QLabel,
    QLineEdit, QFileDialog, QProgressBar, QTextEdit, QComboBox, QCheckBox,
    QStackedWidget, QGroupBox, QMessageBox, QTableWidget, QTableWidgetItem, QHeaderView
)
from PySide6.QtCore import Qt, QTimer
from src.config import config

from src.gui.workers.pipeline_worker import ToolsWorkerThread

class ToolsTab(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        
        self.worker = None

        self.setup_ui()

    def log(self, message: str, color: str = None):
        self.main_window.log(message, color)

    def save_config(self):
        config.save()

    def _update_stem_button_style(self):
        """更新轨道选择按钮的样式（标签/徽章样式）"""
        unchecked_style = (
            "QPushButton {"
            "   background: #f5f7fa;"
            "   color: #606266;"
            "   border: 1.5px solid #e4e7ed;"
            "   border-radius: 16px;"
            "   padding: 6px 14px;"
            "   font-weight: 500;"
            "   font-size: 12px;"
            "}"
            "QPushButton:hover {"
            "   background: #e6f0ff;"
            "   border-color: #3b82f6;"
            "   color: #3b82f6;"
            "}"
        )
        checked_style = (
            "QPushButton {"
            "   background: #3b82f6;"
            "   color: #ffffff;"
            "   border: 1.5px solid #3b82f6;"
            "   border-radius: 16px;"
            "   padding: 6px 14px;"
            "   font-weight: 700;"
            "   font-size: 12px;"
            "}"
            "QPushButton:hover {"
            "   background: #2563eb;"
            "   border-color: #2563eb;"
            "}"
        )
        for btn in [self.sep_stem_vocals, self.sep_stem_no_vocals,
                    self.sep_stem_drums, self.sep_stem_bass,
                    self.sep_stem_piano, self.sep_stem_other]:
            btn.setStyleSheet(checked_style if btn.isChecked() else unchecked_style)

    def setup_ui(self):
            """创建工具箱标签页 - 提供独立的单步工具功能"""
            layout = QVBoxLayout(self)
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
                "字幕翻译 (翻译字幕文件)",
                "台本转字幕 (LLM 智能对齐)",
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

            # --- Page 5: 字幕翻译 ---
            subtrans_page, self._subtrans_params = self._build_subtitle_translate_ui()
            self.tools_param_stack.addWidget(subtrans_page)  # Index 5

            # --- Page 6: 台本转字幕 (LLM 流水线) ---
            pdfvtt_page, self._pdfvtt_params = self._build_pdf_to_vtt_ui()
            self.tools_param_stack.addWidget(pdfvtt_page)  # Index 6

            self.tools_param_stack.setCurrentIndex(0)
            layout.addWidget(self.tools_param_stack, stretch=1)

            # ===== 运行按钮行 =====
            btn_layout = QHBoxLayout()
            self.tools_run_btn = QPushButton("▶ 运行")
            self.tools_run_btn.setMinimumHeight(36)
            self.tools_run_btn.setMinimumWidth(120)
            self.tools_run_btn.setEnabled(False)
            self.tools_run_btn.setProperty("primary", "true")
            self.tools_run_btn.clicked.connect(self._start_tool_run)
            btn_layout.addWidget(self.tools_run_btn)

            self.tools_stop_btn = QPushButton("停止")
            self.tools_stop_btn.setMinimumHeight(32)
            self.tools_stop_btn.setEnabled(False)
            self.tools_stop_btn.clicked.connect(self._stop_tool_run)
            btn_layout.addWidget(self.tools_stop_btn)

            # 进度条
            self.progress_bar = QProgressBar()
            self.progress_bar.setMaximumWidth(200)
            self.progress_bar.setMinimum(0)
            self.progress_bar.setMaximum(100)
            self.progress_bar.setValue(0)
            btn_layout.addWidget(self.progress_bar)

            btn_layout.addStretch()
            layout.addLayout(btn_layout)

            layout.addStretch()

            

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
            self.main_window._init_vocal_model_combo(self.sep_model)
            form.addWidget(self.sep_model, 2, 1, 1, 2)

            # 分离轨道（多选）- 标签/徽章样式
            form.addWidget(QLabel("提取轨道:"), 3, 0)
            stems_layout = QHBoxLayout()
            stems_layout.setSpacing(8)

            # 创建标签样式的轨道选择按钮
            def make_stem_btn(text, default_checked=True):
                btn = QPushButton(text)
                btn.setCheckable(True)
                btn.setChecked(default_checked)
                btn.setCursor(Qt.PointingHandCursor)
                return btn

            self.sep_stem_vocals = make_stem_btn("🎤 vocals (人声)", True)
            self.sep_stem_no_vocals = make_stem_btn("🎵 no_vocals (伴奏)", False)
            self.sep_stem_drums = make_stem_btn("🥁 drums (鼓声)", False)
            self.sep_stem_bass = make_stem_btn("🎸 bass (贝斯)", False)
            self.sep_stem_piano = make_stem_btn("🎹 piano (钢琴)", False)
            self.sep_stem_other = make_stem_btn("📦 other (其他)", False)

            # 为每个轨道按钮添加样式更新连接
            for btn in [self.sep_stem_vocals, self.sep_stem_no_vocals,
                        self.sep_stem_drums, self.sep_stem_bass,
                        self.sep_stem_piano, self.sep_stem_other]:
                btn.clicked.connect(self._update_stem_button_style)

            # 初始更新样式
            QTimer.singleShot(0, self._update_stem_button_style)

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
            self.main_window._init_asr_model_combo(self.asr_tool_model)
            self.asr_tool_model.setCurrentIndex(3)  # large-v3
            form.addWidget(self.asr_tool_model, 2, 1, 1, 2)

            form.addWidget(QLabel("识别语言:"), 3, 0)
            self.asr_tool_lang = QComboBox()
            self.main_window._init_asr_lang_combo(self.asr_tool_lang)
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
            self.main_window._init_asr_lang_combo(self.subtrans_source_lang)
            self.subtrans_source_lang.setCurrentIndex(0)  # 默认日语
            lang_row.addWidget(self.subtrans_source_lang)

            lang_row.addWidget(QLabel("目标语言:"))
            self.subtrans_target_lang = QComboBox()
            self.main_window._init_asr_lang_combo(self.subtrans_target_lang)
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

    def _build_pdf_to_vtt_ui(self) -> tuple:
        """构建 PDF台本转字幕 (LLM 流水线) 的参数面板"""
        page = QWidget()
        form = QGridLayout(page)
        form.setSpacing(10)

        row = 0

        # ===== 模式选择 =====
        mode_layout = QHBoxLayout()
        mode_layout.addWidget(QLabel("运行模式:"))
        self.pdfvtt_mode = QComboBox()
        self.pdfvtt_mode.addItems([
            "完整流程 (台本 + 音频 → 字幕)",
            "已有 ASR 字幕 (台本 + VTT → 修正字幕)",
            "仅清洗文本 (台本 → 纯台词)",
        ])
        self.pdfvtt_mode.currentIndexChanged.connect(self._on_pdfvtt_mode_changed)
        mode_layout.addWidget(self.pdfvtt_mode, 1)
        form.addLayout(mode_layout, row, 0, 1, 3)
        row += 1

        # ===== 台本文件 =====
        r_pdf, self.pdfvtt_pdf = self._make_file_input_row(
            "台本文件:", "选择台本文件 (PDF/TXT)...",
            self._browse_pdfvtt_pdf, self
        )
        form.addLayout(r_pdf, row, 0, 1, 3)
        row += 1

        # ===== 音频文件（完整模式）=====
        self.pdfvtt_audio_row = QWidget()
        r_audio = QHBoxLayout(self.pdfvtt_audio_row)
        r_audio.setContentsMargins(0, 0, 0, 0)
        r_audio.addWidget(QLabel("音频文件:"))
        self.pdfvtt_audio = QLineEdit()
        self.pdfvtt_audio.setPlaceholderText("选择音频文件 (MP3/WAV)...")
        r_audio.addWidget(self.pdfvtt_audio, 1)
        audio_browse = QPushButton("浏览...")
        audio_browse.setMaximumWidth(70)
        audio_browse.clicked.connect(self._browse_pdfvtt_audio)
        r_audio.addWidget(audio_browse)
        form.addWidget(self.pdfvtt_audio_row, row, 0, 1, 3)
        row += 1

        # ===== 已有 VTT 文件（VTT 模式）=====
        self.pdfvtt_vtt_row = QWidget()
        r_vtt = QHBoxLayout(self.pdfvtt_vtt_row)
        r_vtt.setContentsMargins(0, 0, 0, 0)
        r_vtt.addWidget(QLabel("已有字幕:"))
        self.pdfvtt_vtt = QLineEdit()
        self.pdfvtt_vtt.setPlaceholderText("选择已有的 ASR 字幕文件 (VTT/SRT)...")
        r_vtt.addWidget(self.pdfvtt_vtt, 1)
        vtt_browse = QPushButton("浏览...")
        vtt_browse.setMaximumWidth(70)
        vtt_browse.clicked.connect(self._browse_pdfvtt_vtt)
        r_vtt.addWidget(vtt_browse)
        self.pdfvtt_vtt_row.setVisible(False)
        form.addWidget(self.pdfvtt_vtt_row, row, 0, 1, 3)
        row += 1

        # ===== 输出文件 =====
        r_out, self.pdfvtt_output = self._make_file_input_row(
            "输出文件:", "字幕输出路径...",
            self._browse_pdfvtt_output, self
        )
        form.addLayout(r_out, row, 0, 1, 3)
        row += 1

        # ===== 选项 =====
        opt_layout = QHBoxLayout()

        opt_layout.addWidget(QLabel("输出格式:"))
        self.pdfvtt_fmt = QComboBox()
        self.pdfvtt_fmt.addItems(["VTT", "SRT", "LRC"])
        opt_layout.addWidget(self.pdfvtt_fmt)

        opt_layout.addSpacing(20)

        opt_layout.addWidget(QLabel("ASR 模型:"))
        self.pdfvtt_asr_model = QComboBox()
        self.main_window._init_asr_model_combo(self.pdfvtt_asr_model)
        self.pdfvtt_asr_model.setCurrentIndex(3)
        opt_layout.addWidget(self.pdfvtt_asr_model)

        opt_layout.addSpacing(20)

        opt_layout.addWidget(QLabel("语言:"))
        self.pdfvtt_lang = QComboBox()
        self.main_window._init_asr_lang_combo(self.pdfvtt_lang)
        self.pdfvtt_lang.setCurrentIndex(0)
        opt_layout.addWidget(self.pdfvtt_lang)

        opt_layout.addStretch()
        form.addLayout(opt_layout, row, 0, 1, 3)
        row += 1

        # ===== LLM 清洗 + 竖排模式 =====
        opt2_layout = QHBoxLayout()
        self.pdfvtt_use_llm = QCheckBox("启用 LLM 辅助清洗")
        self.pdfvtt_use_llm.setChecked(True)
        self.pdfvtt_use_llm.setToolTip("使用 LLM 从杂乱的台本文本中提取纯净对话（需要配置 API Key）")
        opt2_layout.addWidget(self.pdfvtt_use_llm)

        opt2_layout.addSpacing(20)

        opt2_layout.addWidget(QLabel("PDF 竖排模式:"))
        self.pdfvtt_vertical_mode = QComboBox()
        self.pdfvtt_vertical_mode.addItems(["自动检测", "强制横排", "强制竖排"])
        self.pdfvtt_vertical_mode.setToolTip(
            "自动检测：根据文本特征自动判断（默认）\n"
            "强制横排：跳过竖排检测，直接横排提取\n"
            "强制竖排：使用 pdfplumber 竖排模式提取"
        )
        opt2_layout.addWidget(self.pdfvtt_vertical_mode)

        opt2_layout.addStretch()
        form.addLayout(opt2_layout, row, 0, 1, 3)
        row += 1

        # ===== 说明 =====
        hint = QLabel(
            "流程说明：\n"
            "1. clean_script: 台本(PDF/TXT) → 清洗后的台词文本（regex 粗洗 + LLM 精洗）\n"
            "2. asr_recognize: 音频 → ASR 语音识别（已有 VTT 则跳过）\n"
            "3. llm_align: 台词 + ASR → LLM 智能对齐重排 → 带时间轴的字幕"
        )
        hint.setStyleSheet("color: #666; font-size: 11px;")
        hint.setWordWrap(True)
        form.addWidget(hint, row, 0, 1, 3)
        row += 1

        params = {
            "mode": self.pdfvtt_mode,
            "pdf": self.pdfvtt_pdf,
            "audio": self.pdfvtt_audio,
            "vtt": self.pdfvtt_vtt,
            "output": self.pdfvtt_output,
            "fmt": self.pdfvtt_fmt,
            "asr_model": self.pdfvtt_asr_model,
            "lang": self.pdfvtt_lang,
            "use_llm": self.pdfvtt_use_llm,
        }

        form.setRowStretch(row, 1)
        return page, params

    def _on_pdfvtt_mode_changed(self, index: int):
        """切换 PDF→VTT 运行模式时更新 UI"""
        is_full = (index == 0)       # 完整流程：需要音频
        is_vtt = (index == 1)        # 已有 VTT：需要 VTT 文件
        self.pdfvtt_audio_row.setVisible(is_full)
        self.pdfvtt_vtt_row.setVisible(is_vtt)

    def _browse_pdfvtt_pdf(self):
        fp, _ = QFileDialog.getOpenFileName(
            self, "选择台本文件", "", "台本文件 (*.pdf *.txt);;PDF 文件 (*.pdf);;TXT 文件 (*.txt);;所有文件 (*)")
        if fp:
            self.pdfvtt_pdf.setText(fp)
            if not self.pdfvtt_output.text():
                p = Path(fp)
                fmt_ext = self.pdfvtt_fmt.currentText().lower()
                self.pdfvtt_output.setText(str(p.parent / "output" / f"{p.stem}.{fmt_ext}"))

    def _browse_pdfvtt_audio(self):
        fp, _ = QFileDialog.getOpenFileName(
            self, "选择音频文件", "",
            "音频文件 (*.wav *.mp3 *.flac *.m4a *.ogg);;所有文件 (*)")
        if fp:
            self.pdfvtt_audio.setText(fp)

    def _browse_pdfvtt_vtt(self):
        fp, _ = QFileDialog.getOpenFileName(
            self, "选择字幕文件", "",
            "字幕文件 (*.vtt *.srt *.lrc);;所有文件 (*)")
        if fp:
            self.pdfvtt_vtt.setText(fp)

    def _browse_pdfvtt_output(self):
        fp, _ = QFileDialog.getSaveFileName(
            self, "选择输出文件", "output.vtt",
            "VTT 文件 (*.vtt);;SRT 文件 (*.srt);;LRC 文件 (*.lrc)")
        if fp:
            self.pdfvtt_output.setText(fp)

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
                5: "将字幕文件翻译为目标语言，输出双语对照字幕。"
                    "\n支持 DeepSeek / OpenAI 翻译引擎。",
                6: "台本(PDF/TXT) + 音频 → 完整字幕的 LLM 智能流水线。"
                    "\n支持三种模式：完整流程（台本+音频）、已有 VTT 修正、仅清洗文本。"
                    "\nLLM 负责精洗台本和智能对齐重排（修正错字、处理顺序差异）。",
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

            from src.gui.workers.pipeline_worker import ToolsWorkerThread
            self.worker = ToolsWorkerThread(
                tool_id=tool_index,
                params=params,
            )
            self.worker.progress.connect(self.log)
            self.worker.finished.connect(self._on_tool_finished)
            self.worker.start()

    def _stop_tool_run(self):
            """停止工具执行"""
            if hasattr(self, 'worker') and self.worker and self.worker.isRunning():
                self.worker.cancel()
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
                lang_code = self.asr_tool_lang.currentData() or "ja"
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

            elif tool_index == 6:
                # 台本转字幕 (LLM 流水线)
                script_path = self.pdfvtt_pdf.text().strip()
                if not script_path or not Path(script_path).exists():
                    QMessageBox.warning(self, "警告", "请选择有效的台本文件（PDF 或 TXT）！")
                    return None

                mode_index = self.pdfvtt_mode.currentIndex()
                output = self.pdfvtt_output.text().strip()
                if not output:
                    p = Path(script_path)
                    fmt_ext = self.pdfvtt_fmt.currentText().lower()
                    output = str(p.parent / "output" / f"{p.stem}.{fmt_ext}")

                # 竖排模式映射: 0=auto, 1=horizontal, 2=vertical
                vertical_mode_map = ["auto", "horizontal", "vertical"]
                vertical_mode = vertical_mode_map[self.pdfvtt_vertical_mode.currentIndex()]

                if mode_index == 0:
                    # 完整流程
                    audio = self.pdfvtt_audio.text().strip()
                    if not audio or not Path(audio).exists():
                        QMessageBox.warning(self, "警告", "完整流程模式需要选择音频文件！")
                        return None
                    return {
                        "tool": "script_to_vtt",
                        "mode": "full",
                        "script_path": script_path,
                        "audio_path": audio,
                        "output_path": output,
                        "fmt": self.pdfvtt_fmt.currentText().lower(),
                        "model": self.pdfvtt_asr_model.currentData() or "large-v3",
                        "language": self.pdfvtt_lang.currentData() or "ja",
                        "use_llm_clean": self.pdfvtt_use_llm.isChecked(),
                        "vertical_mode": vertical_mode,
                    }
                elif mode_index == 1:
                    # 已有 VTT
                    vtt_path = self.pdfvtt_vtt.text().strip()
                    if not vtt_path or not Path(vtt_path).exists():
                        QMessageBox.warning(self, "警告", "请选择已有的 ASR 字幕文件！")
                        return None
                    return {
                        "tool": "script_to_vtt",
                        "mode": "from_vtt",
                        "script_path": script_path,
                        "vtt_path": vtt_path,
                        "output_path": output,
                        "fmt": self.pdfvtt_fmt.currentText().lower(),
                        "use_llm_clean": self.pdfvtt_use_llm.isChecked(),
                        "vertical_mode": vertical_mode,
                    }
                else:
                    # 仅清洗文本
                    return {
                        "tool": "script_to_vtt",
                        "mode": "text_only",
                        "script_path": script_path,
                        "output_path": output,
                        "use_llm_clean": self.pdfvtt_use_llm.isChecked(),
                        "vertical_mode": vertical_mode,
                    }

            return None

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