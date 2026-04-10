import ast
import re
import os

with open('src/gui/app.py', 'r', encoding='utf-8') as f:
    code = f.read()

tree = ast.parse(code)

tools_funcs = [
  "create_tools_tab", "_build_separation_tool_ui", "_build_split_tool_ui",
  "_build_asr_tool_ui", "_build_convert_tool_ui", "_build_subtitle_gen_ui",
  "_build_subtitle_translate_ui", "_on_tool_changed", "_start_tool_run",
  "_stop_tool_run", "_on_tool_finished", "_collect_tool_params",
  "_browse_sep_input", "_browse_sep_output", "_browse_split_audio",
  "_browse_split_subtitle", "_browse_split_output", "_browse_subgen_input",
  "_populate_pdf_script_selector", "_browse_subgen_output",
  "_browse_subgen_audio", "_on_subgen_mode_changed", "_on_subgen_source_changed",
  "_browse_subtrans_input", "_browse_subtrans_output", "_browse_asr_tool_input",
  "_browse_asr_tool_output", "_browse_conv_input", "_browse_conv_output_dir",
  "_on_alignment_preview_ready"
]

method_nodes = []
for node in tree.body:
    if isinstance(node, ast.ClassDef) and node.name == 'MainWindow':
        for n in node.body:
            if isinstance(n, ast.FunctionDef) and n.name in tools_funcs:
                method_nodes.append(n)

methods_code = []
for n in method_nodes:
    m_code = ast.get_source_segment(code, n)
    methods_code.append(m_code)

output_class = '''import os
from pathlib import Path
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QPushButton, QLabel,
    QLineEdit, QFileDialog, QProgressBar, QTextEdit, QComboBox, QCheckBox,
    QStackedWidget, QGroupBox, QMessageBox, QTableWidget, QTableWidgetItem, QHeaderView
)
from PySide6.QtCore import Qt, QThread

from src.gui.workers.pipeline_worker import ToolsWorkerThread

class ToolsTab(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.config = main_window.config
        self.worker = None

        self.setup_ui()

    def log(self, message: str, color: str = None):
        self.main_window.log(message, color)

    def save_config(self):
        self.main_window.save_config()

'''

methods_text = "\n\n".join(methods_code)

# Replace 'create_tools_tab' signature to 'setup_ui'
methods_text = re.sub(r'def create_tools_tab\(self\).*?:', 'def setup_ui(self):', methods_text)
methods_text = methods_text.replace('return widget', '')
methods_text = re.sub(r'widget = QWidget\(\)\s*', '', methods_text)
methods_text = re.sub(r'layout = QVBoxLayout\(widget\)\s*', 'layout = QVBoxLayout(self)\n        ', methods_text)

# Adjust remaining self references
methods_text = methods_text.replace('self.tools_worker', 'self.worker')

# Add 4 spaces indent to methods
indented_methods = []
for line in methods_text.split('\n'):
    indented_methods.append('    ' + line if line else '')

output_class += "\n".join(indented_methods)

os.makedirs('src/gui/views', exist_ok=True)
with open('src/gui/views/tools_tab.py', 'w', encoding='utf-8') as f:
    f.write(output_class)

print("Created tools_tab.py")

# Now script to remove these from app.py
new_code = code
for m in method_nodes:
    start_line = m.lineno - 1
    end_line = m.end_lineno
    # to be safer, do exact string replace for methods
    m_code = ast.get_source_segment(code, m)
    new_code = new_code.replace(m_code, '')

with open('src/gui/app.py', 'w', encoding='utf-8') as f:
    f.write(new_code)
print("Removed tools from app.py")

