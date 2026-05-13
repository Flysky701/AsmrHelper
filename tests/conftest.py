"""
pytest configuration
"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication


project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def qtbot(qapp):
    widgets = []

    def add_widget(widget):
        widgets.append(widget)
        widget.show()

    yield SimpleNamespace(addWidget=add_widget)

    for widget in widgets:
        widget.close()
