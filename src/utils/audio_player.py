"""
嵌入式音频播放器组件 - AudioPlayerWidget

极简设计：仅含 ▶开始 / ■ 停止 / 可拖拽进度条
嵌入主窗口布局中，替代 os.startfile 系统播放器调用
"""

from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QPushButton, QSlider, QLabel, QSizePolicy,
    QStyle
)
from PySide6.QtCore import Qt, QUrl
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput


class AudioPlayerWidget(QWidget):
    """嵌入式音频播放器 - 仅含 开始/停止/进度条"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_path: str = ""
        self._is_playing = False
        self._dragging = False

        # 播放引擎
        self._player = QMediaPlayer()
        self._audio_output = QAudioOutput()
        self._player.setAudioOutput(self._audio_output)

        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(8)

        # 开始按钮
        self.start_btn = QPushButton("▶")
        self.start_btn.setToolTip("播放")
        self.start_btn.setMinimumSize(36, 28)
        self.start_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        # 停止按钮
        self.stop_btn = QPushButton("■")
        self.stop_btn.setToolTip("停止")
        self.stop_btn.setEnabled(False)
        self.stop_btn.setMinimumSize(36, 28)
        self.stop_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        # 进度条（可拖拽）
        self.seek_slider = QSlider(Qt.Horizontal)
        self.seek_slider.setMinimum(0)
        self.seek_slider.setMaximum(0)  # 加载音频前为0
        self.seek_slider.setValue(0)
        self.seek_slider.setMinimumWidth(200)
        self.seek_slider.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        # 时间标签
        self.time_label = QLabel("--:-- / --:--")
        self.time_label.setMinimumWidth(110)
        self.time_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.time_label.setStyleSheet("color: #999; font-size: 11px;")

        layout.addWidget(self.start_btn)
        layout.addWidget(self.stop_btn)
        layout.addWidget(self.seek_slider)
        layout.addWidget(self.time_label)

    def _connect_signals(self):
        self.start_btn.clicked.connect(self._on_start_clicked)
        self.stop_btn.clicked.connect(self._on_stop_clicked)
        self.seek_slider.sliderPressed.connect(lambda: setattr(self, '_dragging', True))
        self.seek_slider.sliderReleased.connect(self._on_seek_released)

        self._player.positionChanged.connect(self._on_position_changed)
        self._player.durationChanged.connect(self._on_duration_changed)
        self._player.playbackStateChanged.connect(self._on_playback_state_changed)

    # ========== 公共接口 ==========

    def load_and_play(self, audio_path: str):
        """加载并播放音频 - 唯一公共接口"""
        self._current_path = audio_path
        self._player.setSource(QUrl.fromLocalFile(audio_path))
        self._player.play()

    # ========== 内部回调 ==========

    def _on_start_clicked(self):
        if not self._current_path:
            return
        state = self._player.playbackState()
        if state == QMediaPlayer.PlayingState:
            self._player.pause()  # 已在播放则暂停
        else:
            self._player.play()

    def _on_stop_clicked(self):
        self._player.stop()
        self.seek_slider.setValue(0)

    def _on_seek_released(self):
        position_ms = self.seek_slider.value()
        self._player.setPosition(position_ms)
        self._dragging = False

    def _on_position_changed(self, position_ms: int):
        if not self._dragging and self.seek_slider.maximum() > 0:
            self.seek_slider.setValue(int(position_ms))
        self.time_label.setText(
            f"{self._format_time(position_ms)} / {self._format_time(self._player.duration())}"
        )

    def _on_duration_changed(self, duration_ms: int):
        self.seek_slider.setMaximum(int(duration_ms) if duration_ms > 0 else 0)

    def _on_playback_state_changed(self, state: int):
        is_playing = (state == QMediaPlayer.PlayingState)
        self.start_btn.setText("⏸" if is_playing else "▶")
        self.stop_btn.setEnabled(state != QMediaPlayer.StoppedState or bool(self._current_path))
        self._is_playing = is_playing

    @staticmethod
    def _format_time(ms: int) -> str:
        """格式化毫秒为 mm:ss"""
        if ms < 0 or ms == -1:
            return "--:--"
        s = ms // 1000
        m = s // 60
        s = s % 60
        return f"{m:02d}:{s:02d}"
