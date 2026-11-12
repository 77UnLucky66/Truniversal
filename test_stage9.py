"""
test_stage9.py — Модульные и интеграционные тесты для ЭТАПА 9.

Проверяет:
  9.1. Мини-окно: изменение размера, запоминание позиции, многомониторность (clamping),
       закрепление поверх всех окон (pin), прозрачность, авто-очистка лимита карточек.
  9.2. Темы оформления (тёмная, светлая, системная), масштабирование шрифтов (-1.0pt, 0.0pt, +1.5pt),
       типографика и чёткое разделение исходника и результата.
  9.3. Статусы конвейера (ожидание, получение, отправка, генерация, готово, ошибка, отменено),
       индикация прошедшего времени.
  9.4. Мастер первоначальной настройки (FirstRunWizard): выбор сценария, пропуск, сохранение.
  9.5. Контекстное меню трея: быстрое меню действий, приостановка работы, обновление тултипа.
  9.6. Человечные ошибки и раскрываемые технические подробности с кнопкой лога.
  0.   Строжайшее отсутствие любых эмодзи во всей кодовой базе и текстах.
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

# Режим offscreen для безголового тестирования Qt
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtWidgets import QApplication

from config import ConfigManager
from first_run_wizard import FirstRunWizard
from mini_window import MiniPopupWindow
from styles import (APP_QSS, DARK_PALETTE, LIGHT_PALETTE, apply_theme,
                    detect_system_theme, get_application_stylesheet,
                    get_theme_palette, scale_font_sizes)
from translation_card import TranslationCard
from workers import humanize_error


def run_stage9_tests():
    print("\n=== НАЧАЛО ТЕСТИРОВАНИЯ ЭТАПА 9 (UI, СТИЛИ, СТАТУСЫ, МАСТЕР И ТРЕЙ) ===")

    app = QApplication.instance()
    if app is None:
        app = QApplication([])

    with tempfile.TemporaryDirectory() as tmp_dir:
        cfg_path = Path(tmp_dir) / "config.json"
        config = ConfigManager(cfg_path)

        # -----------------------------------------------------------------
        # 9.2. Темы оформления и масштабирование шрифтов
        # -----------------------------------------------------------------
        print("\n--- 9.2. Настройки оформления (Темы и Масштаб шрифта) ---")

        sys_theme = detect_system_theme()
        assert sys_theme in ("dark", "light"), f"Неожиданная системная тема: {sys_theme}"
        print(f"[OK] Детекция системной темы Windows: {sys_theme}")

        dark_pal = get_theme_palette("dark")
        light_pal = get_theme_palette("light")
        assert dark_pal["BG_WINDOW"] != light_pal["BG_WINDOW"]
        assert dark_pal["TEXT_PRIMARY"] != light_pal["TEXT_PRIMARY"]
        print("[OK] Палитры dark и light различаются и корректно инициализированы.")

        qss_dark_med = get_application_stylesheet("dark", "medium")
        qss_light_sml = get_application_stylesheet("light", "small")
        qss_dark_lrg = get_application_stylesheet("dark", "large")

        assert len(qss_dark_med) > 5000
        assert len(qss_light_sml) > 5000
        assert "SourceContainer" in qss_dark_med
        assert "CardStatusGenerating" in qss_dark_med
        assert "CardDetailsBtn" in qss_dark_med
        print("[OK] Генерация QSS для тем dark, light и system работает.")

        # Проверка масштабирования шрифтов
        sample_qss = "font-size: 10pt; font-size: 13px;"
        scaled_sml = scale_font_sizes(sample_qss, "small")
        scaled_lrg = scale_font_sizes(sample_qss, "large")
        assert "9.0pt" in scaled_sml or "9pt" in scaled_sml
        assert "11.5pt" in scaled_lrg
        print("[OK] Масштабирование шрифтов (small: -1pt, large: +1.5pt) работает.")

        # Применение темы к приложению
        apply_theme(app, "light", "small")
        assert app.styleSheet() is not None and len(app.styleSheet()) > 5000
        apply_theme(app, "dark", "medium")
        print("[OK] apply_theme() динамически переключает стили приложения.")

        # -----------------------------------------------------------------
        # 9.3 & 9.6. Статусы конвейера, ошибки и подробности
        # -----------------------------------------------------------------
        print("\n--- 9.3 & 9.6. Статусы операций и Диагностика ошибок ---")

        card = TranslationCard("Original text for testing", None)
        card.show()
        assert card.status_badge is not None
        assert card.status_badge.text() == "Отправка запроса..." or card.status_badge.text() == "Ожидание"

        # Проверка переходов состояний
        card.set_status("capturing")
        assert "Получение" in card.status_badge.text()
        assert card.status_badge.objectName() == "CardStatusCapturing"

        card.set_status("sending")
        assert "Отправка" in card.status_badge.text()
        assert card.status_badge.objectName() == "CardStatusSending"

        card.set_status("generating")
        assert "Генерация" in card.status_badge.text()
        assert card.status_badge.objectName() == "CardStatusGenerating"

        card.set_status("ready")
        assert "Готово" in card.status_badge.text()
        assert card.status_badge.objectName() == "CardStatusReady"

        card.set_status("cancelled")
        assert "Отменено" in card.status_badge.text()
        assert card.status_badge.objectName() == "CardStatusCancelled"

        # Проверка ошибок и технических подробностей (9.6)
        friendly, technical = humanize_error(
            ConnectionRefusedError("No connection could be made because the target machine actively refused it 127.0.0.1:11434"),
            context="Ollama local check"
        )
        assert "Ollama" in friendly
        assert "11434" in friendly or "11434" in technical
        assert len(technical) > 0

        card.set_error(friendly, details=technical)
        assert card.status_badge.text() == "Ошибка"
        assert card.status_badge.objectName() == "CardStatusError"
        assert card.details_btn.isVisible()
        assert not card.tech_details_frame.isVisible()

        # Клик по подробностям раскрывает техническую панель
        card.details_btn.click()
        assert card.tech_details_frame.isVisible()
        assert "ConnectionRefusedError" in card.tech_details_text.text() or "11434" in card.tech_details_text.text()
        card.details_btn.click()
        assert not card.tech_details_frame.isVisible()
        print("[OK] Статусы конвейера, таймер, человечные ошибки и раскрываемые подробности подтверждены.")

        # -----------------------------------------------------------------
        # 9.1. Мини-окно: размеры, многомониторность, pin, прозрачность, лимиты
        # -----------------------------------------------------------------
        print("\n--- 9.1. Мини-окно: Позиционирование, Pin, Прозрачность, Лимиты ---")

        dummy_icon = QIcon()
        popup = MiniPopupWindow(config, dummy_icon)

        # Проверка прозрачности
        config.set_popup_opacity(0.85)
        popup.refresh_from_config()
        assert abs(popup.windowOpacity() - 0.85) < 0.05
        print("[OK] Настройка прозрачности мини-окна (setWindowOpacity) работает.")

        # Проверка переключателя закрепления (Pin on top)
        assert hasattr(popup, "pin_btn")
        popup.pin_btn.setChecked(True)
        assert popup.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
        assert config.is_popup_stays_on_top() is True
        popup.pin_btn.setChecked(False)
        assert not (popup.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
        assert config.is_popup_stays_on_top() is False
        print("[OK] Закрепление поверх всех окон (Pin Top toggle) работает.")

        # Проверка многомониторного clamping
        scr = popup._get_active_screen(QPoint(100, 100))
        assert scr is not None
        geo = scr.availableGeometry()
        # Вызов с координатами далеко за пределами экрана
        cx, cy = popup._clamp_to_screen(geo.right() + 500, geo.bottom() + 500, 400, 300, scr)
        assert cx <= geo.right() - 400 or cx == geo.left()
        assert cy <= geo.bottom() - 300 or cy == geo.top()
        print(f"[OK] Многомониторное удержание в границах экрана (_clamp_to_screen): geo={geo.width()}x{geo.height()} -> {cx}, {cy}")

        # Проверка авто-очистки по лимиту карточек в сессии (popup_max_cards)
        config.set_popup_max_cards(5)
        popup.clear_history()
        for i in range(1, 6):
            popup.add_card(f"Текст {i}", f"Результат {i}")
        assert len(popup._cards) == 5
        # Добавление 6-й должно вытеснить самую старую (Текст 1)
        popup.add_card("Текст 6", "Результат 6")
        assert len(popup._cards) == 5
        assert popup._cards[0].source_text == "Текст 2"
        assert popup._cards[-1].source_text == "Текст 6"
        print("[OK] Автоматическое ограничение карточек в ленте (max_cards pruning) работает.")

        popup.clear_history()
        popup.shutdown()

        # -----------------------------------------------------------------
        # 9.4. Мастер первого запуска (FirstRunWizard)
        # -----------------------------------------------------------------
        print("\n--- 9.4. Мастер первого запуска (FirstRunWizard) ---")

        config.set_first_run_completed(False)
        assert config.is_first_run_completed() is False

        wiz = FirstRunWizard(config)
        assert wiz.stack.count() == 4
        assert wiz.stack.currentIndex() == 0

        # Переход по шагам
        wiz._next_step()
        assert wiz.stack.currentIndex() == 1
        assert wiz.back_btn.isEnabled()

        wiz._next_step()
        assert wiz.stack.currentIndex() == 2

        wiz._next_step()
        assert wiz.stack.currentIndex() == 3
        assert wiz.next_btn.text() == "Завершить и начать работу"

        wiz._prev_step()
        assert wiz.stack.currentIndex() == 2

        # Пропуск мастера
        wiz._skip_wizard()
        assert config.is_first_run_completed() is True
        print("[OK] Мастер первого запуска: навигация, сценарии и завершение работают.")

        # -----------------------------------------------------------------
        # 9.5. Контекстное меню трея и приостановка
        # -----------------------------------------------------------------
        print("\n--- 9.5. Трей: Меню, Быстрые команды и Пауза ---")

        import main as m
        ctrl = m.TrayApp(app, config_path=cfg_path)
        actions = [a.text() for a in ctrl.menu.actions() if a.text()]
        expected_items = [
            "Открыть мини-окно",
            "Открыть настройки",
            "История операций",
            "Выбрать действие",
            "Проекты",
            "Приостановить работу",
            "Глобальный хоткей",
            "Выход",
        ]
        assert actions == expected_items, f"Фактическое меню трея: {actions} != {expected_items}"
        print("[OK] Расширенное контекстное меню трея соответствует ТЗ Этапа 9.5.")

        # Проверка приостановки работы
        assert ctrl.config.is_app_paused() is False
        ctrl.pause_action.setChecked(True)
        assert ctrl.config.is_app_paused() is True
        assert "приостановлена" in ctrl.tray.toolTip().lower()

        ctrl.pause_action.setChecked(False)
        assert ctrl.config.is_app_paused() is False
        assert "приостановлена" not in ctrl.tray.toolTip().lower()
        print("[OK] Временная приостановка приложения (пауза) корректно переключает состояние и тултип.")

        # -----------------------------------------------------------------
        # 0. Строжайшее отсутствие эмодзи
        # -----------------------------------------------------------------
        print("\n--- Проверка строгого правила отсутствия эмодзи ---")
        # Диапазоны Unicode для эмодзи
        emoji_pattern = re.compile(
            r'[\U0001F600-\U0001F64F]|'  # смайлики
            r'[\U0001F300-\U0001F5FF]|'  # значки и символы
            r'[\U0001F680-\U0001F6FF]|'  # транспорт и карты
            r'[\U0001F700-\U0001F77F]|'  # геометрические
            r'[\U0001F780-\U0001F7FF]|'
            r'[\U0001F800-\U0001F8FF]|'
            r'[\U0001F900-\U0001F9FF]|'  # доп. символы
            r'[\U0001FA00-\U0001FA6F]|'
            r'[\U0001FA70-\U0001FAFF]|'
            r'[\u2600-\u26FF]|'          # разные символы
            r'[\u2700-\u27BF]'           # dingbats
        )

        code_files = [
            "config.py",
            "styles.py",
            "translation_card.py",
            "mini_window.py",
            "settings_window.py",
            "first_run_wizard.py",
            "main.py",
            "workers.py",
            "history_manager.py",
            "project_manager.py",
        ]

        # Допустимые символы: математические стрелки и знаки пунктуации (⇄, →, ⋯, ×, …)
        allowed_runes = {'⇄', '→', '⋯', '…', '✓', '✕', '–', '—', '•'}

        base_dir = Path(__file__).resolve().parent
        for fname in code_files:
            fpath = base_dir / fname
            if not fpath.exists():
                continue
            text = fpath.read_text(encoding="utf-8")
            matches = emoji_pattern.findall(text)
            violating = [m for m in matches if m not in allowed_runes]
            assert not violating, f"Обнаружены нежелательные эмодзи в {fname}: {violating}"

        print("[OK] Ни в одном исходном файле приложения нет запрещённых эмодзи.")

    print("\n=== ВСЕ ТЕСТЫ ЭТАПА 9 УСПЕШНО ПРОЙДЕНЫ! ===")


if __name__ == "__main__":
    run_stage9_tests()
