import sys
with open('src/gui/app.py', 'r', encoding='utf-8') as f:
    text = f.read()

old_str = '''        self.tabs.addTab(self._wrap_scroll(self.create_single_tab()), "单文件处理")
        self.tabs.addTab(self._wrap_scroll(self.create_batch_tab()), "批量处理")
        self.tabs.addTab(self._wrap_scroll(self.create_voice_workshop_tab()), "音色工坊")
        self.tabs.addTab(self._wrap_scroll(self.create_tools_tab()), "工具箱")
        main_layout.addWidget(self.tabs)'''

new_str = '''        self.tabs.addTab(self._wrap_scroll(self.create_single_tab()), "单文件处理")
        self.tabs.addTab(self._wrap_scroll(self.create_batch_tab()), "批量处理")
        self.tabs.addTab(self._wrap_scroll(self.create_voice_workshop_tab()), "音色工坊")
        
        from src.gui.views.tools_tab import ToolsTab
        self.tools_tab = ToolsTab(self)
        self.tabs.addTab(self._wrap_scroll(self.tools_tab), "工具箱")
        
        main_layout.addWidget(self.tabs)'''

text = text.replace(old_str, new_str)
with open('src/gui/app.py', 'w', encoding='utf-8') as f:
    f.write(text)
