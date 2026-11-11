"""
single_instance.py — защита от повторного запуска Truniversal (Этап 1).

Вторая копия приложения бесполезна и вредна: обе копии регистрируют один
и тот же глобальный хоткей, конфликтуют за буфер обмена и показывают две
иконки в трее. Единственность проверяется ИМЕНОВАННЫМ МЬЮТЕКСОМ Windows
(kernel32, без внешних зависимостей): мьютекс живёт, пока жив процесс, и
ОС автоматически освобождает его даже при аварийном завершении — «зависших
блокировок» после крушения не остаётся.
"""

from __future__ import annotations

import ctypes
import sys
from typing import Optional

# ERROR_ALREADY_EXISTS — мьютекс с таким именем уже существует (копия работает).
_ERROR_ALREADY_EXISTS = 183

# «Local\…» — область видимости в пределах сеанса пользователя: разные
# пользователи одного компьютера держат свои копии независимо друг от друга.
_MUTEX_NAME = "Local\\Truniversal.SingleInstance.v1"

if sys.platform == "win32":
    from ctypes import wintypes
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    _kernel32.CreateMutexW.restype = wintypes.HANDLE
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.CloseHandle.restype = wintypes.BOOL
else:
    _kernel32 = None


class SingleInstanceGuard:
    """Держатель мьютекса единственности экземпляра приложения.

    acquire() → True: мы первая копия, мьютекс наш (держим до release()
    или до завершения процесса — ОС закроет дескриптор сама).
    acquire() → False: копия уже запущена. На не-Windows проверка
    отключена (всегда True) — приложение и так ориентировано на Windows.
    При любой ошибке WinAPI метод возвращает True: лучше запустить вторую
    копию, чем не пустить ни одну.
    """

    def __init__(self, name: str = _MUTEX_NAME) -> None:
        self._name = name
        self._handle: Optional[int] = None

    def acquire(self) -> bool:
        """Пытается стать единственным экземпляром. True — мы первые."""
        if sys.platform != "win32" or _kernel32 is None:
            return True
        if self._handle is not None:
            return True  # уже захвачено этим же объектом
        try:
            handle = _kernel32.CreateMutexW(None, False, self._name)
            if not handle:
                # Создать мьютекс не вышло (крайне маловероятно) — не мешаем запуску.
                return True
            if ctypes.get_last_error() == _ERROR_ALREADY_EXISTS:
                _kernel32.CloseHandle(handle)
                return False  # копия уже работает
            self._handle = handle
            return True
        except Exception:
            # Любая проблема с API не должна мешать запуску приложения.
            return True

    def release(self) -> None:
        """Закрывает мьютекс (обычно не требуется: ОС закроет его при выходе)."""
        handle, self._handle = self._handle, None
        if handle and _kernel32 is not None:
            try:
                _kernel32.CloseHandle(handle)
            except Exception:
                pass

    def __del__(self) -> None:
        try:
            self.release()
        except Exception:
            pass
