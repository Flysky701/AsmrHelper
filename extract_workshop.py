import ast

with open('src/gui/app.py', 'r', encoding='utf-8') as f:
    text = f.read()
    tree = ast.parse(text)

funcs = [
  "create_voice_workshop_tab",
  "_open_voice_guide",
  "_on_template_changed",
  "_start_voice_design",
  "_on_design_progress",
  "_on_design_finished",
  "_browse_workshop_audio",
  "_start_segment_analysis",
  "_on_segment_analysis_progress",
  "_on_segment_analysis_finished",
  "_populate_segment_table",
  "_on_segment_table_changed",
  "_get_selected_segments",
  "_select_recommended_segments",
  "_clear_segment_selection",
  "_play_selected_segments",
  "_browse_workshop_subtitle",
  "_start_voice_clone",
  "_on_clone_progress",
  "_on_clone_finished",
  "_refresh_my_voices",
  "_refresh_custom_voice_combos",
  "_preview_workshop_voice",
  "_on_workshop_preview_finished",
  "_delete_workshop_voice",
  "_update_ref_text_preview"
]

method_nodes = []
for node in tree.body:
    if isinstance(node, ast.ClassDef) and node.name == 'MainWindow':
        for n in node.body:
            if isinstance(n, ast.FunctionDef) and n.name in funcs:
                method_nodes.append(n)

methods_code = []
for n in method_nodes:
    methods_code.append(ast.get_source_segment(text, n))

output_class = '''import os
from pathlib import Path
from typing import Optional, List, Dict
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QPushButton, QLabel,
    QLineEdit, QFileDialog, QProgressBar, QTextEdit, QComboBox, QCheckBox,
    QStackedWidget, QGroupBox, QMessageBox, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QSpinBox
)
from PySide6.QtCore import Qt, QThread
from PySide6.QtGui import QAction

from src.utils.audio_player import AudioPlayer
from src.gui.workers.pipeline_worker import VoiceCloneWorker, VoicePreviewWorker, SegmentAnalysisWorker, VoiceDesignWorker
from src.config import config

class VoiceWorkshopTab(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.audio_player = AudioPlayer()
        
        self.design_worker = None
        self.segment_worker = None
        self.clone_worker = None
        self.ws_preview_worker = None
        
        self.setup_ui()

    def log(self, message: str, color: str = None):
        self.main_window.log(message, color)

    def save_config(self):
        config.save()

'''

methods_text = "\n\n".join(methods_code)

import re
methods_text = re.sub(r'def create_voice_workshop_tab\(self\).*?:', 'def setup_ui(self):', methods_text)
methods_text = methods_text.replace('return widget', '')
methods_text = re.sub(r'widget = QWidget\(\)\s*', '', methods_text)
methods_text = re.sub(r'layout = QVBoxLayout\(widget\)\s*', 'layout = QVBoxLayout(self)\n        ', methods_text)

# Adjust self.* calls
methods_text = methods_text.replace('self.config.', 'config.')
methods_text = methods_text.replace('self.main_window._make_file_input_row', 'self.main_window._make_file_input_row')
methods_text = methods_text.replace('self._make_file_input_row', 'self.main_window._make_file_input_row')

indented_methods = []
for line in methods_text.split('\n'):
    indented_methods.append('    ' + line if line else '')

output_class += "\n".join(indented_methods)

with open('src/gui/views/workshop_tab.py', 'w', encoding='utf-8') as f:
    f.write(output_class)
    
new_code = text
for m in method_nodes:
    m_code = ast.get_source_segment(text, m)
    new_code = new_code.replace(m_code, '')

with open('src/gui/app.py', 'w', encoding='utf-8') as f:
    f.write(new_code)
print("Created workshop_tab.py and updated app.py")
