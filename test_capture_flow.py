"""
test_capture_flow.py — юнит-проверки потока захвата HotkeyManager (Этап 2).

Запуск:  python test_capture_flow.py
Реальные клавиши НЕ нажимаются: способ копирования подменяется моком, снимок
буфера — фейком. Проверяются: гашение авто-повтора (дебаунс), сообщение при
занятом захвате, восстановление буфера, отказы (занятый буфер, неподдержи-
ваемый формат), пробельные выделения, валидация сочетаний и статусы
включённости хоткея.
"""

import os
import sys
import tempfile
import threading
import time
from pathlib import Path

# ДО импорта PyQt6: без реального дисплея (тестируем только логику).
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pyperclip
from PyQt6.QtCore import QCoreApplication

import hotkey_manager
from config import ConfigManager
from hotkey_manager import HotkeyManager, validate_hotkey


class FakeSnapshot:
    """Минимальный двойник ClipboardSnapshot для тестов потока."""

    def __init__(self, old_text: str):
        self.old_text = old_text
        self.restore_calls = 0
        self.force_unsafe = False
        self.expected_text = None

    def format_names(self):
        return ["CF_UNICODETEXT"]

    def mark_reference(self, expected_text):
        self.expected_text = expected_text

    def can_safely_restore(self):
        if self.force_unsafe:
            return False
        try:
            return pyperclip.paste() == self.expected_text
        except Exception:
            return False

    def restore(self):
        self.restore_calls += 1
        try:
            pyperclip.copy(self.old_text)
            return True
        except Exception:
            return False


def make_config(tmp, **overrides):
    cfg = ConfigManager(Path(tmp) / "config.json")
    for key, value in overrides.items():
        cfg.set(key, value, autosave=False)
    return cfg


def run_capture(mgr, captured_value, *, snapshot=None, clear_ok=True):
    """Прогоняет _capture_sequence с моками вместо клавиш и снимка.

    captured_value — текст, который «приложение скопировало» (None = ничего).
    Возвращает (тексты, ошибки, снимок).
    """
    texts, fails = [], []
    mgr.text_captured.connect(texts.append)
    mgr.capture_failed.connect(fails.append)

    old_text = pyperclip.paste() or ""
    snapshot = snapshot or FakeSnapshot(old_text)

    orig_save = hotkey_manager.clipboard_backup.save_snapshot
    orig_clear = hotkey_manager.clipboard_backup.clear_clipboard
    orig_methods = mgr._copy_methods
    orig_window = mgr._remember_target_window

    def fake_copy():
        if captured_value is not None:
            pyperclip.copy(captured_value)

    def fake_clear():
        if not clear_ok:
            return False
        try:
            pyperclip.copy("")  # реальная очистка — иначе найдём старый текст
            return True
        except Exception:
            return False

    hotkey_manager.clipboard_backup.save_snapshot = lambda: snapshot
    hotkey_manager.clipboard_backup.clear_clipboard = fake_clear
    mgr._copy_methods = (("fake", fake_copy),)
    mgr._remember_target_window = lambda: {
        "hwnd": 0, "pid": 0, "process": "test", "title": "тестовое окно"
    }
    try:
        mgr._capture_sequence()  # синхронно, в этом же потоке
    finally:
        hotkey_manager.clipboard_backup.save_snapshot = orig_save
        hotkey_manager.clipboard_backup.clear_clipboard = orig_clear
        mgr._copy_methods = orig_methods
        mgr._remember_target_window = orig_window
    return texts, fails, snapshot


