"""
test_stage5.py — Комплексное тестирование функциональности ЭТАПА 5
(AI Quick Actions — универсальные действия с выделенным текстом).

Проверяет:
  5.1. Каталог быстрых действий (12+ реальных действий, уникальные промпты).
  5.2. Настраиваемые действия (CRUD, выбор модели/профиля, reorder, pin/unpin).
  5.3. Переменные в промптах ({text}, {source_lang}, {target_lang}, {project_context}, {glossary}, безопасное разделение).
  5.4. Быстрый доступ в мини-окне (кнопка меню, закреплённые pills, вызов по 1..9, хоткеи действий, кастомный промпт).
  5.5. Стартовые пресеты (Литературный, Разговорный, 3 варианта, Редактура, Исправление MT, Перефразирование, Идиомы, Технический).
"""

from copy import deepcopy
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

# Offscreen режим для Qt
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt, QCoreApplication
from PyQt6.QtGui import QKeyEvent, QIcon, QPixmap
from PyQt6.QtWidgets import QApplication

import config
from config import ConfigManager, DEFAULT_ACTIONS, DEFAULT_PROMPTS, format_prompt_template
from mini_window import MiniPopupWindow
from settings_window import SettingsWindow
from translation_card import TranslationCard
from workers import TranslationWorker


