"""
history_manager.py — долговременное хранение истории переводов и действий в SQLite (ЭТАП 7).

Обеспечивает:
  • Локальное безопасное хранение в SQLite (history.db).
  • Исключение API-ключей из базы данных.
  • Постраничную выборку (LIMIT/OFFSET), быстрый поиск и фильтрацию по полям.
  • Избранное (is_favorite).
  • Экспорт в форматы TXT, JSON, CSV (UTF-8 BOM для Excel).
  • Резервное копирование базы данных (sqlite3 backup API).
  • Настройку срока хранения (retention policy) и очистку.
  • Потокобезопасность (WAL-режим, thread lock).
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import shutil
import sqlite3
import sys
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

DB_FILENAME = "history.db"


def default_db_path() -> Path:
    """Путь к файлу history.db рядом с приложением (или исполняемым файлом)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / DB_FILENAME
    return Path(__file__).resolve().parent / DB_FILENAME


class HistoryManager:
    """Управляет базой данных SQLite для постоянной истории операций Truniversal."""

    def __init__(self, db_path: Optional[os.PathLike | str] = None) -> None:
        if db_path is None:
            self.db_path = default_db_path()
        elif str(db_path) == ":memory:":
            self.db_path = Path(":memory:")
        else:
            self.db_path = Path(db_path)

        self._lock = threading.Lock()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """Создает и настраивает соединение с базой данных."""
        if str(self.db_path) == ":memory:":
            if not hasattr(self, "_memory_conn"):
                self._memory_conn = sqlite3.connect(":memory:", check_same_thread=False)
                self._memory_conn.row_factory = sqlite3.Row
            return self._memory_conn

        conn = sqlite3.connect(str(self.db_path), timeout=10.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        # Оптимизация для высокой производительности и параллелизма
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
        except Exception:
            pass
        return conn

    def _init_db(self) -> None:
        """Создает схему таблиц и необходимые индексы."""
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        source_text TEXT NOT NULL,
                        result_text TEXT NOT NULL,
                        action_id TEXT,
                        action_name TEXT,
                        prompt_text TEXT,
                        provider_type TEXT,
                        model_name TEXT,
                        source_lang TEXT,
                        target_lang TEXT,
                        direction TEXT,
                        created_at TEXT NOT NULL,
                        project_context TEXT,
                        is_favorite INTEGER DEFAULT 0,
                        is_edited INTEGER DEFAULT 0,
                        variants_json TEXT
                    );
                    """
                )
                conn.execute("CREATE INDEX IF NOT EXISTS idx_history_created_at ON history(created_at DESC);")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_history_favorite ON history(is_favorite);")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_history_action_id ON history(action_id);")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_history_model ON history(model_name);")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_history_project ON history(project_context);")
                conn.commit()
            finally:
                if str(self.db_path) != ":memory:":
                    conn.close()

    # ---------------------------------------------------------------- Запись
    def add_record(
        self,
        source_text: str,
        result_text: str,
        action_id: str = "",
        action_name: str = "",
        prompt_text: str = "",
        provider_type: str = "",
        model_name: str = "",
        source_lang: str = "",
        target_lang: str = "",
        direction: str = "",
        project_context: str = "",
        is_favorite: bool = False,
        is_edited: bool = False,
        variants_json: str = "",
        created_at: Optional[str] = None,
    ) -> int:
        """Сохраняет выполненную операцию в историю.
        
        ГАРАНТИЯ БЕЗОПАСНОСТИ: API-ключи сюда не передаются и не сохраняются.
        Возвращает ID созданной записи.
        """
        source_text = str(source_text or "").strip()
        result_text = str(result_text or "").strip()
        if not source_text or not result_text:
            return -1

        if not created_at:
            created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with self._lock:
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    INSERT INTO history (
                        source_text, result_text, action_id, action_name, prompt_text,
                        provider_type, model_name, source_lang, target_lang, direction,
                        created_at, project_context, is_favorite, is_edited, variants_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        source_text,
                        result_text,
                        str(action_id or ""),
                        str(action_name or ""),
                        str(prompt_text or ""),
                        str(provider_type or ""),
                        str(model_name or ""),
                        str(source_lang or ""),
                        str(target_lang or ""),
                        str(direction or ""),
                        created_at,
                        str(project_context or ""),
                        1 if is_favorite else 0,
                        1 if is_edited else 0,
                        str(variants_json or ""),
                    ),
                )
                conn.commit()
                return int(cur.lastrowid or -1)
            finally:
                if str(self.db_path) != ":memory:":
                    conn.close()

    # ------------------------------------------------------------- Обновление
    def toggle_favorite(self, record_id: int) -> bool:
        """Переключает статус «Избранное» для записи. Возвращает новое состояние."""
        with self._lock:
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                cur.execute("SELECT is_favorite FROM history WHERE id = ?", (record_id,))
                row = cur.fetchone()
                if not row:
                    return False
                new_state = 0 if row["is_favorite"] else 1
                cur.execute("UPDATE history SET is_favorite = ? WHERE id = ?", (new_state, record_id))
                conn.commit()
                return bool(new_state)
            finally:
                if str(self.db_path) != ":memory:":
                    conn.close()

    def set_favorite(self, record_id: int, is_favorite: bool) -> bool:
        """Устанавливает статус «Избранное»."""
        with self._lock:
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                cur.execute("UPDATE history SET is_favorite = ? WHERE id = ?", (1 if is_favorite else 0, record_id))
                conn.commit()
                return cur.rowcount > 0
            finally:
                if str(self.db_path) != ":memory:":
                    conn.close()

    def update_result_text(self, record_id: int, new_result: str, is_edited: bool = True) -> bool:
        """Обновляет результат (когда пользователь вручную отредактировал карточку)."""
        new_result = str(new_result or "").strip()
        if not new_result:
            return False
        with self._lock:
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                cur.execute(
                    "UPDATE history SET result_text = ?, is_edited = ? WHERE id = ?",
                    (new_result, 1 if is_edited else 0, record_id),
                )
                conn.commit()
                return cur.rowcount > 0
            finally:
                if str(self.db_path) != ":memory:":
                    conn.close()

    # --------------------------------------------------------------- Удаление
    def delete_record(self, record_id: int) -> bool:
        """Удаляет запись по ID."""
        with self._lock:
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                cur.execute("DELETE FROM history WHERE id = ?", (record_id,))
                conn.commit()
                return cur.rowcount > 0
            finally:
                if str(self.db_path) != ":memory:":
                    conn.close()

    def clear_all(self, keep_favorites: bool = False) -> int:
        """Очищает всю историю. Возвращает количество удалённых записей."""
        with self._lock:
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                if keep_favorites:
                    cur.execute("DELETE FROM history WHERE is_favorite = 0")
                else:
                    cur.execute("DELETE FROM history")
                deleted = cur.rowcount
                conn.commit()
                return deleted
            finally:
                if str(self.db_path) != ":memory:":
                    conn.close()

    def clear_older_than(self, days: int, keep_favorites: bool = True) -> int:
        """Удаляет записи старше указанного количества дней."""
        if days <= 0:
            return 0
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        with self._lock:
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                if keep_favorites:
                    cur.execute("DELETE FROM history WHERE created_at < ? AND is_favorite = 0", (cutoff,))
                else:
                    cur.execute("DELETE FROM history WHERE created_at < ?", (cutoff,))
                deleted = cur.rowcount
                conn.commit()
                return deleted
            finally:
                if str(self.db_path) != ":memory:":
                    conn.close()

    def clear_period(self, date_from: Optional[str] = None, date_to: Optional[str] = None, keep_favorites: bool = False) -> int:
        """Удаляет записи за указанный диапазон дат (формат строк 'YYYY-MM-DD' или 'YYYY-MM-DD HH:MM:SS')."""
        clauses = []
        params = []
        if date_from:
            clauses.append("created_at >= ?")
            params.append(date_from if len(date_from) > 10 else f"{date_from} 00:00:00")
        if date_to:
            clauses.append("created_at <= ?")
            params.append(date_to if len(date_to) > 10 else f"{date_to} 23:59:59")
        if keep_favorites:
            clauses.append("is_favorite = 0")

        where_sql = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._lock:
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                cur.execute(f"DELETE FROM history{where_sql}", params)
                deleted = cur.rowcount
                conn.commit()
                return deleted
            finally:
                if str(self.db_path) != ":memory:":
                    conn.close()

    def apply_retention_policy(self, retention_days: int) -> int:
        """Применяет настройку срока хранения. 0 = бессрочно (не удалять)."""
        if retention_days <= 0:
            return 0
        # Избранные записи сохраняются независимо от срока давности
        return self.clear_older_than(retention_days, keep_favorites=True)

    # ---------------------------------------------------- Чтение и фильтрация
    def get_record(self, record_id: int) -> Optional[Dict[str, Any]]:
        """Возвращает запись по ID в виде словаря."""
        with self._lock:
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                cur.execute("SELECT * FROM history WHERE id = ?", (record_id,))
                row = cur.fetchone()
                return dict(row) if row else None
            finally:
                if str(self.db_path) != ":memory:":
                    conn.close()

    def list_records(
        self,
        limit: int = 50,
        offset: int = 0,
        search_text: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        action_id: Optional[str] = None,
        model_name: Optional[str] = None,
        project_context: Optional[str] = None,
        is_favorite: Optional[bool] = None,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Возвращает страницу записей (LIMIT, OFFSET) и общее количество подходящих записей.
        
        Обеспечивает высокую отзывчивость интерфейса при базе любого размера.
        """
        clauses = []
        params: List[Any] = []

        if search_text and search_text.strip():
            st = f"%{search_text.strip()}%"
            clauses.append("(source_text LIKE ? OR result_text LIKE ? OR project_context LIKE ?)")
            params.extend([st, st, st])

        if date_from and date_from.strip():
            df = date_from.strip()
            clauses.append("created_at >= ?")
            params.append(df if len(df) > 10 else f"{df} 00:00:00")

        if date_to and date_to.strip():
            dt = date_to.strip()
            clauses.append("created_at <= ?")
            params.append(dt if len(dt) > 10 else f"{dt} 23:59:59")

        if action_id and action_id.strip() and action_id != "all":
            clauses.append("action_id = ?")
            params.append(action_id.strip())

        if model_name and model_name.strip() and model_name != "all":
            clauses.append("model_name = ?")
            params.append(model_name.strip())

        if project_context and project_context.strip() and project_context != "all":
            if project_context == "__none__":
                clauses.append("(project_context IS NULL OR project_context = '')")
            else:
                clauses.append("project_context = ?")
                params.append(project_context.strip())

        if is_favorite is True:
            clauses.append("is_favorite = 1")
        elif is_favorite is False:
            clauses.append("is_favorite = 0")

        where_sql = (" WHERE " + " AND ".join(clauses)) if clauses else ""

        with self._lock:
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                # 1. Считаем общее число для пагинатора
                count_query = f"SELECT COUNT(*) AS cnt FROM history{where_sql}"
                cur.execute(count_query, params)
                total_count = cur.fetchone()["cnt"]

                # 2. Выбираем страницу
                select_query = (
                    f"SELECT * FROM history{where_sql} "
                    f"ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?"
                )
                query_params = list(params)
                query_params.extend([max(limit, 1), max(offset, 0)])
                cur.execute(select_query, query_params)
                rows = [dict(r) for r in cur.fetchall()]
                return rows, total_count
            finally:
                if str(self.db_path) != ":memory:":
                    conn.close()

    def get_filter_options(self) -> Dict[str, List[str]]:
        """Возвращает уникальные значения действий, моделей и проектов для выпадающих списков фильтров."""
        with self._lock:
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                cur.execute("SELECT DISTINCT action_name, action_id FROM history WHERE action_id != '' ORDER BY action_name ASC")
                actions = [{"id": r["action_id"], "name": r["action_name"] or r["action_id"]} for r in cur.fetchall()]

                cur.execute("SELECT DISTINCT model_name FROM history WHERE model_name != '' ORDER BY model_name ASC")
                models = [r["model_name"] for r in cur.fetchall()]

                cur.execute("SELECT DISTINCT project_context FROM history WHERE project_context != '' ORDER BY project_context ASC")
                projects = [r["project_context"] for r in cur.fetchall()]

                return {
                    "actions": actions,  # list of dicts: {'id': '...', 'name': '...'}
                    "models": models,
                    "projects": projects,
                }
            finally:
                if str(self.db_path) != ":memory:":
                    conn.close()

    # ----------------------------------------------------------------- Экспорт
    def export_data(
        self,
        format_type: str,
        target_path: Optional[os.PathLike | str] = None,
        search_text: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        action_id: Optional[str] = None,
        model_name: Optional[str] = None,
        project_context: Optional[str] = None,
        is_favorite: Optional[bool] = None,
    ) -> str:
        """Экспортирует записи истории в TXT, JSON или CSV.
        
        Если target_path указан — сохраняет в файл и возвращает путь.
        Если target_path не указан — возвращает строку с содержимым.
        """
        # Экспортируем все подходящие записи (до 50 000 за раз)
        records, _ = self.list_records(
            limit=50000,
            offset=0,
            search_text=search_text,
            date_from=date_from,
            date_to=date_to,
            action_id=action_id,
            model_name=model_name,
            project_context=project_context,
            is_favorite=is_favorite,
        )

        fmt = format_type.strip().lower()
        content = ""

        if fmt == "json":
            # Чистый JSON-экспорт
            content = json.dumps(records, ensure_ascii=False, indent=2)

        elif fmt == "csv":
            # CSV с UTF-8 BOM для безупречного открытия в Microsoft Excel
            output = io.StringIO()
            fieldnames = [
                "id", "created_at", "action_name", "direction",
                "model_name", "provider_type", "project_context",
                "is_favorite", "is_edited", "source_text", "result_text"
            ]
            writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for r in records:
                writer.writerow(r)
            content = output.getvalue()

        else:  # TXT
            # Удобочитаемый текстовый документ с разделителями
            lines = [
                "=" * 80,
                "Truniversal — Экспорт истории операций",
                f"Всего записей: {len(records)}",
                f"Дата экспорта: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                "=" * 80,
                "",
            ]
            for r in records:
                fav_mark = " [Избранное]" if r.get("is_favorite") else ""
                edited_mark = " (отредактировано)" if r.get("is_edited") else ""
                lines.append(f"Запись #{r.get('id')} | {r.get('created_at')}{fav_mark}")
                lines.append(f"Действие: {r.get('action_name') or r.get('action_id') or 'Перевод'}")
                lines.append(f"Направление: {r.get('direction') or 'авто'} | Модель: {r.get('model_name') or 'стандарт'}")
                if r.get("project_context"):
                    lines.append(f"Проект: {r.get('project_context')}")
                lines.append("-" * 40)
                lines.append("ИСХОДНЫЙ ТЕКСТ:")
                lines.append(r.get("source_text", ""))
                lines.append("-" * 40)
                lines.append(f"РЕЗУЛЬТАТ{edited_mark}:")
                lines.append(r.get("result_text", ""))
                lines.append("\n" + "=" * 80 + "\n")
            content = "\n".join(lines)

        if target_path:
            p = Path(target_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            if fmt == "csv":
                # utf-8-sig добавляет BOM для Excel
                p.write_text(content, encoding="utf-8-sig")
            else:
                p.write_text(content, encoding="utf-8")
            return str(p)

        return content

    # ----------------------------------------------------- Резервное копирование
    def backup_database(self, backup_path: Optional[os.PathLike | str] = None) -> str:
        """Создает резервную копию базы данных SQLite через sqlite3 backup API.
        
        Гарантирует целостность копии даже при активных операциях записи.
        Возвращает путь к созданному файлу бэкапа.
        """
        if str(self.db_path) == ":memory:":
            raise ValueError("Резервное копирование in-memory базы данных не поддерживается на диск.")

        if backup_path is None:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = self.db_path.with_name(f"history_backup_{ts}.db")
        else:
            backup_path = Path(backup_path)

        backup_path.parent.mkdir(parents=True, exist_ok=True)

        with self._lock:
            src_conn = self._get_connection()
            try:
                dest_conn = sqlite3.connect(str(backup_path))
                try:
                    src_conn.backup(dest_conn)
                finally:
                    dest_conn.close()
            finally:
                src_conn.close()

        return str(backup_path)


# Глобальный синглтон-экземпляр
_history_instance: Optional[HistoryManager] = None
_history_lock = threading.Lock()


def get_history_manager(db_path: Optional[os.PathLike | str] = None) -> HistoryManager:
    """Возвращает глобальный менеджер истории."""
    global _history_instance
    with _history_lock:
        if _history_instance is None or (db_path is not None and _history_instance.db_path != Path(db_path)):
            _history_instance = HistoryManager(db_path=db_path)
        return _history_instance
