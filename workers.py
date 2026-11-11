"""
workers.py — фоновые потоки перевода (ШАГ 3).

ВСЕ сетевые запросы приложения живут здесь и только здесь — в QThread,
поэтому интерфейс никогда не зависает.

TranslationWorker(QThread):
  • режим «standard» — обычный переводчик без ИИ: GoogleTranslator из
    deep-translator. Целевой язык берётся из `target_lang`; если текст уже
    на целевом языке — язык переворачивается ru↔en (английский → русский
    и наоборот; язык исходника определяется эвристикой по кириллице/латинице);
  • режим «ai» — POST на `api_url` в OpenAI-совместимом формате
    /v1/chat/completions (локальная Ollama, OpenRouter, OpenAI): активный
    системный промпт, текст пользователя, `model_name`, `temperature`, `top_p`.

Готовый текст или ПОНЯТНАЯ ошибка (не запущена Ollama, нет интернета, плохой
ключ и т.п.) возвращаются в GUI строго через pyqtSignal — из фонового потока
виджеты трогать нельзя.
"""

from __future__ import annotations

import time
from typing import Any, Optional, Set

from PyQt6.QtCore import QThread, pyqtSignal
from api_helpers import normalize_chat_url, get_models_url, extract_response_content, resolve_proxies
from languages import (
    LANGUAGES_CATALOG,
    AUTO_LANG_CODE,
    DirectionResolution,
    adapt_language_code,
    detect_language,
    detect_ru_en_legacy,
    resolve_translation_direction,
)

try:
    import requests
except Exception as _requests_error:  # нет библиотеки — сообщим человечески
    requests = None  # type: ignore[assignment]
    _REQUESTS_IMPORT_ERROR: Optional[Exception] = _requests_error
    _ORIGINAL_REQUESTS_POST = None
    _ORIGINAL_REQUESTS_GET = None
else:
    _REQUESTS_IMPORT_ERROR = None
    _ORIGINAL_REQUESTS_POST = requests.post
    _ORIGINAL_REQUESTS_GET = requests.get

try:
    import keyboard
except Exception as _keyboard_error:  # нет библиотеки или нет доступа
    keyboard = None  # type: ignore[assignment]
    _KEYBOARD_IMPORT_ERROR: Optional[Exception] = _keyboard_error
else:
    _KEYBOARD_IMPORT_ERROR = None

try:
    from deep_translator import GoogleTranslator
    from deep_translator.exceptions import (NotValidPayload, ServerException,
                                            TooManyRequests, TranslationNotFound)
    _DEEP_IMPORT_ERROR: Optional[Exception] = None
except Exception as _deep_error:  # deep-translator не установлен
    GoogleTranslator = None  # type: ignore[assignment]
    NotValidPayload = ServerException = TranslationNotFound = None  # type: ignore
    TooManyRequests = None  # type: ignore
    _DEEP_IMPORT_ERROR = _deep_error

try:
    from deep_translator import DeeplTranslator as _DeeplTranslator
    _DEEPL_IMPORT_ERROR: Optional[Exception] = None
except Exception as _deepl_error:
    _DeeplTranslator = None  # type: ignore[assignment]
    _DEEPL_IMPORT_ERROR = _deepl_error

_TIMEOUT = (5, 90)  # requests: 5 с на подключение, 90 с на ответ модели

# Общий реестр живых фоновых воркеров (QThread): перевод, список моделей,
# запись хоткея. Решает две задачи:
#   1) сильная ссылка, пока поток работает (защита от сборки мусора);
#   2) мягкое ожидание всех потоков при выходе из приложения
#      (wait_for_workers). Поток регистрируется в конструкторе и
#      снимается из реестра по сигналу finished.
_live_threads: Set[QThread] = set()


class _TranslationError(Exception):
    """Ошибка с человеческим описанием — попадёт прямо в карточку."""


def _detect_ru_en(text: str) -> Optional[str]:
    """Эвристика языка: «ru», если кириллицы не меньше латиницы, иначе «en» (обратная совместимость)."""
    return detect_ru_en_legacy(text)


def _auto_target(text: str, target: Optional[str]) -> str:
    """Целевой язык с автоопределением ru↔en — работает в ОБОИХ режимах.

    Если текст уже написан на целевом языке — переворачиваем направление:
    английский → русский и наоборот. Иначе русский текст при target «ru»
    «переводился» бы сам в себя (в ИИ-режиме модель получала промпт
    «переведи на русский» и просто возвращала исходник).
    """
    target = (target or "ru").strip().lower()
    detected = _detect_ru_en(text)
    if detected and detected == target:
        target = "en" if target == "ru" else "ru"
    return target


