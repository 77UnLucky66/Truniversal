"""
api_helpers.py — нормализация URL и совместимость с OpenAI-совместимыми API (ЭТАП 3).

Обрабатывает адреса различных провайдеров и прокси без необходимости правки кода:
  • полный URL: /v1/chat/completions
  • базовый URL с /v1 или /api/v1
  • хост/прокси: http://localhost:11434 -> http://localhost:11434/v1/chat/completions
  • защита от дублирования частей (/v1/v1, /chat/completions/chat/completions)
  • эндпоинты для загрузки списка моделей (/models, /api/tags)
  • извлечение контента из разнообразных форматов ответов.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse, urlunparse


DEFAULT_PROVIDER_URLS = {
    "ollama": "http://localhost:11434/v1/chat/completions",
    "openrouter": "https://openrouter.ai/api/v1/chat/completions",
    "openai": "https://api.openai.com/v1/chat/completions",
    "custom": "http://localhost:11434/v1/chat/completions",
}


def normalize_chat_url(url: str, provider_type: str = "custom") -> str:
    """Приводит произвольный URL к каноническому эндпоинту чат-комплишенов.

    Примеры:
      http://localhost:11434 -> http://localhost:11434/v1/chat/completions
      https://api.openai.com/v1 -> https://api.openai.com/v1/chat/completions
      https://openrouter.ai/api/v1 -> https://openrouter.ai/api/v1/chat/completions
      https://myproxy.com/prefix/v1/chat/completions -> сохраняется как есть
    """
    url = (url or "").strip()
    if not url:
        return DEFAULT_PROVIDER_URLS.get(provider_type, DEFAULT_PROVIDER_URLS["custom"])

    # Убираем концевые слэши
    url = url.rstrip("/")

    # Если уже полный эндпоинт chat/completions
    if url.endswith("/chat/completions"):
        return url

    # Если заканчивается на /v1 или /api/v1
    if url.endswith("/v1"):
        return f"{url}/chat/completions"

    # Если уже содержит /v1/chat/completions в середине (например, с query params)
    if "/v1/chat/completions" in url:
        return url

    # Проверяем структуру пути
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")

    if not path or path == "":
        new_path = "/v1/chat/completions"
    elif path.endswith("/v1"):
        new_path = f"{path}/chat/completions"
    else:
        # Путь пользовательского прокси или префикса
        new_path = f"{path}/v1/chat/completions"

    # Защита от случайного дублирования /v1/v1 или двойных слэшей
    new_path = re.sub(r"/+", "/", new_path)
    new_path = re.sub(r"(/v1)+", "/v1", new_path)
    new_path = re.sub(r"(/chat/completions)+", "/chat/completions", new_path)

    # Собираем обратно
    return urlunparse((
        parsed.scheme or "http",
        parsed.netloc or parsed.path,
        new_path if parsed.netloc else new_path,
        parsed.params,
        parsed.query,
        parsed.fragment,
    ))


def get_models_url(chat_url: str, provider_type: str = "custom") -> str:
    """Формирует URL для запроса списка моделей.

    Для Ollama: http://localhost:11434/api/tags
    Для OpenAI / OpenRouter / Custom: /v1/models
    """
    chat_url = normalize_chat_url(chat_url, provider_type)

    if provider_type == "ollama" or ("11434" in chat_url and "openrouter" not in chat_url):
        # Ollama эндпоинт тегов
        parsed = urlparse(chat_url)
        return f"{parsed.scheme}://{parsed.netloc}/api/tags"

    # Для OpenAI-совместимых: заменяем /chat/completions на /models
    if "/chat/completions" in chat_url:
        return chat_url.replace("/chat/completions", "/models")

    # Базовый fallback
    parsed = urlparse(chat_url)
    return f"{parsed.scheme}://{parsed.netloc}/v1/models"


def extract_response_content(data: Any) -> str:
    """Извлекает сгенерированный текст из ответа OpenAI-совместимого API.

    Поддерживает:
      • стандартный message.content (строка)
      • мультимодальный message.content (список частей [{"type":"text","text":"..."}])
      • choices[0].text (legacy / текстовые модели)
      • choices[0].delta.content (потоковый/прокси формат)
      • message.refusal (отказ модели)
    """
    if not isinstance(data, dict):
        raise ValueError("Сервер вернул ответ не в формате JSON-объекта.")

    # Проверяем блок ошибки от провайдера (OpenAI, OpenRouter, Groq и т.д.)
    if "error" in data:
        err = data["error"]
        msg = err.get("message") if isinstance(err, dict) else str(err)
        if msg:
            raise ValueError(f"Ответ провайдера: {msg}")

    choices = data.get("choices")
    if not choices or not isinstance(choices, list) or len(choices) == 0:
        raise ValueError("В ответе API нет сгенерированного текста (список choices пуст).")

    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        raise ValueError("Некорректная структура первого элемента choices.")

    # 1. message.content
    message = first_choice.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if content:
            if isinstance(content, str) and content.strip():
                return content.strip()
            if isinstance(content, list):
                # Список текстовых блоков
                parts = []
                for item in content:
                    if isinstance(item, dict) and "text" in item:
                        parts.append(str(item["text"]))
                    elif isinstance(item, str):
                        parts.append(item)
                joined = "".join(parts).strip()
                if joined:
                    return joined
        # Проверка refusal
        refusal = message.get("refusal")
        if refusal and isinstance(refusal, str) and refusal.strip():
            raise ValueError(f"Модель отказалась отвечать: {refusal.strip()}")

    # 2. choices[0].text
    text = first_choice.get("text")
    if text and isinstance(text, str) and text.strip():
        return text.strip()

    # 3. choices[0].delta.content
    delta = first_choice.get("delta")
    if isinstance(delta, dict):
        delta_content = delta.get("content")
        if delta_content and isinstance(delta_content, str) and delta_content.strip():
            return delta_content.strip()

    raise ValueError("Модель вернула пустой текстовый ответ.")


def resolve_proxies(proxy_str: Optional[str] = None, target_url: Optional[str] = None) -> Optional[Dict[str, str]]:
    """Определяет параметры прокси для сетевых запросов.

    1. Если указан явный прокси (в профиле или настройках) — использует его.
    2. Если в ОС установлены переменные HTTPS_PROXY/HTTP_PROXY/ALL_PROXY — оставляет None
       (requests автоматически использует переменные окружения).
    3. Если целевой URL — локальный (localhost/127.0.0.1) — прокси НЕ используется.
    4. Если целевой URL — облачный провайдер с региональными ограничениями Cloudflare
       (openrouter.ai, openai.com, anthropic.com) и прокси не задан — автоматически проверяет
       запущенные на машине стандартные локальные прокси (Xray/V2Ray 10809, Clash 7890 и т.д.).
    """
    if proxy_str and str(proxy_str).strip():
        p = str(proxy_str).strip()
        if not p.startswith(("http://", "https://", "socks5://", "socks5h://")):
            p = f"http://{p}"
        return {"http": p, "https": p}

    import os
    if os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY") or os.environ.get("ALL_PROXY"):
        return None

    if target_url and ("localhost" in target_url or "127.0.0.1" in target_url):
        return None

    # Авто-проверка запущенного локального VPN/прокси клиента (Xray, V2Ray, Clash, NekoBox)
    if target_url and any(domain in target_url.lower() for domain in ("openrouter.ai", "openai.com", "anthropic.com")):
        import socket
        for host, port in [("127.0.0.1", 10809), ("127.0.0.1", 7890), ("127.0.0.1", 10808), ("127.0.0.1", 2080)]:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(0.05)
                    if s.connect_ex((host, port)) == 0:
                        p = f"http://{host}:{port}"
                        return {"http": p, "https": p}
            except Exception:
                pass
    return None
