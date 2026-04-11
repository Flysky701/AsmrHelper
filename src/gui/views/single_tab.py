import os
import re
from pathlib import Path
from typing import Optional, List, Dict
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel, QLineEdit, QPushButton, QComboBox, QSlider, QDoubleSpinBox, QCheckBox, QStackedWidget, QSpinBox, QFileDialog, QMessageBox
from PySide6.QtCore import Qt, QThread

from src.gui.workers.pipeline_worker import SingleWorkerThread
from src.gui.utils.validators import validate_single_params
from src.config import config
from src.utils.constants import AUDIO_EXTENSIONS

class SingleTab(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.setup_ui()

    def log(self, message: str, color: str = None):
        self.main_window.log(message, color)

    def save_config(self):
        config.save()

    def setup_ui(self):
            """创建单文件处理标签页"""
            layout = QVBoxLayout(self)
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

            # 可选字幕文件
            subtitle_layout = QHBoxLayout()
            self.single_subtitle_input = QLineEdit()
            self.single_subtitle_input.setPlaceholderText("可选：手动选择字幕文件（.vtt/.srt/.lrc）")
            subtitle_layout.addWidget(QLabel("字幕:"))
            subtitle_layout.addWidget(self.single_subtitle_input)
            subtitle_browse_btn = QPushButton("浏览...")
            subtitle_browse_btn.clicked.connect(self.browse_single_subtitle)
            subtitle_layout.addWidget(subtitle_browse_btn)
            input_layout.addLayout(subtitle_layout)

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
            self.main_window._init_vocal_model_combo(self.single_vocal_model)
            self.single_vocal_model.setToolTip("htdemucs_ft 及以上版本分离效果更好，但需要更多显存")
            vocal_layout.addWidget(self.single_vocal_model)
            vocal_layout.addSpacing(20)
            vocal_layout.addWidget(QLabel("识别模型:"))
            self.single_asr_model = QComboBox()
            self.main_window._init_asr_model_combo(self.single_asr_model)
            self.single_asr_model.setCurrentIndex(3)  # 默认 large-v3
            self.single_asr_model.setToolTip("large-v3 对轻声/日语识别效果最好（RTX 4070 Ti SUPER 可流畅运行）")
            vocal_layout.addWidget(self.single_asr_model)
            vocal_layout.addSpacing(20)
            vocal_layout.addWidget(QLabel("识别语言:"))
            self.single_asr_lang = QComboBox()
            self.main_window._init_asr_lang_combo(self.single_asr_lang)
            self.single_asr_lang.setCurrentIndex(0)  # 默认日语
            vocal_layout.addWidget(self.single_asr_lang)
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
            # Edge-TTS 音色选择器 (Index 0)
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
            qwen3_voice_widget = QWidget()
            qwen3_voice_layout = QVBoxLayout()
            qwen3_voice_layout.addWidget(self.single_voice_type)
            qwen3_voice_layout.addWidget(self.single_qwen3_voice_stack, 1)  # 拉伸因子=1
            qwen3_voice_widget.setLayout(qwen3_voice_layout)
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

            # 音量预览按钮区域
            vol_preview_layout = QHBoxLayout()
            self.single_vol_preview_btn = QPushButton("预听合成音量")
            self.single_vol_preview_btn.setMinimumWidth(100)
            self.single_vol_preview_btn.setToolTip("截取原音频前段（最多5分钟），与合成的测试语段按当前设置循环混合，用于预览音量")
            self.single_vol_preview_btn.clicked.connect(self.preview_volume_mix)
            vol_preview_layout.addWidget(self.single_vol_preview_btn)
            vol_preview_layout.addStretch()
            settings_layout.addLayout(vol_preview_layout)

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
            self.single_start_btn.setMinimumHeight(40)
            self.single_start_btn.setMinimumWidth(160)
            self.single_start_btn.setProperty("primary", "true")
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

    def browse_single_subtitle(self):
            """选择字幕文件（可选）"""
            file_path, _ = QFileDialog.getOpenFileName(
                self, "选择字幕文件", "",
                "字幕文件 (*.vtt *.srt *.lrc);;所有文件 (*.*)"
            )
            if file_path:
                self.single_subtitle_input.setText(file_path)

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
                "asr_language": self.single_asr_lang.currentData() if hasattr(self, "single_asr_lang") else "ja",
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
            ok, err = validate_single_params(params)
            if not ok:
                QMessageBox.warning(self, "参数错误", err)
                return
            
            # 查找字幕文件 (支持 VTT / SRT / LRC)
            subtitle_path = self.single_subtitle_input.text().strip()
            if subtitle_path and not Path(subtitle_path).exists():
                QMessageBox.warning(self, "警告", "手动字幕文件不存在，请重新选择！")
                return

            if not subtitle_path:
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
            self.main_window.progress_bar.setValue(0)

            self.main_window.worker = SingleWorkerThread(input_file, output_dir, params, subtitle_path)
            self.main_window.worker.progress.connect(self.on_single_progress)
            self.main_window.worker.finished.connect(self.on_single_finished)
            self.main_window.worker.start()

    def stop_single(self):
            """停止单文件处理"""
            if self.main_window.worker and self.main_window.worker.isRunning():
                self.main_window.worker.cancel()
                # 不调用 wait()：worker 的 finished 信号会自然触发 on_single_finished 回调
                # wait() 会阻塞主线程且可能与 finished 信号回调产生竞态
            else:
                # worker 已结束或为 None，手动恢复按钮状态
                self.log("\n[已停止]")
                self.single_start_btn.setEnabled(True)
                self.single_stop_btn.setEnabled(False)

    def on_single_progress(self, msg: str):
            """单文件进度更新（支持动态步骤数）"""
            self.log(msg)

            # 动态解析步骤数：支持 [1/3], [2/5], [1/4] 等格式
            match = re.search(r"\[(\d+)/(\d+)\]", msg)
            if match:
                current = int(match.group(1))
                total = int(match.group(2))
                if total > 0:
                    # 进度 = 当前步骤 / 总步骤 * 100
                    progress = int((current / total) * 100)
                    self.main_window.progress_bar.setMaximum(100)
                    self.main_window.progress_bar.setValue(progress)

    def on_single_finished(self, success: bool, message: str):
            """单文件处理完成"""
            self.main_window.progress_bar.setValue(100 if success else 0)
            self.single_start_btn.setEnabled(True)
            self.single_stop_btn.setEnabled(False)

            # 如果是用户主动取消，不弹窗
            if self.main_window.worker and self.main_window.worker._cancel_event.is_set():
                self.log("\n[已停止]")
                return

            if success:
                self.log(f"\n处理完成!\n输出: {message}")
                QMessageBox.information(self, "完成", f"处理完成！\n\n{message}")
            else:
                self.log(f"\n处理失败: {message}")
                QMessageBox.critical(self, "错误", f"处理失败:\n\n{message}")
    def preview_voice(self):
        """试音功能（使用线程避免阻塞）"""
        # 防止重复点击
        if getattr(self.main_window, 'preview_thread', None) and self.main_window.preview_thread.isRunning():
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
        from src.gui.workers.pipeline_worker import PreviewWorkerThread
        self.main_window.preview_thread = PreviewWorkerThread(
            engine=engine,
            voice=voice,
            voice_profile_id=voice_profile_id,
            speed=self.single_tts_speed.value() if engine == "qwen3" else 1.0,
            test_text=test_text,
        )
        self.main_window.preview_thread.finished.connect(self._on_preview_finished)
        self.main_window.preview_thread.start()
    def _on_preview_finished(self, success: bool, message: str, output_path: str):
        """试音完成回调"""
        self.single_preview_btn.setEnabled(True)
        self.single_preview_btn.setText("试音")

        if success:
            self.main_window.log(f"[试音] {message}")
            # 使用内置播放器
            self.main_window.audio_player.load_and_play(output_path)
        else:
            self.main_window.log(f"[试音] 失败: {message}")
            QMessageBox.critical(self, "错误", f"试音失败:\n{message}")

    def preview_volume_mix(self):
        """音量合成预览（原音截取前段 + 测试TTS循环混合）"""
        if getattr(self.main_window, 'vol_preview_thread', None) and self.main_window.vol_preview_thread.isRunning():
            return

        input_path = self.single_file_input.text().strip()
        if not input_path or not Path(input_path).exists():
            QMessageBox.warning(self, "警告", "请先选择合法的原音频文件！")
            return

        params = self.get_single_params()
        
        # 预检查音色信息
        engine = "edge" if self.single_tts_engine.currentText() == "Edge-TTS" else "qwen3"
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

        # 补全参数
        params["tts_engine"] = engine
        params["tts_voice"] = voice
        params["voice_profile_id"] = voice_profile_id

        self.log(f"[音量预览] 开始合成，截取 {Path(input_path).name} 前端...")
        self.single_vol_preview_btn.setEnabled(False)
        self.single_vol_preview_btn.setText("生成中...")

        from src.gui.workers.pipeline_worker import VolumePreviewWorker
        self.main_window.vol_preview_thread = VolumePreviewWorker(
            audio_path=input_path,
            params=params,
        )
        self.main_window.vol_preview_thread.progress.connect(self._on_vol_preview_progress)
        self.main_window.vol_preview_thread.finished.connect(self._on_vol_preview_finished)
        self.main_window.vol_preview_thread.start()

    def _on_vol_preview_progress(self, msg: str, pct: int):
        self.single_vol_preview_btn.setText(f"{pct}% {msg[:6]}...")
        self.main_window.log(f"[音量预览] {msg} ({pct}%)")

    def _on_vol_preview_finished(self, success: bool, message: str, output_path: str):
        self.single_vol_preview_btn.setEnabled(True)
        self.single_vol_preview_btn.setText("预听合成音量")

        if success:
            self.main_window.log(f"[音量预览] 成功: {message}")
            self.main_window.audio_player.load_and_play(output_path)
        else:
            self.main_window.log(f"[音量预览] 失败: {message}")

    def _get_voice_info(self, engine: str, voice_tabs=None,
                         preset_combo=None, custom_combo=None,
                         clone_line=None, edge_combo=None) -> tuple:
        """
        从音色选择器获取音色信息
        """
        def _parse_voice_text(voice_text: str) -> tuple:
            voice_text = (voice_text or "").strip()
            if not voice_text:
                return "", None
            match = re.search(r"\(([^()]+)\)\s*$", voice_text)
            profile_id = match.group(1).strip() if match else None
            voice_name = voice_text.split(" (", 1)[0].strip()
            return voice_name, profile_id

        if engine == "edge":
            if edge_combo is not None:
                voice_text = edge_combo.currentText()
                voice_name, _ = _parse_voice_text(voice_text)
                return voice_name, None
            return "zh-CN-XiaoxiaoNeural", None

        if voice_tabs is None:
            return "Vivian", "A1"

        tab_index = voice_tabs.currentIndex()
        if tab_index == 0:
            voice_text = preset_combo.currentText()
            return _parse_voice_text(voice_text)
        else:
            voice_text = custom_combo.currentText()
            return _parse_voice_text(voice_text)

