"""
main.py — точка входа приложения «Truniversal» (ШАГИ 1–5).

«Truniversal» — помощник переводчика для Windows. Архитектура из трёх узлов:

  1. Иконка в системном трее — приложение всегда работает в фоне.
     Одиночный клик по иконке открывает настройки, правый клик — меню.
  2. Главное окно («Комбайн» / Настройки) — пока заглушка (интерфейс — следующий шаг).
  3. Мини-окно (Quick Popup) — лента карточек с результатами. Шаг 2: глобальный
     хоткей, захват выделения, окно с карточками. Шаг 3: реальный перевод —
     «Обычный» (deep-translator / Google) или «ИИ» (OpenAI-совместимый API:
     Ollama, OpenRouter, OpenAI) строго в QThread (workers.py); пока идёт
     запрос, в карточке крутится «Думаю…», ошибки показываются в карточке.

Потоки: хоткей и захват — в фоновых потоках, перевод — в QThread; всё
попадает в GUI СТРОГО через pyqtSignal (hotkey_manager.py → TrayApp →
мини-окно → карточка).

Ключевое правило трея: закрытие любого окна НЕ завершает приложение —
оно остаётся работать в трее (setQuitOnLastWindowClosed(False)).

Этап 1 (стабилизация): защита от повторного запуска (мьютекс Windows),
предупреждение при неудачной регистрации хоткея и корректное завершение
приложения с активными фоновыми запросами (см. main()).
"""

from __future__ import annotations

import os
import sys
from typing import Optional

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import (QColor, QIcon, QLinearGradient, QPainter, QPen,
                         QPixmap)
from PyQt6.QtWidgets import (QApplication, QMenu, QMessageBox,
                             QSystemTrayIcon)

from config import ConfigManager
from hotkey_manager import HotkeyManager
from mini_window import MiniPopupWindow
from project_manager import get_project_manager
from settings_window import SettingsWindow
from single_instance import SingleInstanceGuard
from styles import APP_QSS, apply_theme
from workers import wait_for_workers

APP_NAME = "Truniversal"
APP_VERSION = "0.1.0"


def create_app_icon(size: int = 256) -> QIcon:
    """Рисует иконку приложения программно — внешний .png не нужен.

    Схема: скруглённый квадрат с диагональным градиентом (индиго → фиолет),
    мягкий блик в верхней части, тонкая светлая окантовка и стилизованная
    буква «T» из двух «капсул» с точкой-акцентом (конец переведённого
    предложения). Рисуем в высоком разрешении (256 px) — QIcon сам
    масштабирует картинку под размер трея/заголовка окна.
    """
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    # 1. Скруглённый квадрат-подложка с диагональным градиентом.
    rect = QRectF(size * 0.03, size * 0.03, size * 0.94, size * 0.94)
    radius = size * 0.22
    gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
    gradient.setColorAt(0.0, QColor("#4F5BFF"))
    gradient.setColorAt(1.0, QColor("#8A4DFF"))
    painter.setBrush(gradient)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(rect, radius, radius)

    # 2. Мягкий блик в верхней половине (объём и глубина).
    highlight = QLinearGradient(rect.topLeft(), QPointF(rect.left(), rect.center().y()))
    highlight.setColorAt(0.0, QColor(255, 255, 255, 42))
    highlight.setColorAt(1.0, QColor(255, 255, 255, 0))
    painter.setBrush(highlight)
    painter.drawRoundedRect(rect, radius, radius)

    # 3. Тонкая светлая окантовка.
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(QColor(255, 255, 255, 38), max(2.0, size * 0.008)))
    painter.drawRoundedRect(rect, radius, radius)

    # 4. Буква «T» из двух скруглённых «капсул»: перекладина + ножка.
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#FFFFFF"))
    bar_height = size * 0.115
    painter.drawRoundedRect(
        QRectF(size * 0.24, size * 0.29, size * 0.52, bar_height),
        bar_height / 2, bar_height / 2,
    )
    stem_width = size * 0.114
    painter.drawRoundedRect(
        QRectF(size * 0.443, size * 0.29, stem_width, size * 0.44),
        stem_width / 2, stem_width / 2,
    )

    # 5. Точка-акцент справа снизу (стилизованный «конец фразы»).
    painter.setBrush(QColor(255, 255, 255, 235))
    dot_radius = size * 0.05
    painter.drawEllipse(QPointF(size * 0.73, size * 0.73), dot_radius, dot_radius)

    painter.end()
    return QIcon(pixmap)


