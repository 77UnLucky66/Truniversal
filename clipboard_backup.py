"""
clipboard_backup.py — полный снимок буфера обмена Windows (Этап 2).

Захват выделенного текста работает через ВРЕМЕННУЮ замену содержимого
буфера обмена, поэтому чужие данные обязаны переживать захват без потерь.
pyperclip умеет только текст (CF_UNICODETEXT) — картинки, списки файлов,
RTF/HTML и прочие форматы он бы молча уничтожил. Этот модуль через Win32
API (ctypes, БЕЗ внешних зависимостей) сохраняет ВСЕ форматы буфера и
точно восстанавливает их:

  • форматы, хранящиеся в HGLOBAL (CF_UNICODETEXT/CF_TEXT/CF_OEMTEXT,
    CF_LOCALE, CF_DIB, CF_DIBV5, CF_HDROP и зарегистрированные — «HTML
    Format», «Rich Text Format», PNG…) — копируются побайтно;
  • CF_BITMAP — копируется через GDI (совместимые DC + BitBlt);
  • CF_PALETTE — копируется через GetPaletteEntries/CreatePalette;
  • CF_ENHMETAFILE — CopyEnhMetaFile; CF_METAFILEPICT — CopyMetaFile
    внутри пересобранной структуры METAFILEPICT;
  • CF_OWNERDISPLAY и CF_DSP* — «владельческие» форматы, которые чужому
    процессу скопировать безопасно НЕЛЬЗЯ. Если такой формат присутствует,
    снимок не делается: захват обязан отказаться, не тронув буфер
    (безопасный отказ вместо потери пользовательских данных).

Для контроля «не скопировал ли кто-то новое поверх» используется счётчик
изменений буфера Windows (GetClipboardSequenceNumber): он растёт на КАЖДУЮ
запись в буфер, чем бы она ни была вызвана.

На не-Windows системах (разработка) модуль вырождается в текстовый снимок
через pyperclip.
"""

from __future__ import annotations

import ctypes
import sys
import time
from ctypes import wintypes
from typing import List, Optional, Tuple

import pyperclip

_IS_WINDOWS = sys.platform == "win32"

# --- Стандартные форматы буфера -----------------------------------------------
CF_TEXT = 1
CF_BITMAP = 2
CF_METAFILEPICT = 3
CF_OEMTEXT = 7
CF_DIB = 8
CF_PALETTE = 9
CF_UNICODETEXT = 13
CF_ENHMETAFILE = 14
CF_HDROP = 15
CF_LOCALE = 16
CF_DIBV5 = 17
CF_OWNERDISPLAY = 0x0080
CF_DSPTEXT = 0x0081
CF_DSPBITMAP = 0x0082
CF_DSPMETAFILEPICT = 0x0083
CF_DSPENHMETAFILE = 0x008E

GMEM_MOVEABLE = 0x0002
SRCCOPY = 0x00CC0020

_KNOWN_FORMAT_NAMES = {
    CF_TEXT: "CF_TEXT", CF_BITMAP: "CF_BITMAP", CF_METAFILEPICT: "CF_METAFILEPICT",
    CF_OEMTEXT: "CF_OEMTEXT", CF_DIB: "CF_DIB", CF_PALETTE: "CF_PALETTE",
    CF_UNICODETEXT: "CF_UNICODETEXT", CF_ENHMETAFILE: "CF_ENHMETAFILE",
    CF_HDROP: "CF_HDROP", CF_LOCALE: "CF_LOCALE", CF_DIBV5: "CF_DIBV5",
    CF_OWNERDISPLAY: "CF_OWNERDISPLAY", CF_DSPTEXT: "CF_DSPTEXT",
    CF_DSPBITMAP: "CF_DSPBITMAP", CF_DSPMETAFILEPICT: "CF_DSPMETAFILEPICT",
    CF_DSPENHMETAFILE: "CF_DSPENHMETAFILE",
}

