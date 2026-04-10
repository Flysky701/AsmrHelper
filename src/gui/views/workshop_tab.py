import os
from pathlib import Path
from typing import Optional, List, Dict
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QPushButton, QLabel,
    QLineEdit, QFileDialog, QProgressBar, QTextEdit, QComboBox, QCheckBox, QListWidget,
    QStackedWidget, QGroupBox, QMessageBox, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QSpinBox
)
from PySide6.QtCore import Qt, QThread
from PySide6.QtGui import QAction

from src.utils.audio_player import AudioPlayerWidget
from src.core.tts.voice_profile import VoiceProfileManager, get_voice_manager
from src.gui.workers.pipeline_worker import VoiceCloneWorker, VoicePreviewWorker, SegmentAnalysisWorker, VoiceDesignWorker
from src.config import config

class VoiceWorkshopTab(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.audio_player = AudioPlayerWidget()
        
        self.design_worker = None
        self.segment_worker = None
        self.clone_worker = None
        self.ws_preview_worker = None
        
        self.setup_ui()

    def log(self, message: str, color: str = None):
        self.main_window.log(message, color)

    def save_config(self):
        config.save()

    def setup_ui(self):
            """创建音色工坊标签页"""
            layout = QVBoxLayout(self)
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
            self.main_window._init_asr_lang_combo(self.workshop_asr_lang)
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
            gpu_info = self.main_window._get_gpu_info(self.main_window)
            gpu_label = QLabel(f"GPU: {gpu_info}")
            gpu_label.setStyleSheet("color: gray; font-size: 11px;")
            layout.addWidget(gpu_label)

            layout.addStretch()

            # 初始化音色列表
            self._refresh_my_voices()

            

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
            from src.gui.workers.pipeline_worker import VoiceDesignWorker

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

            from src.gui.workers.pipeline_worker import SegmentAnalysisWorker
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

            from src.gui.workers.pipeline_worker import VoiceCloneWorker

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
            current_single = self.main_window.single_custom_voice.currentText() if self.main_window.single_custom_voice.count() > 0 else ""
            current_batch = self.main_window.batch_custom_voice.currentText() if self.main_window.batch_custom_voice.count() > 0 else ""

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
            populate_combo(self.main_window.single_custom_voice)
            populate_combo(self.main_window.batch_custom_voice)

            # 恢复选中项（如果存在）
            if current_single and self.main_window.single_custom_voice.findText(current_single) >= 0:
                self.main_window.single_custom_voice.setCurrentText(current_single)
            if current_batch and self.main_window.batch_custom_voice.findText(current_batch) >= 0:
                self.main_window.batch_custom_voice.setCurrentText(current_batch)

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

            from src.gui.workers.pipeline_worker import VoicePreviewWorker

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