"""
credentials.py — безопасное хранение API-ключей в Windows Credential Manager (ЭТАП 3).

Для защиты конфиденциальных данных пользователя (ключи OpenAI, OpenRouter, DeepL и др.)
ключи сохраняются в защищенном системном хранилище Windows Credential Manager
(через библиотеку keyring). В открытом виде в config.json ключи не хранятся.

Принцип работы:
  • Сервис: "Truniversal"
  • Имена ключей: "profile_<profile_id>" для AI-профилей, "deepl_api_key" для DeepL.
  • Маскирование: ключи маскируются в интерфейсе (sk-...abcd) и никогда не пишутся в логи.
  • Отказоустойчивость: если Credential Manager недоступен (виртуальное/тестовое окружение),
    работает безопасный fallback с предупреждением в UI.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

SERVICE_NAME = "Truniversal"

try:
    import keyring
    import keyring.errors
    _KEYRING_AVAILABLE = True
except Exception:
    keyring = None  # type: ignore[assignment]
    _KEYRING_AVAILABLE = False

# Локальный fallback-кэш для сред, где Windows Credential Manager временно недоступен
_fallback_store: dict[str, str] = {}


def is_secure_storage_available() -> bool:
    """Проверяет, доступен ли Windows Credential Manager для чтения и записи."""
    if not _KEYRING_AVAILABLE or keyring is None:
        return False
    try:
        # Тестовая проверка записи/чтения проверочного ключа
        test_key = "__canary_test__"
        keyring.set_password(SERVICE_NAME, test_key, "1")
        val = keyring.get_password(SERVICE_NAME, test_key)
        keyring.delete_password(SERVICE_NAME, test_key)
        return val == "1"
    except Exception:
        return False


def save_credential(key_name: str, secret: str) -> bool:
    """Сохраняет секрет в Windows Credential Manager.

    Если secret пустой — удаляет ключ из хранилища.
    Возвращает True при успешном сохранении в Credential Manager.
    Если хранилище недоступно, сохраняет в fallback-кэш и возвращает False.
    """
    key_name = (key_name or "").strip()
    if not key_name:
        return False

    secret = (secret or "").strip()
    if not secret:
        return delete_credential(key_name)

    if _KEYRING_AVAILABLE and keyring is not None:
        try:
            keyring.set_password(SERVICE_NAME, key_name, secret)
            # Проверяем, что ключ действительно записался и читается обратно
            saved_val = keyring.get_password(SERVICE_NAME, key_name)
            if saved_val == secret:
                _fallback_store.pop(key_name, None)
                return True
        except Exception as exc:
            logger.warning("Не удалось сохранить ключ в Credential Manager: %s", exc)

    # Fallback: сохраняем в локальный сессионный кэш, чтобы пользователь не потерял ввод
    _fallback_store[key_name] = secret
    return False


def get_credential(key_name: str) -> str:
    """Считывает секрет из Windows Credential Manager (или из fallback-кэша)."""
    key_name = (key_name or "").strip()
    if not key_name:
        return ""

    if _KEYRING_AVAILABLE and keyring is not None:
        try:
            val = keyring.get_password(SERVICE_NAME, key_name)
            if val is not None:
                return str(val).strip()
        except Exception:
            pass

    return _fallback_store.get(key_name, "")


def delete_credential(key_name: str) -> bool:
    """Удаляет секрет из Windows Credential Manager и fallback-кэша."""
    key_name = (key_name or "").strip()
    if not key_name:
        return False

    _fallback_store.pop(key_name, None)
    if _KEYRING_AVAILABLE and keyring is not None:
        try:
            keyring.delete_password(SERVICE_NAME, key_name)
            return True
        except Exception:
            pass
    return True


def mask_key(secret: str) -> str:
    """Безопасная маска ключа для отображения в интерфейсе (sk-...abcd).

    Никогда не возвращает полный ключ.
    """
    secret = (secret or "").strip()
    if not secret:
        return ""
    if len(secret) <= 8:
        return "••••••••"
    prefix = secret[:3]
    suffix = secret[-4:]
    return f"{prefix}••••{suffix}"
