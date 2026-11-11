"""
hotkey_manager.py — глобальный хоткей и захват выделенного текста (Этап 2).

Как это работает:
  1. `keyboard.add_hotkey()` регистрирует хоткей из config.json; колбэк
     срабатывает в собственном потоке библиотеки `keyboard`.
  2. Авто-повтор при удержании клавиш гасится дебаунсом (0.4 с): каждый
     повтор сдвигает окно, поэтому пока клавиша удерживается, новых
     захватов не будет.
  3. Захваты строго сериализованы блокировкой _clipboard_lock — буфер
     обмена в системе один. Если предыдущий захват ещё не завершён,
     пользователь получает понятное сообщение, а не «тихое ничего».
  4. Сам захват (см. _run_capture_locked):
       • запоминает ИСХОДНОЕ окно Windows для «Заменить в тексте» — и
         никогда не принимает за исходное окно самого Truniversal;
       • делает ПОЛНЫЙ снимок буфера обмена (clipboard_backup.py: текст,
         картинки, файлы, RTF/HTML и другие форматы). Если какой-то формат
         нельзя сохранить безопасно — захват ОТКАНОВЛЯЕТСЯ, буфер остаётся
         нетронутым, пользователь получает понятное сообщение;
       • очищает буфер и проверяет пустоту — защита от чтения старого
         содержимого (если очистить не удалось, захват честно отказывается);
       • выдерживает настраиваемую паузу (capture_delay_ms) и «отпускает»
         модификаторы (пользователь может ещё держать alt);
       • пробует ЦЕПОЧКУ способов копирования (Ctrl+Insert → Ctrl+C через
         vk-коды → Ctrl+C через scan-коды); раунд можно повторить
         (capture_attempts), между раундами закрывается меню, которое мог
         открыть Alt; всё ограничено общим бюджетом времени;
       • восстанавливает буфер пользователя ТОЛЬКО если никто не успел
         скопировать что-то новое (контроль по счётчику изменений буфера
         Windows GetClipboardSequenceNumber + сверка текста);
       • выделение из одних пробелов не уходит в переводчик — вместо этого
         понятное сообщение.
  5. Каждый шаг пишется в диагностический журнал (diagnostics.py), если
     включена настройка «diagnostics». Содержимое выделенного текста в
     журнал НЕ записывается — только длины, имена форматов и процессов.
  6. Готовый текст уходит в GUI строго через pyqtSignal — напрямую трогать
     виджеты из фонового потока нельзя (Qt это запрещает).
"""

from __future__ import annotations

import ctypes
import os
import sys
import threading
import time
from typing import Any, Callable, Dict, Optional, Tuple

import pyperclip
from PyQt6.QtCore import QObject, pyqtSignal

import clipboard_backup
import diagnostics

try:
    import keyboard
except Exception as _import_error:  # нет прав / библиотека недоступна
    keyboard = None  # type: ignore[assignment]
    _KEYBOARD_IMPORT_ERROR: Optional[Exception] = _import_error
else:
    _KEYBOARD_IMPORT_ERROR = None

if sys.platform == "win32":
    from ctypes import wintypes
    _kernel32 = ctypes.windll.kernel32
    _user32 = ctypes.windll.user32

    # kernel32
    _kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.CloseHandle.restype = wintypes.BOOL
    _kernel32.GetCurrentThreadId.argtypes = []
    _kernel32.GetCurrentThreadId.restype = wintypes.DWORD

    # user32
    _user32.GetForegroundWindow.argtypes = []
    _user32.GetForegroundWindow.restype = wintypes.HWND
    _user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    _user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    _user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    _user32.GetWindowTextW.restype = ctypes.c_int
    _user32.IsWindow.argtypes = [wintypes.HWND]
    _user32.IsWindow.restype = wintypes.BOOL
    _user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    _user32.SetForegroundWindow.restype = wintypes.BOOL
    _user32.BringWindowToTop.argtypes = [wintypes.HWND]
    _user32.BringWindowToTop.restype = wintypes.BOOL
    _user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
    _user32.AttachThreadInput.restype = wintypes.BOOL
    _user32.keybd_event.argtypes = [ctypes.c_byte, ctypes.c_byte, wintypes.DWORD, ctypes.c_size_t]
    _user32.keybd_event.restype = None
else:
    _kernel32 = None
    _user32 = None


