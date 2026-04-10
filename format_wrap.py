with open('src/gui/app.py', 'r', encoding='utf-8') as f:
    text = f.read()

import re
text = re.sub(r'        self\.tabs\.addTab\(self\._wrap_scroll\(self\.create_batch_tab\(\)\), "批量处理"\)',
              '        from src.gui.views.batch_tab import BatchTab\n        self.batch_tab = BatchTab(self)\n        self.tabs.addTab(self._wrap_scroll(self.batch_tab), "批量处理")', 
              text)

with open('src/gui/app.py', 'w', encoding='utf-8') as f:
    f.write(text)