# Форматы, которые чужой процесс скопировать безопасно не может: владелец
# окна сам рисует их содержимое (owner-display) — скопированная копия
# была бы «мёртвой» и при возврате подменила бы живые данные мусором.
_UNSUPPORTED_FORMATS = {
    CF_OWNERDISPLAY, CF_DSPTEXT, CF_DSPBITMAP,
    CF_DSPMETAFILEPICT, CF_DSPENHMETAFILE,
}


class ClipboardBackupError(Exception):
    """Безопасный отказ: буфер нельзя тронуть (причина — в тексте ошибки)."""


if _IS_WINDOWS:
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

    # --- объявления: argtypes/restype ОБЯЗАТЕЛЬНЫ для 64-битных хендлов ---
    _user32.OpenClipboard.argtypes = [wintypes.HWND]
    _user32.OpenClipboard.restype = wintypes.BOOL
    _user32.CloseClipboard.argtypes = []
    _user32.CloseClipboard.restype = wintypes.BOOL
    _user32.EmptyClipboard.argtypes = []
    _user32.EmptyClipboard.restype = wintypes.BOOL
    _user32.EnumClipboardFormats.argtypes = [wintypes.UINT]
    _user32.EnumClipboardFormats.restype = wintypes.UINT
    _user32.GetClipboardData.argtypes = [wintypes.UINT]
    _user32.GetClipboardData.restype = wintypes.HANDLE
    _user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    _user32.SetClipboardData.restype = wintypes.HANDLE
    _user32.GetClipboardSequenceNumber.argtypes = []
    _user32.GetClipboardSequenceNumber.restype = wintypes.DWORD
    _user32.GetClipboardFormatNameW.argtypes = [wintypes.UINT, wintypes.LPWSTR, ctypes.c_int]
    _user32.GetClipboardFormatNameW.restype = ctypes.c_int
    _user32.GetDC.argtypes = [wintypes.HWND]
    _user32.GetDC.restype = wintypes.HDC
    _user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    _user32.ReleaseDC.restype = ctypes.c_int

    _kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    _kernel32.GlobalLock.restype = wintypes.LPVOID
    _kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    _kernel32.GlobalUnlock.restype = wintypes.BOOL
    _kernel32.GlobalSize.argtypes = [wintypes.HGLOBAL]
    _kernel32.GlobalSize.restype = ctypes.c_size_t
    _kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    _kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    _kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
    _kernel32.GlobalFree.restype = wintypes.HGLOBAL

    _gdi32.GetObjectW.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID]
    _gdi32.GetObjectW.restype = ctypes.c_int
    _gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    _gdi32.CreateCompatibleDC.restype = wintypes.HDC
    _gdi32.DeleteDC.argtypes = [wintypes.HDC]
    _gdi32.DeleteDC.restype = wintypes.BOOL
    _gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    _gdi32.SelectObject.restype = wintypes.HGDIOBJ
    _gdi32.BitBlt.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int,
                              ctypes.c_int, ctypes.c_int, wintypes.HDC,
                              ctypes.c_int, ctypes.c_int, wintypes.DWORD]
    _gdi32.BitBlt.restype = wintypes.BOOL
    _gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    _gdi32.DeleteObject.restype = wintypes.BOOL
    _gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    _gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    _gdi32.CopyMetaFileW.argtypes = [wintypes.HANDLE, wintypes.LPCWSTR]
    _gdi32.CopyMetaFileW.restype = wintypes.HANDLE
    _gdi32.DeleteMetaFile.argtypes = [wintypes.HANDLE]
    _gdi32.DeleteMetaFile.restype = wintypes.BOOL
    _gdi32.CopyEnhMetaFileW.argtypes = [wintypes.HANDLE, wintypes.LPCWSTR]
    _gdi32.CopyEnhMetaFileW.restype = wintypes.HANDLE
    _gdi32.DeleteEnhMetaFile.argtypes = [wintypes.HANDLE]
    _gdi32.DeleteEnhMetaFile.restype = wintypes.BOOL
    _gdi32.GetPaletteEntries.argtypes = [wintypes.HANDLE, wintypes.UINT,
                                         wintypes.UINT, wintypes.LPVOID]
    _gdi32.GetPaletteEntries.restype = wintypes.UINT
    _gdi32.CreatePalette.argtypes = [wintypes.LPVOID]
    _gdi32.CreatePalette.restype = wintypes.HANDLE

    class _BITMAP(ctypes.Structure):
        _fields_ = [("bmType", wintypes.LONG), ("bmWidth", wintypes.LONG),
                    ("bmHeight", wintypes.LONG), ("bmWidthBytes", wintypes.LONG),
                    ("bmPlanes", wintypes.WORD), ("bmBitsPixel", wintypes.WORD),
                    ("bmBits", wintypes.LPVOID)]

    class _METAFILEPICT(ctypes.Structure):
        _fields_ = [("mm", wintypes.LONG), ("xExt", wintypes.LONG),
                    ("yExt", wintypes.LONG), ("hMF", wintypes.HANDLE)]

    class _PALETTEENTRY(ctypes.Structure):
        _fields_ = [("peRed", ctypes.c_ubyte), ("peGreen", ctypes.c_ubyte),
                    ("peBlue", ctypes.c_ubyte), ("peFlags", ctypes.c_ubyte)]

    class _LOGPALETTE(ctypes.Structure):
        _fields_ = [("palVersion", ctypes.c_uint16),
                    ("palNumEntries", ctypes.c_uint16),
                    ("palPalEntry", _PALETTEENTRY * 256)]