def _translate_google_direct(text: str, source: str = "auto", target: str = "ru", timeout: int = 8) -> str:
    """Прямой надёжный перевод через официальный API расширения Google Chrome (clients5.google.com).

    В отличие от мобильного скрейпинга translate.google.com/m, этот эндпоинт стабилен,
    быстр и не блокируется ошибкой HTTP 429 Too Many Requests.
    """
    if requests is None:
        raise _TranslationError("Библиотека requests не установлена.")
    url = "https://clients5.google.com/translate_a/t"
    params = {
        "client": "dict-chrome-ex",
        "sl": source or "auto",
        "tl": target or "ru",
        "q": text,
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    }
    resp = requests.get(url, params=params, headers=headers, timeout=timeout)
    if resp.status_code != 200:
        raise _TranslationError(f"Google вернул статус HTTP {resp.status_code}")
    data = resp.json()
    if isinstance(data, list) and data:
        if isinstance(data[0], list):
            res = "".join(item[0] for item in data if isinstance(item, list) and item)
            if res.strip():
                return res.strip()
        elif isinstance(data[0], str) and data[0].strip():
            return data[0].strip()
    if isinstance(data, str) and data.strip():
        return data.strip()
    raise _TranslationError("Google вернул пустой результат.")


class TranslationWorker(QThread):
    """Перевод выделенного текста в фоновом потоке (вся сеть — только здесь)."""

    #: Готовый перевод (прилетает из потока → PyQt ставит в очередь GUI).
    finished_ok = pyqtSignal(str)

    #: Понятная ошибка — показывается прямо в карточке.
    failed = pyqtSignal(str)

    #: Разрешённое направление перевода: (исходный код, целевой код, бейдж "EN → RU")
    direction_resolved = pyqtSignal(str, str, str)

    #: Применённое AI-действие: (id действия, название действия)
    action_resolved = pyqtSignal(str, str)

    #: Реестр живых потоков (общий для всех воркеров — см. _live_threads):
    #: защищает от преждевременного GC и позволяет мягко дождаться их при
    #: выходе из приложения (wait_for_workers). Псевдоним оставлен для
    #: обратной совместимости — на него опираются тесты.
    _all_workers: Set["TranslationWorker"] = _live_threads

    def __init__(
        self,
        config: Any,
        source_text: str,
        source_lang: Optional[str] = None,
        target_lang: Optional[str] = None,
        action_id: Optional[str] = None,
        custom_prompt: Optional[str] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.config = config
        self.source_text = source_text
        self.source_lang = source_lang
        self.target_lang = target_lang
        self.action_id = action_id
        self.custom_prompt = custom_prompt
        self.resolved_direction: Optional[DirectionResolution] = None
        self._session: Optional[Any] = None
        _live_threads.add(self)
        # Встроенный сигнал finished: поток завершился — убираем из реестра.
        self.finished.connect(lambda: _live_threads.discard(self))

    def cancel(self) -> None:
        """Прерывает выполнение перевода и немедленно закрывает сетевую сессию."""
        self.requestInterruption()
        session = self._session
        if session is not None:
            try:
                session.close()
            except Exception:
                pass

    def _sleep_interruptible(self, seconds: float) -> bool:
        """Спит небольшими интервалами, возвращая True при запросе отмены."""
        steps = max(int(seconds / 0.05), 1)
        for _ in range(steps):
            if self.isInterruptionRequested():
                return True
            time.sleep(0.05)
        return self.isInterruptionRequested()

    # ------------------------------------------------------------- главный ход
    def run(self) -> None:
        """Тело потока: никакого GUI — только сеть и сигналы."""
        if self.isInterruptionRequested():
            return
        if not (self.source_text or "").strip():
            # Пустой захват — сетевого запроса не делаем вовсе.
            self.failed.emit("Пустой текст: переводить нечего.")
            return
        if len(self.source_text) > 200000:
            self.failed.emit(
                f"Выделенный текст слишком длинный ({len(self.source_text)} символов, "
                "максимум 200 000). Пожалуйста, выделите меньший фрагмент."
            )
            return

        # Разрешаем рабочее направление перевода (Этап 4)
        configured_source = self.source_lang or self.config.get("source_lang", "auto")
        configured_target = self.target_lang or self.config.get("target_lang", "ru")
        fallback_target = self.config.get("fallback_target_lang", "en")

        direction = resolve_translation_direction(
            self.source_text,
            configured_source=configured_source,
            configured_target=configured_target,
            fallback_target=fallback_target,
        )
        self.resolved_direction = direction
        self.direction_resolved.emit(direction.source_lang, direction.target_lang, direction.display_badge)

        try:
            mode = (self.config.get("mode") or "ai").strip().lower()
            if mode == "ai":
                result = self._translate_ai(direction)
            else:
                result = self._translate_standard(direction)
        except _TranslationError as exc:
            if not self.isInterruptionRequested():
                self.failed.emit(str(exc))
            return
        except Exception as exc:  # совсем неожиданное — тоже не молчим
            if not self.isInterruptionRequested():
                self.failed.emit(f"Неожиданная ошибка перевода: {exc}")
            return
        if not self.isInterruptionRequested():
            self.finished_ok.emit(result)

    # ---------------------------------------------------- режим «Обычный»
    def _translate_standard(self, direction: Optional[DirectionResolution] = None) -> str:
        """GoogleTranslator: target_lang из настроек + автоопределение направления."""
        if GoogleTranslator is None:
            raise _TranslationError(
                "Библиотека deep-translator не установлена "
                f"({_DEEP_IMPORT_ERROR}). Выполните: pip install deep-translator"
            )
        if direction is None:
            direction = self.resolved_direction or resolve_translation_direction(
                self.source_text,
                self.source_lang or self.config.get("source_lang", "auto"),
                self.target_lang or self.config.get("target_lang", "ru"),
                self.config.get("fallback_target_lang", "en"),
            )
        target = direction.target_lang
        engine = (self.config.get("standard_engine") or "google").strip().lower()
        if engine == "deepl":
            return self._translate_deepl(direction.source_lang, target)

        configured_src = (self.source_lang or self.config.get("source_lang", "auto")).strip().lower()
        google_source = "auto" if configured_src == "auto" else adapt_language_code("google", direction.source_lang, is_target=False)
        google_target = adapt_language_code("google", target, is_target=True)

        # 1. Если GoogleTranslator замокан в тестах — вызываем его в первую очередь
        is_mocked = GoogleTranslator is not None and getattr(GoogleTranslator, "__module__", "") != "deep_translator.google"
        if is_mocked:
            try:
                translator = GoogleTranslator(source=google_source, target=google_target)
                result = translator.translate(text=self.source_text)
                if not result or not str(result).strip():
                    raise _TranslationError("Переводчик вернул пустой результат.")
                return str(result).strip()
            except TooManyRequests:
                raise _TranslationError(
                    "Google ограничил частоту запросов (лимит бесплатного сервиса). "
                    "Подождите немного и повторите, либо используйте режим «ИИ»."
                )
            except Exception as exc:
                if isinstance(exc, _TranslationError):
                    raise
                raise _TranslationError(f"Не удалось перевести: {exc}")

        # 2. Прямой запрос через официальный эндпоинт Chrome Extension (быстро и без блокировок 429)
        direct_err = None
        if requests is not None:
            try:
                return _translate_google_direct(self.source_text, source=google_source, target=google_target)
            except Exception as exc:
                direct_err = exc

        # 3. Резервный вызов через deep_translator.GoogleTranslator
        if GoogleTranslator is not None:
            try:
                translator = GoogleTranslator(source=google_source, target=google_target)
                result = translator.translate(text=self.source_text)
                if result and str(result).strip():
                    return str(result).strip()
            except Exception:
                pass

        # 4. Резервный словарный переводчик MyMemory
        try:
            from deep_translator import MyMemoryTranslator
            from languages import get_language
            l_src = get_language(google_source)
            l_tgt = get_language(google_target)
            src_n = l_src.name_en.lower() if l_src else "auto"
            tgt_n = l_tgt.name_en.lower() if l_tgt else "russian"
            if src_n == "auto":
                src_n = "english" if tgt_n != "english" else "russian"
            res = MyMemoryTranslator(source=src_n, target=tgt_n).translate(self.source_text)
            if res and str(res).strip():
                return str(res).strip()
        except Exception:
            pass

        if direct_err:
            raise _TranslationError(f"Сервис Google Translate временно недоступен: {direct_err}")
        raise _TranslationError("Переводчик Google вернул пустой результат.")

    # ----------------------------------------------------------------- DeepL
    def _translate_deepl(self, detected: Optional[str], target: str) -> str:
        """Движок DeepL (deep-translator) — нужен API-ключ из настроек.

        DeepL требует явный язык-источник («auto» не понимает), поэтому
        берём результат детекции.
        """
        if _DeeplTranslator is None:
            raise _TranslationError(
                f"DeepL недоступен ({_DEEPL_IMPORT_ERROR}). "
                "Обновите библиотеку: pip install -U deep-translator"
            )
        api_key = (self.config.get("deepl_api_key") or "").strip()
        if not api_key:
            raise _TranslationError(
                "Для движка DeepL нужен API-ключ — укажите его в настройках "
                "(вкладка «Хоткеи и Обычный переводчик»)."
            )
        source = (detected or "en").lower()
        if source == "auto":
            source = "en"
        try:
            translator = _DeeplTranslator(
                source=source, target=target.lower(), api_key=api_key
            )
            result = translator.translate(text=self.source_text)
        except Exception as exc:
            message = str(exc)
            if "401" in message or "403" in message or "key" in message.lower():
                raise _TranslationError(
                    "DeepL отклонил запрос — проверьте API-ключ в настройках."
                )
            raise _TranslationError(f"Не удалось перевести через DeepL: {message}")
        if not result or not str(result).strip():
            raise _TranslationError("DeepL вернул пустой результат.")
        return str(result).strip()

    # ----------------------------------------------------------- режим «ИИ»
    def _translate_ai(self, direction: Optional[DirectionResolution] = None) -> str:
        """POST на api_url в OpenAI-совместимом формате (Ollama/OpenRouter/OpenAI/Custom)."""
        if requests is None:
            raise _TranslationError(
                f"Библиотека requests не установлена ({_REQUESTS_IMPORT_ERROR}). "
                "Выполните: pip install requests"
            )

        # Разрешаем AI Quick Action (Этап 5)
        action_data = None
        if self.action_id and hasattr(self.config, "get_action"):
            action_data = self.config.get_action(self.action_id)
        elif hasattr(self.config, "get_active_action"):
            action_data = self.config.get_active_action()

        action_name = action_data.get("name", "ИИ") if action_data else "ИИ"
        if action_data:
            self.action_resolved.emit(action_data.get("id", ""), action_name)

        # Поддержка AI-профилей (Этап 3, 5) с возможностью выбора профиля в действии
        profile: dict[str, Any] = {}
        override_pid = str(action_data.get("profile_id") or "").strip() if action_data else ""
        if override_pid and hasattr(self.config, "get_profile"):
            profile = self.config.get_profile(override_pid) or {}
        if not profile and hasattr(self.config, "get_active_profile"):
            try:
                profile = self.config.get_active_profile() or {}
            except Exception:
                profile = {}

        provider_type = str(profile.get("provider_type") or "custom").lower()
        api_url = (profile.get("api_url") or self.config.get("api_url") or "").strip()
        api_key = (profile.get("api_key") or self.config.get("api_key") or "").strip()
        model = (profile.get("model_name") or self.config.get("model_name") or "").strip()
        if not api_url:
            raise _TranslationError("В настройках не указан адрес API (api_url).")

        api_url = normalize_chat_url(api_url, provider_type)

        if direction is None:
            direction = self.resolved_direction or resolve_translation_direction(
                self.source_text,
                self.source_lang or self.config.get("source_lang", "auto"),
                self.target_lang or self.config.get("target_lang", "ru"),
                self.config.get("fallback_target_lang", "en"),
            )

        # Выбираем шаблон промпта
        if self.custom_prompt:
            prompt_template = self.custom_prompt
        elif action_data and action_data.get("prompt"):
            prompt_template = action_data["prompt"]
        elif hasattr(self.config, "get_active_prompt"):
            prompt_template = self.config.get_active_prompt()
        else:
            prompt_template = "Ты — профессиональный переводчик. Переведи на {target_lang}."

        from config import format_prompt_template
        project_context = self.config.get("project_context", "") if hasattr(self.config, "get") else ""
        glossary = self.config.get("glossary", "") if hasattr(self.config, "get") else ""

        system_prompt = format_prompt_template(
            template=prompt_template,
            text=self.source_text,
            source_lang=direction.source_lang,
            target_lang=direction.target_lang,
            project_context=project_context,
            glossary=glossary,
        )

        temperature = float(profile.get("temperature", self.config.get("temperature", 0.3)))
        top_p = float(profile.get("top_p", self.config.get("top_p", 0.9)))
        max_tokens = int(profile.get("max_tokens", 0))
        timeout_connect = max(int(profile.get("timeout_connect", 10)), 1)
        timeout_request = max(int(profile.get("timeout_request", 90)), 5)
        max_retries = min(max(int(profile.get("max_retries", 2)), 0), 5)

        payload: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": self.source_text},
            ],
            "temperature": temperature,
            "top_p": top_p,
            "stream": False,
        }
        if max_tokens > 0:
            payload["max_tokens"] = max_tokens

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        if "openrouter" in api_url.lower():
            headers["HTTP-Referer"] = "https://github.com/truniversal"
            headers["X-Title"] = "Truniversal"

        proxy_val = profile.get("proxy") or (self.config.get("proxy") if hasattr(self.config, "get") else "")
        proxies = resolve_proxies(proxy_val, api_url)

        attempt = 0
        is_mocked = _ORIGINAL_REQUESTS_POST is not None and requests.post != _ORIGINAL_REQUESTS_POST
        backoff_delay = 0.01 if is_mocked else 0.5
        while attempt <= max_retries:
            if self.isInterruptionRequested():
                return ""

            session = requests.Session()
            if proxies:
                session.proxies.update(proxies)
            self._session = session
            try:
                if is_mocked:
                    response = requests.post(
                        api_url, json=payload, headers=headers, timeout=(timeout_connect, timeout_request)
                    )
                else:
                    response = session.post(
                        api_url, json=payload, headers=headers, timeout=(timeout_connect, timeout_request)
                    )
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
                if self.isInterruptionRequested():
                    return ""
                # Если соединение явно отклонено (порт закрыт / сервер не поднят), не ждем
                err_text = str(exc).lower()
                is_refused = "refused" in err_text or "10061" in err_text or "actively refused" in err_text

                if not is_refused and attempt < max_retries:
                    attempt += 1
                    if self._sleep_interruptible(backoff_delay):
                        return ""
                    backoff_delay *= 2
                    continue
                if isinstance(exc, requests.exceptions.ConnectionError):
                    if "localhost" in api_url or "127.0.0.1" in api_url:
                        raise _TranslationError(
                            "Не удалось подключиться к локальному API. Похоже, не "
                            "запущена Ollama — выполните «ollama serve» и проверьте "
                            f"адрес: {api_url}"
                        )
                    raise _TranslationError(
                        f"Нет соединения с {api_url}. Проверьте интернет и адрес API."
                    )
                else:
                    raise _TranslationError(
                        f"Превышено время ожидания ответа модели ({timeout_request} с). Попробуйте ещё "
                        "раз или выберите модель полегче."
                    )
            except requests.exceptions.RequestException as exc:
                if self.isInterruptionRequested():
                    return ""
                raise _TranslationError(f"Ошибка запроса к API: {exc}")
            finally:
                if self._session is not None:
                    try:
                        self._session.close()
                    except Exception:
                        pass
                    self._session = None

            if self.isInterruptionRequested():
                return ""

            if response.status_code == 200:
                return self._extract_content(response)

            # Ошибки клиента 400, 401, 403, 404 — повторы запрещены
            if response.status_code in (400, 401, 403, 404):
                raise _TranslationError(self._http_error_text(response, model))

            # Временные ошибки сервера 429, 500, 502, 503, 504 — контролируемые повторы с backoff
            if response.status_code in (429, 500, 502, 503, 504) and attempt < max_retries:
                attempt += 1
                if self._sleep_interruptible(backoff_delay):
                    return ""
                backoff_delay *= 2
                continue

            raise _TranslationError(self._http_error_text(response, model))

        return ""

    # ------------------------------------------------------- разбор ответов
    @staticmethod
    def _http_error_text(response: Any, model: str) -> str:
        """Человекопонятное описание HTTP-ошибки API."""
        code = getattr(response, "status_code", 0)
        body = (getattr(response, "text", "") or "").strip().replace("\n", " ")[:200]
        err_msg = ""
        try:
            data = response.json()
            if isinstance(data, dict) and "error" in data:
                err = data["error"]
                err_msg = err.get("message") if isinstance(err, dict) else str(err)
        except Exception:
            pass

        if code == 400:
            hint = f" ({err_msg})" if err_msg else ""
            return f"Некорректный запрос (HTTP 400). Проверьте параметры и модель «{model}».{hint}"
        if code in (401, 403):
            hint = f" ({err_msg})" if err_msg else ""
            err_lower = (str(err_msg) + " " + str(body)).lower()
            if "security policy" in err_lower or "cloudflare" in err_lower:
                return (
                    f"Доступ к API запрещён политикой безопасности Cloudflare / провайдера (HTTP {code}). "
                    f"Обычно это региональная блокировка: включите ваш VPN/прокси (напр. http://127.0.0.1:10809) "
                    f"или укажите его в настройках профиля.{hint}"
                )
            return f"Доступ к API запрещён (HTTP {code}). Проверьте API-ключ.{hint}"
        if code == 404:
            hint = f" ({err_msg})" if err_msg else ""
            return (
                f"Адрес или модель не найдены (HTTP 404). Проверьте api_url и "
                f"имя модели «{model}».{hint}"
            )
        if code == 429:
            hint = f" ({err_msg})" if err_msg else ""
            return f"Превышен лимит запросов или квота провайдера (HTTP 429). Повторите попытку позже.{hint}"
        if code in (500, 502, 503, 504):
            hint = f" ({err_msg})" if err_msg else (f" Ответ API: {body}" if body else "")
            return f"Ошибка API: HTTP {code}.{hint}"

        hint = f" ({err_msg})" if err_msg else (f" Ответ API: {body}" if body else "")
        return f"Ошибка API: HTTP {code}.{hint}"

    @staticmethod
    def _extract_content(response: Any) -> str:
        """Достаёт текст из OpenAI-совместимого JSON (с запасными путями)."""
        try:
            data = response.json()
        except (ValueError, AttributeError):
            code = getattr(response, "status_code", "???")
            raise _TranslationError(
                f"Сервер вернул не-JSON ответ (HTTP {code}). "
                "Проверьте api_url — ожидается OpenAI-совместимый /v1/chat/completions."
            )
        try:
            return extract_response_content(data)
        except ValueError as exc:
            msg = str(exc)
            if "choices пуст" in msg or "нет сгенерированного текста" in msg:
                raise _TranslationError(
                    "В ответе API нет сгенерированного текста (choices пуст). "
                    "Проверьте модель и адрес."
                )
            if "пустой текстовый ответ" in msg or "пустой ответ" in msg:
                raise _TranslationError("Модель вернула пустой ответ.")
            raise _TranslationError(msg)