class TrayApp:
    """Контроллер трея: связывает конфиг, меню и окна приложения."""

    def __init__(self, app: QApplication,
                 config_path: Optional[os.PathLike | str] = None) -> None:
        self.app = app

        # Конфигурация (config.json создаётся автоматически при первом запуске).
        # config_path нужен тестам, чтобы не трогать реальный файл пользователя.
        self.config = ConfigManager(config_path)

        # Программно сгенерированная иконка — для трея, окон и диалогов.
        self.app_icon = create_app_icon()
        self.app.setWindowIcon(self.app_icon)

        # Применение сохранённой темы и размера шрифта (Этап 9.2)
        theme = self.config.get_theme() if hasattr(self.config, "get_theme") else "dark"
        font_size = self.config.get_font_size() if hasattr(self.config, "get_font_size") else "medium"
        apply_theme(self.app, theme, font_size)

        # Окна создаём лениво и храним ссылки: повторный клик по меню
        # не плодит копии, а просто поднимает уже открытое окно.
        self._settings_window: Optional[SettingsWindow] = None
        self._mini_window: Optional[MiniPopupWindow] = None

        # --- Иконка в системном трее ---------------------------------------
        self.tray = QSystemTrayIcon(self.app_icon)
        self.tray.setToolTip(f"{APP_NAME} — помощник переводчика")

        self.menu = QMenu()
        action_mini = self.menu.addAction("Открыть мини-окно")
        # lambda, чтобы triggered(bool) не передавал checked в captured_text
        action_mini.triggered.connect(lambda: self.show_mini_window())

        action_settings = self.menu.addAction("Открыть настройки")
        action_settings.triggered.connect(self.show_settings)

        action_history = self.menu.addAction("История операций")
        action_history.triggered.connect(self.show_history_window)

        # Подменю выбора действия (Этап 9.5)
        self.actions_menu = self.menu.addMenu("Выбрать действие")
        self.actions_menu.aboutToShow.connect(self._refresh_tray_actions_menu)
        self._refresh_tray_actions_menu()

        # Быстрое переключение проектов из трея (Этап 8)
        self.projects_menu = self.menu.addMenu("Проекты")
        self.projects_menu.aboutToShow.connect(self._refresh_tray_projects_menu)
        self._refresh_tray_projects_menu()

        self.menu.addSeparator()

        # Приостановить работу (Этап 9.5)
        self.pause_action = self.menu.addAction("Приостановить работу")
        self.pause_action.setCheckable(True)
        is_paused = bool(self.config.is_app_paused() if hasattr(self.config, "is_app_paused") else False)
        self.pause_action.setChecked(is_paused)
        self.pause_action.toggled.connect(self._toggle_app_paused)

        # Быстрое включение/выключение хоткея, не открывая настройки.
        self.hotkey_toggle = self.menu.addAction("Глобальный хоткей")
        self.hotkey_toggle.setCheckable(True)
        self.hotkey_toggle.setChecked(
            bool(self.config.get("hotkey_enabled", True))
        )
        self.hotkey_toggle.toggled.connect(self._toggle_hotkey_enabled)

        self.menu.addSeparator()

        action_quit = self.menu.addAction("Выход")
        action_quit.triggered.connect(self.quit_app)

        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

        # --- Глобальный хоткей (библиотека keyboard, свой поток) --------------
        # Захват выделения происходит в фоновом потоке; в GUI текст попадает
        # строго через pyqtSignal (см. hotkey_manager.py).
        self.hotkey_manager = HotkeyManager(self.config)
        self.hotkey_manager.text_captured.connect(self._on_text_captured)
        self.hotkey_manager.action_captured.connect(self._on_action_captured)
        self.hotkey_manager.capture_failed.connect(self._on_capture_failed)

        if is_paused:
            self.hotkey_manager.set_enabled(False)

        start_status = self.hotkey_manager.start()
        if start_status == "failed":
            # Без хоткея приложение почти бесполезно — честно предупреждаем.
            self.tray.showMessage(
                APP_NAME,
                "Не удалось зарегистрировать глобальный хоткей "
                f"«{self.config.get('hotkey')}».\n"
                "Возможно, сочетание занято другой программой или не хватает "
                "прав (окна от администратора требуют запуска от "
                "администратора). Изменить хоткей можно в настройках.",
                QSystemTrayIcon.MessageIcon.Warning,
                8000,
            )
        elif start_status == "ok":
            # Вежливое уведомление при старте: приложение работает в фоне.
            self.tray.showMessage(
                APP_NAME,
                "Приложение запущено и работает в фоне.\n"
                f"Выделите текст и нажмите «{self.config.get('hotkey')}», "
                "чтобы перевести его.",
                QSystemTrayIcon.MessageIcon.Information,
                5000,
            )
        # "disabled" — пользователь сам выключил хоткей; тултип скажет,
        # как включить обратно. Балун не нужен.

        # Автоматическая очистка истории по сроку хранения (Этап 7.3)
        try:
            retention_days = self.config.get_history_retention_days() if hasattr(self.config, "get_history_retention_days") else 0
            if retention_days > 0:
                from history_manager import get_history_manager
                get_history_manager().apply_retention_policy(retention_days)
        except Exception:
            pass

        self._refresh_tray_tooltip()

        # Мастер первоначальной настройки (Этап 9.4)
        if hasattr(self.config, "is_first_run_completed") and not self.config.is_first_run_completed():
            QTimer.singleShot(250, self.show_first_run_wizard)

    # ------------------------------------------------------------------ трей
    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        """Одиночный/двойной клик по иконке → открыть настройки."""
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.show_settings()

    # ------------------------------------------------------------------ окна
    @staticmethod
    def _show_and_focus(window) -> None:
        """Поднимает окно на передний план (дубликаты не создаются)."""
        window.showNormal()
        window.raise_()
        window.activateWindow()

    def show_settings(self) -> None:
        """«Открыть настройки» — главное окно («Комбайн»)."""
        if self._settings_window is None:
            self._settings_window = SettingsWindow(
                self.config, self.app_icon, self.hotkey_manager
            )
            # Окно настроек сообщает об изменениях — обновляем мини-окно и трей.
            self._settings_window.prompts_changed.connect(self._on_prompts_changed)
            self._settings_window.hotkey_changed.connect(self._on_hotkey_changed)
            self._settings_window.open_card_requested.connect(self._on_history_open_card)
            self._settings_window.repeat_request_requested.connect(self._on_history_repeat_request)
            self._settings_window.projects_changed.connect(self._on_projects_changed)
        self._show_and_focus(self._settings_window)

    def show_history_window(self) -> None:
        """«История операций» — открывает окно настроек на вкладке истории (Этап 7.2)."""
        self.show_settings()
        if self._settings_window is not None:
            self._settings_window.open_history_tab()

    def show_projects_window(self) -> None:
        """«Проекты и Глоссарий» — открывает окно настроек на вкладке проектов (Этап 8)."""
        self.show_settings()
        if self._settings_window is not None:
            self._settings_window.open_projects_tab()

    def _refresh_tray_projects_menu(self) -> None:
        """Обновляет подменю проектов в трее (список проектов + галочка активного)."""
        self.projects_menu.clear()
        pm = get_project_manager()
        active_pid = pm.get_active_project_id()
        projects = pm.list_projects()

        # Пункт "Без проекта (общий)"
        no_proj_act = self.projects_menu.addAction("Без проекта (общий)")
        no_proj_act.setCheckable(True)
        no_proj_act.setChecked(not bool(active_pid))
        no_proj_act.triggered.connect(lambda: self._set_active_project(""))

        if projects:
            self.projects_menu.addSeparator()
            for p in projects:
                pid = p.get("id", "")
                pname = p.get("name", "Без названия")
                is_act = (pid == active_pid)
                act = self.projects_menu.addAction(pname)
                act.setCheckable(True)
                act.setChecked(is_act)
                act.triggered.connect(lambda checked, project_id=pid: self._set_active_project(project_id))

        self.projects_menu.addSeparator()
        manage_act = self.projects_menu.addAction("Управление проектами...")
        manage_act.triggered.connect(self.show_projects_window)

    def _refresh_tray_actions_menu(self) -> None:
        """Обновляет подменю выбора действий в трее (Этап 9.5)."""
        self.actions_menu.clear()
        actions = self.config.get_actions() if hasattr(self.config, "get_actions") else []
        active_id = self.config.get_active_action_id() if hasattr(self.config, "get_active_action_id") else ""
        for act in actions:
            aid = act["id"]
            name = act["name"]
            item = self.actions_menu.addAction(name)
            item.setCheckable(True)
            item.setChecked(aid == active_id)
            item.triggered.connect(lambda checked=False, a_id=aid: self._set_active_action_from_tray(a_id))

    def _set_active_action_from_tray(self, action_id: str) -> None:
        """Переключает активное действие из меню трея (Этап 9.5)."""
        if hasattr(self.config, "set_active_action"):
            self.config.set_active_action(action_id)
        self._refresh_tray_actions_menu()
        if self._mini_window is not None:
            self._mini_window.refresh_from_config()

    def _toggle_app_paused(self, paused: bool) -> None:
        """Приостанавливает/возобновляет работу приложения (Этап 9.5)."""
        if hasattr(self.config, "set_app_paused"):
            self.config.set_app_paused(paused)
        else:
            self.config.set("app_paused", paused)
        self.hotkey_manager.set_enabled(not paused)
        self._refresh_tray_tooltip()

    def show_first_run_wizard(self) -> None:
        """Запуск мастера первоначальной настройки (Этап 9.4)."""
        try:
            from first_run_wizard import FirstRunWizard
            wizard = FirstRunWizard(self.config)
            wizard.exec()
            self._refresh_tray_tooltip()
            self._sync_hotkey_menu_state()
            if self._mini_window is not None:
                self._mini_window.refresh_from_config()
        except Exception:
            pass

    def _set_active_project(self, project_id: str) -> None:
        """Переключает активный проект из любого интерфейса (трей, мини-окно, настройки)."""
        pm = get_project_manager()
        pm.set_active_project_id(project_id)
        if hasattr(self.config, "set_active_project_id"):
            self.config.set_active_project_id(project_id)
        self._refresh_tray_projects_menu()
        if self._mini_window is not None:
            self._mini_window.refresh_from_config()
        if self._settings_window is not None:
            self._settings_window.refresh_from_config()

    def _on_active_project_changed(self, project_id: str) -> None:
        """Обработчик изменения проекта из мини-окна."""
        self._set_active_project(project_id)

    def _on_projects_changed(self) -> None:
        """Обработчик изменения проектов из окна настроек."""
        self._refresh_tray_projects_menu()
        if self._mini_window is not None:
            self._mini_window.refresh_from_config()

    def _on_history_open_card(self, record: dict) -> None:
        """Отображает карточку из постоянной истории в мини-окне (Этап 7.2)."""
        if self._mini_window is None:
            self.show_mini_window()
        if self._mini_window is not None:
            self._mini_window.display_history_card(record)

    def _on_history_repeat_request(self, record: dict) -> None:
        """Повторный запуск запроса из истории (Этап 7.2)."""
        src = str(record.get("source_text", ""))
        aid = record.get("action_id", "")
        self.show_mini_window(captured_text=src, action_id=aid)

    def _on_prompts_changed(self) -> None:
        """Пресеты пересохранены — освежаем панель мини-окна (если открыто)."""
        if self._mini_window is not None:
            self._mini_window.refresh_from_config()

    def _on_hotkey_changed(self, hotkey: str) -> None:
        """Хоткей перерегистрирован из настроек — обновляем трей и мини-окно."""
        self._refresh_tray_tooltip()
        self._sync_hotkey_menu_state()
        if self._mini_window is not None:
            self._mini_window.refresh_from_config()

    def _toggle_hotkey_enabled(self, enabled: bool) -> None:
        """Вкл/выкл хоткея прямо из меню трея (сразу сохраняем в config.json)."""
        enabled = bool(enabled)
        if not self.config.set("hotkey_enabled", enabled):
            self.tray.showMessage(
                APP_NAME,
                "Не удалось записать config.json — состояние хоткея "
                "не сохранено после перезапуска.",
                QSystemTrayIcon.MessageIcon.Warning,
                5000,
            )
        self.hotkey_manager.set_enabled(enabled)
        self._refresh_tray_tooltip()
        if self._mini_window is not None:
            self._mini_window.refresh_from_config()

    def _sync_hotkey_menu_state(self) -> None:
        """Галочка меню трея отражает конфиг (настройки могли его изменить)."""
        self.hotkey_toggle.setChecked(bool(self.config.get("hotkey_enabled", True)))

    def show_mini_window(self, captured_text: Optional[str] = None,
                         action_id: Optional[str] = None) -> None:
        """Открыть мини-окно.

        captured_text — текст, пойманный хоткеем: для него создаётся карточка;
        action_id — конкретное AI-действие, если захват инициирован хоткеем действия;
        окно открывается у курсора (если было закрыто) либо просто дописывает
        карточку в конец открытой ленты. Без captured_text (пункт меню трея)
        окно открывается в правом нижнем углу экрана.
        """
        if self._mini_window is None:
            self._mini_window = MiniPopupWindow(
                self.config, self.app_icon, self.hotkey_manager
            )
            self._mini_window.history_requested.connect(self.show_history_window)
            self._mini_window.projects_requested.connect(self.show_projects_window)
            self._mini_window.project_changed.connect(self._on_active_project_changed)
        if captured_text is not None:
            self._mini_window.handle_new_text(captured_text, action_id=action_id)
        else:
            self._mini_window.show_bottom_right()

    # ---------------------------------------------- поток хоткея → GUI-поток
    # Сигналы приходят из фонового потока; PyQt сам ставит их в очередь
    # событий GUI-потока (queued connection) — трогать виджеты из потока
    # нельзя, поэтому здесь только «пересадка» на мини-окно.
    def _on_text_captured(self, text: str) -> None:
        """Готовый выделенный текст → карточка «Думаю…» в мини-окне."""
        if hasattr(self.config, "is_app_paused") and self.config.is_app_paused():
            return
        self.show_mini_window(captured_text=text)

    def _on_action_captured(self, text: str, action_id: str) -> None:
        """Готовый текст по выделенному хоткею действия → мини-окно с этим действием."""
        if hasattr(self.config, "is_app_paused") and self.config.is_app_paused():
            return
        self.show_mini_window(captured_text=text, action_id=action_id)

    def _on_capture_failed(self, message: str) -> None:
        """Не удалось захватить выделение — мягко сообщаем через трей."""
        self.tray.showMessage(
            APP_NAME, message, QSystemTrayIcon.MessageIcon.Warning, 3000
        )

    def _refresh_tray_tooltip(self) -> None:
        """Тултип иконки трея: хоткей, состояние паузы либо почему его нет (Этап 9.5)."""
        if hasattr(self.config, "is_app_paused") and self.config.is_app_paused():
            self.tray.setToolTip(f"{APP_NAME} — Работа приостановлена")
            return
        tip = f"{APP_NAME} — помощник переводчика"
        hotkey = (self.config.get("hotkey") or "").strip()
        if bool(self.config.get("hotkey_enabled", True)):
            if hotkey:
                tip += f"\nХоткей мини-окна: {hotkey}"
            else:
                tip += "\nХоткей не задан — настройте его в окне настроек"
        else:
            tip += "\nХоткей отключён (меню трея → «Глобальный хоткей»)"
        self.tray.setToolTip(tip)

    # ----------------------------------------------------------------- выход
    def quit_app(self) -> None:
        """«Выход»: останавливаем фоновые задачи, снимаем хоткей, завершаем."""
        # Окно настроек могло запустить фоновые задачи (запись хоткея,
        # загрузку списка моделей) — останавливаем их ДО выхода: живой
        # QThread при завершении приложения роняет его (qFatal).
        if self._settings_window is not None:
            self._settings_window.shutdown()
        # Мини-окно могло иметь активные фоновые переводы — отменяем их
        if self._mini_window is not None:
            self._mini_window.shutdown()
        # shutdown снимает хоткей, все хуки keyboard и дожидается освобождения буфера
        self.hotkey_manager.shutdown()
        self.tray.hide()
        self.app.quit()


