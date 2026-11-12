"""
project_manager.py — Система проектов, контекста и глоссария (ЭТАП 8).

Обеспечивает:
  8.1. Создание и управление отдельными проектами (новеллы, игры, документация и т.д.).
  8.2. Полноценный пользовательский словарь проекта (глоссарий) с категориями,
       комментариями, примерами, поиском, детекцией дубликатов, импортом и экспортом.
  8.3. Умную выборку релевантных терминов из глоссария по исходному тексту (smart matching).
  8.4. Контекст проекта, правила перевода и разовые заметки (ad-hoc context).
  8.5. Краткосрочную контекстную память предыдущих фрагментов (Translation Memory / Sliding Window).
  8.6. Определение конфиденциальности (Ollama локально vs Облачный провайдер).
"""

from __future__ import annotations

import csv
import json
import os
import re
import sys
import threading
import time
import uuid
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


STANDARD_CATEGORIES: List[str] = [
    "Имена персонажей",
    "Географические названия",
    "Термины мира",
    "Способности / Навыки",
    "Технические термины",
    "Устойчивые выражения",
    "Организации и фракции",
    "Другое",
]


def _app_dir() -> Path:
    """Определяет портабельный каталог приложения."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def term_matches_text(term: str, text: str, case_sensitive: bool = False) -> bool:
    """Умная проверка вхождения термина в текст.

    Для языков с пробелами (латиница, кириллица) используется совпадение по границам слов
    (чтобы 'Mana' не находилась внутри 'Manager').
    Для CJK (китайский, японский, корейский) используется вхождение подстроки.
    """
    if not term or not text:
        return False

    term = term.strip()
    if not term:
        return False

    # Проверка на наличие иероглифов / CJK слогов
    has_cjk = any(
        "\u4e00" <= c <= "\u9fff"  # CJK Unified Ideographs
        or "\u3040" <= c <= "\u30ff"  # Hiragana & Katakana
        or "\uac00" <= c <= "\ud7af"  # Hangul Syllables
        for c in term
    )

    if has_cjk:
        if case_sensitive:
            return term in text
        return term.lower() in text.lower()

    # Для алфавитных языков: учитываем границы слов Unicode
    flags = 0 if case_sensitive else re.IGNORECASE
    # Регулярное выражение с негативным просмотром назад и вперед на буквенно-цифровые символы
    pattern = r"(?<!\w)" + re.escape(term) + r"(?!\w)"
    try:
        return bool(re.search(pattern, text, flags))
    except Exception:
        if case_sensitive:
            return term in text
        return term.lower() in text.lower()


class ProjectManager:
    """Менеджер проектов, контекста и глоссариев.

    Потокобезопасен, данные сохраняются в projects.json с атомарной записью.
    """

    def __init__(self, storage_path: Optional[os.PathLike | str] = None) -> None:
        if storage_path is None:
            storage_path = _app_dir() / "projects.json"
        self.storage_path = Path(storage_path)
        self._lock = threading.RLock()
        self._projects: Dict[str, Dict[str, Any]] = {}
        self._active_project_id: str = ""
        self._ad_hoc_context: str = ""
        # Временная память предыдущих переводов в рамках сессии: {project_id: [{"source":..., "result":..., "timestamp":...}]}
        self._memory_chunks: Dict[str, List[Dict[str, str]]] = {}
        self._load()

    # ------------------------------------------------------------------ Загрузка / Сохранение
    def _load(self) -> None:
        with self._lock:
            if not self.storage_path.exists():
                self._projects = {}
                self._active_project_id = ""
                return

            try:
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    self._active_project_id = str(data.get("active_project_id") or "")
                    raw_projects = data.get("projects", {})
                    if isinstance(raw_projects, dict):
                        self._projects = raw_projects
                    elif isinstance(raw_projects, list):
                        self._projects = {p["id"]: p for p in raw_projects if isinstance(p, dict) and "id" in p}
                    else:
                        self._projects = {}
                else:
                    self._projects = {}
            except Exception as exc:
                print(f"[projects] Ошибка чтения {self.storage_path}: {exc}. Создание резервной копии...")
                try:
                    bak = self.storage_path.with_suffix(".json.bak")
                    if self.storage_path.exists():
                        import shutil
                        shutil.copy2(self.storage_path, bak)
                except Exception:
                    pass
                self._projects = {}
                self._active_project_id = ""

    def _save(self) -> bool:
        with self._lock:
            payload = {
                "version": 1,
                "active_project_id": self._active_project_id,
                "projects": self._projects,
            }
            tmp_path = self.storage_path.with_suffix(".json.tmp")
            try:
                self.storage_path.parent.mkdir(parents=True, exist_ok=True)
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(payload, f, ensure_ascii=False, indent=2)
                if self.storage_path.exists():
                    self.storage_path.unlink()
                tmp_path.rename(self.storage_path)
                return True
            except Exception as exc:
                print(f"[projects] Не удалось сохранить {self.storage_path}: {exc}")
                if tmp_path.exists():
                    try:
                        tmp_path.unlink()
                    except Exception:
                        pass
                return False

    # ------------------------------------------------------------------ Управление проектами
    def list_projects(self) -> List[Dict[str, Any]]:
        """Возвращает список всех проектов, отсортированных по имени."""
        with self._lock:
            projs = list(self._projects.values())
            projs.sort(key=lambda p: str(p.get("name") or "").lower())
            return deepcopy(projs)

    def get_project(self, project_id: str) -> Optional[Dict[str, Any]]:
        """Получает проект по идентификатору."""
        with self._lock:
            p = self._projects.get(project_id)
            return deepcopy(p) if p else None

    def get_active_project(self) -> Optional[Dict[str, Any]]:
        """Получает текущий активный проект (или None, если режим без проекта)."""
        with self._lock:
            if not self._active_project_id:
                return None
            return self.get_project(self._active_project_id)

    def get_active_project_id(self) -> str:
        """Возвращает ID активного проекта."""
        with self._lock:
            return self._active_project_id

    def set_active_project_id(self, project_id: str) -> bool:
        """Устанавливает активный проект ('' для режима без проекта)."""
        with self._lock:
            if project_id and project_id not in self._projects:
                return False
            self._active_project_id = project_id
            self._save()
            return True

    def create_project(
        self,
        name: str,
        description: str = "",
        source_lang: str = "auto",
        target_lang: str = "ru",
        ai_profile_id: str = "",
        action_id: str = "",
        context: str = "",
        translation_rules: str = "",
        notes: str = "",
        glossary_enabled: bool = True,
        context_memory_enabled: bool = False,
        context_memory_count: int = 3,
        context_memory_max_chars: int = 1500,
        context_memory_include_translation: bool = True,
    ) -> Dict[str, Any]:
        """Создает новый проект с заданными параметрами."""
        with self._lock:
            project_id = f"proj_{uuid.uuid4().hex[:10]}"
            now = time.strftime("%Y-%m-%d %H:%M:%S")
            project_data: Dict[str, Any] = {
                "id": project_id,
                "name": name.strip() or "Новый проект",
                "description": description.strip(),
                "source_lang": source_lang.strip() or "auto",
                "target_lang": target_lang.strip() or "ru",
                "ai_profile_id": ai_profile_id.strip(),
                "action_id": action_id.strip(),
                "context": context.strip(),
                "translation_rules": translation_rules.strip(),
                "notes": notes.strip(),
                "glossary_enabled": bool(glossary_enabled),
                "context_memory_enabled": bool(context_memory_enabled),
                "context_memory_count": max(1, min(int(context_memory_count), 10)),
                "context_memory_max_chars": max(200, min(int(context_memory_max_chars), 10000)),
                "context_memory_include_translation": bool(context_memory_include_translation),
                "glossary": [],
                "created_at": now,
                "updated_at": now,
            }
            self._projects[project_id] = project_data
            self._save()
            return deepcopy(project_data)

    def update_project(self, project_id: str, **kwargs: Any) -> bool:
        """Обновляет параметры существующего проекта."""
        with self._lock:
            if project_id not in self._projects:
                return False
            proj = self._projects[project_id]
            for key, val in kwargs.items():
                if key in (
                    "name", "description", "source_lang", "target_lang",
                    "ai_profile_id", "action_id", "context", "translation_rules", "notes",
                ):
                    proj[key] = str(val or "").strip()
                elif key in ("glossary_enabled", "context_memory_enabled", "context_memory_include_translation"):
                    proj[key] = bool(val)
                elif key == "context_memory_count":
                    proj[key] = max(1, min(int(val), 10))
                elif key == "context_memory_max_chars":
                    proj[key] = max(200, min(int(val), 10000))
                elif key == "glossary" and isinstance(val, list):
                    proj["glossary"] = val

            proj["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            return self._save()

    def duplicate_project(self, project_id: str) -> Optional[Dict[str, Any]]:
        """Создает копию существующего проекта."""
        with self._lock:
            source = self.get_project(project_id)
            if not source:
                return None
            new_id = f"proj_{uuid.uuid4().hex[:10]}"
            clone = deepcopy(source)
            clone["id"] = new_id
            clone["name"] = f"{source.get('name', 'Проект')} (Копия)"
            now = time.strftime("%Y-%m-%d %H:%M:%S")
            clone["created_at"] = now
            clone["updated_at"] = now
            # Перегенерируем ID терминов в глоссарии
            new_glossary = []
            for t in clone.get("glossary", []):
                tc = deepcopy(t)
                tc["id"] = f"term_{uuid.uuid4().hex[:8]}"
                new_glossary.append(tc)
            clone["glossary"] = new_glossary

            self._projects[new_id] = clone
            self._save()
            return deepcopy(clone)

    def delete_project(self, project_id: str) -> bool:
        """Удаляет проект по ID."""
        with self._lock:
            if project_id not in self._projects:
                return False
            del self._projects[project_id]
            if self._active_project_id == project_id:
                self._active_project_id = ""
            if project_id in self._memory_chunks:
                del self._memory_chunks[project_id]
            return self._save()

    # ------------------------------------------------------------------ Глоссарий
    def add_glossary_term(
        self,
        project_id: str,
        source_term: str,
        target_term: str,
        category: str = "Другое",
        comment: str = "",
        examples: str = "",
        case_sensitive: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """Добавляет термин в глоссарий проекта."""
        with self._lock:
            if project_id not in self._projects:
                return None
            source_term = source_term.strip()
            target_term = target_term.strip()
            if not source_term or not target_term:
                return None

            term_id = f"term_{uuid.uuid4().hex[:8]}"
            term: Dict[str, Any] = {
                "id": term_id,
                "source_term": source_term,
                "target_term": target_term,
                "category": category.strip() or "Другое",
                "comment": comment.strip(),
                "examples": examples.strip(),
                "case_sensitive": bool(case_sensitive),
            }
            proj = self._projects[project_id]
            if "glossary" not in proj or not isinstance(proj["glossary"], list):
                proj["glossary"] = []
            proj["glossary"].append(term)
            proj["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            self._save()
            return deepcopy(term)

    def update_glossary_term(self, project_id: str, term_id: str, **kwargs: Any) -> bool:
        """Обновляет поля термина в глоссарии проекта."""
        with self._lock:
            if project_id not in self._projects:
                return False
            proj = self._projects[project_id]
            glossary = proj.get("glossary", [])
            for term in glossary:
                if term.get("id") == term_id:
                    for key, val in kwargs.items():
                        if key in ("source_term", "target_term", "category", "comment", "examples"):
                            term[key] = str(val or "").strip()
                        elif key == "case_sensitive":
                            term[key] = bool(val)
                    proj["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                    return self._save()
            return False

    def delete_glossary_term(self, project_id: str, term_id: str) -> bool:
        """Удаляет термин из глоссария проекта."""
        with self._lock:
            if project_id not in self._projects:
                return False
            proj = self._projects[project_id]
            glossary = proj.get("glossary", [])
            initial_len = len(glossary)
            proj["glossary"] = [t for t in glossary if t.get("id") != term_id]
            if len(proj["glossary"]) != initial_len:
                proj["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                return self._save()
            return False

    def list_glossary_terms(
        self, project_id: str, search: str = "", category: str = "all"
    ) -> List[Dict[str, Any]]:
        """Возвращает список терминов глоссария с фильтрацией по поисковой строке и категории."""
        with self._lock:
            proj = self.get_project(project_id)
            if not proj:
                return []
            glossary = proj.get("glossary", [])
            search = search.strip().lower()
            filtered = []
            for t in glossary:
                cat = str(t.get("category") or "Другое")
                if category and category != "all" and cat != category:
                    continue
                if search:
                    s_term = str(t.get("source_term") or "").lower()
                    t_term = str(t.get("target_term") or "").lower()
                    comm = str(t.get("comment") or "").lower()
                    ex = str(t.get("examples") or "").lower()
                    if (
                        search not in s_term
                        and search not in t_term
                        and search not in comm
                        and search not in ex
                    ):
                        continue
                filtered.append(t)
            # Сортируем по исходному термину
            filtered.sort(key=lambda x: str(x.get("source_term") or "").lower())
            return deepcopy(filtered)

    def find_matching_terms(self, project_id: str, text: str) -> List[Dict[str, Any]]:
        """Находит термины глоссария, которые реально присутствуют в переданном тексте.

        Сортирует совпадения по длине исходного термина (убывание), чтобы более
        длинные словосочетания имели приоритет.
        """
        if not text or not text.strip():
            return []

        with self._lock:
            proj = self.get_project(project_id)
            if not proj or not proj.get("glossary_enabled", True):
                return []

            glossary = proj.get("glossary", [])
            matches = []
            for t in glossary:
                s_term = str(t.get("source_term") or "").strip()
                if not s_term:
                    continue
                case_sensitive = bool(t.get("case_sensitive", False))
                if term_matches_text(s_term, text, case_sensitive=case_sensitive):
                    matches.append(t)

            # Длинные термины впереди
            matches.sort(key=lambda t: len(str(t.get("source_term") or "")), reverse=True)
            return deepcopy(matches)

    def find_duplicate_terms(self, project_id: str) -> List[Dict[str, Any]]:
        """Находит повторяющиеся исходные термины (регистронезависимо)."""
        with self._lock:
            proj = self.get_project(project_id)
            if not proj:
                return []
            glossary = proj.get("glossary", [])
            seen: Dict[str, List[Dict[str, Any]]] = {}
            for t in glossary:
                key = str(t.get("source_term") or "").strip().lower()
                if key:
                    seen.setdefault(key, []).append(t)

            duplicates: List[Dict[str, Any]] = []
            for key, items in seen.items():
                if len(items) > 1:
                    duplicates.extend(items)
            return deepcopy(duplicates)

    def import_glossary_file(self, project_id: str, file_path: str | Path) -> Tuple[int, int]:
        """Импортирует словарь из файла JSON или CSV.

        Возвращает (кол-во добавленных, кол-во пропущенных/ошибочных).
        """
        path = Path(file_path)
        if not path.exists():
            return (0, 0)

        imported = 0
        skipped = 0
        ext = path.suffix.lower()

        with self._lock:
            if project_id not in self._projects:
                return (0, 0)

            new_terms: List[Dict[str, Any]] = []

            if ext == ".json":
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    items = data if isinstance(data, list) else data.get("glossary", [])
                    for item in items:
                        if not isinstance(item, dict):
                            skipped += 1
                            continue
                        src = str(item.get("source_term") or item.get("source") or item.get("term") or "").strip()
                        tgt = str(item.get("target_term") or item.get("target") or item.get("translation") or "").strip()
                        if src and tgt:
                            new_terms.append({
                                "id": f"term_{uuid.uuid4().hex[:8]}",
                                "source_term": src,
                                "target_term": tgt,
                                "category": str(item.get("category") or "Другое").strip() or "Другое",
                                "comment": str(item.get("comment") or "").strip(),
                                "examples": str(item.get("examples") or "").strip(),
                                "case_sensitive": bool(item.get("case_sensitive", False)),
                            })
                            imported += 1
                        else:
                            skipped += 1
                except Exception as exc:
                    print(f"[projects] Ошибка импорта JSON: {exc}")
                    return (0, 0)

            elif ext in (".csv", ".tsv", ".txt"):
                try:
                    # Читаем с utf-8-sig для поддержки Excel BOM
                    with open(path, "r", encoding="utf-8-sig", newline="") as f:
                        sample = f.read(2048)
                        f.seek(0)
                        # Определяем разделитель
                        delimiter = ";" if ";" in sample else ("\t" if "\t" in sample else ",")
                        reader = csv.reader(f, delimiter=delimiter)
                        header = next(reader, None)

                        # Проверяем, есть ли именованные колонки
                        col_src = 0
                        col_tgt = 1
                        col_cat = 2
                        col_com = 3
                        col_ex = 4

                        if header:
                            low_h = [str(h).strip().lower() for h in header]
                            for idx, h in enumerate(low_h):
                                if h in ("source_term", "source", "term", "оригинал", "исходный термин"):
                                    col_src = idx
                                elif h in ("target_term", "target", "translation", "перевод", "утверждённый перевод"):
                                    col_tgt = idx
                                elif h in ("category", "категория"):
                                    col_cat = idx
                                elif h in ("comment", "комментарий", "примечание"):
                                    col_com = idx
                                elif h in ("examples", "примеры", "пример"):
                                    col_ex = idx

                        for row in reader:
                            if not row:
                                continue
                            if len(row) <= max(col_src, col_tgt):
                                skipped += 1
                                continue
                            src = str(row[col_src]).strip()
                            tgt = str(row[col_tgt]).strip()
                            if src and tgt:
                                cat = str(row[col_cat]).strip() if len(row) > col_cat else "Другое"
                                com = str(row[col_com]).strip() if len(row) > col_com else ""
                                ex = str(row[col_ex]).strip() if len(row) > col_ex else ""
                                new_terms.append({
                                    "id": f"term_{uuid.uuid4().hex[:8]}",
                                    "source_term": src,
                                    "target_term": tgt,
                                    "category": cat or "Другое",
                                    "comment": com,
                                    "examples": ex,
                                    "case_sensitive": False,
                                })
                                imported += 1
                            else:
                                skipped += 1
                except Exception as exc:
                    print(f"[projects] Ошибка импорта CSV: {exc}")
                    return (0, 0)

            if new_terms:
                proj = self._projects[project_id]
                if "glossary" not in proj or not isinstance(proj["glossary"], list):
                    proj["glossary"] = []
                proj["glossary"].extend(new_terms)
                proj["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                self._save()

        return (imported, skipped)

    def export_glossary_file(self, project_id: str, file_path: str | Path, format: str = "auto") -> int:
        """Экспортирует словарь проекта в JSON или CSV (с UTF-8 BOM)."""
        path = Path(file_path)
        with self._lock:
            proj = self.get_project(project_id)
            if not proj:
                return 0
            glossary = proj.get("glossary", [])
            path.parent.mkdir(parents=True, exist_ok=True)

            fmt = format.lower().strip()
            if fmt == "auto":
                fmt = "csv" if path.suffix.lower() == ".csv" else "json"

            if fmt == "json":
                export_data = []
                for t in glossary:
                    export_data.append({
                        "source_term": t.get("source_term", ""),
                        "target_term": t.get("target_term", ""),
                        "category": t.get("category", "Другое"),
                        "comment": t.get("comment", ""),
                        "examples": t.get("examples", ""),
                        "case_sensitive": bool(t.get("case_sensitive", False)),
                    })
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(export_data, f, ensure_ascii=False, indent=2)
                return len(export_data)

            # CSV с UTF-8 BOM для безупречного открытия в Excel
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.writer(f, delimiter=";")
                writer.writerow(["Исходный термин", "Утверждённый перевод", "Категория", "Комментарий", "Примеры"])
                for t in glossary:
                    writer.writerow([
                        t.get("source_term", ""),
                        t.get("target_term", ""),
                        t.get("category", "Другое"),
                        t.get("comment", ""),
                        t.get("examples", ""),
                    ])
                return len(glossary)

    # ------------------------------------------------------------------ Память фрагментов (Translation Memory)
    def add_memory_chunk(self, project_id: str, source_text: str, result_text: str) -> None:
        """Добавляет выполненный перевод в скользящий буфер памяти проекта."""
        if not project_id:
            return
        src = (source_text or "").strip()
        res = (result_text or "").strip()
        if not src or not res:
            return

        with self._lock:
            if project_id not in self._memory_chunks:
                self._memory_chunks[project_id] = []
            chunks = self._memory_chunks[project_id]
            chunks.append({
                "source": src,
                "result": res,
                "timestamp": time.strftime("%H:%M:%S"),
            })
            # Ограничиваем буфер последними 15 записями
            if len(chunks) > 15:
                self._memory_chunks[project_id] = chunks[-15:]

    def get_memory_chunks(self, project_id: str) -> List[Dict[str, str]]:
        """Возвращает текущие фрагменты из буфера памяти проекта."""
        with self._lock:
            return deepcopy(self._memory_chunks.get(project_id, []))

    def clear_memory(self, project_id: str) -> None:
        """Очищает накопленные фрагменты памяти для проекта."""
        with self._lock:
            if project_id in self._memory_chunks:
                self._memory_chunks[project_id] = []

    def format_memory_context(self, project_id: str) -> str:
        """Форматирует предшествующий контекст согласно настройкам проекта."""
        with self._lock:
            proj = self.get_project(project_id)
            if not proj or not proj.get("context_memory_enabled", False):
                return ""

            chunks = self._memory_chunks.get(project_id, [])
            if not chunks:
                return ""

            count = int(proj.get("context_memory_count", 3))
            max_chars = int(proj.get("context_memory_max_chars", 1500))
            include_translation = bool(proj.get("context_memory_include_translation", True))

            selected = chunks[-count:]
            lines: List[str] = []
            total_chars = 0

            # Формируем от более старых к более новым
            for idx, c in enumerate(selected, 1):
                src_part = c.get("source", "").strip()
                res_part = c.get("result", "").strip()
                if include_translation and res_part:
                    chunk_text = f"[Фрагмент {idx}]:\nОригинал: {src_part}\nПеревод: {res_part}"
                else:
                    chunk_text = f"[Фрагмент {idx}]:\n{src_part}"

                if total_chars + len(chunk_text) > max_chars and lines:
                    # Превышение лимита: останавливаемся
                    break
                lines.append(chunk_text)
                total_chars += len(chunk_text)

            if not lines:
                return ""

            return "ПРЕДШЕСТВУЮЩИЙ КОНТЕКСТ (ДЛЯ СВЯЗНОСТИ ПОВЕСТВОВАНИЯ):\n" + "\n\n".join(lines)

    # ------------------------------------------------------------------ Разовые заметки (Ad-hoc context)
    def set_ad_hoc_context(self, text: str) -> None:
        """Устанавливает разовый контекст/примечание для следующего запроса."""
        with self._lock:
            self._ad_hoc_context = (text or "").strip()

    def get_ad_hoc_context(self) -> str:
        """Получает текущий разовый контекст."""
        with self._lock:
            return self._ad_hoc_context

    def consume_ad_hoc_context(self) -> str:
        """Возвращает разовый контекст и сразу очищает его (однократное использование)."""
        with self._lock:
            val = self._ad_hoc_context
            self._ad_hoc_context = ""
            return val

    # ------------------------------------------------------------------ Сборщик промпт-контекста
    def build_prompt_context(
        self, source_text: str, project_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Собирает полный контекст проекта для передачи в системную инструкцию модели.

        Возвращает:
          - glossary_block: строка с утверждённым глоссарием
          - project_context_block: строка с контекстом произведения, правилами, памятью и разовой заметкой
          - matching_terms_count: число совпавших терминов
          - memory_chunks_count: число использованных фрагментов памяти
          - project_name: название активного проекта (или пустая строка)
          - is_project_active: флаг активности проекта
        """
        pid = project_id if project_id is not None else self.get_active_project_id()
        proj = self.get_project(pid) if pid else None

        if not proj:
            # Режим без проекта: проверяем разовую заметку
            ad_hoc = self.consume_ad_hoc_context()
            ctx_block = f"ВРЕМЕННОЕ ПРИМЕЧАНИЕ К ДАННОМУ ФРАГМЕНТУ:\n{ad_hoc}" if ad_hoc else ""
            return {
                "glossary_block": "",
                "project_context_block": ctx_block,
                "matching_terms_count": 0,
                "memory_chunks_count": 0,
                "project_name": "",
                "is_project_active": False,
            }

        # 1. Глоссарий
        glossary_block = ""
        matching_terms: List[Dict[str, Any]] = []
        if proj.get("glossary_enabled", True):
            matching_terms = self.find_matching_terms(pid, source_text)
            if matching_terms:
                glo_lines = [
                    "УТВЕРЖДЁННЫЙ ГЛОССАРИЙ ПРОЕКТА (ОБЯЗАТЕЛЬНО К СОБЛЮДЕНИЮ):",
                    "Следующие утверждённые варианты перевода имеют наивысший приоритет и не должны изменяться:",
                ]
                for t in matching_terms:
                    src = t.get("source_term", "")
                    tgt = t.get("target_term", "")
                    cat = t.get("category", "")
                    comm = t.get("comment", "")
                    extra = []
                    if cat and cat != "Другое":
                        extra.append(f"Категория: {cat}")
                    if comm:
                        extra.append(f"Примечание: {comm}")
                    extra_str = f" ({'; '.join(extra)})" if extra else ""
                    glo_lines.append(f"• «{src}» → «{tgt}»{extra_str}")
                glossary_block = "\n".join(glo_lines)

        # 2. Контекст, правила и заметки проекта
        ctx_parts: List[str] = []
        p_name = proj.get("name", "Проект")
        ctx_text = proj.get("context", "").strip()
        rules_text = proj.get("translation_rules", "").strip()

        header_lines = [f"ПРАВИЛА И КОНТЕКСТ ПРОЕКТА «{p_name}»:"]
        if ctx_text:
            header_lines.append(f"Контекст произведения:\n{ctx_text}")
        if rules_text:
            header_lines.append(f"Специальные правила перевода:\n{rules_text}")

        if len(header_lines) > 1:
            ctx_parts.append("\n\n".join(header_lines))

        # 3. Предшествующий контекст (память)
        mem_block = self.format_memory_context(pid)
        if mem_block:
            ctx_parts.append(mem_block)

        # 4. Разовая заметка к текущему фрагменту
        ad_hoc = self.consume_ad_hoc_context()
        if ad_hoc:
            ctx_parts.append(f"ВРЕМЕННОЕ ПРИМЕЧАНИЕ К ТЕКУЩЕМУ ФРАГМЕНТУ:\n{ad_hoc}")

        project_context_block = "\n\n".join(ctx_parts)

        return {
            "glossary_block": glossary_block,
            "project_context_block": project_context_block,
            "matching_terms_count": len(matching_terms),
            "memory_chunks_count": len(self.get_memory_chunks(pid)),
            "project_name": p_name,
            "is_project_active": True,
        }

    # ------------------------------------------------------------------ Проверка приватности
    @staticmethod
    def get_privacy_info(api_url: str, model_name: str, provider_type: str = "") -> Dict[str, Any]:
        """Определяет, отправляются ли данные в облако или обрабатываются локально."""
        url_lower = (api_url or "").lower().strip()
        is_local = (
            provider_type.lower() == "ollama"
            or "localhost" in url_lower
            or "127.0.0.1" in url_lower
            or "0.0.0.0" in url_lower
            or ":11434" in url_lower
        )
        if is_local:
            return {
                "is_local": True,
                "badge_text": "Локально (Ollama)",
                "tooltip": (
                    "Полная конфиденциальность: модель Ollama запущена локально на этом ПК.\n"
                    "Текст и контекст проекта никуда не передаются через интернет."
                ),
                "warning": "",
            }

        # Облачный провайдер
        host = url_lower.split("://")[-1].split("/")[0] if "://" in url_lower else url_lower
        return {
            "is_local": False,
            "badge_text": f"Облако ({model_name or 'AI'})",
            "tooltip": (
                f"Внимание: используется облачный AI-сервис ({host}).\n"
                f"Выделенный текст и контекст проекта отправляются внешнему провайдеру.\n"
                f"Для конфиденциальных текстов используйте профиль с локальной Ollama."
            ),
            "warning": (
                f"Внимание: облачный режим ({host}). Текст и контекст проекта передаются "
                f"внешнему AI-провайдеру. Для работы офлайн переключитесь на профиль Ollama."
            ),
        }


_GLOBAL_PROJECT_MANAGER: Optional[ProjectManager] = None


def get_project_manager(storage_path: Optional[os.PathLike | str] = None) -> ProjectManager:
    """Глобальный синглтон менеджера проектов."""
    global _GLOBAL_PROJECT_MANAGER
    if _GLOBAL_PROJECT_MANAGER is None or storage_path is not None:
        _GLOBAL_PROJECT_MANAGER = ProjectManager(storage_path=storage_path)
    return _GLOBAL_PROJECT_MANAGER