def _open_clipboard(attempts: int = 12, delay: float = 0.01) -> bool:
    """Открывает буфер с короткими повторами (другой процесс мог держать его)."""
    if not _IS_WINDOWS:
        return False
    for _ in range(attempts):
        if _user32.OpenClipboard(None):
            return True
        time.sleep(delay)
    return False


def get_sequence_number() -> int:
    """Счётчик изменений буфера Windows (0 — недоступно / не-Windows)."""
    if not _IS_WINDOWS:
        return 0
    try:
        return int(_user32.GetClipboardSequenceNumber())
    except Exception:
        return 0


def _format_name(fmt: int) -> str:
    known = _KNOWN_FORMAT_NAMES.get(fmt)
    if known:
        return known
    try:
        buf = ctypes.create_unicode_buffer(128)
        if _user32.GetClipboardFormatNameW(fmt, buf, 128):
            return buf.value
    except Exception:
        pass
    return f"format#{fmt}"


def _enum_formats() -> List[int]:
    """Все форматы, находящиеся в буфере прямо сейчас (буфер должен быть открыт)."""
    formats: List[int] = []
    fmt = 0
    while True:
        fmt = _user32.EnumClipboardFormats(fmt)
        if not fmt:
            break
        formats.append(fmt)
    return formats


def _copy_hglobal(handle: int) -> bytes:
    """Побайтовое копирование формата, хранящегося в HGLOBAL."""
    size = int(_kernel32.GlobalSize(handle))
    if size == 0:
        return b""  # «пустой» формат — нормальная ситуация
    ptr = _kernel32.GlobalLock(handle)
    if not ptr:
        raise ClipboardBackupError("не удалось прочитать данные формата (GlobalLock)")
    try:
        return ctypes.string_at(ptr, size)
    finally:
        _kernel32.GlobalUnlock(handle)


