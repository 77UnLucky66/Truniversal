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

Промпты: {target_lang} — плейсхолдер, который при отправке запроса к ИИ
подменяется значением настройки `target_lang` (реализация — следующий шаг).
"""

from __future__ import annotations

import json
import os
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Optional

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
# Дефолтная конфигурация приложения
# ---------------------------------------------------------------------------
DEFAULT_CONFIG: Dict[str, Any] = {
    # --- Горячие клавиши ---------------------------------------------------
    "hotkey": "alt+q",             # глобальный хоткей мини-окна (библиотека keyboard)
    # --- Режим работы --------------------------------------------------------
    "mode": "ai",                  # "ai" — ИИ-перевод | "standard" — обычный переводчик
    "standard_engine": "google",   # движок обычного переводчика: "google" | "deepl"
    "target_lang": "ru",           # целевой язык перевода
    "deepl_api_key": "",           # API-ключ движка DeepL (для режима «Обычный»)
    # --- Настройки ИИ (OpenAI-совместимый API: Ollama, OpenAI и др.) ----------
    "api_url": "http://localhost:11434/v1/chat/completions",  # дефолт — локальная Ollama
    "api_key": "",                 # API-ключ (для локальной Ollama не нужен)
    "model_name": "llama3",        # имя модели
    "temperature": 0.3,            # «креативность» ответа (0.0 — строго, 2.0 — хаос)
    "top_p": 0.9,                  # nucleus sampling (0.0–1.0)
    # --- Системные промпты ----------------------------------------------------
    "active_prompt_name": "Живой перевод",  # активный пресет из словаря prompts
    "prompts": deepcopy(DEFAULT_PROMPTS),   # имя пресета → системный промпт
}

class ConfigManager:
    """Читает и сохраняет `config.json`, даёт удобный доступ к настройкам."""

    def __init__(self, config_path: Optional[os.PathLike | str] = None) -> None:
        if config_path is None:
            config_path = app_dir() / CONFIG_FILE_NAME
        self.config_path: Path = Path(config_path)
        self.data: Dict[str, Any] = deepcopy(DEFAULT_CONFIG)
        self.load()

    # ------------------------------------------------------------- загрузка
    def load(self) -> Dict[str, Any]:
        """Загружает конфиг с диска; создаёт/восстанавливает файл при проблемах."""
        if not self.config_path.exists():
            self.data = deepcopy(DEFAULT_CONFIG)
            self.save()
            print(f"[config] Файл не найден — создан новый: {self.config_path}")
            return self.data

        try:
            # utf-8-sig — на случай, если файл редактировали в старом Блокноте (BOM)
            loaded = json.loads(self.config_path.read_text(encoding="utf-8-sig"))
            if not isinstance(loaded, dict):
                raise ValueError("корень config.json должен быть JSON-объектом")
        except (json.JSONDecodeError, ValueError, OSError) as exc:
            self._backup_corrupted(exc)
            self.data = deepcopy(DEFAULT_CONFIG)
            self.save()
            return self.data

        self.data = self._normalize(self._merge_with_defaults(loaded))
        return self.data

    def _backup_corrupted(self, exc: Exception) -> None:
        """Сохраняет повреждённый файл в `*.bak`, чтобы пользовательский текст не пропал."""
        backup = self.config_path.with_name(self.config_path.name + ".bak")
        try:
            self.config_path.replace(backup)
            print(f"[config] Файл повреждён ({exc}). Бэкап: {backup.name}")
        except OSError:
            print(f"[config] Файл повреждён ({exc}). Создать бэкап не удалось.")
        print(f"[config] Восстановлены дефолтные настройки: {self.config_path}")

    def _merge_with_defaults(self, loaded: Dict[str, Any]) -> Dict[str, Any]:
        """Берёт значения из файла, а отсутствующие ключи — из дефолтов.

        Словарь `prompts` — исключение: если он есть в файле, то используется
        целиком — пользователь имеет право удалять пресеты, и они не должны
        «воскресать» при перезапуске приложения.
        """
        merged = deepcopy(DEFAULT_CONFIG)
        for key, value in loaded.items():
            if key == "prompts" and isinstance(value, dict):
                merged["prompts"] = {str(name): str(text) for name, text in value.items()}
            else:
                merged[key] = deepcopy(value)
        return merged

    # ------------------------------------------------------------ сохранение
    def save(self) -> None:
        """Атомарно сохраняет конфиг (tmp-файл + os.replace — без «полуфайлов»)."""
        tmp_path = self.config_path.with_name(self.config_path.name + ".tmp")
        try:
            with open(tmp_path, "w", encoding="utf-8") as fh:
                json.dump(self.data, fh, ensure_ascii=False, indent=2)
                fh.write("\n")
            os.replace(tmp_path, self.config_path)
        except OSError as exc:
            tmp_path.unlink(missing_ok=True)
            raise RuntimeError(f"Не удалось сохранить config.json: {exc}") from exc

    # ---------------------------------------------------------------- доступ
    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def set(self, key: str, value: Any, autosave: bool = True) -> None:
        self.data[key] = value
        if autosave:
            self.save()

    def update(self, values: Dict[str, Any], autosave: bool = True) -> None:
        """Массовое обновление (удобно для формы настроек)."""
        self.data.update(values)
        if autosave:
            self.save()

    def reset_to_defaults(self, autosave: bool = True) -> None:
        """Полный сброс к дефолтам (кнопка «Сбросить» в настройках)."""
        self.data = deepcopy(DEFAULT_CONFIG)
        if autosave:
            self.save()

    # --------------------------------------------------------------- промпты
    def get_prompt(self, name: str) -> Optional[str]:
        return self.data.get("prompts", {}).get(name)

    def set_prompt(self, name: str, text: str, autosave: bool = True) -> None:
        self.data.setdefault("prompts", {})[name] = text
        if autosave:
            self.save()

    def get_active_prompt(self) -> str:
        """Системный промпт активного пресета (с graceful fallback)."""
        prompts: Dict[str, str] = self.data.get("prompts", {})
        prompt = prompts.get(self.data.get("active_prompt_name", ""))
        if prompt is None:
            # Активный пресет был удалён — берём первый доступный.
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

        # Хоткей: пустая строка или не-строка → дефолт.
        hotkey = cfg.get("hotkey")
        if not isinstance(hotkey, str) or not hotkey.strip():
            cfg["hotkey"] = DEFAULT_CONFIG["hotkey"]

        # Промпты: должен быть непустой словарь строк.
        prompts = cfg.get("prompts")
        if not isinstance(prompts, dict) or not prompts:
            cfg["prompts"] = deepcopy(DEFAULT_PROMPTS)

        # Активный пресет должен существовать.
        if cfg.get("active_prompt_name") not in cfg["prompts"]:
            cfg["active_prompt_name"] = next(iter(cfg["prompts"]))

        # Строковые поля: гарантируем тип str.
        for key in ("target_lang", "api_url", "api_key", "model_name", "deepl_api_key"):
            if not isinstance(cfg.get(key), str):
                cfg[key] = str(DEFAULT_CONFIG[key])
        return cfg