def run_tests():
    app = QApplication.instance() or QApplication(sys.argv)

    print("=== НАЧАЛО ТЕСТИРОВАНИЯ ЭТАПА 5 (AI QUICK ACTIONS) ===\n")

    with tempfile.TemporaryDirectory() as tmp_dir:
        cfg_path = Path(tmp_dir) / "config.json"
        cm = ConfigManager(cfg_path)

        # ---------------------------------------------------------------------
        # 5.1 & 5.5. Каталог действий и стартовые пресеты
        # ---------------------------------------------------------------------
        print("--- 5.1 & 5.5. Проверка каталога действий и стартовых пресетов ---")
        actions = cm.get_actions()
        assert len(actions) >= 15, f"Ожидается минимум 15 действий, получено {len(actions)}"

        # Проверяем наличие всех обязательных стартовых пресетов (5.5)
        action_names = {a["name"].lower() for a in actions}

        required_5_5 = [
            "литературный перевод",
            "естественный разговорный перевод",
            "три варианта перевода",
            "редактура русского текста",
            "исправление машинного перевода",
            "перефразирование без изменения смысла",
            "объяснение идиом",
            "технический перевод",
        ]
        for req in required_5_5:
            # Литературный перевод / Живой перевод
            found = any(req in name or (req == "литературный перевод" and "живой перевод" in name) or (req == "три варианта перевода" and "3 варианта" in name) for name in action_names)
            assert found, f"Не найден обязательный пресет из 5.5: {req}"

        # Проверяем наличие всех действий из 5.1
        required_5_1 = [
            "грамматик",
            "формальн",
            "разговорн",
            "сократить",
            "расширить",
            "смысл",
            "альтернатив",
            "пользовательский",
        ]
        for req in required_5_1:
            found = any(req in name for name in action_names)
            assert found, f"Не найдено действие из 5.1: {req}"

        # Проверяем, что промпты уникальны (реальные разные действия, а не копии)
        prompts = [a["prompt"] for a in actions]
        assert len(prompts) == len(set(prompts)), "Промпты действий не должны дублироваться!"

        print("[OK] 5.1 и 5.5: Все стартовые действия и пресеты присутствуют и уникальны.")

        # ---------------------------------------------------------------------
        # 5.2. Настраиваемые действия (CRUD, выбор модели, pin, reorder)
        # ---------------------------------------------------------------------
        print("\n--- 5.2. Настраиваемые действия: CRUD, модель, закрепление, порядок ---")

        # 1. Создание нового действия
        custom_act = {
            "name": "Мой переводчик сленга",
            "prompt": "Ты — эксперт по молодежному сленгу. Переведи текст на {target_lang} с использованием сленга.",
            "profile_id": "openrouter_default",
            "pinned": True,
            "hotkey": "alt+shift+s",
        }
        assert cm.save_action(custom_act) is True
        saved = cm.get_action("Мой переводчик сленга")
        assert saved is not None
        assert saved["pinned"] is True
        assert saved["hotkey"] == "alt+shift+s"
        assert saved["profile_id"] == "openrouter_default"
        assert cm.get_prompt("Мой переводчик сленга") == custom_act["prompt"]

        # 2. Редактирование названия и промпта
        saved["name"] = "Обновлённый сленг"
        saved["prompt"] = "Новый текст промпта."
        assert cm.save_action(saved) is True
        updated = cm.get_action(saved["id"])
        assert updated["name"] == "Обновлённый сленг"
        assert updated["prompt"] == "Новый текст промпта."

        # 3. Закрепление и список pinned действий
        pinned = cm.get_pinned_actions()
        assert any(a["id"] == saved["id"] for a in pinned)

        # 4. Изменение порядка действий (reorder)
        all_ids = [a["id"] for a in cm.get_actions()]
        # Ставим наше новое действие на первое место
        reordered_ids = [saved["id"]] + [aid for aid in all_ids if aid != saved["id"]]
        assert cm.reorder_actions(reordered_ids) is True
        first_act = cm.get_actions()[0]
        assert first_act["id"] == saved["id"]

        # 5. Удаление действия
        assert cm.delete_action(saved["id"]) is True
        assert cm.get_action(saved["id"]) is None
        assert cm.get_action("Обновлённый сленг") is None

        # Проверка защиты: нельзя удалить единственное оставшееся действие
        cm.data["actions"] = [cm.data["actions"][0]]
        assert cm.delete_action(cm.data["actions"][0]["id"]) is False
        assert len(cm.get_actions()) == 1

        # Восстанавливаем дефолты для следующих тестов
        cm.data["actions"] = deepcopy(DEFAULT_ACTIONS)
        cm.save()
        print("[OK] 5.2: Создание, редактирование, выбор модели, закрепление и порядок работают корректно.")

        # ---------------------------------------------------------------------
        # 5.3. Переменные в промптах
        # ---------------------------------------------------------------------
        print("\n--- 5.3. Переменные шаблонов промпта и безопасное разделение ---")

        template = (
            "Ты — переводчик. Переведи с {source_lang} на {target_lang}. "
            "{project_context} {glossary} Исходник: {text}"
        )
        formatted = format_prompt_template(
            template=template,
            text="Тестовый текст",
            source_lang="en",
            target_lang="ru",
            project_context="Криптографический софт",
            glossary="ИИ -> AI\nтокен -> token",
        )

        assert "Контекст проекта: Криптографический софт." in formatted
        assert "Глоссарий терминов:\nИИ -> AI\nтокен -> token" in formatted
        assert "Исходник: Тестовый текст" in formatted
        assert "en" in formatted
        assert "ru" in formatted

        # Проверка пустого контекста/глоссария: переменные удаляются без лишнего мусора
        formatted_empty = format_prompt_template(
            template="Инструкция. {project_context} {glossary} Готово.",
            text="текст",
            source_lang="ru",
            target_lang="en",
            project_context="",
            glossary="",
        )
        assert "{project_context}" not in formatted_empty
        assert "{glossary}" not in formatted_empty
        assert "Контекст проекта:" not in formatted_empty
        assert "Глоссарий терминов:" not in formatted_empty

        # Проверка передачи в воркере: текст пользователя уходит в role=user
        captured_payload = {}
        def mock_post(url, json=None, **kwargs):
            captured_payload["data"] = json
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {
                "choices": [{"message": {"role": "assistant", "content": "Результат"}}]
            }
            return resp

        import workers
        orig_post = workers.requests.post
        workers.requests.post = mock_post
        try:
            worker = TranslationWorker(
                config=cm,
                source_text="Строка для обработки",
                action_id="action_trans_natural",
            )
            worker.start()
            worker.wait(5000)
            app.processEvents()

            payload = captured_payload.get("data", {})
            messages = payload.get("messages", [])
            assert len(messages) >= 2, "Запрос должен содержать system и user сообщения"
            assert messages[0]["role"] == "system"
            assert messages[1]["role"] == "user"
            assert messages[1]["content"] == "Строка для обработки", "Текст пользователя должен передаваться отдельно от системного промпта"
        finally:
            workers.requests.post = orig_post

        print("[OK] 5.3: Переменные корректно подставляются, текст пользователя надёжно изолирован.")

        # ---------------------------------------------------------------------
        # 5.4. Быстрый доступ в мини-окне (Pill-кнопки, цифры 1..9, кастомный промпт)
        # ---------------------------------------------------------------------
        print("\n--- 5.4. Быстрый доступ в GUI: мини-окно, кнопки, хоткеи, кастомный промпт ---")

        pixmap = QPixmap(16, 16)
        pixmap.fill(Qt.GlobalColor.blue)
        icon = QIcon(pixmap)
        popup = MiniPopupWindow(cm, icon)

        # Проверяем наличие компонентов быстрого доступа
        assert popup.actions_menu_btn is not None
        assert popup.custom_prompt_btn is not None
        assert popup.pinned_bar is not None
        assert popup.custom_prompt_bar is not None

        # Проверяем наличие закреплённых кнопок-пилюль
        pinned_actions = cm.get_pinned_actions()
        from PyQt6.QtWidgets import QPushButton
        pill_buttons = popup.pinned_bar.findChildren(QPushButton, "QuickActionPill")
        assert len(pill_buttons) == min(len(pinned_actions), 6)

        # Проверяем добавление карточки и вызов действия
        popup.handle_new_text("Какая-то фраза", action_id="action_trans_natural")
        assert len(popup._cards) == 1
        card = popup._cards[0]
        assert card.action_badge is not None
        assert card.copy_button is not None

        # Проверяем вызов по цифровой клавише (нажатие '1')
        event_key_1 = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_1, Qt.KeyboardModifier.NoModifier)
        popup.keyPressEvent(event_key_1)
        # Должна добавиться новая карточка со 1-м закрепленным действием
        assert len(popup._cards) == 2

        # Проверяем кастомный промпт
        popup.custom_prompt_edit.setText("Переведи в стиле Шекспира")
        popup._run_custom_prompt()
        assert len(popup._cards) == 3

        popup.clear_history()
        popup.shutdown()
        print("[OK] 5.4: Быстрый доступ в 1 клик, цифровые клавиши и пользовательский промпт протестированы.")

        # ---------------------------------------------------------------------
        # Проверка окна настроек (SettingsWindow Tab 2)
        # ---------------------------------------------------------------------
        print("\n--- Проверка вкладки «Быстрые действия и Промпты» в SettingsWindow ---")
        settings = SettingsWindow(cm, icon)
        assert settings.preset_list.count() >= 15
        assert settings.action_profile_combo is not None
        assert settings.action_pinned_check is not None
        assert settings.action_hotkey_edit is not None
        assert settings.project_context_edit is not None
        assert settings.glossary_edit is not None

        # Сохранение контекста проекта из формы настроек
        settings.project_context_edit.setText("Новый проект ИИ")
        settings.glossary_edit.setPlainText("термин1 -> term1")
        settings._save_project_context()
        assert cm.get("project_context") == "Новый проект ИИ"
        assert cm.get("glossary") == "термин1 -> term1"

        # Перемещение действия ▲ / ▼
        initial_first = settings.preset_list.item(0).text()
        initial_second = settings.preset_list.item(1).text()
        settings.preset_list.setCurrentRow(1)
        settings._move_preset_up()
        assert settings.preset_list.item(0).text() == initial_second
        assert settings.preset_list.item(1).text() == initial_first

        # Дублирование действия
        initial_count = settings.preset_list.count()
        settings._duplicate_preset()
        assert settings.preset_list.count() == initial_count + 1

        settings.close()

    print("\n=== ВСЕ ТЕСТЫ ЭТАПА 5 УСПЕШНО ПРОЙДЕНЫ! ===")


if __name__ == "__main__":
    run_tests()
