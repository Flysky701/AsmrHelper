import sys
from PySide6.QtWidgets import QApplication, QStyleFactory
from src.gui.app import MainWindow

def main():
    app = QApplication(sys.argv)
    app.setStyle(QStyleFactory.create("Fusion"))

    window = MainWindow()
    window.show()

    sys.exit(app.exec())

if __name__ == "__main__":
    main()
