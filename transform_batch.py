def build_batch():
    with open('extract_batch_tmp.py', 'r', encoding='utf-8') as f:
        text = f.read()

    import re
    replacements = {
        'self.batch_worker': 'self.main_window.batch_worker',
        'self.log': 'self.main_window.log',
        'self.progress_bar': 'self.main_window.progress_bar',
        'self.progress_text': 'self.main_window.progress_text',
        'self._get_voice_info': 'self.main_window._get_voice_info',
        'self._init_vocal_model_combo': 'self.main_window._init_vocal_model_combo',
        'self._init_asr_model_combo': 'self.main_window._init_asr_model_combo',
        'self._init_asr_lang_combo': 'self.main_window._init_asr_lang_combo'
    }
    for k, v in replacements.items():
        text = text.replace(k, v)

    text = re.sub(r'def create_batch_tab\(self\).*?:', 'def setup_ui(self):', text)
    text = text.replace('        widget = QWidget()\n        layout = QVBoxLayout(widget)\n', '        layout = QVBoxLayout(self)\n')
    text = text.replace('        return widget\n', '')
    text = re.sub(r'\bwidget\b\.', 'self.', text)
    text = re.sub(r'\blayout = QVBoxLayout\(self\)', 'layout = QVBoxLayout(self)', text)

    header = '''import os
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, 
                               QLabel, QLineEdit, QPushButton, QComboBox, 
                               QFileDialog, QListWidget, QSpinBox, QMessageBox,
                               QDoubleSpinBox, QCheckBox, QStackedWidget, QSlider)
from PySide6.QtCore import Qt
from src.gui.gui_workers import BatchProcessWorker

class BatchTab(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.setup_ui()

'''
    with open('src/gui/views/batch_tab.py', 'w', encoding='utf-8') as f:
        f.write(header + text)

build_batch()
