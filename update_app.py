import ast
import re

with open('src/gui/app.py', 'r', encoding='utf-8') as f:
    src = f.read()

parsed = ast.parse(src)
lines = src.splitlines(keepends=True)
batch_methods = ['create_batch_tab', 'browse_batch_dir', 'browse_batch_output', 
                 'refresh_batch_files', 'on_batch_engine_changed', 'get_batch_params', 
                 'start_batch', 'stop_batch', 'on_batch_file_progress', 'on_batch_finished']

ranges_to_remove = []

for node in parsed.body:
    if isinstance(node, ast.ClassDef) and node.name == 'MainWindow':
        for n in node.body:
            if isinstance(n, ast.FunctionDef) and n.name in batch_methods:
                start = n.lineno - 1
                end = n.end_lineno
                if n.decorator_list:
                    start = n.decorator_list[0].lineno - 1
                ranges_to_remove.append((start, end))

ranges_to_remove.sort(key=lambda x: x[0], reverse=True)

for start, end in ranges_to_remove:
    del lines[start:end]

new_src = ''.join(lines)

props = """
    @property
    def batch_custom_voice(self):
        return self.batch_tab.batch_custom_voice

    @property
    def batch_edge_voice(self):
        return self.batch_tab.batch_edge_voice
        
    @property
    def batch_preset_voice(self):
        return self.batch_tab.batch_preset_voice

    @property
    def batch_voice_type(self):
        return self.batch_tab.batch_voice_type
        
    @property
    def batch_voice_container(self):
        return self.batch_tab.batch_voice_container
"""

# insert properties
lines = new_src.splitlines(keepends=True)
for i, line in enumerate(lines):
    if 'def setup_ui(self):' in line:
        lines.insert(i, props)
        break
        
new_src = ''.join(lines)

# update setup_ui replacement
new_src = new_src.replace('        self.tabs.addTab(self.create_batch_tab(), "批量处理")', 
                          '        from src.gui.views.batch_tab import BatchTab\n        self.batch_tab = BatchTab(self)\n        self.tabs.addTab(self.batch_tab, "批量处理")')

with open('src/gui/app.py', 'w', encoding='utf-8') as f:
    f.write(new_src)

print("Batch methods removed from app.py, proxy properties added.")
