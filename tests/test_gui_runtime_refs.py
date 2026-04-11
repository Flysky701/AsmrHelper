"""GUI runtime regression tests for tab references and parameter wiring."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QComboBox, QProgressBar, QTextEdit

from src.gui.views.batch_tab import BatchTab
from src.gui.views.single_tab import SingleTab


class _DummyMainWindow:
    def __init__(self) -> None:
        self.worker = None
        self.batch_worker = None
        self.progress_bar = QProgressBar()
        self.progress_text = QTextEdit()

    def log(self, message: str, color: str | None = None) -> None:
        _ = color
        self.progress_text.append(message)

    @staticmethod
    def _init_vocal_model_combo(combo: QComboBox) -> None:
        combo.addItem("htdemucs", userData="htdemucs")
        combo.addItem("htdemucs_ft", userData="htdemucs_ft")

    @staticmethod
    def _init_asr_lang_combo(combo: QComboBox) -> None:
        combo.addItem("ja", userData="ja")
        combo.addItem("zh", userData="zh")

    @staticmethod
    def _init_asr_model_combo(combo: QComboBox) -> None:
        combo.addItem("base", userData="base")
        combo.addItem("small", userData="small")
        combo.addItem("medium", userData="medium")
        combo.addItem("large-v3", userData="large-v3")

    @staticmethod
    def _get_voice_info(engine: str, voice_tabs=None, preset_combo=None, custom_combo=None, clone_line=None, edge_combo=None):
        _ = (voice_tabs, preset_combo, custom_combo, clone_line, edge_combo)
        if engine == "edge":
            return "zh-CN-XiaoxiaoNeural", None
        return "Vivian", "A1"


class _DummySignal:
    def __init__(self):
        self._callbacks = []

    def connect(self, callback):
        self._callbacks.append(callback)

    def emit(self, *args, **kwargs):
        for callback in self._callbacks:
            callback(*args, **kwargs)


class _DummySingleWorker:
    def __init__(self, input_path: str, output_dir: str, params: dict, vtt_path: str = None):
        self.input_path = input_path
        self.output_dir = output_dir
        self.params = params
        self.vtt_path = vtt_path
        self.progress = _DummySignal()
        self.finished = _DummySignal()
        self.started = False

    def start(self):
        self.started = True


@pytest.mark.gui
def test_single_tab_start_uses_main_window_progress_bar_and_manual_subtitle(qtbot, tmp_path, monkeypatch):
    main_window = _DummyMainWindow()
    tab = SingleTab(main_window)
    qtbot.addWidget(tab)

    input_file = tmp_path / "input.wav"
    subtitle_file = tmp_path / "manual.vtt"
    input_file.write_bytes(b"fake-audio")
    subtitle_file.write_text("WEBVTT\n\n00:00.000 --> 00:01.000\nhello\n", encoding="utf-8")

    tab.single_file_input.setText(str(input_file))
    tab.single_output_input.setText(str(tmp_path / "out"))
    tab.single_subtitle_input.setText(str(subtitle_file))

    monkeypatch.setattr("src.gui.views.single_tab.validate_single_params", lambda params: (True, ""))
    monkeypatch.setattr("src.gui.views.single_tab.SingleWorkerThread", _DummySingleWorker)
    monkeypatch.setattr(
        "src.utils.find_subtitle_file",
        lambda *args, **kwargs: pytest.fail("manual subtitle should skip auto-discovery"),
    )

    tab.start_single()

    assert isinstance(main_window.worker, _DummySingleWorker)
    assert main_window.worker.started is True
    assert main_window.worker.vtt_path == str(subtitle_file)
    assert main_window.progress_bar.value() == 0


@pytest.mark.gui
def test_single_tab_progress_updates_main_window_progress_bar(qtbot):
    main_window = _DummyMainWindow()
    tab = SingleTab(main_window)
    qtbot.addWidget(tab)

    tab.on_single_progress("[2/4] processing")

    assert main_window.progress_bar.maximum() == 100
    assert main_window.progress_bar.value() == 50


@pytest.mark.gui
def test_batch_tab_add_file_item_deduplicates_and_filters_non_audio(qtbot, tmp_path):
    main_window = _DummyMainWindow()
    tab = BatchTab(main_window)
    qtbot.addWidget(tab)

    audio_file = tmp_path / "clip.wav"
    text_file = tmp_path / "note.txt"
    audio_file.write_bytes(b"x")
    text_file.write_text("x", encoding="utf-8")

    existing = set()
    tab._add_file_item(str(audio_file), existing)
    tab._add_file_item(str(audio_file), existing)
    tab._add_file_item(str(text_file), existing)

    assert tab.batch_file_list.count() == 1
    assert Path(tab.batch_file_list.item(0).text()).name == "clip.wav"


@pytest.mark.gui
def test_batch_tab_get_batch_params_reads_asr_user_data(qtbot):
    main_window = _DummyMainWindow()
    tab = BatchTab(main_window)
    qtbot.addWidget(tab)

    tab.batch_tts_engine.setCurrentText("Qwen3-TTS")
    tab.batch_asr_model.setCurrentIndex(1)

    params = tab.get_batch_params()

    assert params["asr_model"] == "small"
