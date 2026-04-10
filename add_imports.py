import re

with open('src/gui/views/single_tab.py', 'r', encoding='utf-8') as f:
    content = f.read()

# adding missing QtWidgets
content = re.sub(r'(from PySide6\.QtWidgets import.*?)\n', r'\1, QSlider, QDoubleSpinBox, QCheckBox, QStackedWidget\n', content, count=1)
if 'from PySide6.QtCore import' in content and 'Qt' not in content.split('from PySide6.QtCore import')[1].split('\n')[0]:
    content = re.sub(r'(from PySide6\.QtCore import.*?)\n', r'\1, Qt\n', content, count=1)
elif 'from PySide6.QtCore import Qt' not in content:
    content = content.replace('from PySide6.QtWidgets import', 'from PySide6.QtCore import Qt\nfrom PySide6.QtWidgets import')

with open('src/gui/views/single_tab.py', 'w', encoding='utf-8') as f:
    f.write(content)
print('added imports')