def _copy_bitmap(handle: int) -> int:
    """Копия CF_BITMAP через GDI: совместимые DC + BitBlt (память не шарим!).

    HBITMAP из буфера принадлежит его владельцу — рисуем его содержимое в
    СВОЙ совместимый битмап и отдаём копию. Оригинал остаётся нетронутым.
    """
    bm = _BITMAP()
    if not _gdi32.GetObjectW(handle, ctypes.sizeof(_BITMAP), ctypes.byref(bm)):
        raise ClipboardBackupError("не удалось получить размеры CF_BITMAP")
    if bm.bmWidth <= 0 or bm.bmHeight <= 0:
        raise ClipboardBackupError("у CF_BITMAP некорректные размеры")
    hdc_screen = _user32.GetDC(None)
    if not hdc_screen:
        raise ClipboardBackupError("не удалось получить экранный DC")
    error = ""
    hbm_copy = 0
    hdc_src = hdc_dst = 0
    try:
        hdc_src = _gdi32.CreateCompatibleDC(hdc_screen)
        hdc_dst = _gdi32.CreateCompatibleDC(hdc_screen)
        hbm_copy = _gdi32.CreateCompatibleBitmap(hdc_screen, bm.bmWidth, bm.bmHeight)
        if not hdc_src or not hdc_dst or not hbm_copy:
            error = "не удалось создать совместимый DC/битмап для CF_BITMAP"
        else:
            old_src = _gdi32.SelectObject(hdc_src, handle)
            old_dst = _gdi32.SelectObject(hdc_dst, hbm_copy)
            try:
                if not _gdi32.BitBlt(hdc_dst, 0, 0, bm.bmWidth, bm.bmHeight,
                                     hdc_src, 0, 0, SRCCOPY):
                    error = "не удалось скопировать CF_BITMAP (BitBlt)"
            finally:
                if old_src:
                    _gdi32.SelectObject(hdc_src, old_src)
                if old_dst:
                    _gdi32.SelectObject(hdc_dst, old_dst)
    finally:
        if hdc_src:
            _gdi32.DeleteDC(hdc_src)
        if hdc_dst:
            _gdi32.DeleteDC(hdc_dst)
        if hdc_screen:
            _user32.ReleaseDC(None, hdc_screen)
    if error:
        if hbm_copy:
            _gdi32.DeleteObject(hbm_copy)
        raise ClipboardBackupError(error)
    return int(hbm_copy)


def _copy_palette(handle: int) -> int:
    """Копия CF_PALETTE через GetPaletteEntries → CreatePalette."""
    lp = _LOGPALETTE()
    lp.palVersion = 0x0300
    try:
        lp.palNumEntries = min(int(_gdi32.GetPaletteEntries(handle, 0, 0, None)), 256)
    except Exception:
        lp.palNumEntries = 0
    if lp.palNumEntries:
        got = _gdi32.GetPaletteEntries(
            handle, 0, lp.palNumEntries, ctypes.byref(lp.palPalEntry)
        )
        if got != lp.palNumEntries:
            raise ClipboardBackupError("не удалось прочитать CF_PALETTE")
    copy = _gdi32.CreatePalette(ctypes.byref(lp))
    if not copy:
        raise ClipboardBackupError("не удалось создать копию CF_PALETTE")
    return int(copy)


def _copy_enhmetafile(handle: int) -> int:
    """Копия CF_ENHMETAFILE через CopyEnhMetaFile."""
    copy = _gdi32.CopyEnhMetaFileW(handle, None)
    if not copy:
        raise ClipboardBackupError("не удалось скопировать CF_ENHMETAFILE")
    return int(copy)


def _copy_metafilepict(handle: int) -> Tuple[int, int]:
    """Копия CF_METAFILEPICT: HGLOBAL со структурой METAFILEPICT внутри.

    Возвращаем (новый HGLOBAL, копия HMETAFILE): при неудачной установке
    вызывающий код обязан освободить оба, при успешной — всё уходит системе.
    """
    ptr = _kernel32.GlobalLock(handle)
    if not ptr:
        raise ClipboardBackupError("не удалось прочитать CF_METAFILEPICT")
    h_mf_copy = 0
    mm = x_ext = y_ext = 0
    try:
        pict = ctypes.cast(ptr, ctypes.POINTER(_METAFILEPICT)).contents
        mm, x_ext, y_ext = pict.mm, pict.xExt, pict.yExt
        h_mf = int(pict.hMF or 0)
        if not h_mf:
            raise ClipboardBackupError("CF_METAFILEPICT без метафайла внутри")
        h_mf_copy = int(_gdi32.CopyMetaFileW(h_mf, None))
    finally:
        _kernel32.GlobalUnlock(handle)
    if not h_mf_copy:
        raise ClipboardBackupError("не удалось скопировать метафайл CF_METAFILEPICT")
    h_global = _kernel32.GlobalAlloc(GMEM_MOVEABLE, ctypes.sizeof(_METAFILEPICT))
    if not h_global:
        _gdi32.DeleteMetaFile(h_mf_copy)
        raise ClipboardBackupError("не удалось выделить память под CF_METAFILEPICT")
    ptr2 = _kernel32.GlobalLock(h_global)
    if not ptr2:
        _kernel32.GlobalFree(h_global)
        _gdi32.DeleteMetaFile(h_mf_copy)
        raise ClipboardBackupError("GlobalLock для CF_METAFILEPICT не удался")
    try:
        pict2 = ctypes.cast(ptr2, ctypes.POINTER(_METAFILEPICT)).contents
        pict2.mm, pict2.xExt, pict2.yExt, pict2.hMF = mm, x_ext, y_ext, h_mf_copy
    finally:
        _kernel32.GlobalUnlock(h_global)
    return int(h_global), h_mf_copy


