"""
config.py — менеджер конфигурации приложения «Truniversal».

Все настройки хранятся в локальном файле `config.json` рядом со скриптом
(«портабельный» режим — приложение можно переносить папкой целиком).

Принципы работы:
  • При первом запуске файл создаётся с дефолтными значениями.
  • При каждом запуске значения перечитываются; отсутствующие ключи
    (например, появившиеся в будущих версиях) берутся из дефолтов.
  • Явно «битые» значения мягко исправляются — приложение не падает.
  • Если JSON повреждён, файл бэкапится в `config.json.bak`,
    а вместо него создаётся свежий конфиг с дефолтами.
  • Схема версионируется («config_version»): старые файлы автоматически
    мигрируются цепочкой шагов при загрузке (см. _apply_migrations).
  • save() не бросает исключений: ошибка диска возвращает False и пишется
    в лог — вызовы идут прямо из GUI-слотов PyQt, где исключение роняет
    всё приложение.

Промпты: {target_lang} — плейсхолдер, который при отправке запроса к ИИ
подменяется значением настройки `target_lang` (реализация — следующий шаг).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
import time
import uuid
from copy import deepcopy
from pathlib import Path
from api_helpers import normalize_chat_url
import credentials
from typing import Any, Dict, Optional

# Изолированное хранилище секретов для временных конфигураций (тесты, изолированные экземпляры)
_TEMP_CREDENTIALS: Dict[str, Dict[str, str]] = {}

# Имя файла конфигурации (лежит рядом с этим модулем).
CONFIG_FILE_NAME = "config.json"


def app_dir() -> Path:
    """Каталог приложения.

    В обычном запуске — папка с кодом; в сборке PyInstaller (--onefile) —
    папка с .exe: иначе config.json улетал бы во временный каталог
    распаковки и настройки терялись бы при каждом выходе.
    """
    if getattr(sys, "frozen", False):  # запущен собранный .exe
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent

# Допустимые значения ключевых полей (лёгкая валидация при загрузке).
VALID_MODES: tuple[str, ...] = ("ai", "standard")
VALID_STANDARD_ENGINES: tuple[str, ...] = ("google", "deepl")

# ---------------------------------------------------------------------------
# Версионирование схемы конфигурации + последовательные миграции (Этап 1).
#
# config.json живёт у пользователя и обновляется вместе с приложением.
# Чтобы старые файлы не терялись и не ломались:
#   • файл без ключа «config_version» — старая (деверсионная) схема = v0;
#   • при загрузке применяются миграции цепочкой 0→1→2→…→CONFIG_VERSION
#     (каждый новый шаг добавляйте отдельно, существующие шаги не меняйте);
#   • файл из БУДУЩЕЙ версии (даунгрейд приложения) не откатывается: merge
#     с дефолтами даёт новым ключам значения из кода, неизвестные ключи
#     сохраняются как есть.
# ---------------------------------------------------------------------------
CONFIG_VERSION = 2

# ---------------------------------------------------------------------------
# Предустановленные AI-профили (ЭТАП 3)
# ---------------------------------------------------------------------------
DEFAULT_AI_PROFILES: Dict[str, Dict[str, Any]] = {
    "ollama_default": {
        "id": "ollama_default",
        "name": "Локальная Ollama (Llama 3)",
        "provider_type": "ollama",
        "api_url": "http://localhost:11434/v1/chat/completions",
        "model_name": "llama3",
        "proxy": "",
        "temperature": 0.3,
        "top_p": 0.9,
        "max_tokens": 0,
        "timeout_connect": 5,
        "timeout_request": 90,
        "max_retries": 2,
    },
    "openrouter_default": {
        "id": "openrouter_default",
        "name": "OpenRouter (DeepSeek / Llama 3)",
        "provider_type": "openrouter",
        "api_url": "https://openrouter.ai/api/v1/chat/completions",
        "model_name": "deepseek/deepseek-chat",
        "proxy": "",
        "temperature": 0.3,
        "top_p": 0.9,
        "max_tokens": 0,
        "timeout_connect": 10,
        "timeout_request": 60,
        "max_retries": 2,
    },
    "openai_default": {
        "id": "openai_default",
        "name": "OpenAI (GPT-4o-mini)",
        "provider_type": "openai",
        "api_url": "https://api.openai.com/v1/chat/completions",
        "model_name": "gpt-4o-mini",
        "proxy": "",
        "temperature": 0.3,
        "top_p": 0.9,
        "max_tokens": 0,
        "timeout_connect": 10,
        "timeout_request": 60,
        "max_retries": 2,
    },
}


def _migrate_v1_to_v2(cfg: Dict[str, Any]) -> None:
    """Миграция v1 -> v2: перенос одиночных параметров ИИ в систему профилей."""
    profiles = deepcopy(DEFAULT_AI_PROFILES)
    old_url = cfg.get("api_url", "")
    old_key = cfg.get("api_key", "")
    old_model = cfg.get("model_name", "llama3")
    old_temp = cfg.get("temperature", 0.3)
    old_top_p = cfg.get("top_p", 0.9)

    active_id = "ollama_default"
    if "openrouter" in str(old_url).lower():
        active_id = "openrouter_default"
    elif "openai" in str(old_url).lower():
        active_id = "openai_default"
    elif old_url and "localhost" not in str(old_url) and "11434" not in str(old_url):
        active_id = "custom_migrated"
        profiles[active_id] = {
            "id": active_id,
            "name": "Пользовательский API",
            "provider_type": "custom",
            "api_url": str(old_url),
            "model_name": str(old_model),
            "temperature": float(old_temp),
            "top_p": float(old_top_p),
            "max_tokens": 0,
            "timeout_connect": 10,
            "timeout_request": 90,
            "max_retries": 2,
        }

    if active_id in profiles:
        if old_url:
            profiles[active_id]["api_url"] = str(old_url)
        if old_model:
            profiles[active_id]["model_name"] = str(old_model)
        profiles[active_id]["temperature"] = float(old_temp)
        profiles[active_id]["top_p"] = float(old_top_p)

    # Безопасная миграция ключа в Credential Manager (или изолированное тестовое хранилище)
    path_key = cfg.get("_temp_path_key")
    if old_key:
        if path_key:
            _TEMP_CREDENTIALS.setdefault(path_key, {})[f"profile_{active_id}"] = str(old_key)
            cfg["api_key"] = ""
        else:
            try:
                if credentials.save_credential(f"profile_{active_id}", str(old_key)):
                    cfg["api_key"] = ""
            except Exception:
                pass

    old_deepl_key = cfg.get("deepl_api_key", "")
    if old_deepl_key:
        if path_key:
            _TEMP_CREDENTIALS.setdefault(path_key, {})["deepl_api_key"] = str(old_deepl_key)
            cfg["deepl_api_key"] = ""
        else:
            try:
                if credentials.save_credential("deepl_api_key", str(old_deepl_key)):
                    cfg["deepl_api_key"] = ""
            except Exception:
                pass

    cfg["active_profile_id"] = active_id
    cfg["ai_profiles"] = profiles


# Номер исходной версии → функция cfg → cfg (один шаг миграции).
_CONFIG_MIGRATIONS = {
    1: _migrate_v1_to_v2,
}

# ---------------------------------------------------------------------------
# Дефолтные системные промпты (пресеты). Пользователь сможет редактировать их
# в окне настроек на следующем шаге. {target_lang} подставляется при запросе.
# ---------------------------------------------------------------------------
DEFAULT_PROMPTS: Dict[str, str] = {
    "Живой перевод": (
        "Ты — профессиональный переводчик с художественным чутьём. "
        "Переведи текст ниже на язык «{target_lang}» живым, естественным языком — "
        "так, как будто его изначально написал носитель языка. "
        "Точно сохрани смысл, стиль и тональность оригинала. "
        "В ответе верни только готовый перевод — без комментариев, пояснений и кавычек."
    ),
    "3 варианта перефразирования": (
        "Ты — опытный редактор. Перефразируй текст ниже на том же языке, "
        "в котором он написан. Предложи ровно 3 варианта: "
        "1) нейтрально-деловой; 2) более простой и разговорный; 3) более выразительный. "
        "Сохрани исходный смысл. Оформи ответ нумерованным списком 1–3, "
        "без вступления и пояснений."
    ),
    "Исправление стилистики и грамматики": (
        "Ты — профессиональный корректор и литературный редактор. "
        "Исправь в тексте ниже все орфографические, пунктуационные и грамматические "
        "ошибки, выровняй стилистику и убери канцелярит. "
        "Сохрани смысл, тон и авторский стиль. "
        "В ответе верни только исправленный текст — без комментариев и списка правок."
    ),
}

# ---------------------------------------------------------------------------
# Стартовые AI Quick Actions (ЭТАП 5)
# ---------------------------------------------------------------------------
DEFAULT_ACTIONS: List[Dict[str, Any]] = [
    {
        "id": "action_trans_literary",
        "name": "Живой перевод",
        "prompt": (
            "Ты — литературный переводчик с художественным чутьём. "
            "Переведи текст ниже на язык «{target_lang}» художественно, выразительно и естественно, "
            "сохранив точный смысл, подтекст, образность и эмоциональную тональность оригинала. "
            "{glossary} {project_context} "
            "В ответе верни только готовый перевод — без комментариев, пояснений и кавычек."
        ),
        "profile_id": "",
        "pinned": True,
        "hotkey": "",
        "order": 0,
    },
    {
        "id": "action_trans_3_variants",
        "name": "3 варианта перефразирования",
        "prompt": (
            "Ты — опытный редактор и переводчик. Перефразируй или переведи текст на язык «{target_lang}» "
            "в 3 разных вариантах:\n"
            "1) нейтрально-деловой;\n"
            "2) живой разговорный;\n"
            "3) более выразительный.\n"
            "Сохрани исходный смысл. Оформи ответ нумерованным списком 1–3, без вступления и пояснений."
        ),
        "profile_id": "",
        "pinned": True,
        "hotkey": "",
        "order": 1,
    },
    {
        "id": "action_grammar_style",
        "name": "Исправление стилистики и грамматики",
        "prompt": (
            "Ты — профессиональный корректор и литературный редактор. "
            "Исправь в тексте ниже все орфографические, пунктуационные и грамматические "
            "ошибки, выровняй стилистику и убери канцелярит. "
            "Сохрани смысл, тон и авторский стиль. "
            "В ответе верни только исправленный текст — без комментариев и списка правок."
        ),
        "profile_id": "",
        "pinned": True,
        "hotkey": "",
        "order": 2,
    },
    {
        "id": "action_trans_natural",
        "name": "Естественный разговорный перевод",
        "prompt": (
            "Ты — носитель языка «{target_lang}». Переведи текст на язык «{target_lang}» "
            "максимально живо и естественно, как говорят в повседневной речи. "
            "Избегай неестественных дословных калек и канцелярита. "
            "{glossary} "
            "В ответе верни только готовый перевод — без вводных слов и пояснений."
        ),
        "profile_id": "",
        "pinned": True,
        "hotkey": "",
        "order": 3,
    },
    {
        "id": "action_rephrase",
        "name": "Перефразирование без изменения смысла",
        "prompt": (
            "Ты — опытный редактор. Перефразируй текст на том же языке ({source_lang}), "
            "полностью сохранив исходный смысл и факты, но изменив структуру предложений "
            "и подобрав точные, выразительные синонимы. "
            "В ответе верни только перефразированный текст."
        ),
        "profile_id": "",
        "pinned": True,
        "hotkey": "",
        "order": 4,
    },
    {
        "id": "action_russian_edit",
        "name": "Редактура русского текста",
        "prompt": (
            "Ты — ведущий литературный редактор. Отредактируй текст: устрани канцелярит, "
            "плеоназмы, тавтологии, согласуй падежи и времена, выровняй ритм предложений. "
            "Сделай слог ясным, сильным и убедительным. "
            "В ответе верни только отредактированный текст."
        ),
        "profile_id": "",
        "pinned": False,
        "hotkey": "",
        "order": 5,
    },
    {
        "id": "action_mt_fix",
        "name": "Исправление машинного перевода",
        "prompt": (
            "Ты — редактор постредактирования машинного перевода (MTPE). Исправь корявый "
            "машинный перевод: сделай фразы естественными, согласуй падежи и времена, "
            "исправь ложные друзья переводчика. "
            "В ответе верни только чистый текст."
        ),
        "profile_id": "",
        "pinned": False,
        "hotkey": "",
        "order": 6,
    },
    {
        "id": "action_idioms",
        "name": "Объяснение идиом",
        "prompt": (
            "Ты — лингвист-фразеолог. Найди в тексте идиомы, фразеологизмы, сленг или устойчивые выражения. "
            "Объясни их происхождение, точное значение и приведи их естественные эквиваленты на языке «{target_lang}»."
        ),
        "profile_id": "",
        "pinned": False,
        "hotkey": "",
        "order": 7,
    },
    {
        "id": "action_tech_trans",
        "name": "Технический перевод",
        "prompt": (
            "Ты — инженер-переводчик. Выполни точный перевод текста на язык «{target_lang}», "
            "строго соблюдая общепринятую техническую терминологию, стандарты и однозначность формулировок. "
            "{glossary} {project_context} "
            "В ответе верни только технический перевод."
        ),
        "profile_id": "",
        "pinned": False,
        "hotkey": "",
        "order": 8,
    },
    {
        "id": "action_formal",
        "name": "Сделать текст более формальным",
        "prompt": (
            "Ты — эксперт по деловой коммуникации. Перепиши текст в строгом, вежливом "
            "и профессиональном деловом стиле, подходящем для официальных писем, "
            "документов или презентаций. "
            "В ответе верни только готовый текст."
        ),
        "profile_id": "",
        "pinned": False,
        "hotkey": "",
        "order": 9,
    },
    {
        "id": "action_conversational",
        "name": "Сделать текст более разговорным",
        "prompt": (
            "Ты — автор, пишущий для живой аудитории. Перепиши текст в легком, "
            "непринужденном, дружеском разговорном тоне, как при общении с хорошим знакомым. "
            "В ответе верни только готовый текст."
        ),
        "profile_id": "",
        "pinned": False,
        "hotkey": "",
        "order": 10,
    },
    {
        "id": "action_shorten",
        "name": "Сократить текст",
        "prompt": (
            "Ты — мастер лаконичности. Сократи текст, убрав всю «воду», второстепенные "
            "детали и повторы. Оставь только самую суть и ключевую мысль в 1–3 емких предложениях. "
            "В ответе верни только сокращенный текст."
        ),
        "profile_id": "",
        "pinned": False,
        "hotkey": "",
        "order": 11,
    },
    {
        "id": "action_expand",
        "name": "Расширить текст",
        "prompt": (
            "Ты — эссеист и копирайтер. Разверни и дополни текст: раскрой мысль подробнее, "
            "добавь логические связки, обогати контекст и примеры, сохраняя исходную идею. "
            "{project_context} "
            "В ответе верни только расширенный текст."
        ),
        "profile_id": "",
        "pinned": False,
        "hotkey": "",
        "order": 12,
    },
    {
        "id": "action_explain",
        "name": "Объяснить смысл",
        "prompt": (
            "Ты — мудрый преподаватель и эксперт по культуре. Разбери и понятно объясни смысл "
            "выделенного текста: прямое значение, скрытый подтекст, контекст употребления, "
            "встретившиеся идиомы, метафоры или культурные отсылки. Изложи кратко и доступно."
        ),
        "profile_id": "",
        "pinned": False,
        "hotkey": "",
        "order": 13,
    },
    {
        "id": "action_alternatives",
        "name": "Предложить несколько альтернатив",
        "prompt": (
            "Ты — консультант по стилистике. Предложи 4 разных альтернативных варианта выражения "
            "той же мысли: от ультра-краткого до выразительного образного. "
            "Оформи ответ нумерованным списком 1–4 без лишних вступлений."
        ),
        "profile_id": "",
        "pinned": False,
        "hotkey": "",
        "order": 14,
    },
    {
        "id": "action_custom",
        "name": "Пользовательский промпт",
        "prompt": (
            "Ты — универсальный AI-помощник. Выполни инструкцию пользователя к выделенному тексту "
            "максимально качественно, точно и лаконично. В ответе верни готовый результат."
        ),
        "profile_id": "",
        "pinned": False,
        "hotkey": "",
        "order": 15,
    },
]


def format_prompt_template(
    template: str,
    text: str,
    source_lang: str,
    target_lang: str,
    project_context: str = "",
    glossary: str = "",
) -> str:
    """Подставляет переменные в шаблон промпта (Этап 5).

    Поддерживаемые переменные:
      {target_lang}     — целевой язык (человеческое название или код)
      {source_lang}     — исходный язык
      {text}            — исходный текст
      {project_context} — контекст проекта (или пустая строка)
      {glossary}        — глоссарий терминов (или пустая строка)
    """
    res = template or ""
    res = res.replace("{target_lang}", str(target_lang))
    res = res.replace("{source_lang}", str(source_lang))

    ctx_str = f"Контекст проекта: {project_context.strip()}." if (project_context or "").strip() else ""
    res = res.replace("{project_context}", ctx_str)

    glo_str = f"Глоссарий терминов:\n{glossary.strip()}" if (glossary or "").strip() else ""
    res = res.replace("{glossary}", glo_str)

    if "{text}" in res:
        res = res.replace("{text}", text or "")

    # Очищаем лишние двойные пробелы и пустые строки, оставшиеся от пустых переменных
    lines = [line.strip() for line in res.splitlines()]
    cleaned = "\n".join(l for l in lines if l)
    return cleaned or res


# ---------------------------------------------------------------------------
# Дефолтная конфигурация приложения
# ---------------------------------------------------------------------------
DEFAULT_CONFIG: Dict[str, Any] = {
    # --- Версия схемы (миграции — см. _apply_migrations) ---------------------
    "config_version": CONFIG_VERSION,
    # --- Горячие клавиши ---------------------------------------------------
    "hotkey": "alt+q",             # глобальный хоткей мини-окна (библиотека keyboard)
    "hotkey_enabled": True,        # временное отключение хоткея (меню трея / настройки)
    # --- Захват выделения (Этап 2) --------------------------------------------
    "capture_delay_ms": 120,       # пауза между очисткой буфера и попыткой копирования
    "capture_attempts": 2,        # раундов цепочки копирования (1–4)
    "diagnostics": False,          # журнал захвата truniversal_diag.log (без текста!)
    # --- Режим работы --------------------------------------------------------
    "mode": "ai",                  # "ai" — ИИ-перевод | "standard" — обычный переводчик
    "standard_engine": "google",   # движок обычного переводчика: "google" | "deepl"
    "source_lang": "auto",         # исходный язык: "auto" или код ("ru", "en", "de"...)
    "target_lang": "ru",           # целевой язык перевода
    "fallback_target_lang": "en",  # резервный целевой язык (при авто-перевороте)
    "deepl_api_key": "",           # API-ключ движка DeepL (для режима «Обычный»)
    # --- Система AI-профилей (Этап 3) ----------------------------------------
    "active_profile_id": "ollama_default",
    "ai_profiles": deepcopy(DEFAULT_AI_PROFILES),
    # --- Настройки ИИ (совместимость со старым форматом) ---------------------
    "api_url": "http://localhost:11434/v1/chat/completions",
    "api_key": "",
    "model_name": "llama3",
    "temperature": 0.3,
    "top_p": 0.9,
    # --- Системные промпты ----------------------------------------------------
    "active_prompt_name": "Живой перевод",  # активный пресет из словаря prompts
    "prompts": deepcopy(DEFAULT_PROMPTS),   # имя пресета → системный промпт
    # --- Быстрые действия ИИ (Этап 5) ----------------------------------------
    "actions": deepcopy(DEFAULT_ACTIONS),
    "active_action_id": "action_trans_literary",
    "project_context": "",
    "glossary": "",
}

def _clean_relaxed_json(text: str) -> str:
    """Очищает JSON от распространённых пользовательских ошибок:
    однострочные комментарии (// и #), концевые запятые перед } или ]."""
    cleaned_lines = []
    for line in text.splitlines():
        trimmed = line.strip()
        if trimmed.startswith("//") or trimmed.startswith("#"):
            continue
        if "//" in line and "://" not in line:
            parts = line.split("//", 1)
            if parts[0].count('"') % 2 == 0:
                line = parts[0]
        cleaned_lines.append(line)
    result = "\n".join(cleaned_lines)
    result = re.sub(r",\s*([\]}])", r"\1", result)
    return result


def _salvage_custom_data(text: str) -> Dict[str, Any]:
    """Пытается извлечь ключевые настройки (промпты, ключи, url) из повреждённого текста."""
    salvaged: Dict[str, Any] = {}
    try:
        # Ищем блок prompts: { ... }
        match = re.search(r'"prompts"\s*:\s*\{([^}]+)\}', text, re.DOTALL)
        if match:
            prompts_block = match.group(1)
            # Ищем пары "имя": "текст"
            pair_pattern = r'"([^"]+)"\s*:\s*"((?:\\.|[^"\\])*)"'
            found_prompts = dict(re.findall(pair_pattern, prompts_block))
            if found_prompts:
                # Декодируем \n, \", \\
                decoded = {}
                for k, v in found_prompts.items():
                    try:
                        decoded[k] = json.loads(f'"{v}"')
                    except Exception:
                        decoded[k] = v.replace('\\"', '"').replace('\\n', '\n')
                salvaged["prompts"] = decoded
    except Exception:
        pass

    # Ищем строковые параметры: api_key, deepl_api_key, api_url, model_name, hotkey, языки
    for key in ("api_key", "deepl_api_key", "api_url", "model_name", "hotkey", "target_lang", "source_lang", "fallback_target_lang"):
        try:
            m = re.search(rf'"{key}"\s*:\s*"([^"]*)"', text)
            if m:
                salvaged[key] = m.group(1)
        except Exception:
            pass

    return salvaged


class ConfigManager:
    """Читает и сохраняет `config.json`, даёт удобный доступ к настройкам."""

    def __init__(self, config_path: Optional[os.PathLike | str] = None) -> None:
        if config_path is None:
            config_path = app_dir() / CONFIG_FILE_NAME
        self.config_path: Path = Path(config_path)
        try:
            resolved_str = str(self.config_path.resolve()).lower()
            temp_root = tempfile.gettempdir().lower()
            self._is_temp = resolved_str.startswith(temp_root) or "tmp" in self.config_path.parts or "temp" in self.config_path.parts
        except Exception:
            self._is_temp = False
        self._path_key = str(self.config_path.resolve()) if self._is_temp else ""
        self.data: Dict[str, Any] = deepcopy(DEFAULT_CONFIG)
        self.load()

    def _save_secret(self, key_name: str, value: str) -> None:
        if self._is_temp:
            _TEMP_CREDENTIALS.setdefault(self._path_key, {})[key_name] = value
        else:
            credentials.save_credential(key_name, value)

    def _get_secret(self, key_name: str) -> Optional[str]:
        if self._is_temp:
            return _TEMP_CREDENTIALS.get(self._path_key, {}).get(key_name)
        return credentials.get_credential(key_name)

    def _delete_secret(self, key_name: str) -> None:
        if self._is_temp:
            _TEMP_CREDENTIALS.get(self._path_key, {}).pop(key_name, None)
        else:
            credentials.delete_credential(key_name)

    # ------------------------------------------------------------- загрузка
    def load(self) -> Dict[str, Any]:
        """Загружает конфиг с диска; создаёт/восстанавливает файл при проблемах."""
        tmp_path = self.config_path.with_name(self.config_path.name + ".tmp")

        # Если основного файла нет или он пуст (0 байт), проверяем временный файл
        if not self.config_path.exists() or (self.config_path.exists() and self.config_path.stat().st_size == 0):
            if tmp_path.exists() and tmp_path.stat().st_size > 0:
                try:
                    tmp_data = json.loads(tmp_path.read_text(encoding="utf-8-sig"))
                    if isinstance(tmp_data, dict):
                        os.replace(tmp_path, self.config_path)
                        print(f"[config] Восстановлен config.json из временного файла: {self.config_path}")
                except Exception:
                    pass

        if not self.config_path.exists():
            self.data = deepcopy(DEFAULT_CONFIG)
            self.save()
            print(f"[config] Файл не найден — создан новый: {self.config_path}")
            return self.data

        raw_text = ""
        try:
            raw_text = self.config_path.read_text(encoding="utf-8-sig")
            loaded = json.loads(raw_text)
            if not isinstance(loaded, dict):
                raise ValueError("корень config.json должен быть JSON-объектом")
        except (json.JSONDecodeError, ValueError, OSError) as exc:
            # 1. Пробуем мягкую очистку (комментарии, концевые запятые)
            recovered = False
            if raw_text.strip():
                try:
                    cleaned_text = _clean_relaxed_json(raw_text)
                    cleaned_loaded = json.loads(cleaned_text)
                    if isinstance(cleaned_loaded, dict):
                        loaded = cleaned_loaded
                        recovered = True
                        print("[config] Файл config.json содержал ошибки синтаксиса и был автоматически исправлен.")
                except Exception:
                    pass

            if not recovered:
                # 2. Серьёзное повреждение: бэкап + попытка спасти пользовательские данные
                self._backup_corrupted(exc, raw_text)
                return self.data

        # Очищаем временный файл, если он остался от прошлых запусков
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass

        # Миграции идут по СЫРЫМ данным файла — ДО merge с дефолтами:
        # иначе ключ «config_version» (и любые новые ключи) попадал бы в
        # данные из DEFAULT_CONFIG и схема файла не штамповалась бы на диск.
        migrated = self._apply_migrations(loaded)
        self.data = self._normalize(self._merge_with_defaults(loaded))
        if migrated:
            # Схема изменилась — сразу штампим файл. Миграции идемпотентны:
            # если записать не удалось, они спокойно повторятся при следующем
            # запуске (save() ошибок не бросает).
            self.save()
        return self.data

    def _backup_corrupted(self, exc: Exception, raw_text: str = "") -> None:
        """Сохраняет повреждённый файл в `*.bak`, пытаясь спасти пользовательские настройки."""
        backup = self.config_path.with_name(self.config_path.name + ".bak")
        salvaged_data: Dict[str, Any] = {}

        # 1. Извлекаем данные из текущего файла (наивысший приоритет)
        if raw_text:
            text_salvage = _salvage_custom_data(raw_text)
            salvaged_data.update(text_salvage)

        # 2. Если каких-то настроек не хватает, дополняем из существующего валидного бэкапа
        if backup.exists():
            try:
                prev_bak = json.loads(backup.read_text(encoding="utf-8-sig"))
                if isinstance(prev_bak, dict):
                    for k, v in prev_bak.items():
                        if k not in salvaged_data:
                            salvaged_data[k] = v
                        elif k == "prompts" and isinstance(salvaged_data.get("prompts"), dict) and isinstance(v, dict):
                            for pname, pval in v.items():
                                salvaged_data["prompts"].setdefault(pname, pval)
            except Exception:
                pass

        try:
            self.config_path.replace(backup)
            print(f"[config] Файл повреждён ({exc}). Бэкап: {backup.name}")
        except OSError:
            print(f"[config] Файл повреждён ({exc}). Создать бэкап не удалось.")

        # Восстанавливаем дефолты + спасённые данные
        self.data = deepcopy(DEFAULT_CONFIG)
        if salvaged_data:
            self.data = self._normalize(self._merge_with_defaults(salvaged_data))
            print(f"[config] Восстановлены сохранённые настройки пользователя из повреждённого файла/бэкапа.")
        else:
            print(f"[config] Восстановлены дефолтные настройки: {self.config_path}")

        self.save()

    def _merge_with_defaults(self, loaded: Dict[str, Any]) -> Dict[str, Any]:
        """Берёт значения из файла, а отсутствующие ключи — из дефолтов.

        Словари `prompts` и `ai_profiles` — исключение: если они есть в файле,
        то используются пользовательские данные целиком.
        """
        merged = deepcopy(DEFAULT_CONFIG)
        for key, value in loaded.items():
            if key == "prompts" and isinstance(value, dict):
                merged["prompts"] = {str(name): str(text) for name, text in value.items()}
            elif key == "ai_profiles" and isinstance(value, dict):
                merged["ai_profiles"] = deepcopy(value)
            else:
                merged[key] = deepcopy(value)
        return merged

    def _apply_migrations(self, cfg: Dict[str, Any]) -> bool:
        """Поднимает схему cfg (СЫРЫЕ данные файла) до CONFIG_VERSION.

        Возвращает True, если схема менялась (файл стоит перезаписать).
        Файл из БУДУЩЕЙ версии не трогаем — обратная совместимость
        при даунгрейде приложения важнее «чистоты» схемы.
        """
        try:
            version = int(cfg.get("config_version", 0))
        except (TypeError, ValueError):
            version = 0
        version = max(version, 0)
        if version >= CONFIG_VERSION:
            # Уже актуально (или конфиг из будущей версии) — не откатываем.
            return False
        if self._is_temp:
            cfg["_temp_path_key"] = self._path_key
        while version < CONFIG_VERSION:
            step = _CONFIG_MIGRATIONS.get(version)
            if step is not None:
                step(cfg)
            version += 1
        cfg.pop("_temp_path_key", None)
        cfg["config_version"] = CONFIG_VERSION
        print(f"[config] Схема файла мигрирована до версии {CONFIG_VERSION}.")
        return True

    # ------------------------------------------------------------ сохранение
    def save(self) -> bool:
        """Атомарно сохраняет конфиг (tmp-файл + os.replace — без «полуфайлов»).

        Возвращает True при успехе и False при ошибке диска, НЕ бросая
        исключение: save() вызывается прямо из GUI-слотов PyQt, где
        необработанное исключение аварийно завершает всё приложение
        (qFatal). Текст ошибки пишется в лог (print), а вызывающий код
        может показать пользователю своё сообщение по возвращённому False.
        """
        tmp_path = self.config_path.with_name(self.config_path.name + ".tmp")
        try:
            with open(tmp_path, "w", encoding="utf-8") as fh:
                json.dump(self.data, fh, ensure_ascii=False, indent=2)
                fh.write("\n")
            os.replace(tmp_path, self.config_path)
        except Exception as exc:  # OSError — диск/права; прочее — защита GUI
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass  # даже очистка tmp не должна ронять GUI-слот
            print(f"[config] Не удалось сохранить config.json: {exc}")
            return False
        return True

    # ---------------------------------------------------------------- доступ
    def get(self, key: str, default: Any = None) -> Any:
        if key == "api_key":
            active_id = self.get_active_profile_id()
            cred = self._get_secret(f"profile_{active_id}")
            if cred:
                return cred
            active_prof = self.data.get("ai_profiles", {}).get(active_id, {})
            return active_prof.get("api_key") or self.data.get("api_key", default)

        if key == "deepl_api_key":
            cred = self._get_secret("deepl_api_key")
            return cred or self.data.get("deepl_api_key", default)

        if key in ("api_url", "model_name", "temperature", "top_p"):
            active_id = self.get_active_profile_id()
            active_prof = self.data.get("ai_profiles", {}).get(active_id, {})
            if key in active_prof:
                return active_prof[key]

        return self.data.get(key, default)

    def set(self, key: str, value: Any, autosave: bool = True) -> bool:
        """Записывает значение; при autosave сохраняет файл. True — сохранено."""
        if key == "api_key":
            active_id = self.get_active_profile_id()
            self._save_secret(f"profile_{active_id}", str(value or ""))
            self.data["api_key"] = value
            if active_id in self.data.get("ai_profiles", {}):
                self.data["ai_profiles"][active_id]["api_key"] = value
        elif key == "deepl_api_key":
            self._save_secret("deepl_api_key", str(value or ""))
            self.data["deepl_api_key"] = value
        else:
            self.data[key] = value
            if key in ("api_url", "model_name", "temperature", "top_p"):
                active_id = self.get_active_profile_id()
                if active_id in self.data.get("ai_profiles", {}):
                    self.data["ai_profiles"][active_id][key] = value

        if autosave:
            return self.save()
        return True

    def update(self, values: Dict[str, Any], autosave: bool = True) -> bool:
        """Массовое обновление (удобно для формы настроек). True — сохранено."""
        for k, v in values.items():
            self.set(k, v, autosave=False)
        if autosave:
            return self.save()
        return True

    def reset_to_defaults(self, autosave: bool = True) -> bool:
        """Полный сброс к дефолтам (кнопка «Сбросить все настройки»).

        Перед сбросом создаёт резервную копию *.bak, чтобы пользовательские
        промпты и настройки можно было восстановить при случайном нажатии.
        """
        if self.config_path.exists():
            try:
                backup = self.config_path.with_name(self.config_path.name + ".bak")
                shutil.copy2(self.config_path, backup)
            except Exception:
                pass
        self.data = deepcopy(DEFAULT_CONFIG)
        if autosave:
            return self.save()
        return True

    # ----------------------------------------------------------- AI-профили
    def get_profiles(self) -> Dict[str, Dict[str, Any]]:
        """Возвращает словарь всех настроенных AI-профилей {id: profile_dict}."""
        return deepcopy(self.data.get("ai_profiles", DEFAULT_AI_PROFILES))

    def get_active_profile_id(self) -> str:
        """Идентификатор текущего активного AI-профиля."""
        pid = self.data.get("active_profile_id")
        profiles = self.data.get("ai_profiles", {})
        if pid and pid in profiles:
            return str(pid)
        return next(iter(profiles)) if profiles else "ollama_default"

    def get_active_profile(self) -> Dict[str, Any]:
        """Возвращает данные активного AI-профиля с подставленным API-ключом."""
        pid = self.get_active_profile_id()
        profiles = self.data.get("ai_profiles", {})
        prof = deepcopy(profiles.get(pid) or DEFAULT_AI_PROFILES["ollama_default"])
        prof["api_key"] = self.get_profile_api_key(pid)
        return prof

    def get_profile(self, profile_id: str) -> Optional[Dict[str, Any]]:
        """Возвращает копию данных профиля по id или None, если профиль не найден."""
        profiles = self.data.get("ai_profiles", {})
        if profile_id not in profiles:
            return None
        prof = deepcopy(profiles[profile_id])
        prof["api_key"] = self.get_profile_api_key(profile_id)
        return prof

    get_profile_by_id = get_profile

    def set_active_profile(self, profile_id: str, autosave: bool = True) -> bool:
        """Переключает активный AI-профиль."""
        profiles = self.data.get("ai_profiles", {})
        if profile_id not in profiles:
            return False
        self.data["active_profile_id"] = profile_id
        active = profiles[profile_id]
        self.data["api_url"] = active["api_url"]
        self.data["model_name"] = active["model_name"]
        self.data["temperature"] = active["temperature"]
        self.data["top_p"] = active["top_p"]
        if autosave:
            return self.save()
        return True

    def get_profile_api_key(self, profile_id: str) -> str:
        """Считывает API-ключ профиля из Windows Credential Manager или изолированного хранилища."""
        key = self._get_secret(f"profile_{profile_id}")
        if key:
            return key
        return str(self.data.get("ai_profiles", {}).get(profile_id, {}).get("api_key") or "")

    def save_profile(self, profile_data: Dict[str, Any], api_key: Optional[str] = None, autosave: bool = True) -> bool:
        """Создает или обновляет AI-профиль."""
        pid = str(profile_data.get("id") or "").strip()
        if not pid:
            pid = f"profile_{uuid.uuid4().hex[:8]}"
            profile_data["id"] = pid
        clean = deepcopy(profile_data)
        clean["id"] = pid
        clean["name"] = str(clean.get("name") or pid).strip()
        clean["provider_type"] = str(clean.get("provider_type") or "custom").lower()
        clean["api_url"] = normalize_chat_url(str(clean.get("api_url") or ""), clean["provider_type"])
        clean["model_name"] = str(clean.get("model_name") or "llama3").strip()

        for k, lo, hi, d in (("temperature", 0.0, 2.0, 0.3), ("top_p", 0.0, 1.0, 0.9)):
            try:
                clean[k] = min(max(float(clean.get(k, d)), lo), hi)
            except (TypeError, ValueError):
                clean[k] = d

        try:
            clean["timeout_connect"] = max(int(clean.get("timeout_connect", 10)), 1)
        except (TypeError, ValueError):
            clean["timeout_connect"] = 10

        try:
            clean["timeout_request"] = max(int(clean.get("timeout_request", 90)), 5)
        except (TypeError, ValueError):
            clean["timeout_request"] = 90

        try:
            clean["max_retries"] = min(max(int(clean.get("max_retries", 2)), 0), 5)
        except (TypeError, ValueError):
            clean["max_retries"] = 2

        if api_key is not None:
            self._save_secret(f"profile_{pid}", api_key)
            clean["api_key"] = ""

        self.data.setdefault("ai_profiles", {})[pid] = clean

        if self.get_active_profile_id() == pid:
            self.data["api_url"] = clean["api_url"]
            self.data["model_name"] = clean["model_name"]
            self.data["temperature"] = clean["temperature"]
            self.data["top_p"] = clean["top_p"]

        if autosave:
            return self.save()
        return True

    def delete_profile(self, profile_id: str, autosave: bool = True) -> bool:
        """Удаляет профиль (нельзя удалить единственный оставшийся)."""
        profiles = self.data.get("ai_profiles", {})
        if profile_id not in profiles or len(profiles) <= 1:
            return False
        self._delete_secret(f"profile_{profile_id}")
        del profiles[profile_id]
        if self.data.get("active_profile_id") == profile_id:
            self.set_active_profile(next(iter(profiles)), autosave=False)
        if autosave:
            return self.save()
        return True

    def duplicate_profile(self, profile_id: str, autosave: bool = True) -> Optional[str]:
        """Клонирует профиль с уникальным идентификатором и копирует его ключ."""
        profiles = self.data.get("ai_profiles", {})
        if profile_id not in profiles:
            return None
        source = deepcopy(profiles[profile_id])
        n = 2
        new_id = f"{profile_id}_copy"
        while new_id in profiles:
            new_id = f"{profile_id}_copy{n}"
            n += 1
        source["id"] = new_id
        source["name"] = f"{source.get('name', profile_id)} (копия)"
        old_key = self.get_profile_api_key(profile_id)
        if old_key:
            self._save_secret(f"profile_{new_id}", old_key)
        profiles[new_id] = source
        if autosave:
            self.save()
        return new_id

    # ------------------------------------------------ Быстрые действия (Этап 5)
    def get_actions(self) -> List[Dict[str, Any]]:
        """Возвращает упорядоченный список всех AI Quick Actions."""
        raw_actions = self.data.get("actions")
        if not isinstance(raw_actions, list) or not raw_actions:
            raw_actions = deepcopy(DEFAULT_ACTIONS)
            self.data["actions"] = raw_actions
        res = [a for a in raw_actions if isinstance(a, dict)]
        res.sort(key=lambda a: int(a.get("order", 0)))
        return deepcopy(res)

    def get_action(self, id_or_name: str) -> Optional[Dict[str, Any]]:
        """Ищет действие по id или названию (без учёта регистра)."""
        target = (id_or_name or "").strip().lower()
        if not target:
            return None
        for act in self.get_actions():
            if act.get("id", "").lower() == target or act.get("name", "").lower() == target:
                return deepcopy(act)
        return None

    def get_active_action(self) -> Dict[str, Any]:
        """Возвращает текущее активное действие (или первое доступное)."""
        act_id = self.data.get("active_action_id")
        act = self.get_action(act_id) if act_id else None
        if act is None:
            prompt_name = self.data.get("active_prompt_name", "")
            act = self.get_action(prompt_name)
        if act is None:
            actions = self.get_actions()
            act = actions[0] if actions else DEFAULT_ACTIONS[0]
        return deepcopy(act)

    def set_active_action(self, id_or_name: str, autosave: bool = True) -> bool:
        """Переключает активное действие."""
        act = self.get_action(id_or_name)
        if act is None:
            return False
        self.data["active_action_id"] = act["id"]
        self.data["active_prompt_name"] = act["name"]
        if autosave:
            return self.save()
        return True

    def save_action(self, action_data: Dict[str, Any], autosave: bool = True) -> bool:
        """Создаёт или обновляет AI-действие."""
        actions = self.get_actions()
        aid = str(action_data.get("id") or "").strip()
        if not aid:
            aid = f"action_{uuid.uuid4().hex[:8]}"
            action_data["id"] = aid

        name = str(action_data.get("name") or aid).strip()
        prompt = str(action_data.get("prompt") or "").strip()
        profile_id = str(action_data.get("profile_id") or "").strip()
        pinned = bool(action_data.get("pinned", False))
        hotkey = str(action_data.get("hotkey") or "").strip().lower()
        order = int(action_data.get("order", len(actions)))

        clean_act = {
            "id": aid,
            "name": name,
            "prompt": prompt,
            "profile_id": profile_id,
            "pinned": pinned,
            "hotkey": hotkey,
            "order": order,
        }

        updated = False
        new_list = []
        for a in actions:
            if a.get("id") == aid:
                new_list.append(clean_act)
                updated = True
            else:
                new_list.append(a)
        if not updated:
            new_list.append(clean_act)

        new_list.sort(key=lambda a: int(a.get("order", 0)))
        self.data["actions"] = new_list

        # Синхронизируем prompts
        self.data.setdefault("prompts", {})[name] = prompt

        if autosave:
            return self.save()
        return True

    def delete_action(self, action_id_or_name: str, autosave: bool = True) -> bool:
        """Удаляет действие (нельзя удалить единственное оставшееся)."""
        actions = self.get_actions()
        if len(actions) <= 1:
            return False
        act = self.get_action(action_id_or_name)
        if act is None:
            return False
        aid = act["id"]
        aname = act["name"]
        new_list = [a for a in actions if a.get("id") != aid]
        self.data["actions"] = new_list
        if aname in self.data.get("prompts", {}):
            del self.data["prompts"][aname]
        if self.data.get("active_action_id") == aid:
            self.set_active_action(new_list[0]["id"], autosave=False)
        if autosave:
            return self.save()
        return True

    def reorder_actions(self, action_ids: List[str], autosave: bool = True) -> bool:
        """Переупорядочивает действия в соответствии со списком id."""
        actions_dict = {a["id"]: a for a in self.get_actions()}
        ordered = []
        for idx, aid in enumerate(action_ids):
            if aid in actions_dict:
                act = actions_dict.pop(aid)
                act["order"] = idx
                ordered.append(act)
        for act in actions_dict.values():
            act["order"] = len(ordered)
            ordered.append(act)
        self.data["actions"] = ordered
        if autosave:
            return self.save()
        return True

    def get_pinned_actions(self) -> List[Dict[str, Any]]:
        """Возвращает список закреплённых действий для панели быстрого доступа."""
        actions = self.get_actions()
        pinned = [a for a in actions if a.get("pinned")]
        pinned.sort(key=lambda a: int(a.get("order", 0)))
        return pinned

    def get_action_hotkeys(self) -> Dict[str, str]:
        """Возвращает словарь {action_id: hotkey} для действий с назначенными клавишами."""
        return {
            a["id"]: a["hotkey"]
            for a in self.get_actions()
            if a.get("hotkey")
        }

    # --------------------------------------------------------------- промпты
    def get_prompt(self, name: str) -> Optional[str]:
        prompt = self.data.get("prompts", {}).get(name)
        if prompt is not None:
            return prompt
        act = self.get_action(name)
        if act:
            return act.get("prompt")
        return None

    def set_prompt(self, name: str, text: str, autosave: bool = True) -> bool:
        """Сохраняет промпт пресета. True — записано на диск."""
        self.data.setdefault("prompts", {})[name] = text
        act = self.get_action(name)
        if act:
            act["prompt"] = text
            self.save_action(act, autosave=False)
        else:
            actions = self.data.setdefault("actions", deepcopy(DEFAULT_ACTIONS))
            actions.append({
                "id": f"action_{uuid.uuid4().hex[:8]}",
                "name": name,
                "prompt": text,
                "profile_id": "",
                "pinned": False,
                "hotkey": "",
                "order": len(actions),
            })
        if autosave:
            return self.save()
        return True

    def get_active_prompt(self) -> str:
        """Системный промпт активного пресета (с graceful fallback)."""
        act = self.get_active_action()
        if act and act.get("prompt"):
            return act["prompt"]
        prompts: Dict[str, str] = self.data.get("prompts", {})
        prompt = prompts.get(self.data.get("active_prompt_name", ""))
        if prompt is None:
            if prompts:
                first_name = next(iter(prompts))
                self.data["active_prompt_name"] = first_name
                prompt = prompts[first_name]
            else:
                prompt = next(iter(DEFAULT_PROMPTS.values()))
        return prompt

    # ------------------------------------------------------------- валидация
    def _normalize(self, cfg: Dict[str, Any]) -> Dict[str, Any]:
        """Мягко исправляет явно битые значения, чтобы приложение не падало."""
        if cfg.get("mode") not in VALID_MODES:
            cfg["mode"] = DEFAULT_CONFIG["mode"]
        if cfg.get("standard_engine") not in VALID_STANDARD_ENGINES:
            cfg["standard_engine"] = DEFAULT_CONFIG["standard_engine"]

        # Числовые параметры: приводим к float и ужимаем в разумные границы.
        for key, lo, hi in (("temperature", 0.0, 2.0), ("top_p", 0.0, 1.0)):
            try:
                value = float(cfg.get(key))
            except (TypeError, ValueError):
                value = float(DEFAULT_CONFIG[key])
            cfg[key] = min(max(value, lo), hi)

        # Хоткей: не-строка → дефолт. ПУСТАЯ строка допустима с Этапа 2 —
        # она означает «хоткей не задан» (захват по хоткею отключён).
        hotkey = cfg.get("hotkey")
        if not isinstance(hotkey, str):
            cfg["hotkey"] = DEFAULT_CONFIG["hotkey"]
        else:
            cfg["hotkey"] = hotkey.strip()

        # Числовые параметры захвата: целые, в разумных границах.
        for key, lo, hi in (("capture_delay_ms", 0, 2000),
                            ("capture_attempts", 1, 4)):
            try:
                value = int(cfg.get(key))
            except (TypeError, ValueError):
                value = int(DEFAULT_CONFIG[key])
            cfg[key] = min(max(value, lo), hi)

        # Булевы флаги (строки «true»/«да»/«1» тоже принимаем — конфиг
        # редактируют руками).
        for key in ("hotkey_enabled", "diagnostics"):
            value = cfg.get(key)
            if isinstance(value, str):
                value = value.strip().lower() in ("1", "true", "yes", "on", "да")
            cfg[key] = bool(value)

        # AI-профили (Этап 3)
        profiles = cfg.get("ai_profiles")
        if not isinstance(profiles, dict) or not profiles:
            cfg["ai_profiles"] = deepcopy(DEFAULT_AI_PROFILES)
        else:
            for pid, prof in list(profiles.items()):
                if not isinstance(prof, dict):
                    profiles.pop(pid, None)
                    continue
                prof["id"] = str(prof.get("id") or pid)
                prof["name"] = str(prof.get("name") or pid).strip()
                prof["provider_type"] = str(prof.get("provider_type") or "custom").lower()
                prof["api_url"] = normalize_chat_url(str(prof.get("api_url") or ""), prof["provider_type"])
                prof["model_name"] = str(prof.get("model_name") or "llama3").strip()
                # Авто-исправление устаревших / удалённых моделей OpenRouter
                if prof["model_name"] in ("google/gemini-2.0-flash-001", "google/gemini-2.0-flash-exp:free", "google/gemini-flash-1.5"):
                    prof["model_name"] = "deepseek/deepseek-chat"
                prof["proxy"] = str(prof.get("proxy") or "").strip()
                for k, lo, hi, d in (("temperature", 0.0, 2.0, 0.3), ("top_p", 0.0, 1.0, 0.9)):
                    try:
                        prof[k] = min(max(float(prof.get(k, d)), lo), hi)
                    except (TypeError, ValueError):
                        prof[k] = d
                try:
                    prof["timeout_connect"] = max(int(prof.get("timeout_connect", 10)), 1)
                except (TypeError, ValueError):
                    prof["timeout_connect"] = 10
                try:
                    prof["timeout_request"] = max(int(prof.get("timeout_request", 90)), 5)
                except (TypeError, ValueError):
                    prof["timeout_request"] = 90
                try:
                    prof["max_retries"] = min(max(int(prof.get("max_retries", 2)), 0), 5)
                except (TypeError, ValueError):
                    prof["max_retries"] = 2

        if not cfg.get("ai_profiles"):
            cfg["ai_profiles"] = deepcopy(DEFAULT_AI_PROFILES)

        # active_profile_id
        if cfg.get("active_profile_id") not in cfg["ai_profiles"]:
            cfg["active_profile_id"] = next(iter(cfg["ai_profiles"]))

        # Синхронизируем плоские ключи с активным профилем
        active_prof = cfg["ai_profiles"][cfg["active_profile_id"]]
        active_prof["temperature"] = cfg["temperature"]
        active_prof["top_p"] = cfg["top_p"]
        cfg["api_url"] = active_prof["api_url"]
        cfg["model_name"] = active_prof["model_name"]

        # Промпты: должен быть непустой словарь строк.
        prompts = cfg.get("prompts")
        if not isinstance(prompts, dict) or not prompts:
            cfg["prompts"] = deepcopy(DEFAULT_PROMPTS)

        # Активный пресет должен существовать.
        if cfg.get("active_prompt_name") not in cfg["prompts"]:
            cfg["active_prompt_name"] = next(iter(cfg["prompts"]))

        # Языковые параметры (Этап 4)
        for key, default in (("source_lang", "auto"), ("target_lang", "ru"), ("fallback_target_lang", "en")):
            val = cfg.get(key)
            if not isinstance(val, str) or not val.strip():
                cfg[key] = default
            else:
                cfg[key] = val.strip().lower()

        # Строковые поля: гарантируем тип str.
        for key in ("target_lang", "source_lang", "fallback_target_lang", "api_url", "api_key", "model_name", "deepl_api_key"):
            if not isinstance(cfg.get(key), str):
                cfg[key] = str(DEFAULT_CONFIG.get(key, ""))

        # Быстрые действия ИИ (Этап 5)
        raw_actions = cfg.get("actions")
        if not isinstance(raw_actions, list) or not raw_actions:
            cfg["actions"] = deepcopy(DEFAULT_ACTIONS)
        else:
            clean_actions = []
            for act in raw_actions:
                if not isinstance(act, dict):
                    continue
                aid = str(act.get("id") or "").strip()
                name = str(act.get("name") or aid).strip()
                prompt = str(act.get("prompt") or "").strip()
                if not aid or not name or not prompt:
                    continue
                clean_actions.append({
                    "id": aid,
                    "name": name,
                    "prompt": prompt,
                    "profile_id": str(act.get("profile_id") or "").strip(),
                    "pinned": bool(act.get("pinned", False)),
                    "hotkey": str(act.get("hotkey") or "").strip().lower(),
                    "order": int(act.get("order", len(clean_actions))),
                })
            if not clean_actions:
                clean_actions = deepcopy(DEFAULT_ACTIONS)
            clean_actions.sort(key=lambda a: int(a.get("order", 0)))
            cfg["actions"] = clean_actions

        if not isinstance(cfg.get("active_action_id"), str) or not cfg.get("active_action_id"):
            cfg["active_action_id"] = cfg["actions"][0]["id"]
        if not isinstance(cfg.get("project_context"), str):
            cfg["project_context"] = ""
        if not isinstance(cfg.get("glossary"), str):
            cfg["glossary"] = ""

        return cfg
