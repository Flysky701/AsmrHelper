import re

with open('src/gui/views/tools_tab.py', 'r', encoding='utf-8') as f:
    text = f.read()

text = text.replace('self.config = main_window.config', '')
text = text.replace('def save_config(self):\n        self.main_window.save_config()', 'def save_config(self):\n        config.save()')
if 'from src.config import config' not in text:
    text = text.replace('from PySide6.QtCore import Qt, QThread', 'from PySide6.QtCore import Qt, QThread\nfrom src.config import config')

with open('src/gui/views/tools_tab.py', 'w', encoding='utf-8') as f:
    f.write(text)
