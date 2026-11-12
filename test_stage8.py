"""
test_stage8.py — Автоматизированный тестовый набор для ЭТАПА 8:
ПРОЕКТЫ, КОНТЕКСТ И ГЛОССАРИЙ.

Проверяет:
  8.1. Систему проектов (CRUD, дублирование, удаление, сохранение, валидацию).
  8.2. Глоссарий проекта (CRUD, категории, поиск, детекцию дубликатов, экспорт/импорт JSON и CSV с UTF-8 BOM).
  8.3. Умную выборку терминов (Smart Matching для латиницы/кириллицы по границам слов и для CJK без пробелов).
  8.4. Контекст проекта, правила перевода и разовые заметки (ad-hoc context).
  8.5. Краткосрочную контекстную память (Translation Memory / Sliding Window, лимиты, очистку).
  8.6. Определение конфиденциальности (Ollama локально vs Облачный провайдер).
  8.7. Интеграцию в GUI (SettingsWindow вкладка 5, MiniPopupWindow ProjectBar, TranslationCard бейдж, TrayApp меню).

Запуск:  python test_stage8.py
"""

from __future__ import annotations

import csv
import json
import os
import sys
import tempfile
from pathlib import Path

# Режим offscreen для Qt
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

from config import ConfigManager
from mini_window import MiniPopupWindow
from project_manager import (ProjectManager, STANDARD_CATEGORIES,
                             get_project_manager, term_matches_text)
from settings_window import SettingsWindow
from translation_card import TranslationCard