# Модификаторы, которые пользователь может держать вместе с хоткеем.
_MODIFIER_KEYS = ("ctrl", "alt", "shift", "windows")


def validate_hotkey(hotkey: str) -> Optional[str]:
    """Проверяет строку сочетания клавиш.

    Возвращает None для корректного сочетания (и для пустого — «не задан»)
    либо понятный текст ошибки (показывается в окне настроек).
    """
    hotkey = (hotkey or "").strip()
    if not hotkey or keyboard is None:
        return None  # пусто = «хоткей не задан»; без keyboard проверить нечем
    try:
        keyboard.parse_hotkey(hotkey)
    except Exception as exc:
        return str(exc) or "не удалось разобрать сочетание"
    return None


def _clamp(value: Any, lo: float, hi: float) -> float:
    """Число в разумных границах; мусор → lo."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return lo
    return min(max(number, lo), hi)


def _process_name(pid: int) -> str:
    """Имя процесса по PID (только для диагностики; без внешних библиотек).

    QueryFullProcessImageNameW живёт в kernel32 (Vista+); на старых системах
    запасной вариант — psapi.GetProcessImageFileNameW.
    """
    if pid <= 0:
        return ""
    try:
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
        if not handle:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(512)
            if hasattr(kernel32, "QueryFullProcessImageNameW"):
                size = ctypes.c_ulong(512)
                if kernel32.QueryFullProcessImageNameW(
                    handle, 0, buf, ctypes.byref(size)
                ):
                    return buf.value.rsplit("\\", 1)[-1]
            else:  # старые сборки Windows: имя живёт в psapi
                psapi = ctypes.WinDLL("psapi")
                if psapi.GetProcessImageFileNameW(handle, buf, 512):
                    return buf.value.rsplit("\\", 1)[-1]
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        pass
    return ""


class HotkeyManager(QObject):
    """Слушает глобальный хоткей и захватывает выделенный текст."""

    #: Пойманный текст. Излучается из фонового потока — PyQt сам ставит
    #: сигнал в очередь GUI-потока (queued connection), это безопасно.
    text_captured = pyqtSignal(str)

    #: Пойманный текст с привязкой к конкретному AI-действию (Этап 5): (text, action_id)
    action_captured = pyqtSignal(str, str)

    #: Диагностика: не получилось захватить выделение и т.п.
    capture_failed = pyqtSignal(str)

    #: Удержание клавиши: нажатия ближе этой паузы гасятся (авто-повтор).
    DEBOUNCE_SECONDS = 0.4
    #: Общий бюджет захвата: за его пределами новые попытки не начинаются.
    CAPTURE_TOTAL_TIMEOUT = 6.0
    #: Сколько ждать появления текста после одной попытки копирования.
    COPY_WAIT_SECONDS = 0.7

    def __init__(self, config: Any, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.config = config
        self._hotkey_ref: Any = None
        self._current_hotkey: Optional[str] = None
        self._action_hotkey_refs: Dict[str, Any] = {}
        self._enabled = bool(config.get("hotkey_enabled", True))
        # HWND окна, где пользователь последний раз выделял текст, — нужно
        # для кнопки «Заменить в тексте» (вернуть фокус и нажать Ctrl+V).
        self._last_target_hwnd: int = 0
        # Контекст последнего захвата: окно/процесс (текст НЕ храним).
        self._last_capture_info: Dict[str, Any] = {}
        # Момент последнего нажатия хоткея — для гашения авто-повтора.
        self._last_trigger_ts: float = 0.0
        # Буфер обмена в системе один: параллельные захваты/вставки конфликтуют
        # (один поток чистит буфер, другой в этот момент читает «свой» текст).
        # Блокировка сериализует все манипуляции с буфером: повторное нажатие
        # хоткея во время идущего захвата получает понятное сообщение,
        # а «Заменить в тексте» вежливо дожидается своей очереди.
        self._clipboard_lock = threading.Lock()
        # Способы копирования в порядке надёжности (см. _run_capture_locked).
        self._copy_methods: Tuple[Tuple[str, Callable[[], None]], ...] = (
            ("ctrl+insert", self._send_ctrl_insert),
            ("vk ctrl+c", self._vk_ctrl_c),
            ("scan ctrl+c", self._send_ctrl_c_scan),
        )

    # ---------------------------------------------------------------- свойства
    @property
    def hotkey(self) -> str:
        """Текущий зарегистрированный хоткей (пустая строка — не слушаем)."""
        return self._current_hotkey or ""

    # ------------------------------------------------------- запуск/остановка
    def start(self) -> str:
        """Регистрирует хоткей из конфига.

        Возвращает статус:
          "ok"       — хоткей слушается;
          "disabled" — хоткей отключён настройкой hotkey_enabled;
          "failed"   — зарегистрировать не удалось (подробности в консоли).
        """
        self._enabled = bool(self.config.get("hotkey_enabled", True))
        if not self._enabled:
            print("[hotkey] Хоткей отключён в настройках (hotkey_enabled = false).")
            return "disabled"
        return "ok" if self.set_hotkey(self.config.get("hotkey", "") or "") else "failed"

    def set_hotkey(self, hotkey: str) -> bool:
        """Меняет хоткей на лету: снимает старый, регистрирует новый."""
        self.stop()
        hotkey = (hotkey or "").strip()
        if not hotkey:
            print("[hotkey] Хоткей не задан — глобальный слушатель не запущен.")
            return False
        if not self._enabled:
            print(f"[hotkey] Хоткей «{hotkey}» запомнен, но слушатель отключён.")
            return False
        if keyboard is None:
            print(f"[hotkey] Библиотека keyboard недоступна: {_KEYBOARD_IMPORT_ERROR}")
            return False
        error = validate_hotkey(hotkey)
        if error:
            print(f"[hotkey] Сочетание «{hotkey}» непонятно: {error}")
            return False
        try:
            self._hotkey_ref = keyboard.add_hotkey(hotkey, self._on_hotkey_pressed)
        except Exception as exc:  # сочетание занято другой программой и т.п.
            print(f"[hotkey] Не удалось зарегистрировать хоткей «{hotkey}»: {exc}")
            return False
        self._current_hotkey = hotkey
        self._register_action_hotkeys()
        print(f"[hotkey] Готов: глобальный хоткей «{hotkey}» слушается.")
        return True

    def set_enabled(self, enabled: bool) -> bool:
        """Временно включает/выключает глобальный хоткей на лету.

        Сочетание берётся из конфига. Сам флаг hotkey_enabled метод НЕ
        сохраняет — за запись в config.json отвечает вызывающий код (окно
        настроек, меню трея). False при включении = не удалось
        зарегистрировать сочетание.
        """
        self._enabled = bool(enabled)
        if not self._enabled:
            self.stop()
            print("[hotkey] Глобальный хоткей выключен.")
            return True
        return self.set_hotkey(self.config.get("hotkey", "") or "")

    def stop(self) -> None:
        """Аккуратно снимает хоткей (при выходе и при смене хоткея)."""
        self._unregister_action_hotkeys()
        if self._hotkey_ref is not None:
            try:
                keyboard.remove_hotkey(self._hotkey_ref)
            except Exception:
                pass
            self._hotkey_ref = None
            self._current_hotkey = None

    def _register_action_hotkeys(self) -> None:
        """Регистрирует отдельные хоткеи для AI Quick Actions (Этап 5)."""
        self._unregister_action_hotkeys()
        if not self._enabled or keyboard is None:
            return
        if not hasattr(self.config, "get_action_hotkeys"):
            return
        hotkeys = self.config.get_action_hotkeys()
        main_hk = (self._current_hotkey or "").strip().lower()
        for action_id, hk_str in hotkeys.items():
            hk = (hk_str or "").strip().lower()
            if not hk or hk == main_hk:
                continue
            error = validate_hotkey(hk)
            if error:
                continue
            try:
                ref = keyboard.add_hotkey(
                    hk, lambda aid=action_id: self._on_action_hotkey_pressed(aid)
                )
                self._action_hotkey_refs[action_id] = ref
            except Exception as exc:
                print(f"[hotkey] Не удалось зарегистрировать хоткей действия «{hk}»: {exc}")

    def _unregister_action_hotkeys(self) -> None:
        if keyboard is None:
            return
        for ref in list(self._action_hotkey_refs.values()):
            try:
                keyboard.remove_hotkey(ref)
            except Exception:
                pass
        self._action_hotkey_refs.clear()

    def _on_action_hotkey_pressed(self, action_id: str) -> None:
        """Хоткей конкретного действия нажат."""
        now = time.monotonic()
        if now - self._last_trigger_ts < self.DEBOUNCE_SECONDS:
            self._last_trigger_ts = now
            return
        self._last_trigger_ts = now
        threading.Thread(
            target=lambda: self._safe_capture_sequence(action_id=action_id),
            name="action-hotkey-capture",
            daemon=True,
        ).start()

    def shutdown(self, timeout: float = 2.0) -> None:
        """Полная остановка при выходе: снять хоткей, все хуки и дождаться буфера."""
        self.stop()
        if keyboard is not None:
            try:
                keyboard.unhook_all()
            except Exception:
                pass
        # Если в момент выхода выполнялся захват или возврат буфера — даём потоку закончить
        acquired = self._clipboard_lock.acquire(timeout=timeout)
        if acquired:
            self._clipboard_lock.release()

    # ----------------------------------------------- колбэк из потока keyboard
    def _on_hotkey_pressed(self) -> None:
        """Хоткей нажат (поток листенера keyboard).

        Авто-повтор при удержании гасим дебаунсом: каждый повтор сдвигает
        окно, поэтому пока клавиша удерживается, новый захват не начнётся.
        """
        now = time.monotonic()
        if now - self._last_trigger_ts < self.DEBOUNCE_SECONDS:
            self._last_trigger_ts = now  # удержание: сдвигаем окно дебаунса
            diagnostics.log_event(self.config, "hotkey_debounced")
            return
        self._last_trigger_ts = now
        diagnostics.log_event(self.config, "hotkey_pressed")
        threading.Thread(
            target=self._safe_capture_sequence, name="hotkey-capture", daemon=True
        ).start()

    def _safe_capture_sequence(self, action_id: Optional[str] = None) -> None:
        """Обёртка: ни одно исключение не должно утекать в поток keyboard."""
        try:
            self._capture_sequence(action_id=action_id)
        except Exception as exc:
            diagnostics.log_exception(self.config, "capture", exc)
            try:
                self.capture_failed.emit(
                    "Внутренняя ошибка захвата — повторите попытку. "
                    "Ваш буфер обмена не пострадал."
                )
            except Exception:
                pass

    def _capture_sequence(self, action_id: Optional[str] = None) -> None:
        """Захват: строго по одному — буфер обмена один на всю систему.

        Если предыдущий захват ещё идёт, нажатие получило дебаунс раньше —
        значит, пользователь ждёт реакции: честно сообщаем, а не молчим.
        """
        if not self._clipboard_lock.acquire(blocking=False):
            diagnostics.log_event(self.config, "capture_busy_refused")
            self.capture_failed.emit(
                "Предыдущий захват ещё не завершён — подождите пару мгновений."
            )
            return
        try:
            self._run_capture_locked(action_id=action_id)
        finally:
            self._clipboard_lock.release()

    def _run_capture_locked(self, action_id: Optional[str] = None) -> None:
        """Полное течение захвата (буфер уже под блокировкой). GUI здесь нет.

        Шаги: окно-источник → снимок буфера → очистка с проверкой → пауза
        и отпуск модификаторов → цепочка копирований (раунды, бюджет
        времени) → аккуратный возврат буфера → разбор результата.
        """
        cfg = self.config
        started = time.monotonic()
        deadline = started + self.CAPTURE_TOTAL_TIMEOUT
        delay_s = _clamp(cfg.get("capture_delay_ms", 120), 0, 2000) / 1000.0
        rounds = int(_clamp(cfg.get("capture_attempts", 2), 1, 4))

        # 1) Контекст операции: исходное окно (никогда — окно Truniversal).
        window = self._remember_target_window()
        diagnostics.log_event(cfg, "capture_window", **window)

        # 2) Полный снимок буфера: если хоть один формат нельзя сохранить
        #    безопасно — отказ, буфер остаётся нетронутым.
        try:
            snapshot = clipboard_backup.save_snapshot()
        except clipboard_backup.ClipboardBackupError as exc:
            diagnostics.log_event(cfg, "snapshot_refused", reason=str(exc))
            self.capture_failed.emit(str(exc))
            return
        diagnostics.log_event(
            cfg, "snapshot_saved",
            formats="+".join(snapshot.format_names()) or "empty",
        )

        captured_text: Optional[str] = None
        method_used = ""
        try:
            # 3) Очистка буфера: пустой буфер — обязательное условие, иначе
            #    цепочка копирования могла бы вернуть нам СТАРОЕ содержимое.
            if not clipboard_backup.clear_clipboard():
                diagnostics.log_event(cfg, "clear_failed")
                self.capture_failed.emit(
                    "Буфер обмена занят другим приложением — захват отменён.\n"
                    "Повторите через мгновение."
                )
                return
            diagnostics.log_event(cfg, "clipboard_cleared")

            # 4) Настраиваемая пауза и «отпуск» модификаторов (юзер ещё
            #    держит alt и т.п.).
            if delay_s:
                time.sleep(delay_s)

            for key in _MODIFIER_KEYS:
                try:
                    keyboard.release(key)
                except Exception:
                    pass

            # 5) Цепочка способов копирования; между раундами — Esc (Alt от
            #    хоткея мог открыть меню приложения). Всё ограничено общим
            #    бюджетом времени.
            for round_no in range(1, rounds + 1):
                if round_no > 1:
                    try:
                        keyboard.send("esc")
                    except Exception:
                        pass
                    time.sleep(0.05)
                for name, send_copy in self._copy_methods:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    candidate = self._send_and_wait(
                        send_copy, min(self.COPY_WAIT_SECONDS, remaining)
                    )
                    diagnostics.log_event(
                        cfg, "copy_attempt",
                        round=round_no, method=name,
                        got_len=len(candidate) if candidate else 0,
                    )
                    if candidate:
                        captured_text, method_used = candidate, name
                        break
                if captured_text or time.monotonic() >= deadline:
                    break

            if captured_text:
                diagnostics.log_event(
                    cfg, "copy_success",
                    method=method_used, text_len=len(captured_text),
                    ms=int((time.monotonic() - started) * 1000),
                )
        finally:
            # 6) Возврат буфера — при ЛЮБОМ исходе, но только если никто
            #    не успел скопировать своё поверх (иначе снесли бы свежие
            #    данные пользователя).
            self._restore_user_clipboard(cfg, snapshot, captured_text)

        # 7) Разбор результата.
        if captured_text is None:
            diagnostics.log_event(cfg, "capture_failed", reason="no_text")
            self.capture_failed.emit(
                "Не удалось скопировать выделенный текст.\n"
                "Возможные причины:\n"
                "• текст не выделен или приложение не поддерживает копирование;\n"
                "• окно запущено от администратора — тогда запустите Truniversal "
                "тоже от администратора;\n"
                "• приложение перехватывает Ctrl+C/Ctrl+Insert под себя."
            )
            return
        if not captured_text.strip():
            # Пробельное «выделение» — пустые запросы в переводчик не уходят.
            diagnostics.log_event(cfg, "capture_failed", reason="whitespace_only")
            self.capture_failed.emit(
                "Выделение состоит из одних пробелов — переводить нечего."
            )
            return

        diagnostics.log_event(
            cfg, "capture_done",
            text_len=len(captured_text),
            ms=int((time.monotonic() - started) * 1000),
        )
        # Готовый текст — в GUI строго через pyqtSignal.
        if action_id:
            self.action_captured.emit(captured_text, action_id)
        else:
            self.text_captured.emit(captured_text)

    def _restore_user_clipboard(self, cfg: Any, snapshot: Any,
                                captured_text: Optional[str]) -> None:
        """Возвращает буфер пользователю — аккуратно и только когда можно.

        Правила:
          • контрольная точка фиксируется сразу после нашей последней
            операции с буфером (счётчик изменений Windows + текст);
          • если ПОСЛЕ контрольной точки кто-то изменил буфер (пользователь
            успел скопировать своё) — ничего не трогаем;
          • любая ошибка восстановления пишется в диагностику, но никогда
            не роняет захват.

        Задокументированная теоретическая гонка: если пользователь скопирует
        НЕТЕКСТОВЫЕ данные ровно посреди цепочки копирования, отличить их от
        ответа приложения невозможно — восстановление выполнится, отдав
        приоритет сохранности исходного буфера. Окно гонки ~1 с.
        """
        try:
            snapshot.mark_reference(
                expected_text=captured_text if captured_text is not None else ""
            )
            if not snapshot.can_safely_restore():
                diagnostics.log_event(cfg, "restore_skipped_external_change")
                return
            ok = snapshot.restore()
            diagnostics.log_event(cfg, "restore_done", ok=ok)
        except Exception as exc:
            diagnostics.log_exception(cfg, "restore", exc)

    # ------------------------------------------------------------ способы копии
    def _send_and_wait(self, send_copy, timeout: float) -> Optional[str]:
        """Отправляет один способ копирования и ждёт появления текста."""
        try:
            send_copy()
        except Exception as exc:
            diagnostics.log_exception(self.config, "copy_send", exc)
            return None
        return self._wait_for_any_text(timeout=timeout)

    @staticmethod
    def _send_ctrl_insert() -> None:
        """Ctrl+Insert — самый безопасный способ (терминалы, «занятый» Ctrl+C)."""
        if keyboard is not None:
            keyboard.send("ctrl+insert")

    @staticmethod
    def _send_ctrl_c_scan() -> None:
        """Ctrl+C через scan-коды — для окружений, игнорирующих vk-инъекцию."""
        if keyboard is not None:
            keyboard.send("ctrl+c")

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
        """Течение вставки. Работает в фоновом потоке: GUI здесь нет.

        Дожидаемся своей очереди (до 3 с), если ещё идёт захват выделения:
        буфер обмена один на всю систему.
        """
        if not self._clipboard_lock.acquire(timeout=3.0):
            self.capture_failed.emit(
                "Вставка отменена: захват текста ещё не завершился."
            )
            return
        try:
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
        finally:
            self._clipboard_lock.release()

    def _remember_target_window(self) -> Dict[str, Any]:
        """Контекст операции: активное окно-источник (до отправки Ctrl+C).

        Возвращает словарь для диагностики и запоминает HWND для «Заменить
        в тексте». ВАЖНО: окно самого Truniversal исходным быть не может —
        вставка результата в наше же окно недопустима, поэтому такие окна
        отбрасываются (запомним hwnd=0, paste_to_window честно откажется).
        """
        info: Dict[str, Any] = {"hwnd": 0, "pid": 0, "process": "", "title": ""}
        self._last_target_hwnd = 0
        if sys.platform != "win32":
            return info
        try:
            user32 = ctypes.windll.user32
            hwnd = int(user32.GetForegroundWindow())
            if not hwnd:
                return info
            pid = ctypes.c_ulong(0)
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            title_buf = ctypes.create_unicode_buffer(128)
            user32.GetWindowTextW(hwnd, title_buf, 128)
            info.update(hwnd=hwnd, pid=pid.value, title=title_buf.value)
            if pid.value == os.getpid():
                # Фокус в окне Truniversal: захват продолжится (пользователь
                # мог выделить текст в карточке), но «Заменить в тексте»
                # такое окно не получит.
                diagnostics.log_event(
                    self.config, "capture_target_own_window", title=info["title"]
                )
                return info
            self._last_target_hwnd = hwnd
            info["process"] = _process_name(pid.value)
            info["timestamp"] = time.time()
            self._last_capture_info = dict(info)
        except Exception:
            pass
        return info

    def check_can_replace(self) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """Проверяет возможность безопасного возврата фокуса и замены в исходном окне.

        Возвращает:
          (can_replace, message_or_warning, target_info)
        """
        if sys.platform != "win32":
            return False, "Функция «Заменить в тексте» поддерживается только в Windows.", None

        hwnd = self._last_target_hwnd
        if not hwnd:
            return False, "Исходное окно не зафиксировано (текст был введён вручную или окно не определено).", None

        user32 = ctypes.windll.user32
        try:
            if not user32.IsWindow(hwnd):
                return False, "Исходное окно было закрыто пользователем.", None

            pid = ctypes.c_ulong(0)
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value == os.getpid():
                return False, "Исходным окном является само приложение Truniversal. Вставка заблокирована.", None

            target_info = dict(getattr(self, "_last_capture_info", {}))
            orig_pid = target_info.get("pid", 0)
            if orig_pid and pid.value != orig_pid:
                return False, "Процесс исходного окна изменился.", target_info

            # Проверка давности захвата (контекст операции)
            cap_time = target_info.get("timestamp", 0)
            if cap_time and (time.time() - cap_time > 300):
                return True, "С момента захвата текста прошло более 5 минут. Исходное выделение в приложении могло сброситься.", target_info

            return True, "", target_info
        except Exception as exc:
            return False, f"Ошибка при проверке исходного окна: {exc}", None

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
            # HWND мог быть переиспользован другим (в т.ч. нашим) процессом —
            # перед вставкой сверяем владельца.
            pid = ctypes.c_ulong(0)
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value == os.getpid():
                return False  # указывает на окно Truniversal — вставка запрещена
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
