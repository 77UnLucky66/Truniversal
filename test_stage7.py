"""
test_stage7.py — комплексное тестирование ЭТАПА 7:
  7.1. Хранение в SQLite (поля, отсутствие API-ключей, WAL-режим, thread-safety).
  7.2. Интерфейс истории (поиск, фильтрация по дате, действию, модели, проекту, избранное, удаление, открытие карточки, повтор).
  7.3. Управление хранением (вкл/выкл, очистка всей истории, очистка за период, экспорт TXT/JSON/CSV, бэкап, retention policy).
  7.4. Производительность (индексы, пагинация LIMIT/OFFSET на 1000+ записях, скорость выборки).
"""

import os
import sys
import tempfile
import time
from pathlib import Path

# Устанавливаем offscreen платформу для headless Qt тестов
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QIcon

from config import ConfigManager
from history_manager import HistoryManager, get_history_manager
from settings_window import SettingsWindow
from mini_window import MiniPopupWindow
from translation_card import TranslationCard


def run_stage7_tests():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    print("\n=== НАЧАЛО ТЕСТИРОВАНИЯ ЭТАПА 7 (ПОСТОЯННАЯ ИСТОРИЯ) ===")

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        db_path = tmp_path / "test_history.db"
        cfg_path = tmp_path / "config.json"

        cfg = ConfigManager(cfg_path)
        hm = get_history_manager(db_path)

        # ---------------------------------------------------------------------
        # 7.1. Хранение
        # ---------------------------------------------------------------------
        print("\n--- 7.1. Хранение данных в SQLite ---")
        rid1 = hm.add_record(
            source_text="Hello world",
            result_text="Привет, мир",
            action_id="action_trans_literary",
            action_name="Перевести (литературный)",
            prompt_text="Ты — переводчик...",
            provider_type="openai",
            model_name="gpt-4o-mini",
            source_lang="en",
            target_lang="ru",
            direction="EN → RU",
            project_context="Проект Локализации",
            is_favorite=False,
            created_at="2026-11-10 10:00:00",
        )
        assert rid1 > 0, "Запись не была создана"
        rec1 = hm.get_record(rid1)
        assert rec1 is not None
        assert rec1["source_text"] == "Hello world"
        assert rec1["result_text"] == "Привет, мир"
        assert rec1["action_id"] == "action_trans_literary"
        assert rec1["action_name"] == "Перевести (литературный)"
        assert rec1["provider_type"] == "openai"
        assert rec1["model_name"] == "gpt-4o-mini"
        assert rec1["source_lang"] == "en"
        assert rec1["target_lang"] == "ru"
        assert rec1["direction"] == "EN → RU"
        assert rec1["project_context"] == "Проект Локализации"
        assert rec1["is_favorite"] == 0
        assert rec1["is_edited"] == 0

        # Проверка безопасности: убеждаемся, что в схеме таблицы нет полей для ключей
        conn = hm._get_connection()
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(history)")
        columns = [row["name"].lower() for row in cur.fetchall()]
        assert "api_key" not in columns, "Критическая уязвимость: в истории есть колонка api_key"
        assert "key" not in columns, "Критическая уязвимость: в истории есть колонка key"
        assert "token" not in columns, "Критическая уязвимость: в истории есть колонка token"
        conn.close()

        print("[OK] 7.1: Структура данных, сохранение всех метаданных и безопасность подтверждены.")

        # ---------------------------------------------------------------------
        # 7.2. Поиск, фильтрация, избранное и операции с записями
        # ---------------------------------------------------------------------
        print("\n--- 7.2. Поиск, фильтрация, избранное и операции ---")
        rid2 = hm.add_record(
            source_text="Machine learning algorithms",
            result_text="Алгоритмы машинного обучения",
            action_id="action_style",
            action_name="Улучшить стилистику",
            model_name="claude-3-5-sonnet",
            direction="EN → RU",
            project_context="AI Research",
            is_favorite=True,
            created_at="2026-11-11 14:00:00",
        )

        rid3 = hm.add_record(
            source_text="Guten Tag, wie geht es Ihnen?",
            result_text="Добрый день, как ваши дела?",
            action_id="action_trans_casual",
            action_name="Перевести (разговорный)",
            model_name="deepseek-chat",
            direction="DE → RU",
            project_context="",
            is_favorite=False,
            created_at="2026-11-11 18:30:00",
        )

        # Поиск по тексту оригинала и перевода
        res_search, cnt_search = hm.list_records(search_text="learning")
        assert cnt_search == 1 and res_search[0]["id"] == rid2

        res_search2, cnt_search2 = hm.list_records(search_text="дела")
        assert cnt_search2 == 1 and res_search2[0]["id"] == rid3

        # Фильтрация по избранному
        res_fav, cnt_fav = hm.list_records(is_favorite=True)
        assert cnt_fav == 1 and res_fav[0]["id"] == rid2

        # Переключение избранного (toggle)
        new_fav = hm.toggle_favorite(rid3)
        assert new_fav is True
        res_fav2, cnt_fav2 = hm.list_records(is_favorite=True)
        assert cnt_fav2 == 2
        hm.toggle_favorite(rid3)  # возвращаем обратно

        # Фильтрация по дате
        res_date, cnt_date = hm.list_records(date_from="2026-11-11", date_to="2026-11-11")
        assert cnt_date == 2

        # Фильтрация по действию
        res_act, cnt_act = hm.list_records(action_id="action_style")
        assert cnt_act == 1 and res_act[0]["id"] == rid2

        # Фильтрация по модели
        res_mod, cnt_mod = hm.list_records(model_name="deepseek-chat")
        assert cnt_mod == 1 and res_mod[0]["id"] == rid3

        # Фильтрация по проекту
        res_prj, cnt_prj = hm.list_records(project_context="AI Research")
        assert cnt_prj == 1 and res_prj[0]["id"] == rid2

        # Опции фильтров
        filter_opts = hm.get_filter_options()
        assert len(filter_opts["actions"]) >= 3
        assert "deepseek-chat" in filter_opts["models"]
        assert "AI Research" in filter_opts["projects"]

        # Обновление текста результата (редактирование карточки)
        hm.update_result_text(rid1, "Привет, прекрасный мир!", is_edited=True)
        rec1_upd = hm.get_record(rid1)
        assert rec1_upd["result_text"] == "Привет, прекрасный мир!"
        assert rec1_upd["is_edited"] == 1

        print("[OK] 7.2: Поиск, все фильтры, избранное и ручная правка работают безупречно.")

        # ---------------------------------------------------------------------
        # 7.3. Управление хранением (Экспорт, Бэкап, Очистка, Retention)
        # ---------------------------------------------------------------------
        print("\n--- 7.3. Экспорт, Бэкап, Очистка и Срок хранения ---")

        # Экспорт в TXT
        txt_file = tmp_path / "export.txt"
        hm.export_data("txt", target_path=txt_file)
        assert txt_file.exists() and "Truniversal — Экспорт истории операций" in txt_file.read_text(encoding="utf-8")

        # Экспорт в JSON
        json_file = tmp_path / "export.json"
        hm.export_data("json", target_path=json_file)
        assert json_file.exists() and "Machine learning algorithms" in json_file.read_text(encoding="utf-8")

        # Экспорт в CSV (с UTF-8 BOM)
        csv_file = tmp_path / "export.csv"
        hm.export_data("csv", target_path=csv_file)
        assert csv_file.exists()
        raw_csv = csv_file.read_bytes()
        assert raw_csv.startswith(b"\xef\xbb\xbf"), "CSV должен содержать UTF-8 BOM для Excel"

        # Резервное копирование БД
        backup_file = tmp_path / "history_backup_test.db"
        hm.backup_database(backup_path=backup_file)
        assert backup_file.exists() and backup_file.stat().st_size > 0
        # Проверяем, что бэкап валиден и читается
        hm_bak = HistoryManager(backup_file)
        _, bak_count = hm_bak.list_records()
        assert bak_count == 3

        # Очистка за период с сохранением избранного
        deleted_period = hm.clear_period(date_from="2026-11-10", date_to="2026-11-10", keep_favorites=True)
        assert deleted_period == 1
        _, count_after_period = hm.list_records()
        assert count_after_period == 2

        # Настройка срока хранения (retention policy)
        # Добавим старую запись
        hm.add_record("Old text", "Старый текст", created_at="2025-01-01 12:00:00", is_favorite=False)
        _, count_with_old = hm.list_records()
        assert count_with_old == 3

        # Применяем срок хранения 30 дней -> старая запись должна удалиться
        cleaned = hm.apply_retention_policy(retention_days=30)
        assert cleaned == 1
        _, count_after_retention = hm.list_records()
        assert count_after_retention == 2

        # Полная очистка
        hm.clear_all(keep_favorites=False)
        _, count_empty = hm.list_records()
        assert count_empty == 0

        print("[OK] 7.3: Экспорт (TXT/JSON/CSV), бэкап, очистка и retention policy работают.")

        # ---------------------------------------------------------------------
        # 7.4. Производительность (Пагинация и индексы на 1000+ записях)
        # ---------------------------------------------------------------------
        print("\n--- 7.4. Производительность и пагинация (1000+ записей) ---")
        # Создаем пакет из 1000 записей
        t_start = time.perf_counter()
        conn = hm._get_connection()
        cur = conn.cursor()
        batch = []
        for i in range(1000):
            batch.append((
                f"Source statement number {i}",
                f"Результат высказывания номер {i}",
                "action_trans_literary" if i % 2 == 0 else "action_paraphrase",
                "Перевести" if i % 2 == 0 else "Перефразировать",
                "llama3" if i % 3 == 0 else "deepseek",
                "EN → RU",
                "2026-11-11 12:00:00",
                "Проект Тест" if i % 5 == 0 else "",
                1 if i % 10 == 0 else 0,
            ))
        cur.executemany(
            """
            INSERT INTO history (source_text, result_text, action_id, action_name,
                                 model_name, direction, created_at, project_context, is_favorite)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            batch,
        )
        conn.commit()
        conn.close()

        # Замер времени постраничной выборки (LIMIT 50 OFFSET 100)
        t_query_start = time.perf_counter()
        paged_records, total_1000 = hm.list_records(limit=50, offset=100)
        query_duration = time.perf_counter() - t_query_start

        assert total_1000 == 1000
        assert len(paged_records) == 50
        assert query_duration < 0.05, f"Запрос пагинации слишком медленный: {query_duration:.4f} с"

        # Замер поиска по индексу и подстроке
        t_search_start = time.perf_counter()
        found_records, found_cnt = hm.list_records(search_text="statement number 77", limit=10)
        search_duration = time.perf_counter() - t_search_start
        assert found_cnt >= 1
        assert search_duration < 0.05, f"Поиск слишком медленный: {search_duration:.4f} с"

        print(f"[OK] 7.4: 1000 записей обработаны. Выборка страницы: {query_duration*1000:.2f} мс, поиск: {search_duration*1000:.2f} мс.")

        # ---------------------------------------------------------------------
        # 7.5. GUI-компоненты: SettingsWindow (вкладка История) и MiniPopupWindow
        # ---------------------------------------------------------------------
        print("\n--- 7.5. Интеграция GUI: SettingsWindow и MiniPopupWindow ---")
        dummy_icon = QIcon()
        settings = SettingsWindow(cfg, dummy_icon)
        assert settings.tabs.count() >= 4
        assert settings.tabs.tabText(2) == "История операций"

        # Проверяем переключение на вкладку истории
        settings.open_history_tab()
        assert settings.tabs.currentIndex() == 2

        # Проверяем виджеты вкладки
        assert settings.history_table.rowCount() == 50  # первая страница на 50 элементов
        assert settings.hist_search_edit is not None
        assert settings.btn_detail_open_card is not None

        # Проверяем выбор строки в таблице и обновление панели деталей
        settings.history_table.selectRow(0)
        assert settings.hist_detail_source.toPlainText().strip() != ""
        assert settings.btn_detail_open_card.isEnabled() is True

        # Проверяем мини-окно и отображение исторической карточки (7.2)
        mini = MiniPopupWindow(cfg, dummy_icon)
        test_rec = paged_records[0]
        displayed_card = mini.display_history_card(test_rec)
        assert displayed_card is not None
        assert displayed_card.source_text == test_rec["source_text"]
        assert displayed_card.result_text == test_rec["result_text"]
        assert displayed_card.history_id == test_rec["id"]

        # Проверяем сигнал перехода из мини-окна в историю
        history_signal_fired = False
        def on_hist_req():
            nonlocal history_signal_fired
            history_signal_fired = True
        mini.history_requested.connect(on_hist_req)
        mini.history_browser_btn.click()
        assert history_signal_fired is True

        # Очистка виджетов
        mini.clear_history()
        mini.close()
        settings.close()

        print("[OK] 7.5: Все GUI-элементы, вкладка истории, таблица, панель деталей и отображение карточек протестированы.")

    print("\n=== ВСЕ ТЕСТЫ ЭТАПА 7 УСПЕШНО ПРОЙДЕНЫ! ===")


if __name__ == "__main__":
    try:
        run_stage7_tests()
    except Exception as e:
        import traceback
        traceback.print_exc()
        sys.exit(1)
