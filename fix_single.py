import sys
with open('src/gui/app.py', 'r', encoding='utf-8') as f:
    text = f.read()

old_str = '''        self.tabs.addTab(self._wrap_scroll(self.create_single_tab()), "单文件处理")'''
new_str = '''        from src.gui.views.single_tab import SingleTab
        self.single_tab = SingleTab(self)
        self.tabs.addTab(self._wrap_scroll(self.single_tab), "单文件处理")'''

text = text.replace(old_str, new_str)
with open('src/gui/app.py', 'w', encoding='utf-8') as f:
    f.write(text)
print("Updated tab instantiation for single mode")