class _Entry:
    """Один сохранённый формат буфера."""

    __slots__ = ("fmt", "name", "kind", "payload")

    def __init__(self, fmt: int, name: str, kind: str, payload) -> None:
        self.fmt = fmt
        self.name = name
        self.kind = kind     # hglobal | bitmap | palette | enhmetafile | metafilepict
        self.payload = payload


class ClipboardSnapshot:
    """Снимок буфера обмена: все форматы + точное восстановление.

    Порядок работы захватчика:
      1. save_snapshot() — копирует всё содержимое (или отказывает);
      2. ... захват делает с буфером что нужно (чистит, кладёт текст) ...;
      3. mark_reference(expected_text) — фиксирует «контрольную точку»:
         счётчик изменений буфера и текст, который должен лежать в нём;
      4. can_safely_restore() — True, только если с контрольной точки
         буфер НЕ менялся (пользователь не успел скопировать своё);
      5. restore() — возвращает все форматы на место.
    """

    def __init__(self, entries: Optional[List[_Entry]] = None,
                 fallback_text: str = "") -> None:
        self._entries = entries or []
        self._fallback_text = fallback_text or ""   # для не-Windows (текст)
        self._ref_seq = 0
        self._ref_text: Optional[str] = None

    # ------------------------------------------------------------- информация
    def format_names(self) -> List[str]:
        """Имена сохранённых форматов (для диагностики)."""
        if not _IS_WINDOWS:
            return ["CF_UNICODETEXT"] if self._fallback_text else []
        return [entry.name for entry in self._entries]

    # ------------------------------------------------------- контрольная точка
    def mark_reference(self, expected_text: str) -> None:
        """Фиксирует контрольную точку сразу после чтения захваченного текста."""
        self._ref_seq = get_sequence_number()
        self._ref_text = expected_text or ""

    def can_safely_restore(self) -> bool:
        """True — буфер с контрольной точки никто не менял, можно возвращать.

        Двойная проверка: счётчик изменений Windows (ловит ЛЮБУЮ запись,
        включая невидимую для текста — например, новую картинку) и сверка
        текста (страховка для систем без счётчика).
        """
        now_seq = get_sequence_number()
        if now_seq and self._ref_seq and now_seq != self._ref_seq:
            return False  # кто-то писал в буфер после нашей контрольной точки
        try:
            current = pyperclip.paste() or ""
        except Exception:
            return False  # прочитать не удалось — не рискуем чужими данными
        return current == (self._ref_text or "")

    # ------------------------------------------------------------- восстановление
    def restore(self) -> bool:
        """Возвращает сохранённые форматы в буфер. True — все форматы встали."""
        if not _IS_WINDOWS:
            try:
                pyperclip.copy(self._fallback_text)
                return True
            except Exception:
                return False
        if not _open_clipboard():
            return False
        ok = True
        try:
            if not _user32.EmptyClipboard():
                ok = False
            for entry in self._entries:
                if not self._restore_entry(entry):
                    ok = False
            return ok
        finally:
            _user32.CloseClipboard()

    @staticmethod
    def _restore_entry(entry: "_Entry") -> bool:
        """Ставит один формат обратно. Ресурсы уходят системе при успехе."""
        if entry.kind == "hglobal":
            data = entry.payload
            h = _kernel32.GlobalAlloc(GMEM_MOVEABLE, max(len(data), 1))
            if not h:
                return False
            if data:
                ptr = _kernel32.GlobalLock(h)
                if not ptr:
                    _kernel32.GlobalFree(h)
                    return False
                try:
                    ctypes.memmove(ptr, data, len(data))
                finally:
                    _kernel32.GlobalUnlock(h)
            if not _user32.SetClipboardData(entry.fmt, h):
                _kernel32.GlobalFree(h)
                return False
            return True  # успешный SetClipboardData отдаёт память системе
        if entry.kind in ("bitmap", "palette"):
            if _user32.SetClipboardData(entry.fmt, entry.payload):
                return True
            _gdi32.DeleteObject(entry.payload)
            return False
        if entry.kind == "enhmetafile":
            if _user32.SetClipboardData(entry.fmt, entry.payload):
                return True
            _gdi32.DeleteEnhMetaFile(entry.payload)
            return False
        if entry.kind == "metafilepict":
            h_global, h_mf = entry.payload
            if _user32.SetClipboardData(entry.fmt, h_global):
                return True
            _kernel32.GlobalFree(h_global)
            _gdi32.DeleteMetaFile(h_mf)
            return False
        return False


