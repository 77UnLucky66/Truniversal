"""
hotkey_manager.py — глобальный хоткей и захват выделенного текста (ШАГ 2).

Как это работает:
  1. `keyboard.add_hotkey()` регистрирует хоткей из config.json; колбэк
     срабатывает в собственном потоке библиотеки `keyboard`.
  2. Сам захват вынесен ещё в один daemon-поток, чтобы не блокировать ни
     поток листенера, ни GUI:
       • сохраняем буфер пользователя и очищаем его (успех = появление
         любого непустого текста);
       • пауза 0.1 с и синтетический «отпуск» модификаторов (пользователь
         может ещё держать alt, пока нажимал хоткей);
       • пробуем ЦЕПОЧКУ способов копирования (Ctrl+Insert → Ctrl+C через
         vk-коды → Ctrl+C через scan-коды → Esc+Ctrl+C): разные приложения
         понимают разные хоткеи, а Ctrl+C через scan-коды на нелатинских
         раскладках может не распознаваться вовсе;
       • возвращаем пользователю его старый буфер.
  3. Готовый текст уходит в GUI строго через pyqtSignal — напрямую трогать
     виджеты из фонового потока нельзя (Qt это запрещает).
"""

from __future__ import annotations

import ctypes
import sys
import threading
import time
from typing import Any, Optional

import pyperclip
from PyQt6.QtCore import QObject, pyqtSignal

try:
    import keyboard
except Exception as _import_error:  # нет прав / библиотека недоступна
    keyboard = None  # type: ignore[assignment]
    _KEYBOARD_IMPORT_ERROR: Optional[Exception] = _import_error
else:
    _KEYBOARD_IMPORT_ERROR = None

# Модификаторы, которые пользователь может держать вместе с хоткеем.
_MODIFIER_KEYS = ("ctrl", "alt", "shift", "windows")


