"""
make_icon.py — утилита сборки: генерирует build_icon.ico из программной
иконки приложения (чтобы PyInstaller вшил её в .exe).

Запуск:  python make_icon.py   (создаёт build_icon.ico в текущей папке)
"""

import sys

from PyQt6.QtWidgets import QApplication

import main as m


def main() -> int:
    app = QApplication(sys.argv)
    icon = m.create_app_icon()
    pixmap = icon.pixmap(256, 256)
    if pixmap.save("build_icon.ico", "ICO"):
        print("OK: build_icon.ico создана")
        return 0
    print("FAIL: Qt-плагин ICO не смог записать файл — соберите без --icon")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