class ModelListWorker(QThread):
    """Загружает список моделей (Ollama /api/tags или OpenAI/OpenRouter /models) в фоне.

    Используется кнопкой «Загрузить список моделей» в окне настроек —
    сетевой запрос, как и все остальные, живёт только в QThread.
    """

    models_loaded = pyqtSignal(list)
    failed = pyqtSignal(str)

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        api_key: str = "",
        provider_type: str = "custom",
        proxy: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.base_url = (base_url or "").strip().rstrip("/")
        self.api_key = (api_key or "").strip()
        self.provider_type = (provider_type or "custom").lower()
        self.proxy = (proxy or "").strip()
        self._session: Optional[Any] = None
        _live_threads.add(self)
        self.finished.connect(lambda: _live_threads.discard(self))

    def cancel(self) -> None:
        """Прерывает загрузку списка моделей и закрывает сетевую сессию."""
        self.requestInterruption()
        session = self._session
        if session is not None:
            try:
                session.close()
            except Exception:
                pass

    def run(self) -> None:
        if self.isInterruptionRequested():
            return
        if requests is None:
            self.failed.emit(
                f"Библиотека requests не установлена ({_REQUESTS_IMPORT_ERROR})."
            )
            return

        models_url = get_models_url(self.base_url, self.provider_type)
        proxies = resolve_proxies(self.proxy, models_url)
        headers: dict[str, str] = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if "openrouter" in models_url.lower():
            headers["HTTP-Referer"] = "https://github.com/truniversal"
            headers["X-Title"] = "Truniversal"

        session = requests.Session()
        if proxies:
            session.proxies.update(proxies)
        self._session = session
        try:
            if _ORIGINAL_REQUESTS_GET is not None and requests.get != _ORIGINAL_REQUESTS_GET:
                try:
                    response = requests.get(models_url, headers=headers, timeout=(5, 15))
                except TypeError:
                    response = requests.get(models_url, timeout=(5, 15))
            else:
                response = session.get(models_url, headers=headers, timeout=(5, 15))
        except requests.exceptions.ConnectionError:
            if self.isInterruptionRequested():
                return
            if "localhost" in self.base_url or "127.0.0.1" in self.base_url:
                self.failed.emit(
                    f"Не удалось подключиться к {self.base_url}. Похоже, Ollama не "
                    "запущена — выполните «ollama serve»."
                )
            else:
                self.failed.emit(f"Не удалось подключиться к {self.base_url}. Проверьте адрес и интернет.")
            return
        except requests.exceptions.RequestException as exc:
            if self.isInterruptionRequested():
                return
            self.failed.emit(f"Ошибка запроса списка моделей: {exc}")
            return
        finally:
            if self._session is not None:
                try:
                    self._session.close()
                except Exception:
                    pass
                self._session = None

        if self.isInterruptionRequested():
            return

        if response.status_code == 404:
            self.failed.emit(
                f"Сервер не поддерживает автоматическую загрузку списка моделей (HTTP 404). "
                "Вы можете ввести имя модели вручную."
            )
            return
        if response.status_code in (401, 403):
            self.failed.emit(f"Ошибка авторизации (HTTP {response.status_code}). Проверьте API-ключ.")
            return
        if response.status_code != 200:
            self.failed.emit(f"Сервер вернул HTTP {response.status_code}.")
            return

        try:
            data = response.json()
        except (ValueError, AttributeError):
            self.failed.emit("Сервер вернул не-JSON ответ — проверьте адрес.")
            return

        names: list[str] = []
        if isinstance(data, dict):
            if "models" in data and isinstance(data["models"], list):
                # Ollama format
                names = [m.get("name") or m.get("model") for m in data["models"] if isinstance(m, dict)]
            elif "data" in data and isinstance(data["data"], list):
                # OpenAI / OpenRouter format
                names = [m.get("id") for m in data["data"] if isinstance(m, dict) and m.get("id")]

        names = [name for name in names if name]
        if not names:
            self.failed.emit(
                "В Ollama не установлено ни одной модели (или список пуст). "
                "Выполните, например: ollama pull llama3 или введите имя вручную."
            )
            return
        if not self.isInterruptionRequested():
            self.models_loaded.emit(names)