class HotkeyManager(QObject):
    """Слушает глобальный хоткей и захватывает выделенный текст."""

    #: Пойманный текст. Излучается из фонового потока — PyQt сам ставит
    #: сигнал в очередь GUI-потока (queued connection), это безопасно.
    text_captured = pyqtSignal(str)

    #: Диагностика: не получилось захватить выделение и т.п.
    capture_failed = pyqtSignal(str)

    def __init__(self, config: Any, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.config = config
        self._hotkey_ref: Any = None
        self._current_hotkey: Optional[str] = None
        # HWND окна, где пользователь последний раз выделял текст, — нужно
        # для кнопки «Заменить в тексте» (вернуть фокус и нажать Ctrl+V).
        self._last_target_hwnd: int = 0

    # ---------------------------------------------------------------- свойства
    @property
    def hotkey(self) -> str:
        """Текущий зарегистрированный хоткей (пустая строка — не слушаем)."""
        return self._current_hotkey or ""

    # ------------------------------------------------------- запуск/остановка
    def start(self) -> bool:
        """Регистрирует хоткей из конфига. True — успех."""
        return self.set_hotkey(self.config.get("hotkey", "alt+q"))

    def set_hotkey(self, hotkey: str) -> bool:
        """Меняет хоткей на лету: снимает старый, регистрирует новый."""
        self.stop()
        hotkey = (hotkey or "").strip()
        if not hotkey:
            print("[hotkey] Пустой хоткей — глобальный слушатель не запущен.")
            return False
        if keyboard is None:
            print(f"[hotkey] Библиотека keyboard недоступна: {_KEYBOARD_IMPORT_ERROR}")
            return False
        try:
            self._hotkey_ref = keyboard.add_hotkey(hotkey, self._on_hotkey_pressed)
        except Exception as exc:  # кривая строка хоткея и т.п.
            print(f"[hotkey] Не удалось зарегистрировать хоткей «{hotkey}»: {exc}")
            return False
        self._current_hotkey = hotkey
        print(f"[hotkey] Готов: глобальный хоткей «{hotkey}» слушается.")
        return True

    def stop(self) -> None:
        """Аккуратно снимает хоткей (при выходе и при смене хоткея)."""
        if self._hotkey_ref is not None:
            try:
                keyboard.remove_hotkey(self._hotkey_ref)
            except Exception:
                pass
            self._hotkey_ref = None
            self._current_hotkey = None

    # ----------------------------------------------- колбэк из потока keyboard
    def _on_hotkey_pressed(self) -> None:
        """Хоткей нажат. Захват выносим в отдельный поток, чтобы не блокировать
        поток листенера keyboard (он один на все хоткеи)."""
        threading.Thread(
            target=self._capture_sequence, name="hotkey-capture", daemon=True
        ).start()

    def _capture_sequence(self) -> None:
        """Полное течение захвата. Работает в фоновом потоке: GUI здесь нет.

        Разные приложения понимают разные «копирующие» хоткеи, а Alt от
        хоткея может открыть меню приложения, поэтому пробуем ЦЕПОЧКУ
        способов, пока в буфере не появится текст:
          1. Ctrl+Insert — самый безопасный: не «прерывает» процесс в
             терминалах (в отличие от Ctrl+C) и поддерживается почти везде;
          2. Ctrl+C через виртуальные коды (keybd_event) — vk-инъекция
             надёжно распознаётся приложениями, в том числе на нелатинских
             раскладках (подтверждено диагностикой на этой машине);
          3. Ctrl+C через scan-коды (keyboard.send) — для окружений, где
             vk-инъекция игнорируется;
          4. Esc + Ctrl+C — если Alt успел открыть меню приложения.

        Перед этим сохраняем буфер пользователя и очищаем его: тогда успех =
        появление в буфере ЛЮБОГО непустого текста (и нет ложного «не
        изменился», если выделение совпало со старым буфером). В конце
        буфер возвращаем на место — и при успехе, и при неудаче.
        """
        # 0) Запоминаем окно, где выделен текст, — для «Заменить в тексте».
        self._remember_target_window()

        old_clipboard = self._safe_paste()
        self._safe_copy("")  # успех = любой непустой текст в буфере

        # Пауза, затем «отпускаем» модификаторы (юзер ещё держит alt и т.п.).
        time.sleep(0.1)
        for key in _MODIFIER_KEYS:
            try:
                keyboard.release(key)
            except Exception:
                pass

        new_text = None
        attempts = (
            lambda: keyboard.send("ctrl+insert"),  # 1) безопасно почти везде
            self._vk_ctrl_c,                       # 2) классический Ctrl+C (vk)
            lambda: keyboard.send("ctrl+c"),        # 3) Ctrl+C через scan-коды
        )
        for send_copy in attempts:
            new_text = self._send_and_wait(send_copy, timeout=0.7)
            if new_text:
                break

        if not new_text:
            # Alt мог открыть меню приложения — закрываем его и пробуем ещё раз.
            try:
                keyboard.send("esc")
                time.sleep(0.05)
            except Exception:
                pass
            new_text = self._send_and_wait(self._vk_ctrl_c, timeout=0.7)

        # Возвращаем пользователю его буфер (чистили его мы — вернём при любом исходе).
        if old_clipboard:
            time.sleep(0.05)
            self._safe_copy(old_clipboard)

        if not new_text:
            self.capture_failed.emit(
                "Не удалось скопировать выделенный текст.\n"
                "Возможные причины:\n"
                "• текст не выделен или приложение не поддерживает копирование;\n"
                "• окно запущено от администратора — тогда запустите Truniversal "
                "тоже от администратора;\n"
                "• приложение перехватывает Ctrl+C/Ctrl+Insert под себя."
            )
            return

        # Отдаём текст в GUI — строго через pyqtSignal.
        self.text_captured.emit(new_text)

    # ------------------------------------------------------------ способы копии
    def _send_and_wait(self, send_copy, timeout: float) -> Optional[str]:
        """Отправляет один способ копирования и ждёт появления текста."""
        try:
            send_copy()
        except Exception as exc:
            print(f"[hotkey] Способ копирования не отправился: {exc}")
            return None
        return self._wait_for_any_text(timeout=timeout)

    @staticmethod
    def _vk_ctrl_c() -> None:
        """Ctrl+C через keybd_event с ВИРТУАЛЬНЫМИ кодами.

        На нелатинских раскладках scan-code инъекция Ctrl+C может не
        распознаваться приложениями как копирование (диагностика это
        показала), а vk-инъекция работает стабильно.
        """
        if sys.platform != "win32":
            return
        user32 = ctypes.windll.user32
        VK_CONTROL, VK_C, KEYEVENTF_KEYUP = 0x11, 0x43, 0x0002
        user32.keybd_event(VK_CONTROL, 0, 0, 0)
        user32.keybd_event(VK_C, 0, 0, 0)
        user32.keybd_event(VK_C, 0, KEYEVENTF_KEYUP, 0)
        user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)

    # ------------------------------------------------ «Заменить в тексте»
    def paste_to_window(self, text: str) -> None:
        """Вставить text в исходное окно: копия → фокус → Ctrl+V (в фоне)."""
        threading.Thread(
            target=self._paste_sequence, args=(text,),
            daemon=True, name="paste-replace",
        ).start()

    def _paste_sequence(self, text: str) -> None:
        """Течение вставки. Работает в фоновом потоке: GUI здесь нет."""
        self._safe_copy(text)
        time.sleep(0.05)
        if not self._restore_target_focus():
            self.capture_failed.emit(
                "Исходное окно недоступно — вставка отменена. "
                "Результат остался в буфере обмена."
            )
            return
        time.sleep(0.1)  # даём окну время получить фокус
        self._vk_ctrl_v()

    def _remember_target_window(self) -> None:
        """HWND активного окна на момент захвата (до отправки Ctrl+C)."""
        if sys.platform != "win32":
            self._last_target_hwnd = 0
            return
        try:
            self._last_target_hwnd = int(ctypes.windll.user32.GetForegroundWindow())
        except Exception:
            self._last_target_hwnd = 0

    def _restore_target_focus(self) -> bool:
        """Возвращает фокус в окно, где пользователь выделял текст."""
        if sys.platform != "win32":
            return False
        hwnd = self._last_target_hwnd
        if not hwnd:
            return False
        user32 = ctypes.windll.user32
        try:
            if not user32.IsWindow(hwnd):
                return False  # окно успели закрыть
            if user32.GetForegroundWindow() == hwnd:
                return True
            user32.SetForegroundWindow(hwnd)
            if user32.GetForegroundWindow() == hwnd:
                return True
            # Фоновому процессу Windows запрещает «красть» фокус — трюк
            # с AttachThreadInput (мы им уже пользовались в e2e-тесте).
            fg = user32.GetForegroundWindow()
            fg_tid = user32.GetWindowThreadProcessId(fg, None) if fg else 0
            our_tid = ctypes.windll.kernel32.GetCurrentThreadId()
            attached = bool(fg_tid) and bool(
                user32.AttachThreadInput(our_tid, fg_tid, True)
            )
            try:
                user32.BringWindowToTop(hwnd)
                user32.SetForegroundWindow(hwnd)
            finally:
                if attached:
                    user32.AttachThreadInput(our_tid, fg_tid, False)
            return user32.GetForegroundWindow() == hwnd
        except Exception:
            return False

    @staticmethod
    def _vk_ctrl_v() -> None:
        """Ctrl+V через keybd_event с ВИРТУАЛЬНЫМИ кодами — как и Ctrl+C:
        scan-инъекция букв на нелатинских раскладках ненадёжна."""
        if sys.platform != "win32":
            return
        user32 = ctypes.windll.user32
        VK_CONTROL, VK_V, KEYEVENTF_KEYUP = 0x11, 0x56, 0x0002
        user32.keybd_event(VK_CONTROL, 0, 0, 0)
        user32.keybd_event(VK_V, 0, 0, 0)
        user32.keybd_event(VK_V, 0, KEYEVENTF_KEYUP, 0)
        user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)

    # ------------------------------------------------------------------- буфер
    @staticmethod
    def _safe_paste() -> str:
        try:
            return pyperclip.paste() or ""
        except Exception:
            # Буфер может быть временно занят другим процессом — не падаем.
            return ""

    @staticmethod
    def _safe_copy(text: str) -> None:
        try:
            pyperclip.copy(text)
        except Exception:
            pass

    def _wait_for_any_text(self, timeout: float, interval: float = 0.05) -> Optional[str]:
        """Ждёт, пока в буфере появится любой непустой текст (или таймаут)."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            time.sleep(interval)
            candidate = self._safe_paste()
            if candidate:
                return candidate
        return None
