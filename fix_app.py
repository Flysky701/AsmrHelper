lines = []
with open('src/gui/app.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

props = '''
    @property
    def single_custom_voice(self):
        return self.single_tab.single_custom_voice
    
    @property
    def single_edge_voice(self):
        return self.single_tab.single_edge_voice
        
    @property
    def single_preset_voice(self):
        return self.single_tab.single_preset_voice

    @property
    def single_voice_type(self):
        return self.single_tab.single_voice_type
        
    @property
    def single_voice_container(self):
        return self.single_tab.single_voice_container
'''

for i, line in enumerate(lines):
    if 'def setup_ui(self):' in line:
        lines.insert(i, props)
        break

with open('src/gui/app.py', 'w', encoding='utf-8') as f:
    f.write(''.join(lines))
