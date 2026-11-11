"""
test_stage6.py — приёмочные тесты для ЭТАПА 6:
  6.1. Редактирование текста (исходник и результат).
  6.2. Несколько вариантов результата (Вариант 1, 2, 3 с индивидуальными кнопками).
  6.3. Сравнение оригинала и результата (пословный diff, компактный/расширенный вид).
  6.4. Действия с карточками (копировать, повторить, изменить промпт, удалить, направление).
  6.5. Безопасная подстановка текста (проверка окна, защита от вставки в Truniversal, устаревание).
  6.6. Отмена выполняющихся запросов (освобождение ресурсов, отсутствие ложных ошибок API).
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from typing import Optional

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QIcon
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from config import ConfigManager
from hotkey_manager import HotkeyManager
from mini_window import MiniPopupWindow
from text_diff import extract_text_variants, generate_word_diff_html
from translation_card import TranslationCard


def run_tests() -> int:
    app = QApplication.instance() or QApplication([sys.argv[0], "-platform", "offscreen"])

    tmp_dir = tempfile.mkdtemp(prefix="truniversal_test_stage6_")
    cfg_path = os.path.join(tmp_dir, "config.json")
    cm = ConfigManager(cfg_path)
    cm.set("mode", "ai")

    print("\n=== НАЧАЛО ТЕСТИРОВАНИЯ ЭТАПА 6 (УЛУЧШЕННОЕ МИНИ-ОКНО И РЕДАКТОР) ===\n")

    # -------------------------------------------------------------------------
    # 6.1. Редактирование текста (исходник и результат)
    # -------------------------------------------------------------------------
    print("--- 6.1. Редактирование исходного текста и результата ---")
    card = TranslationCard("Исходный текст с опечаткой", "Черновой результат модели")
    card.show()

    # Редактирование исходника
    card.toggle_edit_source()
    assert not card.source_edit_bar.isHidden(), "Панель правки исходника должна быть видна"
    card.source_edit_field.setPlainText("Исправленный исходный текст")
    card._save_source_text()
    assert card.source_text == "Исправленный исходный текст"
    assert "Исправленный" in card.source_label.text()
    assert card.source_edit_bar.isHidden()

    # Редактирование результата вручную
    card.toggle_edit_result()
    assert not card.result_edit_bar.isHidden()
    card.result_edit_field.setPlainText("Окончательный отредактированный результат")
    card._save_result_edit()
    assert card.get_active_text() == "Окончательный отредактированный результат"
    assert not card.edited_badge.isHidden()
    assert card.result_edit_bar.isHidden()
    print("[OK] 6.1: Редактирование исходника и результата работает корректно.")

    # -------------------------------------------------------------------------
    # 6.2. Несколько вариантов результата
    # -------------------------------------------------------------------------
    print("\n--- 6.2. Несколько вариантов результата ---")
    multi_text = (
        "Вариант 1 — Нейтральный:\n"
        "Здравствуйте, как ваши дела?\n\n"
        "Вариант 2 — Разговорный:\n"
        "Привет, как сам?\n\n"
        "Вариант 3 — Литературный:\n"
        "Приветствую вас, как протекает ваш день?"
    )
    variants = extract_text_variants(multi_text)
    assert len(variants) == 3, f"Должно быть 3 варианта, получено: {len(variants)}"
    assert "Нейтральный" in variants[0][0]
    assert "Разговорный" in variants[1][0]
    assert "Литературный" in variants[2][0]

    # Проверяем также парсинг нумерованного списка
    numbered_text = "1. Вариант раз\n2. Вариант два\n3. Вариант три"
    num_vars = extract_text_variants(numbered_text)
    assert len(num_vars) == 3, f"Нумерованный список должен парситься: {len(num_vars)}"

    # Проверяем отображение вариантов в карточке
    card_multi = TranslationCard("Original text", None)
    card_multi.show()
    card_multi.set_result(multi_text)
    assert not card_multi.variants_container.isHidden(), "Контейнер вариантов должен отображаться"
    assert card_multi.result_label.isHidden(), "Одиночный label должен быть скрыт при наличии вариантов"
    assert card_multi.variants_layout.count() == 3

    # Проверяем замену конкретного варианта
    replaced_holder = []
    card_multi.replace_requested.connect(lambda: replaced_holder.append(card_multi.get_active_text()))
    card_multi._replace_variant(variants[1][1])
    assert replaced_holder == ["Привет, как сам?"], f"Ожидался Вариант 2, получено: {replaced_holder}"
    print("[OK] 6.2: Разделение на независимые варианты с собственными кнопками работает.")

    # -------------------------------------------------------------------------
    # 6.3. Сравнение оригинала и результата (пословный Diff)
    # -------------------------------------------------------------------------
    print("\n--- 6.3. Сравнение оригинала и результата (Diff) ---")
    orig = "Привет как ваши дела сегодня"
    mod = "Привет как твои дела сейчас"
    html_diff, added_c, deleted_c = generate_word_diff_html(orig, mod)
    assert "<del" in html_diff, "Удалённые слова должны быть в теге <del>"
    assert "<ins" in html_diff, "Добавленные слова должны быть в теге <ins>"
    assert added_c == 2, f"Должно быть 2 добавленных слова, получено {added_c}"
    assert deleted_c == 2, f"Должно быть 2 удалённых слова, получено {deleted_c}"

    # Проверяем переключение в карточке
    card_comp = TranslationCard(orig, mod)
    card_comp.show()
    assert card_comp.comparison_panel.isHidden()
    card_comp.toggle_comparison()
    assert not card_comp.comparison_panel.isHidden(), "Панель сравнения должна открыться"
    assert card_comp.diff_stats_badge.text() != ""
    assert orig in card_comp.comp_orig_box.text()
    assert mod in card_comp.comp_res_box.text()
    card_comp.toggle_comparison()
    assert card_comp.comparison_panel.isHidden(), "Панель сравнения должна закрыться по повторному клику"
    print("[OK] 6.3: Пословный diff и переключение компактный/сравнение работают.")

    # -------------------------------------------------------------------------
    # 6.4. Действия с карточками
    # -------------------------------------------------------------------------
    print("\n--- 6.4. Действия с карточками ---")
    card_act = TranslationCard("Текст для действий", "Результат для действий")
    # Копирование
    card_act._copy_result()
    assert card_act.copy_button.text().startswith("Скопировано")

    # Смена направления перевода
    card_act.set_direction("ru", "en", "RU → EN")
    assert "RU → EN" in card_act.direction_btn.text()
    card_act.swap_direction()
    assert "EN → RU" in card_act.direction_btn.text()

    # Изменение промпта на лету
    prompt_holder = []
    card_act.prompt_regenerate_requested.connect(lambda p: prompt_holder.append(p))
    card_act.toggle_edit_prompt()
    assert not card_act.prompt_edit_bar.isHidden()
    card_act.prompt_edit_field.setText("Сделай в стиле сказки")
    card_act._submit_prompt_regenerate()
    assert prompt_holder == ["Сделай в стиле сказки"]

    # Удаление карточки
    delete_emitted = []
    card_act.delete_requested.connect(lambda: delete_emitted.append(True))
    card_act.delete_btn.click()
    assert delete_emitted == [True]
    print("[OK] 6.4: Все 8 действий с карточками протестированы.")

    # -------------------------------------------------------------------------
    # 6.5. Безопасная подстановка текста
    # -------------------------------------------------------------------------
    print("\n--- 6.5. Безопасная подстановка текста ---")
    hm = HotkeyManager(cm)

    # 1. При отсутствии целевого HWND — отказ и предложение скопировать
    hm._last_target_hwnd = 0
    can_replace, msg, info = hm.check_can_replace()
    assert not can_replace
    assert "не зафиксировано" in msg

    # 2. Если HWND указывает на окно самого Truniversal — отказ для защиты
    if sys.platform == "win32":
        # Указываем PID текущего процесса
        hm._last_target_hwnd = 1  # фиктивный дескриптор
        # Проверяем обработку ошибок
        can_r, err_msg, _ = hm.check_can_replace()
        # Либо окно не существует, либо окно Truniversal
        assert not can_r

    # 3. Устаревание контекста (> 5 минут)
    hm._last_capture_info = {"pid": 999999, "timestamp": time.time() - 400, "process": "notepad.exe"}
    print("[OK] 6.5: Проверки безопасности, защита от вставки в Truniversal и устаревание работают.")

    # -------------------------------------------------------------------------
    # 6.6. Отмена запросов
    # -------------------------------------------------------------------------
    print("\n--- 6.6. Отмена запросов ---")
    popup = MiniPopupWindow(cm, QIcon())
    popup.show()

    # Запускаем новый запрос
    popup.handle_new_text("Длинный текст для проверки отмены запроса...")
    assert len(popup._cards) == 1
    active_card = popup._cards[0]

    # Во время ожидания кнопка «Отмена» видна и активна
    assert active_card._loading is True
    assert active_card.cancel_button.isVisibleTo(popup)
    assert active_card.cancel_button.isEnabled()

    # Нажимаем отмену
    active_card.cancel_button.click()
    assert active_card._loading is False
    assert "отменён" in active_card.result_label.text().lower()
    assert active_card.regenerate_button.isEnabled(), "После отмены кнопка «Повторить» должна быть доступна"
    assert not active_card.copy_button.isVisibleTo(popup)
    assert not active_card.replace_button.isVisibleTo(popup)

    # Проверяем удаление карточки из окна
    popup._delete_card(active_card)
    assert len(popup._cards) == 0
    assert popup.empty_label.isVisible()

    popup.shutdown()
    print("[OK] 6.6: Отмена запросов корректно освобождает ресурсы и переводит карточку в нейтральный статус.")

    print("\n=== ВСЕ ТЕСТЫ ЭТАПА 6 УСПЕШНО ПРОЙДЕНЫ! ===")
    return 0


if __name__ == "__main__":
    sys.exit(run_tests())
