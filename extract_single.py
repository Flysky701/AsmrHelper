import ast
with open('src/gui/app.py', 'r', encoding='utf-8') as f:
    text = f.read()

funcs = [
  "create_single_tab",
  "browse_single_file",
  "browse_single_output",
  "on_single_engine_changed",
  "get_single_params",
  "start_single",
  "stop_single",
  "on_single_progress",
  "on_single_finished"
]

method_nodes = []
tree = ast.parse(text)
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
    QStackedWidget, QGroupBox, QMessageBox, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QSpinBox, QDoubleSpinBox
)
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

'''

methods_text = "\n\n".join(methods_code)

import re
methods_text = re.sub(r'def create_single_tab\(self\).*?:', 'def setup_ui(self):', methods_text)
methods_text = methods_text.replace('return widget', '')
methods_text = re.sub(r'widget = QWidget\(\)\s*', '', methods_text)
methods_text = re.sub(r'layout = QVBoxLayout\(widget\)\s*', 'layout = QVBoxLayout(self)\n        ', methods_text)

# Adjust self.* calls
methods_text = methods_text.replace('self.config.', 'config.')
methods_text = methods_text.replace('self.worker', 'self.main_window.worker')
methods_text = methods_text.replace('self.main_window._init_vocal_model_combo', 'self.main_window._init_vocal_model_combo')
methods_text = methods_text.replace('self._init_vocal_model_combo', 'self.main_window._init_vocal_model_combo')

indented_methods = []
for line in methods_text.split('\n'):
    indented_methods.append('    ' + line if line else '')

output_class += "\n".join(indented_methods)

with open('src/gui/views/single_tab.py', 'w', encoding='utf-8') as f:
    f.write(output_class)
    
new_code = text
for m in method_nodes:
    m_code = ast.get_source_segment(text, m)
    new_code = new_code.replace(m_code, '')

with open('src/gui/app.py', 'w', encoding='utf-8') as f:
    f.write(new_code)
print("Created single_tab.py and updated app.py")
