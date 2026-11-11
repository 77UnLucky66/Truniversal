"""
test_clipboard_backup.py — проверка полного снимка буфера обмена (Этап 2).

Запуск:  python test_clipboard_backup.py (только Windows)

Проверяются на НАСТОЯЩЕМ системном буфере: сохранение/восстановление текста,
зарегистрированных форматов («HTML Format»), CF_DIB, CF_HDROP, CF_BITMAP,
пустого буфера, рост счётчика изменений и защита от восстановления поверх
чужих свежих данных. Содержимое буфера пользователя после теста — «текст
после теста» (пишем тестовые данные напрямую).
"""

import ctypes
import struct
import sys

import pyperclip

import clipboard_backup as cb


def put_formats(items) -> None:
    """Очищает буфер и кладёт сырые HGLOBAL-данные: [(формат, bytes), ...]."""
    assert cb._user32.OpenClipboard(None), "буфер не открылся (put)"
    try:
        assert cb._user32.EmptyClipboard()
        for fmt, data in items:
            h = cb._kernel32.GlobalAlloc(cb.GMEM_MOVEABLE, max(len(data), 1))
            assert h, "GlobalAlloc не выделил память"
            ptr = cb._kernel32.GlobalLock(h)
            assert ptr, "GlobalLock не удался (put)"
            ctypes.memmove(ptr, data, len(data))
            cb._kernel32.GlobalUnlock(h)
            assert cb._user32.SetClipboardData(fmt, h), f"SetClipboardData({fmt})"
    finally:
        cb._user32.CloseClipboard()


def get_format(fmt) -> bytes:
    """Читает содержимое формата (пустые байты — формата нет)."""
    if not cb._user32.OpenClipboard(None):
        return b""
    try:
        handle = cb._user32.GetClipboardData(fmt)
        if not handle:
            return b""
        size = int(cb._kernel32.GlobalSize(handle))
        if not size:
            return b""
        ptr = cb._kernel32.GlobalLock(handle)
        try:
            return ctypes.string_at(ptr, size)
        finally:
            cb._kernel32.GlobalUnlock(handle)
    finally:
        cb._user32.CloseClipboard()


def is_available(fmt) -> bool:
    if not cb._user32.OpenClipboard(None):
        return False
    try:
        return bool(cb._user32.IsClipboardFormatAvailable(fmt))
    finally:
        cb._user32.CloseClipboard()


def wstr_bytes(text: str) -> bytes:
    """UTF-16 LE + завершающий ноль."""
    return text.encode("utf-16-le") + b"\x00\x00"