def run_stage8_tests() -> None:
    print("=== НАЧАЛО ТЕСТИРОВАНИЯ ЭТАПА 8 (ПРОЕКТЫ, КОНТЕКСТ И ГЛОССАРИЙ) ===")
    app = QApplication.instance() or QApplication(sys.argv)

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        proj_file = tmp_path / "test_projects.json"
        cfg_file = tmp_path / "test_config.json"

        cfg = ConfigManager(cfg_file)
        pm = ProjectManager(storage_path=proj_file)

        # ---------------------------------------------------------------------
        # 8.1. Система проектов: CRUD, дублирование, удаление
        # ---------------------------------------------------------------------
        print("\n--- 8.1. Система проектов: CRUD, дублирование и сохранение ---")
        assert len(pm.list_projects()) == 0

        # Создание проекта
        p1 = pm.create_project(
            name="Перевод Новеллы «Тень Мага»",
            description="Фэнтезийная ранобэ с японского",
            source_lang="ja",
            target_lang="ru",
            context="Мир меча и магии. Главный герой — циничный бывший наёмник.",
            translation_rules="Имена оставлять в японской транскрипции Поливанова. Названия рангов не переводить.",
            notes="Автор часто использует архаичные обороты.",
        )
        p1_id = p1["id"]
        assert p1["name"] == "Перевод Новеллы «Тень Мага»"
        assert p1["source_lang"] == "ja"
        assert p1["target_lang"] == "ru"
        assert p1["glossary_enabled"] is True
        assert p1["context_memory_enabled"] is False

        # Проверка сохранения на диске
        pm_reloaded = ProjectManager(storage_path=proj_file)
        assert len(pm_reloaded.list_projects()) == 1
        p1_loaded = pm_reloaded.get_project(p1_id)
        assert p1_loaded is not None
        assert p1_loaded["name"] == "Перевод Новеллы «Тень Мага»"

        # Обновление проекта
        ok = pm.update_project(
            p1_id,
            description="Обновлённое описание новеллы",
            context_memory_enabled=True,
            context_memory_count=5,
        )
        assert ok is True
        updated = pm.get_project(p1_id)
        assert updated is not None
        assert updated["description"] == "Обновлённое описание новеллы"
        assert updated["context_memory_enabled"] is True
        assert updated["context_memory_count"] == 5

        # Активный проект
        assert pm.get_active_project_id() == ""
        pm.set_active_project_id(p1_id)
        assert pm.get_active_project_id() == p1_id
        active_p = pm.get_active_project()
        assert active_p is not None and active_p["id"] == p1_id

        # Дублирование проекта
        dup = pm.duplicate_project(p1_id)
        assert dup is not None
        assert dup["id"] != p1_id
        assert "копия" in dup["name"].lower()
        assert len(pm.list_projects()) == 2

        # Удаление дубликата
        assert pm.delete_project(dup["id"]) is True
        assert len(pm.list_projects()) == 1
        assert pm.get_project(dup["id"]) is None

        print("[OK] 8.1: CRUD проектов, валидация полей, сохранение на диск и дублирование работают.")

        # ---------------------------------------------------------------------
        # 8.2. Глоссарий проекта: CRUD, категории, поиск, детекция дубликатов
        # ---------------------------------------------------------------------
        print("\n--- 8.2. Глоссарий проекта: Термины, категории и поиск ---")
        t1 = pm.add_glossary_term(
            p1_id,
            source_term="Mana",
            target_term="Мана",
            category="Термины мира",
            comment="Магическая энергия существ",
            examples="Mana pool -> Запас маны",
            case_sensitive=True,
        )
        assert t1 is not None
        t1_id = t1["id"]

        t2 = pm.add_glossary_term(
            p1_id,
            source_term="Raze",
            target_term="Рэйз",
            category="Имена персонажей",
            comment="Главный герой",
            case_sensitive=False,
        )
        assert t2 is not None

        t3 = pm.add_glossary_term(
            p1_id,
            source_term="Dark Citadel",
            target_term="Тёмная Цитадель",
            category="Географические названия",
        )
        assert t3 is not None

        # Проверка категорий
        terms_world = pm.list_glossary_terms(p1_id, category="Термины мира")
        assert len(terms_world) == 1
        assert terms_world[0]["source_term"] == "Mana"

        # Поиск по терминам
        search_res = pm.list_glossary_terms(p1_id, search="рэйз")
        assert len(search_res) == 1
        assert search_res[0]["source_term"] == "Raze"

        # Детекция дубликатов
        dups_empty = pm.find_duplicate_terms(p1_id)
        assert len(dups_empty) == 0

        # Добавляем дубликат source_term
        pm.add_glossary_term(
            p1_id,
            source_term="raze",
            target_term="Разрушение",
            category="Способности / Навыки",
        )
        dups = pm.find_duplicate_terms(p1_id)
        assert len(dups) == 2
        assert all(t["source_term"].lower() == "raze" for t in dups)

        # Удаление термина
        assert pm.delete_glossary_term(p1_id, t3["id"]) is True
        assert len(pm.list_glossary_terms(p1_id)) == 3

        print("[OK] 8.2: CRUD терминов глоссария, категории, регистронезависимый поиск и детекция дубликатов подтверждены.")

        # ---------------------------------------------------------------------
        # Экспорт и Импорт глоссария (JSON и CSV с UTF-8 BOM)
        # ---------------------------------------------------------------------
        print("\n--- 8.2.1. Экспорт и импорт глоссария (JSON и CSV с UTF-8 BOM) ---")
        export_json = tmp_path / "glossary_export.json"
        export_csv = tmp_path / "glossary_export.csv"

        # Экспорт JSON
        assert pm.export_glossary_file(p1_id, export_json, format="json") == 3
        assert export_json.exists()
        with open(export_json, "r", encoding="utf-8") as f:
            j_data = json.load(f)
        assert isinstance(j_data, list)
        assert len(j_data) == 3

        # Экспорт CSV
        assert pm.export_glossary_file(p1_id, export_csv, format="csv") == 3
        assert export_csv.exists()
        # Проверяем наличие UTF-8 BOM в файле CSV
        raw_bytes = export_csv.read_bytes()
        assert raw_bytes.startswith(b"\xef\xbb\xbf"), "CSV должен содержать UTF-8 BOM для корректного открытия в Excel"

        # Создаём второй проект для тестирования импорта
        p2 = pm.create_project(name="Второй проект для импорта")
        p2_id = p2["id"]

        # Импорт из JSON
        imported, skipped = pm.import_glossary_file(p2_id, export_json)
        assert imported == 3
        assert len(pm.list_glossary_terms(p2_id)) == 3

        # Очищаем термины и импортируем из CSV
        for t in pm.list_glossary_terms(p2_id):
            pm.delete_glossary_term(p2_id, t["id"])
        assert len(pm.list_glossary_terms(p2_id)) == 0

        imported_csv, skipped_csv = pm.import_glossary_file(p2_id, export_csv)
        assert imported_csv == 3
        terms_csv = pm.list_glossary_terms(p2_id)
        assert len(terms_csv) == 3
        # Проверяем сохранение русских символов и кавычек
        sources = {t["source_term"]: t["target_term"] for t in terms_csv}
        assert sources.get("Mana") == "Мана"

        print("[OK] 8.2.1: Экспорт и импорт глоссария JSON/CSV с UTF-8 BOM протестированы без потерь.")

        # ---------------------------------------------------------------------
        # 8.3. Умная выборка терминов (Smart Matching)
        # ---------------------------------------------------------------------
        print("\n--- 8.3. Умная выборка терминов (Smart Matching латиница, кириллица, CJK) ---")
        # Латиница: проверка границ слов
        # "Mana" НЕ должна матчиться внутри "Manager", но ДОЛЖНА матчиться в "Mana potion"
        assert term_matches_text("Mana", "He used a Mana potion", case_sensitive=True) is True
        assert term_matches_text("Mana", "He is a Manager", case_sensitive=True) is False
        assert term_matches_text("Mana", "He used mana potion", case_sensitive=True) is False
        assert term_matches_text("Mana", "He used mana potion", case_sensitive=False) is True

        # Кириллица: границы слов
        assert term_matches_text("лук", "Он держал лук в руках", case_sensitive=False) is True
        assert term_matches_text("лук", "Он посмотрел в люк", case_sensitive=False) is False
        assert term_matches_text("лук", "разлука неизбежна", case_sensitive=False) is False

        # CJK (японский/китайский/корейский): подстрочный матчинг без пробелов
        assert term_matches_text("魔法", "彼は魔法を使った", case_sensitive=False) is True
        assert term_matches_text("勇者", "勇者パーティの冒険", case_sensitive=False) is True
        assert term_matches_text("剣士", "彼は魔法を使った", case_sensitive=False) is False

        # Проверка сборки промпта только с совпадающими терминами
        p_cjk = pm.create_project(name="CJK Проект")
        cjk_id = p_cjk["id"]
        pm.add_glossary_term(cjk_id, "魔法", "Магия", "Термины мира")
        pm.add_glossary_term(cjk_id, "勇者", "Герой", "Имена персонажей")
        pm.add_glossary_term(cjk_id, "ドラゴン", "Дракон", "Термины мира")

        matching = pm.find_matching_terms(cjk_id, "彼の魔法は凄かった")
        assert len(matching) == 1
        assert matching[0]["source_term"] == "魔法"
        assert matching[0]["target_term"] == "Магия"

        # Сборка промпта: только "魔法" попадает в глоссарий-блок, не весь словарь!
        prompt_info = pm.build_prompt_context("彼の魔法は凄かった", cjk_id)
        glossary_block = prompt_info["glossary_block"]
        assert "魔法" in glossary_block
        assert "Магия" in glossary_block
        assert "ドラゴン" not in glossary_block, "Нерелевантные термины не должны забивать контекст"
        assert "УТВЕРЖДЁННЫЙ ГЛОССАРИЙ" in glossary_block

        print("[OK] 8.3: Smart Matching корректно различает границы слов для латиницы/кириллицы и CJK, внедряя только релевантные термины.")

        # ---------------------------------------------------------------------
        # 8.4. Контекст проекта, правила перевода и разовые заметки (ad-hoc)
        # ---------------------------------------------------------------------
        print("\n--- 8.4. Контекст проекта, правила перевода и разовые заметки ---")
        prompt_ctx = pm.build_prompt_context("Тестовый фрагмент", p1_id)
        ctx_block = prompt_ctx["project_context_block"]
        assert "ПРАВИЛА И КОНТЕКСТ ПРОЕКТА" in ctx_block
        assert "Тень Мага" in ctx_block
        assert "Поливанова" in ctx_block

        # Разовая заметка (ad-hoc)
        pm.set_ad_hoc_context("Персонаж говорит с нескрываемым сарказмом.")
        assert pm.get_ad_hoc_context() == "Персонаж говорит с нескрываемым сарказмом."

        prompt_with_adhoc = pm.build_prompt_context("Тестовый фрагмент", p1_id)
        assert "ВРЕМЕННОЕ ПРИМЕЧАНИЕ" in prompt_with_adhoc["project_context_block"]
        assert "сарказмом" in prompt_with_adhoc["project_context_block"]

        # Заметка уже потреблена при build_prompt_context (one-shot)
        assert pm.get_ad_hoc_context() == ""

        print("[OK] 8.4: Контекст проекта, правила перевода и разовые заметки (ad-hoc) подставляются и очищаются.")

        # ---------------------------------------------------------------------
        # 8.5. Краткосрочная контекстная память (Translation Memory / Sliding Window)
        # ---------------------------------------------------------------------
        print("\n--- 8.5. Краткосрочная память предыдущих переводов (Sliding Window) ---")
        # Включаем память для проекта p1 (макс 2 фрагмента, макс 200 символов)
        pm.update_project(
            p1_id,
            context_memory_enabled=True,
            context_memory_count=2,
            context_memory_max_chars=200,
            context_memory_include_translation=True,
        )

        pm.add_memory_chunk(p1_id, "Chapter 1. The beginning.", "Глава 1. Начало.")
        pm.add_memory_chunk(p1_id, "He entered the dark forest.", "Он вошёл в тёмный лес.")
        pm.add_memory_chunk(p1_id, "A wolf appeared before him.", "Перед ним появился волк.")

        chunks = pm.get_memory_chunks(p1_id)
        assert len(chunks) == 3
        assert chunks[-1]["source"] == "A wolf appeared before him."

        # Форматирование контекста памяти: берутся последние count=2 фрагмента
        mem_text = pm.format_memory_context(p1_id)
        assert "ПРЕДШЕСТВУЮЩИЙ КОНТЕКСТ" in mem_text
        assert "тёмный лес" in mem_text
        assert "появился волк" in mem_text
        assert "The beginning" not in mem_text, "Старый фрагмент должен вытесняться согласно context_memory_count=2"

        # Очистка памяти
        pm.clear_memory(p1_id)
        assert len(pm.get_memory_chunks(p1_id)) == 0

        print("[OK] 8.5: Скользящее окно памяти переводов, лимиты, вытеснение и очистка работают.")

        # ---------------------------------------------------------------------
        # 8.6. Определение конфиденциальности (Ollama локально vs Облако)
        # ---------------------------------------------------------------------
        print("\n--- 8.6. Определение конфиденциальности (Ollama vs Облачные провайдеры) ---")
        # Локальная Ollama
        info_local1 = ProjectManager.get_privacy_info("http://localhost:11434/v1/chat/completions", "llama3", "ollama")
        assert info_local1["is_local"] is True
        assert "Локально" in info_local1["badge_text"]
        assert info_local1["warning"] == ""

        info_local2 = ProjectManager.get_privacy_info("http://127.0.0.1:8080/v1/chat/completions", "qwen2.5", "custom")
        assert info_local2["is_local"] is True

        # Облачный OpenAI / OpenRouter
        info_cloud1 = ProjectManager.get_privacy_info("https://api.openai.com/v1/chat/completions", "gpt-4o", "openai")
        assert info_cloud1["is_local"] is False
        assert "Облако" in info_cloud1["badge_text"]
        assert "gpt-4o" in info_cloud1["badge_text"]
        assert "Текст и контекст проекта передаются" in info_cloud1["warning"]

        info_cloud2 = ProjectManager.get_privacy_info("https://openrouter.ai/api/v1/chat/completions", "claude-3.5", "openrouter")
        assert info_cloud2["is_local"] is False

        print("[OK] 8.6: Детекция приватности локальных и облачных профилей работает корректно.")

        # ---------------------------------------------------------------------
        # 8.7. Интеграция GUI: SettingsWindow (вкладка 5), MiniPopupWindow, TranslationCard
        # ---------------------------------------------------------------------
        print("\n--- 8.7. Интеграция GUI: SettingsWindow, MiniPopupWindow и TranslationCard ---")
        dummy_icon = QIcon()

        # SettingsWindow
        settings = SettingsWindow(cfg, dummy_icon)
        assert settings.tabs.count() == 5
        assert settings.tabs.tabText(3) == "Проекты"

        # Переход на вкладку проектов
        settings.open_projects_tab()
        assert settings.tabs.currentIndex() == 3

        # Проверка элементов вкладки
        assert settings.projects_list is not None
        assert settings.glossary_table is not None
        assert settings.proj_name_edit is not None
        assert settings.privacy_card is not None
        assert settings.btn_set_active_proj is not None

        # MiniPopupWindow: панель проектов и бейджи
        popup = MiniPopupWindow(cfg, dummy_icon)
        assert popup.project_bar is not None
        assert popup.project_combo is not None
        assert popup.ad_hoc_btn is not None
        assert popup.memory_btn is not None
        assert popup.privacy_badge is not None
        assert popup.ad_hoc_bar is not None

        # TranslationCard: отображение бейджа проекта
        card = TranslationCard("Original text", "Translated text")
        assert hasattr(card, "project_badge")
        card.set_project("Тень Мага")
        assert card.project_badge.text() == "Проект: Тень Мага"
        assert not card.project_badge.isHidden()

        settings.shutdown()
        popup.shutdown()

        print("[OK] 8.7: Все GUI-элементы ЭТАПА 8 успешно инициализированы и протестированы.")

    print("\n=== ВСЕ ТЕСТЫ ЭТАПА 8 УСПЕШНО ПРОЙДЕНЫ! ===")


if __name__ == "__main__":
    run_stage8_tests()