def main() -> int:
    # Сборка --windowed (PyInstaller): консоли нет, sys.stdout/stderr == None.
    # Наш код печатает диагностику через print() — направим её в «никуда».
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")

    app = QApplication(sys.argv)

    # ГЛАВНОЕ ПРАВИЛО: закрытие окон не завершает приложение —
    # оно продолжает жить в трее, пока не выбран «Выход» из меню.
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setStyleSheet(APP_QSS)  # тёмная минималистичная тема

    # Без системного трея приложению негде жить — честно сообщаем и выходим.
    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.critical(
            None,
            APP_NAME,
            "Системный трей недоступен.\n"
            "Приложение работает в фоновом режиме и не может быть запущено "
            "в среде без области уведомлений.",
        )
        return 1

    # Повторный запуск не имеет смысла: две копии конфликтовали бы за
    # глобальный хоткей и буфер обмена. Проверяем именованным мьютексом
    # Windows; если копия уже работает — сообщаем и выходим.
    _instance_guard = SingleInstanceGuard()  # noqa: F841 — мьютекс живёт до конца процесса
    if not _instance_guard.acquire():
        QMessageBox.information(
            None,
            APP_NAME,
            "Truniversal уже запущен.\n"
            "Его иконка находится в области уведомлений (трей), возле часов.",
        )
        return 0

    _controller = TrayApp(app)  # noqa: F841 — держим ссылку, пока работает app.exec()
    exit_code = app.exec()
    # Даём фоновым воркерам несколько секунд корректно завершиться.
    wait_for_workers(5000)

    # Завершаем процесс немедленно и чисто. Если к этому моменту ещё жив
    # QThread с долгим запросом (локальная модель может думать десятки
    # секунд), разборка Python-интерпретатора уничтожила бы его C++-объект
    # и уронила приложение (qFatal «QThread: Destroyed while thread is
    # still running»). Все настройки пишутся синхронно — незаписанных
    # данных нет, поэтому os._exit() безопасен и не даёт аварийных диалогов.
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass
    os._exit(exit_code)


if __name__ == "__main__":
    sys.exit(main())
