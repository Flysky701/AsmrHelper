import re

with open('preview_tmp.py', 'r', encoding='utf-8') as f:
    text = f.read()

replacements = {
    'self.preview_thread': 'self.main_window.preview_thread',
    'self._get_voice_info': 'self.main_window._get_voice_info',
    'self.log': 'self.main_window.log',
    'self.audio_player': 'self.main_window.audio_player',
    'getattr(self, \'preview_thread\', None)': 'getattr(self.main_window, \'preview_thread\', None)'
}

for k,v in replacements.items():
    text = text.replace(k, v)

# Import will be appended manually or added to SingleTab directly.
with open('src/gui/views/single_tab.py', 'a', encoding='utf-8') as f:
    f.write('\n')
    f.write(text)

print("Appended preview logic to SingleTab")