def run_tests() -> None:
    if sys.platform != "win32":
        print("Проверки буфера работают только на Windows — пропускаем")
        return

    # 1. Текст: снимок → подмена → восстановление.
    pyperclip.copy("СТАРЫЙ БУФЕР ПОЛЬЗОВАТЕЛЯ")
    snap = cb.save_snapshot()
    assert "CF_UNICODETEXT" in snap.format_names()
    pyperclip.copy("ВРЕМЕННЫЙ ЗАХВАТ")
    assert snap.restore()
    assert pyperclip.paste() == "СТАРЫЙ БУФЕР ПОЛЬЗОВАТЕЛЯ"
    print("[OK] 1. Текстовый снимок восстанавливается точно")

    # 2. Мультиформат: CF_UNICODETEXT + зарегистрированный «HTML Format».
    html_fmt = ctypes.windll.user32.RegisterClipboardFormatW("HTML Format")
    assert html_fmt, "не удалось зарегистрировать формат"
    html_bytes = b"<b>HTML Format Test</b>"
    put_formats([
        (cb.CF_UNICODETEXT, wstr_bytes("мультиформатный текст")),
        (html_fmt, html_bytes),
    ])
    snap = cb.save_snapshot()
    assert set(snap.format_names()) >= {"CF_UNICODETEXT", "HTML Format"}
    put_formats([(cb.CF_UNICODETEXT, wstr_bytes("чужое"))])
    assert snap.restore()
    assert pyperclip.paste() == "мультиформатный текст"
    assert get_format(html_fmt) == html_bytes
    print("[OK] 2. Мультиформатный снимок (текст + HTML Format) восстановлен")

    # 3. CF_DIB (растр в HGLOBAL) — побайтовое восстановление.
    dib = (
        struct.pack("<IiiHHIIiiII", 40, 2, 2, 1, 32, 0, 16, 0, 0, 0, 0)
        + bytes(range(16))
    )
    put_formats([(cb.CF_DIB, dib)])
    snap = cb.save_snapshot()
    put_formats([(cb.CF_UNICODETEXT, wstr_bytes("замена"))])
    assert snap.restore()
    assert is_available(cb.CF_DIB)
    assert get_format(cb.CF_DIB) == dib
    print("[OK] 3. CF_DIB переживает снимок/восстановление без потерь")

    # 4. CF_HDROP (список файлов) — побайтовое восстановление.
    drop = (
        struct.pack("<IIIii", 20, 0, 0, 0, 1)          # DROPFILES, fWide=1
        + wstr_bytes("C:\\test\\документ.txt")
        + b"\x00\x00"
    )
    put_formats([(cb.CF_HDROP, drop)])
    snap = cb.save_snapshot()
    put_formats([(cb.CF_UNICODETEXT, wstr_bytes("замена"))])
    assert snap.restore()
    assert get_format(cb.CF_HDROP) == drop
    print("[OK] 4. CF_HDROP (список файлов) восстановлен побайтово")

    # 5. CF_BITMAP (HBITMAP) — копия через GDI восстанавливается с теми же
    #    размерами.
    hdc = cb._user32.GetDC(None)
    assert hdc, "нет экранного DC"
    try:
        hbm = cb._gdi32.CreateCompatibleBitmap(hdc, 24, 12)
        assert hbm, "CreateCompatibleBitmap не удался"
    finally:
        cb._user32.ReleaseDC(None, hdc)
    assert cb._user32.OpenClipboard(None)
    try:
        assert cb._user32.EmptyClipboard()
        assert cb._user32.SetClipboardData(cb.CF_BITMAP, hbm)
    finally:
        cb._user32.CloseClipboard()
    snap = cb.save_snapshot()
    put_formats([(cb.CF_UNICODETEXT, wstr_bytes("текст поверх битмапа"))])
    assert snap.restore()
    assert is_available(cb.CF_BITMAP), "CF_BITMAP не восстановился"
    if cb._user32.OpenClipboard(None):
        try:
            handle = cb._user32.GetClipboardData(cb.CF_BITMAP)
            bm = cb._BITMAP()
            assert cb._gdi32.GetObjectW(handle, ctypes.sizeof(bm), ctypes.byref(bm))
            assert (bm.bmWidth, bm.bmHeight) == (24, 12), (bm.bmWidth, bm.bmHeight)
        finally:
            cb._user32.CloseClipboard()
    print("[OK] 5. CF_BITMAP восстановился копией с теми же размерами")

    # 6. Пустой буфер: снимок пуст, восстановление оставляет пустым.
    assert cb.clear_clipboard()
    snap = cb.save_snapshot()
    assert snap.format_names() == []
    pyperclip.copy("появилось после пустоты")
    assert snap.restore()
    assert pyperclip.paste() == ""
    print("[OK] 6. Пустой буфер: снимок и восстановление корректны")

    # 7. Счётчик изменений растёт на каждую запись.
    seq0 = cb.get_sequence_number()
    pyperclip.copy("изменение 1")
    seq1 = cb.get_sequence_number()
    pyperclip.copy("изменение 2")
    seq2 = cb.get_sequence_number()
    assert seq0 and seq1 > seq0 and seq2 > seq1, (seq0, seq1, seq2)
    print("[OK] 7. GetClipboardSequenceNumber растёт на каждую запись")

    # 8. can_safely_restore: чужое изменение после контрольной точки — отказ.
    pyperclip.copy("ИСХОДНЫЙ БУФЕР 8")
    snap = cb.save_snapshot()
    pyperclip.copy("наш временный текст")
    snap.mark_reference("наш временный текст")
    assert snap.can_safely_restore(), "без изменений восстановление должно быть можно"
    pyperclip.copy("пользователь скопировал своё")
    assert not snap.can_safely_restore(), "после внешней записи — только отказ"
    print("[OK] 8. Восстановление запрещено после внешней записи в буфер")

    # 9. clear_clipboard действительно очищает.
    pyperclip.copy("остаток")
    assert cb.clear_clipboard()
    assert pyperclip.paste() == ""
    print("[OK] 9. clear_clipboard очищает буфер")

    # 10. «Владельческие» форматы числятся неподдерживаемыми (безопасный отказ).
    assert cb.CF_OWNERDISPLAY in cb._UNSUPPORTED_FORMATS
    assert cb.CF_DSPBITMAP in cb._UNSUPPORTED_FORMATS
    print("[OK] 10. Owner-display форматы помечены как неподдерживаемые")

    pyperclip.copy("текст после теста")  # не оставляем мусор в буфере
    print("\nВсе проверки снимка буфера обмена пройдены")


if __name__ == "__main__":
    run_tests()
