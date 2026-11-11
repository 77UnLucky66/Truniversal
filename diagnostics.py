"""
diagnostics.py — безопасный диагностический журнал захвата (Этап 2).

Пишется ТОЛЬКО при включённой настройке «diagnostics» в config.json
(чекбокс в окне настроек). Файл: truniversal_diag.log рядом с программой.

ПРАВИЛО ПРИВАТНОСТИ: содержимое выделенного пользователем текста в журнал
НЕ записывается никогда — только технические факты: сработал ли хоткей,
какое окно было активно (процесс/заголовок), каким способом скопировано,
какие форматы буфера сохранены, восстановлен ли буфер, длины текстов.

Любая ошибка записи журнала молча игнорируется: диагностика не должна
ронять или тормозить захват.
"""

from __future__ import annotations

import time
from typing import Any

LOG_FILE_NAME = "truniversal_diag.log"
_MAX_LOG_BYTES = 5 * 1024 * 1024   # журнал не растёт бесконечно
_MAX_VALUE_LEN = 80                # длинные значения (заголовки окон) режем


def _log_path():
    from config import app_dir  # ленивый импорт — без циклов на старте
    return app_dir() / LOG_FILE_NAME


def is_enabled(config: Any) -> bool:
    """Диагностика включена? (ошибка чтения настройки = выключена)."""
    try:
        return bool(config.get("diagnostics"))
    except Exception:
        return False


def log_event(config: Any, event: str, **fields: Any) -> None:
    """Пишет строку события, если диагностика включена. Никогда не бросает."""
    if not is_enabled(config):
        return
    try:
        parts = []
        for key, value in fields.items():
            text = _clean(value)
            if len(text) > _MAX_VALUE_LEN:
                text = text[:_MAX_VALUE_LEN] + "…"
            if " " in text:
                parts.append(f'{key}="{text}"')
            else:
                parts.append(f"{key}={text}")
        _write(" ".join([_timestamp(), "[capture]", event] + parts))
    except Exception:
        pass


def log_exception(config: Any, where: str, exc: BaseException) -> None:
    """Пишет краткую информацию об исключении (без стека и без данных)."""
    if not is_enabled(config):
        return
    try:
        _write(
            f"{_timestamp()} [capture] exception"
            f' where={where} type={type(exc).__name__} msg="{_clean(exc)}"'
        )
    except Exception:
        pass


def _timestamp() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S") + f".{int(time.time() * 1000) % 1000:03d}"


def _clean(value: Any) -> str:
    return (
        str(value)
        .replace('"', "'")
        .replace("\n", " ")
        .replace("\r", " ")
        .strip()
    )


def _write(line: str) -> None:
    """Дописывает строку в журнал (пересоздаёт его при превышении лимита)."""
    path = _log_path()
    try:
        mode = "a"
        try:
            if path.exists() and path.stat().st_size > _MAX_LOG_BYTES:
                mode = "w"  # журнал дорос до лимита — начинаем заново
        except OSError:
            pass
        with open(path, mode, encoding="utf-8") as fh:
            fh.write(line.rstrip() + "\n")
    except Exception:
        pass  # диск недоступен — диагностика не обязана работать любой ценой
    try:
        print(line)  # консоль разработчика (в сборке stdout может отсутствовать)
    except Exception:
        pass
