with open('src/gui/views/batch_tab.py', 'r', encoding='utf-8') as f:
    text = f.read()

text = text.replace('from src.gui.gui_workers import BatchWorkerThread', 'from src.gui.workers.pipeline_worker import BatchWorkerThread')

with open('src/gui/views/batch_tab.py', 'w', encoding='utf-8') as f:
    f.write(text)
