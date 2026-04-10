import sys
with open('src/gui/app.py', 'r', encoding='utf-8') as f:
    text = f.read()

old_str = '''        self.tabs.addTab(self._wrap_scroll(self.create_voice_workshop_tab()), "音色工坊")'''
new_str = '''        from src.gui.views.workshop_tab import VoiceWorkshopTab
        self.workshop_tab = VoiceWorkshopTab(self)
        self.tabs.addTab(self._wrap_scroll(self.workshop_tab), "音色工坊")'''

text = text.replace(old_str, new_str)
with open('src/gui/app.py', 'w', encoding='utf-8') as f:
    f.write(text)
print("Updated tab instantiation")
