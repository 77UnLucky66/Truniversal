"""
diag_capture.py — разовая диагностика захвата выделения (debug Шага 2).

Открывает СВОЁ окно с выделенным текстом и прогоняет разные способы
эмуляции копирования, чтобы понять, что работает на этой машине:
  1) Ctrl+C (как в текущей реализации);
  2) Esc + Ctrl+C (Esc закрывает меню, которое мог открыть Alt);
  3) Ctrl+Insert (терминалы и приложения, где Ctrl+C занят);
  4) Ctrl+C через keybd_event с виртуальными кодами.

Окно закрывается само, буфер обмена восстанавливается.
"""

import ctypes
import sys

import keyboard
import pyperclip
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QLineEdit, QVBoxLayout, QWidget

SAMPLE = "Диагностический текст 12345"
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32


def force_foreground(hwnd: int) -> bool:
    """Стягивает окно на передний план (фоновому процессу Windows этого не даёт).

    Трюк с AttachThreadInput: подключаем свою очередь ввода к очереди ввода
    текущего активного окна — после этого SetForegroundWindow разрешён.
    Побочных нажатий клавиш при этом не отправляется.
    """
    fg = user32.GetForegroundWindow()
    fg_tid = user32.GetWindowThreadProcessId(fg, None) if fg else 0
    our_tid = kernel32.GetCurrentThreadId()
    attached = bool(fg_tid) and fg_tid != our_tid and bool(
        user32.AttachThreadInput(our_tid, fg_tid, True)
    )
    try:
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    finally:
        if attached:
            user32.AttachThreadInput(our_tid, fg_tid, False)
    return user32.GetForegroundWindow() == hwnd


def poll_clipboard(timeout_ms: int = 900, step_ms: int = 50) -> str:
    """Ждём появления непустого текста, не забывая крутить event loop Qt."""
    waited = 0
    while waited < timeout_ms:
        QTest.qWait(step_ms)
        waited += step_ms
        try:
            value = pyperclip.paste() or ""
        except Exception:
            value = ""
        if value:
            return value
    return ""


def vk_ctrl_c() -> None:
    """Ctrl+C через виртуальные коды (keybd_event) — запасной способ."""
    VK_CONTROL, VK_C, KEYEVENTF_KEYUP = 0x11, 0x43, 0x0002
    user32.keybd_event(VK_CONTROL, 0, 0, 0)
    user32.keybd_event(VK_C, 0, 0, 0)
    user32.keybd_event(VK_C, 0, KEYEVENTF_KEYUP, 0)
    user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)


def main() -> int:
    app = QApplication(sys.argv)

    win = QWidget()
    win.setWindowTitle("Диагностика захвата — окно закроется само")
    win.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    win.resize(460, 100)
    edit = QLineEdit(SAMPLE)
    edit.setReadOnly(True)
    QVBoxLayout(win).addWidget(edit)

    win.show()
    edit.setFocus(Qt.FocusReason.OtherFocusReason)
    edit.selectAll()
    win.raise_()
    win.activateWindow()

    # Ждём реального фокуса на уровне ОС — иначе инъекции уйдут в чужое окно.
    hwnd = int(win.winId())
    focused = False
    for _ in range(30):  # ~1.5 с на естественную активацию
        QTest.qWait(50)
        if user32.GetForegroundWindow() == hwnd and edit.hasFocus():
            focused = True
            break
    if not focused:
        # Фоновый процесс не может просто так взять фокус — применяем трюк.
        focused = force_foreground(hwnd)
        QTest.qWait(100)
        focused = focused and edit.hasFocus()
    if not focused:
        win.setWindowTitle(">>> КЛИКНИТЕ по этому окну — диагностика <<<")
        print("Окну нужен клик мышью; ждём до 15 секунд...")
        for _ in range(300):
            QTest.qWait(50)
            if user32.GetForegroundWindow() == hwnd and edit.hasFocus():
                focused = True
                break
            edit.setFocus(Qt.FocusReason.OtherFocusReason)
            edit.selectAll()
    if not focused:
        print("FOCUS-FAIL: окно не получило фокус — инъекции НЕ выполнялись.")
        win.close()
        return 1

    try:
        old_clipboard = pyperclip.paste() or ""
    except Exception:
        old_clipboard = ""
    print("Старый буфер:", repr(old_clipboard[:60]))
    print("Проверяем способы эмуляции копирования:")

    # «Отпускаем» модификаторы — как это делает приложение после хоткея.
    for key in ("ctrl", "alt", "shift", "windows"):
        try:
            keyboard.release(key)
        except Exception:
            pass
    QTest.qWait(100)

    variants = [
        ("ctrl+c (как сейчас)", lambda: keyboard.send("ctrl+c")),
        (
            "esc + ctrl+c",
            lambda: (
                keyboard.send("esc"),
                QTest.qWait(60),
                edit.selectAll(),  # QLineEdit снимает выделение по Esc
                QTest.qWait(20),
                keyboard.send("ctrl+c"),
            ),
        ),
        ("ctrl+insert", lambda: keyboard.send("ctrl+insert")),
        ("vk ctrl+c (keybd_event)", vk_ctrl_c),
    ]

    results = {}
    for name, action in variants:
        edit.setFocus(Qt.FocusReason.OtherFocusReason)
        edit.selectAll()
        QTest.qWait(40)
        try:
            pyperclip.copy("")
        except Exception:
            pass
        try:
            action()
        except Exception as exc:
            print(f"  [{name}] ОШИБКА ОТПРАВКИ: {exc}")
            results[name] = False
            continue
        got = poll_clipboard()
        results[name] = got == SAMPLE
        print(f"  [{name}] {'OK' if results[name] else 'FAIL'} (в буфере: {got!r})")

    try:
        if old_clipboard:
            pyperclip.copy(old_clipboard)  # возвращаем буфер пользователю
    except Exception:
        pass
    win.close()

    print("ИТОГ:", " | ".join(f"{k}={'OK' if v else 'FAIL'}" for k, v in results.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
