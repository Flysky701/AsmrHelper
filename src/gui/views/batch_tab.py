import os
from pathlib import Path
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, 
                               QLabel, QLineEdit, QPushButton, QComboBox, 
                               QFileDialog, QListWidget, QSpinBox, QMessageBox,
                               QDoubleSpinBox, QCheckBox, QStackedWidget, QSlider,
                               QAbstractItemView)
from PySide6.QtCore import Qt
from src.gui.workers.pipeline_worker import BatchWorkerThread
from src.gui.utils.validators import validate_batch_params
from src.utils.constants import AUDIO_EXTENSIONS

class BatchTab(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.setup_ui()

    def setup_ui(self):
        """创建批量处理标签页"""
        layout = QVBoxLayout(self)
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
        self.batch_file_list.setMinimumHeight(160)
        self.batch_file_list.setMaximumHeight(200)
        self.batch_file_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        input_layout.addWidget(QLabel("待处理文件:"))
        input_layout.addWidget(self.batch_file_list)

        # 文件管理按钮
        file_btn_layout = QHBoxLayout()

        add_file_btn = QPushButton("添加文件")
        add_file_btn.clicked.connect(self.add_batch_files)
        file_btn_layout.addWidget(add_file_btn)

        add_folder_btn = QPushButton("添加文件夹")
        add_folder_btn.clicked.connect(self.add_batch_folder)
        file_btn_layout.addWidget(add_folder_btn)

        remove_btn = QPushButton("移除选中")
        remove_btn.clicked.connect(self.remove_selected_batch_files)
        file_btn_layout.addWidget(remove_btn)

        clear_btn = QPushButton("清空列表")
        clear_btn.clicked.connect(self.clear_batch_files)
        file_btn_layout.addWidget(clear_btn)

        refresh_btn = QPushButton("按目录刷新")
        refresh_btn.clicked.connect(self.refresh_batch_files)
        file_btn_layout.addWidget(refresh_btn)

        input_layout.addLayout(file_btn_layout)

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
        self.main_window._init_asr_model_combo(self.batch_asr_model)
        self.batch_asr_model.setCurrentIndex(3)  # 默认 large-v3
        model_layout.addWidget(self.batch_asr_model)
        model_layout.addSpacing(20)
        model_layout.addWidget(QLabel("分离模型:"))
        self.batch_vocal_model = QComboBox()
        self.main_window._init_vocal_model_combo(self.batch_vocal_model)
        self.batch_vocal_model.setToolTip("人声分离使用的 Demucs 模型")
        model_layout.addWidget(self.batch_vocal_model)
        model_layout.addSpacing(20)
        model_layout.addWidget(QLabel("识别语言:"))
        self.batch_asr_lang = QComboBox()
        self.main_window._init_asr_lang_combo(self.batch_asr_lang)
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
        self.batch_start_btn.setMinimumHeight(40)
        self.batch_start_btn.setMinimumWidth(160)
        self.batch_start_btn.setProperty("primary", "true")
        self.batch_start_btn.clicked.connect(self.start_batch)
        btn_layout.addWidget(self.batch_start_btn)

        self.batch_stop_btn = QPushButton("停止")
        self.batch_stop_btn.setMinimumHeight(40)
        self.batch_stop_btn.setMinimumWidth(80)
        self.batch_stop_btn.setEnabled(False)
        self.batch_stop_btn.clicked.connect(self.stop_batch)
        btn_layout.addWidget(self.batch_stop_btn)

        layout.addLayout(btn_layout)

        # 初始化
        self.on_batch_engine_changed("Edge-TTS")

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
        discovered = set()
        for ext in AUDIO_EXTENSIONS:
            try:
                for f in Path(dir_path).rglob(f"*{ext}"):
                    self._add_file_item(str(f), discovered)
            except (PermissionError, OSError) as e:
                self.main_window.log(f"[WARN] 扫描 {dir_path} 失败 ({ext}): {e}")

        count = self.batch_file_list.count()
        self.main_window.progress_text.append(f"在 {dir_path} 中找到 {count} 个音频文件")

    def add_batch_files(self):
        """手动添加多个文件到批量列表"""
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择音频文件", "",
            f"音频文件 ({' '.join(AUDIO_EXTENSIONS)});;所有文件 (*.*)"
        )
        if not files:
            return

        existing = {self.batch_file_list.item(i).text() for i in range(self.batch_file_list.count())}
        for file_path in files:
            self._add_file_item(file_path, existing)

    def add_batch_folder(self):
        """手动添加文件夹中的音频文件到批量列表"""
        folder = QFileDialog.getExistingDirectory(self, "选择包含音频的文件夹", "")
        if not folder:
            return

        existing = {self.batch_file_list.item(i).text() for i in range(self.batch_file_list.count())}
        for ext in AUDIO_EXTENSIONS:
            for f in Path(folder).rglob(f"*{ext}"):
                self._add_file_item(str(f), existing)

    def remove_selected_batch_files(self):
        """移除已选中的文件"""
        for item in self.batch_file_list.selectedItems():
            row = self.batch_file_list.row(item)
            self.batch_file_list.takeItem(row)

    def clear_batch_files(self):
        """清空文件列表"""
        self.batch_file_list.clear()

    def _add_file_item(self, path: str, existing: set):
        normalized = str(Path(path))
        if normalized in existing:
            return

        suffix = Path(normalized).suffix.lower()
        if suffix not in AUDIO_EXTENSIONS:
            return

        existing.add(normalized)
        self.batch_file_list.addItem(normalized)
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
    def get_batch_params(self) -> dict:
        """获取批量处理参数"""
        engine = "edge" if self.batch_tts_engine.currentText() == "Edge-TTS" else "qwen3"
        asr_model = self.batch_asr_model.currentData() or "large-v3"
        vocal_model = self.batch_vocal_model.currentData() or "htdemucs"

        # 获取音色信息 (根据引擎类型获取)
        tts_voice, voice_profile_id = self.main_window._get_voice_info(
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
    def start_batch(self):
        """开始批量处理"""
        file_count = self.batch_file_list.count()
        if file_count == 0:
            QMessageBox.warning(self, "警告", "没有找到待处理的文件！")
            return

        input_files = [self.batch_file_list.item(i).text() for i in range(file_count)]
        output_dir = self.batch_output_input.text().strip()
        params = self.get_batch_params()
        ok, err = validate_batch_params(params, input_files)
        if not ok:
            QMessageBox.warning(self, "参数错误", err)
            return
        max_workers = params.pop("max_workers", 1)  # 取出并行度，剩余参数传给 Worker

        self.main_window.log(f"开始批量处理 {file_count} 个文件")
        self.main_window.log(f"输出目录: {output_dir or '与源文件同目录'}")
        self.main_window.log(f"跳过已处理: {params['skip_existing']}")
        self.main_window.log(f"并行度: {max_workers}\n")

        self.batch_start_btn.setEnabled(False)
        self.batch_stop_btn.setEnabled(True)
        self.main_window.progress_bar.setValue(0)

        self.main_window.batch_worker = BatchWorkerThread(input_files, output_dir, params, max_workers=max_workers)
        self.main_window.batch_worker.progress.connect(self.main_window.log)
        self.main_window.batch_worker.file_progress.connect(self.on_batch_file_progress)
        self.main_window.batch_worker.finished.connect(self.on_batch_finished)
        self.main_window.batch_worker.start()
    def stop_batch(self):
        """停止批量处理"""
        if self.main_window.batch_worker and self.main_window.batch_worker.isRunning():
            self.main_window.batch_worker.cancel()
            # 不调用 wait()：worker 的 finished 信号会自然触发 on_batch_finished 回调
        else:
            self.main_window.log("\n[已停止]")
            self.batch_start_btn.setEnabled(True)
            self.batch_stop_btn.setEnabled(False)
    def on_batch_file_progress(self, current: int, total: int, filename: str):
        """批量处理文件进度"""
        self.main_window.progress_bar.setMaximum(total)
        self.main_window.progress_bar.setValue(current)
    def on_batch_finished(self, results: list):
        """批量处理完成"""
        self.batch_start_btn.setEnabled(True)
        self.batch_stop_btn.setEnabled(False)

        # 如果是用户主动取消，不弹窗
        if self.main_window.batch_worker and self.main_window.batch_worker._cancel_event.is_set():
            self.main_window.log("\n[已停止]")
            return

        success = sum(1 for r in results if r["status"] == "success")
        skipped = sum(1 for r in results if r["status"] == "skipped")
        failed = sum(1 for r in results if r["status"] == "failed")

        self.main_window.log(f"\n{'='*50}")
        self.main_window.log(f"批量处理完成!")
        self.main_window.log(f"成功: {success}, 跳过: {skipped}, 失败: {failed}")

        if failed > 0:
            self.main_window.log("\n失败的文件:")
            for r in results:
                if r["status"] == "failed":
                    self.main_window.log(f"  - {r['file']}: {r.get('error', 'Unknown')}")

        QMessageBox.information(
            self, "完成",
            f"批量处理完成!\n\n成功: {success}\n跳过: {skipped}\n失败: {failed}"
        )
