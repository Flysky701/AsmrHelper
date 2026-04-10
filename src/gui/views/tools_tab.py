import os
from pathlib import Path
from typing import Optional, List, Dict
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QPushButton, QLabel,
    QLineEdit, QFileDialog, QProgressBar, QTextEdit, QComboBox, QCheckBox,
    QStackedWidget, QGroupBox, QMessageBox, QTableWidget, QTableWidgetItem, QHeaderView
)
from PySide6.QtCore import Qt, QThread
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
            self.main_window._init_asr_model_combo(self.asr_tool_model)
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
            self.main_window._init_asr_lang_combo(self.subgen_lang)
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

            from src.gui.workers.pipeline_worker import ToolsWorkerThread
            self.worker = ToolsWorkerThread(
                tool_id=tool_index,
                params=params,
            )
            self.worker.progress.connect(self.log)
            self.worker.finished.connect(self._on_tool_finished)
            # Q3: ASR对齐预览信号
            self.worker.alignment_ready.connect(self._on_alignment_preview_ready)
            self.worker.start()

    def _stop_tool_run(self):
            """停止工具执行"""
            if hasattr(self, 'tools_worker') and self.worker and self.worker.isRunning():
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