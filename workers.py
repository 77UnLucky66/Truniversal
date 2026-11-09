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

try:
    import requests
except Exception as _requests_error:  # нет библиотеки — сообщим человечески
    requests = None  # type: ignore[assignment]
    _REQUESTS_IMPORT_ERROR: Optional[Exception] = _requests_error
else:
    _REQUESTS_IMPORT_ERROR = None

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


class _TranslationError(Exception):
    """Ошибка с человеческим описанием — попадёт прямо в карточку."""


def _detect_ru_en(text: str) -> Optional[str]:
    """Эвристика языка: «ru», если кириллицы не меньше латиницы, иначе «en»."""
    cyrillic = sum(1 for ch in text if "\u0400" <= ch <= "\u04ff")
    latin = sum(1 for ch in text if "a" <= ch <= "z" or "A" <= ch <= "Z")
    if not cyrillic and not latin:
        return None  # нет букв ни одного алфавита — язык не определён
    return "ru" if cyrillic >= latin else "en"


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


class TranslationWorker(QThread):
    """Перевод выделенного текста в фоновом потоке (вся сеть — только здесь)."""

    #: Готовый перевод (прилетает из потока → PyQt ставит в очередь GUI).
    finished_ok = pyqtSignal(str)

    #: Понятная ошибка — показывается прямо в карточке.
    failed = pyqtSignal(str)

    #: Реестр живых потоков: защищает от преждевременного GC и позволяет
    #: мягко дождаться их при выходе из приложения (wait_for_workers).
    _all_workers: Set["TranslationWorker"] = set()

    def __init__(self, config: Any, source_text: str, parent=None) -> None:
        super().__init__(parent)
        self.config = config
        self.source_text = source_text
        TranslationWorker._all_workers.add(self)
        # Встроенный сигнал finished: поток завершился — убираем из реестра.
        self.finished.connect(lambda: TranslationWorker._all_workers.discard(self))

    # ------------------------------------------------------------- главный ход
    def run(self) -> None:
        """Тело потока: никакого GUI — только сеть и сигналы."""
        try:
            mode = (self.config.get("mode") or "ai").strip().lower()
            if mode == "ai":
                result = self._translate_ai()
            else:
                result = self._translate_standard()
        except _TranslationError as exc:
            self.failed.emit(str(exc))
            return
        except Exception as exc:  # совсем неожиданное — тоже не молчим
            self.failed.emit(f"Неожиданная ошибка перевода: {exc}")
            return
        self.finished_ok.emit(result)

    # ---------------------------------------------------- режим «Обычный»
    def _translate_standard(self) -> str:
        """GoogleTranslator: target_lang из настроек + автоопределение ru↔en."""
        if GoogleTranslator is None:
            raise _TranslationError(
                "Библиотека deep-translator не установлена "
                f"({_DEEP_IMPORT_ERROR}). Выполните: pip install deep-translator"
            )
        detected = _detect_ru_en(self.source_text)
        target = _auto_target(self.source_text, self.config.get("target_lang"))
        engine = (self.config.get("standard_engine") or "google").strip().lower()
        if engine == "deepl":
            return self._translate_deepl(detected, target)
        try:
            translator = GoogleTranslator(source="auto", target=target)
            result = translator.translate(text=self.source_text)
        except NotValidPayload:
            raise _TranslationError(
                "Текст не подходит для обычного переводчика: пустой, слишком "
                "длинный (лимит Google ~5000 символов) или недопустимые символы."
            )
        except TranslationNotFound:
            raise _TranslationError("Переводчик Google вернул пустой результат.")
        except TooManyRequests:
            raise _TranslationError(
                "Google ограничил частоту запросов (лимит бесплатного сервиса). "
                "Подождите немного и повторите, либо используйте режим «ИИ»."
            )
        except ServerException as exc:
            raise _TranslationError(
                "Сервис Google Translate временно недоступен. "
                f"Проверьте интернет (детали: {exc})"
            )
        except Exception as exc:
            raise _TranslationError(f"Не удалось перевести: {exc}")
        if not result or not str(result).strip():
            raise _TranslationError("Переводчик вернул пустой результат.")
        return str(result).strip()

    # ----------------------------------------------------------------- DeepL
    def _translate_deepl(self, detected: Optional[str], target: str) -> str:
        """Движок DeepL (deep-translator) — нужен API-ключ из настроек.

        DeepL требует явный язык-источник («auto» не понимает), поэтому
        берём результат нашей эвристики — переворот ru↔en уже отработан.
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
        source = detected or "en"  # DeepL не умеет «auto» — даём язык эвристикой
        try:
            translator = _DeeplTranslator(
                source=source, target=target, api_key=api_key
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
    def _translate_ai(self) -> str:
        """POST на api_url в OpenAI-совместимом формате (Ollama/OpenRouter/OpenAI)."""
        if requests is None:
            raise _TranslationError(
                f"Библиотека requests не установлена ({_REQUESTS_IMPORT_ERROR}). "
                "Выполните: pip install requests"
            )
        api_url = (self.config.get("api_url") or "").strip()
        api_key = (self.config.get("api_key") or "").strip()
        model = (self.config.get("model_name") or "").strip()
        if not api_url:
            raise _TranslationError("В настройках не указан адрес API (api_url).")

        # Автоопределение ru↔en — как в режиме «Обычный»: если текст уже на
        # целевом языке, переворачиваем направление, иначе русский текст
        # «переводился» бы сам в себя.
        target = _auto_target(self.source_text, self.config.get("target_lang"))

        # {target_lang} в промпте подменяем ЦЕЛЕВЫМ языком (с учётом переворота).
        system_prompt = self.config.get_active_prompt().replace("{target_lang}", target)
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": self.source_text},
            ],
            "temperature": float(self.config.get("temperature", 0.3)),
            "top_p": float(self.config.get("top_p", 0.9)),
            "stream": False,
        }
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        try:
            response = requests.post(
                api_url, json=payload, headers=headers, timeout=_TIMEOUT
            )
        except requests.exceptions.ConnectionError:
            if "localhost" in api_url or "127.0.0.1" in api_url:
                raise _TranslationError(
                    "Не удалось подключиться к локальному API. Похоже, не "
                    "запущена Ollama — выполните «ollama serve» и проверьте "
                    f"адрес: {api_url}"
                )
            raise _TranslationError(
                f"Нет соединения с {api_url}. Проверьте интернет и адрес API."
            )
        except requests.exceptions.Timeout:
            raise _TranslationError(
                "Превышено время ожидания ответа модели (90 с). Попробуйте ещё "
                "раз или выберите модель полегче."
            )
        except requests.exceptions.RequestException as exc:
            raise _TranslationError(f"Ошибка запроса к API: {exc}")

        if response.status_code != 200:
            raise _TranslationError(self._http_error_text(response, model))
        return self._extract_content(response)

    # ------------------------------------------------------- разбор ответов
    @staticmethod
    def _http_error_text(response: Any, model: str) -> str:
        """Человекопонятное описание HTTP-ошибки API."""
        code = response.status_code
        body = (response.text or "").strip().replace("\n", " ")[:160]
        if code in (401, 403):
            return f"Доступ к API запрещён (HTTP {code}). Проверьте API-ключ."
        if code == 404:
            return (
                f"Адрес или модель не найдены (HTTP 404). Проверьте api_url и "
                f"имя модели «{model}»."
            )
        hint = f" Ответ API: {body}" if body else ""
        return f"Ошибка API: HTTP {code}.{hint}"

    @staticmethod
    def _extract_content(response: Any) -> str:
        """Достаёт текст из OpenAI-совместимого JSON (с запасными путями)."""
        try:
            data = response.json()
        except ValueError:
            raise _TranslationError(
                f"Сервер вернул не-JSON ответ (HTTP {response.status_code}). "
                "Проверьте api_url — ожидается OpenAI-совместимый /v1/chat/completions."
            )
        choices = data.get("choices") if isinstance(data, dict) else None
        if not choices:
            raise _TranslationError(
                "В ответе API нет сгенерированного текста (choices пуст). "
                "Проверьте модель и адрес."
            )
        message = choices[0].get("message") or {}
        content = message.get("content")
        if not content or not str(content).strip():
            content = choices[0].get("text")  # запасной формат совместимых API
        if not content or not str(content).strip():
            raise _TranslationError("Модель вернула пустой ответ.")
        return str(content).strip()


class ModelListWorker(QThread):
    """Загружает список установленных моделей Ollama (GET /api/tags) в фоне.

    Используется кнопкой «Загрузить список моделей» в окне настроек —
    сетевой запрос, как и все остальные, живёт только в QThread.
    """

    models_loaded = pyqtSignal(list)
    failed = pyqtSignal(str)

    def __init__(self, base_url: str = "http://localhost:11434", parent=None) -> None:
        super().__init__(parent)
        self.base_url = base_url.rstrip("/")

    def run(self) -> None:
        if requests is None:
            self.failed.emit(
                f"Библиотека requests не установлена ({_REQUESTS_IMPORT_ERROR})."
            )
            return
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=(5, 15))
        except requests.exceptions.ConnectionError:
            self.failed.emit(
                f"Не удалось подключиться к {self.base_url}. Похоже, Ollama не "
                "запущена — выполните «ollama serve»."
            )
            return
        except requests.exceptions.RequestException as exc:
            self.failed.emit(f"Ошибка запроса к Ollama: {exc}")
            return
        if response.status_code != 200:
            self.failed.emit(f"Ollama вернула HTTP {response.status_code}.")
            return
        try:
            data = response.json()
            names = [
                model.get("name") or model.get("model")
                for model in data.get("models", [])
            ]
        except (ValueError, AttributeError):
            self.failed.emit("Ollama вернула не-JSON ответ — проверьте адрес.")
            return
        names = [name for name in names if name]
        if not names:
            self.failed.emit(
                "В Ollama не установлено ни одной модели. "
                "Выполните, например: ollama pull llama3"
            )
            return
        self.models_loaded.emit(names)


class HotkeyRecorder(QThread):
    """Ждёт нажатие сочетания клавиш для кнопки «Записать нажатие» (в фоне).

    keyboard.read_hotkey() — блокирующий вызов, поэтому он обязан жить в
    отдельном потоке. cancel() прерывает ожидание (кнопка-тоггл «Отмена»).
    """

    done = pyqtSignal(str)  # записанное сочетание или "" при отмене

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
    """Мягко ждёт фоновые потоки перевода при выходе из приложения."""
    deadline = time.monotonic() + timeout_ms / 1000.0
    for worker in list(TranslationWorker._all_workers):
        remaining_ms = int((deadline - time.monotonic()) * 1000)
        if remaining_ms <= 0:
            break
        worker.wait(remaining_ms)