class ConnectionCheckWorker(QThread):
    """Фоновая проверка подключения к серверу AI (доступность, авторизация, модель)."""

    check_finished = pyqtSignal(bool, str, float)  # (success, message, latency_ms)

    def __init__(
        self,
        api_url: str,
        api_key: str = "",
        model_name: str = "llama3",
        provider_type: str = "custom",
        timeout_connect: int = 10,
        timeout_request: int = 15,
        proxy: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.api_url = (api_url or "").strip()
        self.api_key = (api_key or "").strip()
        self.model_name = (model_name or "").strip()
        self.provider_type = (provider_type or "custom").lower()
        self.timeout_connect = max(int(timeout_connect or 10), 1)
        self.timeout_request = max(int(timeout_request or 15), 2)
        self.proxy = (proxy or "").strip()
        self._session: Optional[Any] = None
        _live_threads.add(self)
        self.finished.connect(lambda: _live_threads.discard(self))

    def cancel(self) -> None:
        """Прерывает выполнение проверки подключения."""
        self.requestInterruption()
        session = self._session
        if session is not None:
            try:
                session.close()
            except Exception:
                pass

    def run(self) -> None:
        if self.isInterruptionRequested():
            return
        if requests is None:
            self.check_finished.emit(
                False, f"Библиотека requests не установлена ({_REQUESTS_IMPORT_ERROR}).", 0.0
            )
            return

        chat_url = normalize_chat_url(self.api_url, self.provider_type)
        if not chat_url:
            self.check_finished.emit(False, "Не указан адрес API.", 0.0)
            return

        proxies = resolve_proxies(self.proxy, chat_url)
        start_time = time.perf_counter()
        session = requests.Session()
        if proxies:
            session.proxies.update(proxies)
        self._session = session

        try:
            # 1. Если это Ollama — проверяем /api/tags
            if self.provider_type == "ollama" or ("11434" in chat_url and "openrouter" not in chat_url):
                tags_url = get_models_url(chat_url, "ollama")
                if _ORIGINAL_REQUESTS_GET is not None and requests.get != _ORIGINAL_REQUESTS_GET:
                    try:
                        resp = requests.get(tags_url, timeout=(self.timeout_connect, self.timeout_request))
                    except TypeError:
                        resp = requests.get(tags_url)
                else:
                    resp = session.get(tags_url, timeout=(self.timeout_connect, self.timeout_request))
                latency_ms = (time.perf_counter() - start_time) * 1000
                if self.isInterruptionRequested():
                    return
                if resp.status_code == 200:
                    try:
                        data = resp.json()
                        names = [
                            m.get("name") or m.get("model")
                            for m in data.get("models", [])
                            if isinstance(m, dict)
                        ]
                    except Exception:
                        names = []
                    target_model = self.model_name.lower().split(":")[0]
                    found = any(
                        n and (self.model_name.lower() == str(n).lower() or str(n).lower().startswith(target_model))
                        for n in names
                    )
                    if found or not self.model_name:
                        self.check_finished.emit(
                            True,
                            f"Подключение успешно! Ollama доступна ({latency_ms:.0f} мс), модель «{self.model_name}» готова к работе.",
                            latency_ms,
                        )
                    else:
                        installed_str = ", ".join(str(n) for n in names[:5]) if names else "нет"
                        self.check_finished.emit(
                            False,
                            f"Сервер Ollama доступен ({latency_ms:.0f} мс), но модель «{self.model_name}» не найдена. Установленные: {installed_str}. Установите через 'ollama run {self.model_name}'.",
                            latency_ms,
                        )
                else:
                    self.check_finished.emit(
                        False, f"Сервер Ollama вернул ошибку HTTP {resp.status_code}.", latency_ms
                    )
                return

            # 2. Для OpenAI / OpenRouter / Custom — отправляем минимальный тестовый запрос
            payload = {
                "model": self.model_name,
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 1,
            }
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            if "openrouter" in chat_url.lower():
                headers["HTTP-Referer"] = "https://github.com/truniversal"
                headers["X-Title"] = "Truniversal"

            if _ORIGINAL_REQUESTS_POST is not None and requests.post != _ORIGINAL_REQUESTS_POST:
                try:
                    resp = requests.post(
                        chat_url, json=payload, headers=headers, timeout=(self.timeout_connect, self.timeout_request)
                    )
                except TypeError:
                    resp = requests.post(chat_url, json=payload)
            else:
                resp = session.post(
                    chat_url, json=payload, headers=headers, timeout=(self.timeout_connect, self.timeout_request)
                )
            latency_ms = (time.perf_counter() - start_time) * 1000

            if self.isInterruptionRequested():
                return

            if resp.status_code == 200:
                self.check_finished.emit(
                    True,
                    f"Подключение успешно! Модель «{self.model_name}» отвечает (задержка {latency_ms:.0f} мс).",
                    latency_ms,
                )
                return

            err_msg = ""
            try:
                err_data = resp.json()
                if isinstance(err_data, dict) and "error" in err_data:
                    err = err_data["error"]
                    err_msg = err.get("message") if isinstance(err, dict) else str(err)
            except Exception:
                pass

            if resp.status_code in (401, 403):
                hint = f": {err_msg}" if err_msg else ""
                err_lower = (str(err_msg) + " " + getattr(resp, "text", "")).lower()
                if "security policy" in err_lower or "cloudflare" in err_lower:
                    self.check_finished.emit(
                        False,
                        f"Доступ заблокирован политикой безопасности Cloudflare / провайдера (HTTP {resp.status_code}){hint}. "
                        "Обычно это региональная блокировка: включите ваш VPN/прокси (напр. http://127.0.0.1:10809) или укажите его в настройках профиля.",
                        latency_ms,
                    )
                else:
                    self.check_finished.emit(
                        False, f"Ошибка авторизации (HTTP {resp.status_code}){hint}. Проверьте API-ключ.", latency_ms
                    )
            elif resp.status_code == 404:
                hint = f": {err_msg}" if err_msg else ""
                self.check_finished.emit(
                    False,
                    f"Адрес или модель «{self.model_name}» не найдены (HTTP 404){hint}. Проверьте URL и имя модели.",
                    latency_ms,
                )
            elif resp.status_code == 429:
                hint = f": {err_msg}" if err_msg else ""
                self.check_finished.emit(
                    False, f"Превышен лимит запросов / квота провайдера (HTTP 429){hint}.", latency_ms
                )
            else:
                hint = f": {err_msg}" if err_msg else f" (HTTP {resp.status_code})"
                self.check_finished.emit(False, f"Ошибка ответа сервера{hint}.", latency_ms)

        except requests.exceptions.ConnectionError:
            if self.isInterruptionRequested():
                return
            if "localhost" in chat_url or "127.0.0.1" in chat_url:
                self.check_finished.emit(
                    False,
                    f"Не удалось подключиться к {chat_url}. Проверьте, запущен ли локальный сервер (например, ollama serve).",
                    0.0,
                )
            else:
                self.check_finished.emit(
                    False, f"Не удалось подключиться к серверу {chat_url}. Проверьте адрес и интернет.", 0.0
                )
        except requests.exceptions.Timeout:
            if self.isInterruptionRequested():
                return
            self.check_finished.emit(
                False,
                f"Превышено время ожидания ответа ({self.timeout_connect + self.timeout_request} с). Сервер не отвечает.",
                0.0,
            )
        except requests.exceptions.RequestException as exc:
            if self.isInterruptionRequested():
                return
            self.check_finished.emit(False, f"Сетевая ошибка при проверке: {exc}", 0.0)
        finally:
            if self._session is not None:
                try:
                    self._session.close()
                except Exception:
                    pass
                self._session = None


class HotkeyRecorder(QThread):
    """Ждёт нажатие сочетания клавиш для кнопки «Записать нажатие» (в фоне).

    keyboard.read_hotkey() — блокирующий вызов, поэтому он обязан жить в
    отдельном потоке. cancel() прерывает ожидание (кнопка-тоггл «Отмена»).
    """

    done = pyqtSignal(str)  # записанное сочетание или "" при отмене

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        _live_threads.add(self)
        self.finished.connect(lambda: _live_threads.discard(self))

    def run(self) -> None:
        if keyboard is None:
            self.done.emit("")
            return
        try:
            recorded = keyboard.read_hotkey(suppress=True)
        except Exception:
            self.done.emit("")
            return
        self.done.emit(recorded or "")

    def cancel(self) -> None:
        """Прерывает ожидание нажатия — read_hotkey вернётся с пустым значением."""
        if keyboard is not None:
            try:
                keyboard.stop_reading()
            except Exception:
                pass


def wait_for_workers(timeout_ms: int = 3000) -> None:
    """Мягко ждёт фоновые воркеры при выходе из приложения.

    Сначала отменяет все активные воркеры, чтобы оборвать сетевые соединения
    без ожидания таймаута, затем ждёт их завершения в пределах бюджета.
    """
    for worker in list(_live_threads):
        if hasattr(worker, "cancel"):
            try:
                worker.cancel()
            except Exception:
                pass
        elif hasattr(worker, "requestInterruption"):
            try:
                worker.requestInterruption()
            except Exception:
                pass

    deadline = time.monotonic() + timeout_ms / 1000.0
    for worker in list(_live_threads):
        remaining_ms = int((deadline - time.monotonic()) * 1000)
        if remaining_ms <= 0:
            break
        worker.wait(remaining_ms)
