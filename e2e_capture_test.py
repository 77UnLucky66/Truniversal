"""
e2e_capture_test.py — сквозной тест захвата выделения (debug Шага 2).

Полный цикл «как у пользователя», но в безопасных условиях:
  1. открываем СВОЁ окно с выделенным текстом и берём фокус ОС;
  2. регистрируем производственный хоткей (alt+q из config.json), затем для
     симуляции переключаемся на ctrl+shift+f12 — ALT-хоткеи нельзя «нажать»
     инъекцией (листер keyboard игнорирует инъецированные ALT-события),
     а физически alt+q у пользователя работает;
  3. СИМУЛИРУЕМ нажатие хоткея (vk+scan-инъекция, как настоящая клавиша);
  4. менеджер проходит весь путь: очистка буфера → отпуск модификаторов →
     цепочка способов копирования → чтение буфера → возврат буфера →
     pyqtSignal;
  5. проверяем, что сигнал принёс наш текст, а буфер восстановлен.

Запуск:  python e2e_capture_test.py
(На экране ненадолго появится тестовое окно; кликните по нему, если попросит.)
"""

import ctypes
import sys

import pyperclip
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QLineEdit, QVBoxLayout, QWidget

from config import ConfigManager
from hotkey_manager import HotkeyManager

SAMPLE = "Сквозной тест захвата 67890"
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32


def force_foreground(hwnd: int) -> bool:
    """Трюк с AttachThreadInput: фоновому процессу нельзя просто так взять фокус."""
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


KEY_CODES = {
    "ctrl": (0x11, 0x1D),
    "alt": (0x12, 0x38),
    "shift": (0x10, 0x2A),
    "win": (0x5B, 0x5B),
    "windows": (0x5B, 0x5B),
    "f12": (0x7B, 0x58),
}


def send_hotkey_vk(hotkey: str) -> None:
    """Нажимает хоткей инъекцией с корректными vk+scan (как настоящая клавиша).

    ВАЖНО: keyboard.send() на этой машине шлёт БУКВЕННЫЕ клавиши с битыми vk
    (таблица scan_code_to_vk библиотеки ошибочна: 'q' → 0xB1 «media prev»,
    'c' → 0xAE «volume down»), поэтому инъецируем сами — с настоящими
    виртуальными кодами и scan-кодами.
    """
    parts = [p.strip().lower() for p in hotkey.split("+")]
    codes = []
    for part in parts:
        if part in KEY_CODES:
            codes.append(KEY_CODES[part])
        elif len(part) == 1:  # буква: vk знаем точно, scan — US-раскладка
            scan = {"q": 0x10, "c": 0x2E, "w": 0x11}.get(part, 0)
            codes.append((ord(part.upper()), scan))
        else:
            raise ValueError(f"Неизвестная клавиша: {part}")
    for vk, scan in codes:
        user32.keybd_event(vk, scan, 0, 0)
    vk, scan = codes[-1]
    user32.keybd_event(vk, scan, 2, 0)  # KEYEVENTF_KEYUP
    for vk, scan in reversed(codes[:-1]):
        user32.keybd_event(vk, scan, 2, 0)


def main() -> int:
    app = QApplication(sys.argv)

    win = QWidget()
    win.setWindowTitle("E2E тест захвата — окно закроется само")
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

    hwnd = int(win.winId())
    focused = False
    for _ in range(30):  # ~1.5 с на естественную активацию
        QTest.qWait(50)
        if user32.GetForegroundWindow() == hwnd and edit.hasFocus():
            focused = True
            break
    if not focused:
        focused = force_foreground(hwnd)
        QTest.qWait(100)
        focused = focused and edit.hasFocus()
    if not focused:
        win.setWindowTitle(">>> КЛИКНИТЕ по этому окну — e2e тест <<<")
        print("Окну нужен клик мышью; ждём до 15 секунд...")
        for _ in range(300):
            QTest.qWait(50)
            if user32.GetForegroundWindow() == hwnd and edit.hasFocus():
                focused = True
                break
            edit.setFocus(Qt.FocusReason.OtherFocusReason)
            edit.selectAll()
    if not focused:
        print("FOCUS-FAIL: инъекции НЕ выполнялись.")
        win.close()
        return 1

    # Известное старое содержимое буфера — проверим, что приложение вернёт его.
    OLD = "старый буфер пользователя"
    pyperclip.copy(OLD)

    config = ConfigManager()
    hotkey_str = config.get("hotkey", "alt+q")

    manager = HotkeyManager(config)
    received = []
    failures = []
    manager.text_captured.connect(lambda text: received.append(text))
    manager.capture_failed.connect(lambda message: failures.append(message))
    if not manager.start():
        print("Не удалось зарегистрировать производственный хоткей — тест невозможен.")
        win.close()
        return 1
    print(f"Производственный хоткей «{hotkey_str}» зарегистрирован.")

    # НО: ALT-хоткеи нельзя «нажать» инъекцией — листер keyboard игнорирует
    # инъецированные события с флагом ALT (fake_alt-фильтр). Физически alt+q
    # у пользователя работает (балун ошибки это доказал). Поэтому сквозную
    # проверку делаем на ctrl+shift+f12: тот же код, поток и сигнал.
    if not manager.set_hotkey("ctrl+shift+f12"):
        print("Не удалось зарегистрировать тестовый хоткей ctrl+shift+f12.")
        win.close()
        return 1

    print("Тестовый хоткей «ctrl+shift+f12» зарегистрирован. Симулируем нажатие...")
    QTest.qWait(200)
    edit.setFocus(Qt.FocusReason.OtherFocusReason)
    edit.selectAll()
    QTest.qWait(50)
    send_hotkey_vk("ctrl+shift+f12")  # «пользователь» нажал хоткей (vk+scan)

    # Ждём завершения захвата в фоновом потоке (обычно ~0.2 с).
    waited = 0
    while not received and not failures and waited < 6000:
        QTest.qWait(50)
        waited += 50

    manager.stop()

    if not received and not failures:
        print("Ни один сигнал не пришёл — похоже, хоткей не сработал.")

    ok_signal = received == [SAMPLE]
    print("text_captured:", received)
    print("capture_failed:", failures)
    print("Буфер после захвата:", repr(pyperclip.paste()))
    ok_restore = pyperclip.paste() == OLD
    win.close()

    print(f"[{'OK' if ok_signal else 'FAIL'}] сигнал доставил текст выделения")
    print(f"[{'OK' if ok_restore else 'FAIL'}] старый буфер восстановлен")
    if failures:
        print(f"[FAIL] приложение сообщило об ошибке: {failures[0]}")

    passed = ok_signal and ok_restore and not failures
    print("E2E:", "PASSED" if passed else "FAILED")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
