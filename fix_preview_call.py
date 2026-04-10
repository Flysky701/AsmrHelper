with open('src/gui/views/single_tab.py', 'r', encoding='utf-8') as f:
    text = f.read()

text = text.replace('self.single_preview_btn.clicked.connect(self.main_window.preview_voice)', 'self.single_preview_btn.clicked.connect(self.preview_voice)')
text = text.replace('self.main_window.preview_thread = PreviewWorkerThread', 'from src.gui.workers.pipeline_worker import PreviewWorkerThread\n        self.main_window.preview_thread = PreviewWorkerThread')

with open('src/gui/views/single_tab.py', 'w', encoding='utf-8') as f:
    f.write(text)