def save_snapshot() -> ClipboardSnapshot:
    """Сохраняет ВСЕ форматы буфера. Отказ — только через ClipboardBackupError.

    Правила безопасности:
      • буфер открывается с короткими повторами; если открыть не удалось —
        отказ: трогать то, что не удалось прочитать, нельзя;
      • «владельческие» форматы (CF_OWNERDISPLAY и CF_DSP*) скопировать
        безопасно невозможно — отказ, буфер остаётся нетронутым;
      • если чтение любого формата провалилось (источник умер, отложенная
        отрисовка не сработала) — тоже отказ: частичный снимок означал
        бы потерю данных при восстановлении.
    """
    if not _IS_WINDOWS:
        try:
            text = pyperclip.paste() or ""
        except Exception:
            text = ""
        return ClipboardSnapshot(entries=[], fallback_text=text)
    if not _open_clipboard():
        raise ClipboardBackupError(
            "Буфер обмена занят другим приложением — захват отменён, "
            "содержимое буфера не тронуто."
        )
    try:
        entries: List[_Entry] = []
        for fmt in _enum_formats():
            name = _format_name(fmt)
            if fmt in _UNSUPPORTED_FORMATS:
                raise ClipboardBackupError(
                    f"В буфере есть данные формата {name}, которые приложение "
                    "не может временно сохранить. Захват отменён — "
                    "содержимое буфера не тронуто."
                )
            handle = _user32.GetClipboardData(fmt)
            if not handle:
                # Отложенная отрисовка не сработала (источник уже закрылся и т.п.)
                raise ClipboardBackupError(
                    f"Не удалось прочитать формат {name} — захват отменён, "
                    "содержимое буфера не тронуто."
                )
            if fmt == CF_BITMAP:
                entries.append(_Entry(fmt, name, "bitmap", _copy_bitmap(handle)))
            elif fmt == CF_PALETTE:
                entries.append(_Entry(fmt, name, "palette", _copy_palette(handle)))
            elif fmt == CF_ENHMETAFILE:
                entries.append(_Entry(fmt, name, "enhmetafile", _copy_enhmetafile(handle)))
            elif fmt == CF_METAFILEPICT:
                entries.append(
                    _Entry(fmt, name, "metafilepict", _copy_metafilepict(handle))
                )
            else:
                entries.append(_Entry(fmt, name, "hglobal", _copy_hglobal(handle)))
        return ClipboardSnapshot(entries=entries)
    finally:
        _user32.CloseClipboard()


def clear_clipboard() -> bool:
    """Очищает буфер (EmptyClipboard). False — буфер занят или недоступен."""
    if not _IS_WINDOWS:
        try:
            pyperclip.copy("")
            return True
        except Exception:
            return False
    if not _open_clipboard():
        return False
    try:
        return bool(_user32.EmptyClipboard())
    finally:
        _user32.CloseClipboard()
