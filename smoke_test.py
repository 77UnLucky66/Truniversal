"""
smoke_test.py — быстрый smoke-тест GUI (ШАГИ 1–3).

Запускает Qt в режиме «offscreen» (окна реально не отображаются) и без
нажатия реальных хоткеев проверяет механику: генерацию иконки, ленту
карточек мини-окна, кнопку копирования, переключатель режимов, пресеты,
меню трея, регистрацию хоткея и доставку сигнала до карточки.

Запуск:  python smoke_test.py
"""

import os
import sys
import tempfile
from pathlib import Path

# ДО импорта PyQt6: рисуем в «виртуальный» экран, реальный дисплей не нужен.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pyperclip
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QMessageBox

import main as m
from config import ConfigManager
from mini_window import MiniPopupWindow
from settings_window import SettingsWindow
from styles import APP_QSS
from workers import wait_for_workers


def run() -> int:
    app = QApplication(sys.argv)
    app.setStyleSheet(APP_QSS)

    # 1. Программно сгенерированная иконка не пустая.
    icon = m.create_app_icon()
    pixmap = icon.pixmap(256, 256)
    assert not icon.isNull() and not pixmap.isNull(), "иконка пустая"
    print("[OK] 1. create_app_icon — иконка сгенерирована")

    with tempfile.TemporaryDirectory() as tmp_dir:
        cfg = ConfigManager(Path(tmp_dir) / "config.json")

        # 2. Окно настроек: три вкладки, ползунки, пресеты, хоткеи, сохранение.
        settings = SettingsWindow(cfg, icon)
        settings.show()
        assert settings.windowTitle().startswith("Truniversal")
        assert settings.tabs.count() == 3
        # Вкладка 1: значения из конфига, ползунки синхронизированы.
        assert settings.api_url_edit.text() == cfg.get("api_url")
        assert settings.model_combo.currentText() == cfg.get("model_name")
        assert settings.temp_slider.value() == int(cfg.get("temperature") * 100)
        assert settings.top_p_slider.value() == int(cfg.get("top_p") * 100)
        settings.temp_slider.setValue(75)
        assert settings.temp_value_label.text() == "0.75"
        settings._apply_api_preset("OpenRouter")
        assert "openrouter.ai" in settings.api_url_edit.text()
        # Вкладка 2: список пресетов, редактор и сохранение.
        assert settings.preset_list.count() >= 3
        settings.preset_list.setCurrentRow(1)
        assert settings.preset_name_edit.text() == "3 варианта перефразирования"
        settings.preset_text_edit.setPlainText("Тестовый текст пресета")
        settings._save_current_preset()
        assert cfg.get_prompt("3 варианта перефразирования") == "Тестовый текст пресета"
        settings._add_preset()
        assert cfg.get_prompt("Новый пресет") is not None
        # Вкладка 3: движок, язык и хоткей (менеджера нет — пишем в конфиг).
        settings.hotkey_edit.setText("ctrl+shift+t")
        settings.lang_combo.setCurrentText("en")
        settings._save_common_tab()
        assert cfg.get("hotkey") == "ctrl+shift+t"
        assert cfg.get("target_lang") == "en"

        # Чекбоксы Этапа 2: включённость хоткея и режим диагностики.
        assert settings.hotkey_enabled_cb.isChecked()
        assert not settings.diagnostics_cb.isChecked()
        assert settings.hotkey_edit.isEnabled()
        settings.hotkey_enabled_cb.setChecked(False)
        assert not settings.hotkey_edit.isEnabled()   # поле погасло
        settings.diagnostics_cb.setChecked(True)
        settings._save_common_tab()
        assert cfg.get("hotkey_enabled") is False
        assert cfg.get("diagnostics") is True
        assert cfg.get("hotkey") == "ctrl+shift+t"    # сочетание сохранено
        settings.hotkey_enabled_cb.setChecked(True)
        settings._save_common_tab()
        assert cfg.get("hotkey_enabled") is True
        assert settings.hotkey_edit.isEnabled()

        # Полный сброс к заводским настройкам: подтверждение подменяем
        # (иначе тест застрял бы в диалоге). После сброса — дефолты во всех
        # вкладках, «грязный» флаг снят, пользовательские промпты заменены.
        settings.api_url_edit.setText("http://changed/api")
        settings._mark_dirty()
        assert settings._dirty
        original_question = QMessageBox.question
        QMessageBox.question = staticmethod(
            lambda *a, **k: QMessageBox.StandardButton.Yes
        )
        try:
            settings._reset_all_settings()
        finally:
            QMessageBox.question = original_question
        assert cfg.get("hotkey") == "alt+q"
        assert cfg.get("api_url") == "http://localhost:11434/v1/chat/completions"
        assert settings.hotkey_edit.text() == "alt+q"
        assert settings.api_url_edit.text() == cfg.get("api_url")
        assert settings.model_combo.currentText() == "llama3"
        assert settings.preset_list.count() >= 3
        assert "Новый пресет" not in cfg.get("prompts")
        assert settings.hotkey_enabled_cb.isChecked()      # сброс вернул флаги
        assert not settings.diagnostics_cb.isChecked()
        assert not settings._dirty

        # Проверяем отмену несохранённых изменений при закрытии окна
        settings.api_url_edit.setText("http://discarded/api")
        assert settings._dirty
        original_question = QMessageBox.question
        QMessageBox.question = staticmethod(
            lambda *a, **k: QMessageBox.StandardButton.Yes
        )
        try:
            settings.close()
        finally:
            QMessageBox.question = original_question
        assert not settings._dirty, "После закрытия без сохранения _dirty должен быть False"
        assert settings.api_url_edit.text() == cfg.get("api_url"), "Поле должно вернуться к конфигу"

        # shutdown() без запущенных фоновых задач безопасен (используется
        # при закрытии окна и при выходе из приложения).
        settings.shutdown()
        print("[OK] 2. SettingsWindow — вкладки, ползунки, пресеты, сброс, shutdown")

        # 3. Мини-окно: «Думаю…», результат/ошибка, режим, пресеты, очистка.
        # Порт 9 закрыт всегда → ошибка подключения в карточке детерминирована.
        cfg.set("api_url", "http://127.0.0.1:9/v1/chat/completions")
        popup = MiniPopupWindow(cfg, icon)
        popup.show()
        popup.handle_new_text("Hello, world! Это тестовый захват.")
        popup.handle_new_text("Второй захват — карточка добавляется в конец.")
        assert len(popup._cards) == 2, len(popup._cards)
        # Пока запрос идёт — в карточке крутится «Думаю…», копирование выключено.
        assert popup._cards[0].result_label.text().startswith("Думаю")
        assert not popup._cards[0].copy_button.isEnabled()
        assert popup.empty_label.isHidden()

        # Длинный исходник обрезается в превью до ~2 строк.
        popup.handle_new_text("слово " * 100)
        preview = popup._cards[-1].source_label.text()
        assert preview.endswith(("…", "...")) and len(preview) <= 130, preview

        # API недоступен -> в карточку приходит понятная ошибка.
        # Подключение к закрытому порту занимает ~2 с — берём запас.
        QTest.qWait(4500)
        first = popup._cards[0].result_label.text()
        assert "подключ" in first and not first.startswith("Думаю"), first
        assert not popup._cards[0].copy_button.isVisibleTo(popup)

        # Синхронные состояния карточки: результат и ошибка.
        popup._cards[0].set_result("Готовый результат перевода")
        assert popup._cards[0].result_label.text() == "Готовый результат перевода"
        assert popup._cards[0].copy_button.isEnabled()
        popup._cards[0].set_error("Тестовая ошибка")
        assert "Тестовая ошибка" in popup._cards[0].result_label.text()
        assert not popup._cards[0].copy_button.isVisibleTo(popup)

        # Кнопка копирования (реальный буфер в тесте не трогаем — подмена).
        original_copy = pyperclip.copy
        pyperclip.copy = lambda text: None
        popup._cards[1].set_result("Готовый результат 2")
        popup._cards[1].copy_button.click()
        assert popup._cards[1].copy_button.text().startswith("Скопировано")
        QTest.qWait(1100)  # ждём возврат надписи (1 секунда)
        assert popup._cards[1].copy_button.text() == "Скопировать"
        pyperclip.copy = original_copy

        # Переключатель режима пишется в конфиг, пресеты вкл/выкл.
        assert cfg.get("mode") == "ai"
        popup._toggle_mode()
        assert cfg.get("mode") == "standard"
        assert not popup.preset_combo.isEnabled()
        popup._toggle_mode()
        assert cfg.get("mode") == "ai"
        assert popup.preset_combo.isEnabled()

        # Выбор пресета сохраняется в конфиг.
        popup.preset_combo.setCurrentText("3 варианта перефразирования")
        assert cfg.get("active_prompt_name") == "3 варианта перефразирования"

        # Очистка истории.
        popup.clear_history()
        assert len(popup._cards) == 0
        assert popup.empty_label.isVisible()

        # Подсказка про хоткей учитывает его отключение (Этап 2).
        assert "alt+q" in popup.empty_label.text() or cfg.get("hotkey") in popup.empty_label.text()
        cfg.set("hotkey_enabled", False, autosave=False)
        popup.refresh_from_config()
        assert "отключён" in popup.empty_label.text()
        cfg.set("hotkey_enabled", True, autosave=False)
        popup.refresh_from_config()

        # «Повторить»: карточка возвращается в «Думаю…» и перезапускает воркер.
        popup.handle_new_text("Текст для регенерации")
        QTest.qWait(4500)  # ждём ошибку от закрытого порта (~2 с)
        card = popup._cards[0]
        assert "подключ" in card.result_label.text()
        assert card.regenerate_button.isEnabled()  # доступен и после ошибки
        card.regenerate_button.click()
        assert card.result_label.text().startswith("Думаю")
        assert not card.copy_button.isEnabled()
        QTest.qWait(4500)
        assert not card.result_label.text().startswith("Думаю")  # снова ошибка
        assert card.regenerate_button.isEnabled()

        # «Заменить в тексте» (менеджера нет): буфер получает текст, лента прячет окно.
        copied = []
        pyperclip_copy2 = pyperclip.copy
        pyperclip.copy = lambda text: copied.append(text)
        card.set_result("Результат для замены")
        assert card.replace_button.isEnabled()
        card.replace_button.click()
        pyperclip.copy = pyperclip_copy2
        assert copied == ["Результат для замены"], copied
        assert not popup.isVisible()
        assert len(popup._cards) == 0
        # Проверка отмены активных воркеров при clear_history() и shutdown()
        popup.handle_new_text("Ещё один запрос для проверки отмены")
        assert len(popup._workers) >= 1
        popup.clear_history()
        assert len(popup._cards) == 0
        assert len(popup._workers) == 0
        assert popup.empty_label.isVisible()
        popup.shutdown()
        assert len(popup._workers) == 0
    print("[OK] 3. MiniPopupWindow — «Думаю…», «Повторить», «Заменить», отмена воркеров, shutdown")

    # 4. Контроллер трея: меню + глобальный хоткей. Конфиг — во ВРЕМЕННОЙ
    #    папке: реальный config.json пользователя тест не трогает.
    with tempfile.TemporaryDirectory() as tray_dir:
        ctrl = m.TrayApp(app, config_path=Path(tray_dir) / "config.json")
        actions = [a.text() for a in ctrl.menu.actions() if a.text()]
        assert actions == [
            "Открыть настройки", "Открыть мини-окно", "Глобальный хоткей", "Выход"
        ], actions
        assert ctrl.hotkey_manager.hotkey == ctrl.config.get("hotkey"), "хоткей не зарегистрирован"
        assert ctrl.hotkey_toggle.isChecked()
        print("[OK] 4. TrayApp — меню трея; хоткей зарегистрирован:", ctrl.hotkey_manager.hotkey)

        # Переключатель хоткея в меню трея (Этап 2): выключение снимает
        # регистрацию и сохраняется в config.json; включение возвращает.
        ctrl.hotkey_toggle.setChecked(False)
        assert ctrl.config.get("hotkey_enabled") is False
        assert ctrl.hotkey_manager.hotkey == ""
        assert "отключён" in ctrl.tray.toolTip()
        ctrl.hotkey_toggle.setChecked(True)
        assert ctrl.config.get("hotkey_enabled") is True
        assert ctrl.hotkey_manager.hotkey == "alt+q"
        assert "alt+q" in ctrl.tray.toolTip()

        # 5. pyqtSignal-путь: «захват» доходит до мини-окна и превращается
        #    в карточку. Адрес API — заведомо закрытый порт: перевод
        #    детерминированно падает ошибкой и не задевает реальную Ollama.
        ctrl.config.set("api_url", "http://127.0.0.1:9/v1/chat/completions")
        received = []
        ctrl.hotkey_manager.text_captured.connect(lambda text: received.append(text))
        ctrl.hotkey_manager.text_captured.emit("Тестовый захват")
        assert received == ["Тестовый захват"]
        # TrayApp сам подписан на этот же сигнал — карточка создаётся уже при emit:
        assert len(ctrl._mini_window._cards) == 1
        # Карточка сразу в режиме «Думаю…» — фоновый перевод уже запущен.
        assert ctrl._mini_window._cards[0].result_label.text().startswith("Думаю")
        ctrl._on_text_captured("Второй тестовый захват")
        assert len(ctrl._mini_window._cards) == 2
        assert ctrl._mini_window._cards[-1].result_label.text().startswith("Думаю")
        print("[OK] 5. pyqtSignal: захват доходит до мини-окна, карточки создаются")

        # 6. Завершение приложения: quit_app корректно останавливает фоновые
        #    задачи, закрывает открытые окна (настройки и мини-окно),
        #    снимает хоткей и прячет иконку — без падений и зависаний.
        ctrl.show_settings()
        assert ctrl._settings_window is not None
        assert ctrl._mini_window is not None
        ctrl.quit_app()
        assert not ctrl.hotkey_manager.hotkey, "хоткей должен быть снят"
        assert not ctrl.tray.isVisible()

    wait_for_workers()  # мягко ждём фоновые потоки перевода перед выходом
    print("SMOKE TEST PASSED (offscreen)")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