def run() -> int:
    app = QCoreApplication(sys.argv)

    with tempfile.TemporaryDirectory() as tmp:
        cfg = make_config(tmp, capture_delay_ms=0, diagnostics=True)

        # 1. Успешный захват: текст доставлен, буфер пользователя возвращён.
        pyperclip.copy("БУФЕР ПОЛЬЗОВАТЕЛЯ 1")
        mgr = HotkeyManager(cfg)
        texts, fails, snap = run_capture(mgr, "ЗАХВАЧЕННЫЙ ТЕКСТ")
        assert texts == ["ЗАХВАЧЕННЫЙ ТЕКСТ"], (texts, fails)
        assert not fails, fails
        assert snap.restore_calls == 1, "буфер должен быть возвращён"
        assert pyperclip.paste() == "БУФЕР ПОЛЬЗОВАТЕЛЯ 1"
        print("[OK] 1. Успешный захват доставляет текст и возвращает буфер")

        # 2. Пробельное выделение — понятная ошибка, запросов в переводчик нет.
        texts, fails, snap = run_capture(mgr, "   \n\t  ")
        assert not texts, texts
        assert fails and "пробел" in fails[0], fails
        assert snap.restore_calls == 1
        assert pyperclip.paste() == "БУФЕР ПОЛЬЗОВАТЕЛЯ 1"
        print("[OK] 2. Выделение из пробелов → понятная ошибка, буфер цел")

        # 3. Приложение ничего не скопировало — понятная ошибка, буфер цел.
        texts, fails, snap = run_capture(mgr, None)
        assert not texts, texts
        assert fails and "Не удалось скопировать" in fails[0], fails
        assert snap.restore_calls == 1
        assert pyperclip.paste() == "БУФЕР ПОЛЬЗОВАТЕЛЯ 1"
        print("[OK] 3. Пустой результат → понятная ошибка, буфер цел")

        # 4. Буфер занят другим приложением — захват отменён ДО любых изменений.
        texts, fails, snap = run_capture(mgr, "текст", clear_ok=False)
        assert not texts, texts
        assert fails and "занят другим приложением" in fails[0], fails
        assert snap.restore_calls == 0, "восстановление тут не нужно"
        assert pyperclip.paste() == "БУФЕР ПОЛЬЗОВАТЕЛЯ 1"
        print("[OK] 4. Занятый буфер → отказ без единого изменения")

        # 5. Снимок нельзя сделать (владельческий формат) — честный отказ.
        pyperclip.copy("БУФЕР ПОЛЬЗОВАТЕЛЯ 5")
        orig_save = hotkey_manager.clipboard_backup.save_snapshot

        def refuse_snapshot():
            raise hotkey_manager.clipboard_backup.ClipboardBackupError(
                "форматы в буфере нельзя сохранить — тест"
            )

        hotkey_manager.clipboard_backup.save_snapshot = refuse_snapshot
        try:
            texts, fails = [], []
            mgr.text_captured.connect(texts.append)
            mgr.capture_failed.connect(fails.append)
            mgr._capture_sequence()
        finally:
            hotkey_manager.clipboard_backup.save_snapshot = orig_save
        assert not texts and fails and "нельзя сохранить" in fails[0], (texts, fails)
        assert pyperclip.paste() == "БУФЕР ПОЛЬЗОВАТЕЛЯ 5", "буфер должен быть цел"
        print("[OK] 5. Отказ снимка → сообщение, буфер не тронут")

        # 6. Пользователь скопировал новое во время захвата — НЕ затираем.
        pyperclip.copy("БУФЕР ПОЛЬЗОВАТЕЛЯ 6")
        snap = FakeSnapshot("БУФЕР ПОЛЬЗОВАТЕЛЯ 6")
        snap.force_unsafe = True  # «кто-то писал в буфер после контрольной точки»
        texts, fails, snap = run_capture(mgr, "ЗАХВАТ 6", snapshot=snap)
        assert texts == ["ЗАХВАТ 6"], (texts, fails)
        assert snap.restore_calls == 0, "чужие свежие данные трогать нельзя"
        print("[OK] 6. Внешняя запись в буфер → восстановление отменено")

        # 7. Захват занят (блокировка) → понятное сообщение, не молчание.
        assert mgr._clipboard_lock.acquire(blocking=False)
        try:
            fails = []
            mgr.capture_failed.connect(fails.append)
            mgr._capture_sequence()
            assert fails and "ещё не завершён" in fails[0], fails
        finally:
            mgr._clipboard_lock.release()
        print("[OK] 7. Занятый захват → понятное сообщение")

        # 8. Дебаунс: серия «нажатий» подряд порождает ровно один захват.
        count = []
        done = threading.Event()

        def fake_capture(*args, **kwargs):
            count.append(1)
            done.set()

        mgr._capture_sequence = fake_capture
        for _ in range(6):
            mgr._on_hotkey_pressed()
        assert done.wait(2.0), "первый захват не начался"
        time.sleep(0.3)
        assert len(count) == 1, f"авто-повтор должен гаситься: {len(count)}"
        time.sleep(mgr.DEBOUNCE_SECONDS + 0.05)
        mgr._on_hotkey_pressed()  # осознанное повторное нажатие — живёт
        for _ in range(50):
            if len(count) == 2:
                break
            time.sleep(0.02)
        assert len(count) == 2, f"второй осознанный захват должен пройти: {len(count)}"
        del mgr._capture_sequence  # снимаем мок — дальше нужен настоящий захват
        print("[OK] 8. Дебаунс гасит авто-повтор, осознанное нажатие проходит")

        # 9. Валидация сочетаний.
        assert validate_hotkey("alt+q") is None
        assert validate_hotkey("ctrl+shift+f12") is None
        assert validate_hotkey("") is None          # «не задан» — допустимо
        assert validate_hotkey("+++"), "битая строка должна давать ошибку"
        print("[OK] 9. Валидация строк сочетаний клавиш")

        # 10. Статусы включённости: ok / disabled / failed.
        cfg_ok = make_config(tmp, hotkey="alt+q", hotkey_enabled=True)
        mgr_ok = HotkeyManager(cfg_ok)
        assert mgr_ok.start() == "ok" and mgr_ok.hotkey == "alt+q"
        mgr_ok.set_enabled(False)
        assert mgr_ok.hotkey == "" and cfg_ok.get("hotkey") == "alt+q"
        mgr_ok.set_enabled(True)
        assert mgr_ok.hotkey == "alt+q"

        cfg_off = make_config(tmp, hotkey="alt+q", hotkey_enabled=False)
        mgr_off = HotkeyManager(cfg_off)
        assert mgr_off.start() == "disabled"
        assert mgr_off.hotkey == ""

        cfg_bad = make_config(tmp, hotkey="+++", hotkey_enabled=True)
        mgr_bad = HotkeyManager(cfg_bad)
        assert mgr_bad.start() == "failed"
        assert mgr_bad.hotkey == ""
        mgr_ok.shutdown()  # снимаем реальную регистрацию alt+q
        print("[OK] 10. Статусы start(): ok / disabled / failed, вкл-выкл на лету")

        # 11. Диагностика: журнал пишется только при включённой настройке и
        #     НЕ содержит содержимого выделения.
        import diagnostics
        log_path = Path(diagnostics._log_path())
        if log_path.exists():
            log_path.unlink()
        run_capture(mgr, "СЕКРЕТНОЕ СОДЕРЖИМОЕ ВЫДЕЛЕНИЯ")
        assert log_path.exists(), "журнал должен появиться при diagnostics=true"
        log_text = log_path.read_text(encoding="utf-8")
        assert "СЕКРЕТНОЕ" not in log_text, "текст выделения НЕ логируется"
        assert "snapshot_saved" in log_text and "capture_window" in log_text
        assert "restore_done" in log_text
        cfg.set("diagnostics", False, autosave=False)
        log_path.unlink()
        run_capture(mgr, "ещё один захват")
        assert not log_path.exists(), "при выключенной диагностике журнал пуст"
        print("[OK] 11. Диагностика пишется без содержимого выделения")

    print("\nВсе проверки потока захвата пройдены (Этап 2)")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
