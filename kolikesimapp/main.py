import sys
from PyQt6.QtWidgets import QApplication
from kolikesimapp.gui.main_window import MainWindow

def main():
    app = QApplication(sys.argv)
    # "Fusion" stili işletim sistemi/temadan bağımsız olarak tutarlı görünür
    # ve özel QSS'imizi (spin box ok ikonları, onay kutusu tiki vb.) tüm
    # platformlarda (Windows/Linux/Mac) aynı şekilde render eder.
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()