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
"""

from __future__ import annotations

import os
import sys
from typing import Optional

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (QColor, QIcon, QLinearGradient, QPainter, QPen,
                         QPixmap)
from PyQt6.QtWidgets import (QApplication, QMenu, QMessageBox,
                             QSystemTrayIcon)

from config import ConfigManager
from hotkey_manager import HotkeyManager
from mini_window import MiniPopupWindow
from settings_window import SettingsWindow
from styles import APP_QSS
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

    def __init__(self, app: QApplication) -> None:
        self.app = app

        # Конфигурация (config.json создаётся автоматически при первом запуске).
        self.config = ConfigManager()

        # Программно сгенерированная иконка — для трея, окон и диалогов.
        self.app_icon = create_app_icon()
        self.app.setWindowIcon(self.app_icon)

        # Окна создаём лениво и храним ссылки: повторный клик по меню
        # не плодит копии, а просто поднимает уже открытое окно.
        self._settings_window: Optional[SettingsWindow] = None
        self._mini_window: Optional[MiniPopupWindow] = None

        # --- Иконка в системном трее ---------------------------------------
        self.tray = QSystemTrayIcon(self.app_icon)
        self.tray.setToolTip(f"{APP_NAME} — помощник переводчика")

        self.menu = QMenu()
        action_settings = self.menu.addAction("Открыть настройки")
        action_settings.triggered.connect(self.show_settings)

        action_mini = self.menu.addAction("Открыть мини-окно")
        # lambda, чтобы triggered(bool) не передавал checked в captured_text
        action_mini.triggered.connect(lambda: self.show_mini_window())

        self.menu.addSeparator()

        action_quit = self.menu.addAction("Выход")
        action_quit.triggered.connect(self.quit_app)

        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

        # Вежливое уведомление при старте: приложение работает в фоне.
        self.tray.showMessage(
            APP_NAME,
            "Приложение запущено и работает в фоне.\n"
            f"Выделите текст и нажмите «{self.config.get('hotkey')}», "
            "чтобы перевести его.",
            QSystemTrayIcon.MessageIcon.Information,
            5000,
        )

        # --- Глобальный хоткей (библиотека keyboard, свой поток) --------------
        # Захват выделения происходит в фоновом потоке; в GUI текст попадает
        # строго через pyqtSignal (см. hotkey_manager.py).
        self.hotkey_manager = HotkeyManager(self.config)
        self.hotkey_manager.text_captured.connect(self._on_text_captured)
        self.hotkey_manager.capture_failed.connect(self._on_capture_failed)
        self.hotkey_manager.start()

        self._refresh_tray_tooltip()

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
        self._show_and_focus(self._settings_window)

    def _on_prompts_changed(self) -> None:
        """Пресеты пересохранены — освежаем панель мини-окна (если открыто)."""
        if self._mini_window is not None:
            self._mini_window.refresh_from_config()

    def _on_hotkey_changed(self, hotkey: str) -> None:
        """Хоткей перерегистрирован из настроек — обновляем трей и мини-окно."""
        self._refresh_tray_tooltip()
        if self._mini_window is not None:
            self._mini_window.refresh_from_config()

    def show_mini_window(self, captured_text: Optional[str] = None) -> None:
        """Открыть мини-окно.

        captured_text — текст, пойманный хоткеем: для него создаётся карточка;
        окно открывается у курсора (если было закрыто) либо просто дописывает
        карточку в конец открытой ленты. Без captured_text (пункт меню трея)
        окно открывается в правом нижнем углу экрана.
        """
        if self._mini_window is None:
            self._mini_window = MiniPopupWindow(
                self.config, self.app_icon, self.hotkey_manager
            )
        if captured_text is not None:
            self._mini_window.handle_new_text(captured_text)
        else:
            self._mini_window.show_bottom_right()

    # ---------------------------------------------- поток хоткея → GUI-поток
    # Сигналы приходят из фонового потока; PyQt сам ставит их в очередь
    # событий GUI-потока (queued connection) — трогать виджеты из потока
    # нельзя, поэтому здесь только «пересадка» на мини-окно.
    def _on_text_captured(self, text: str) -> None:
        """Готовый выделенный текст → карточка в мини-окне (пока заглушка)."""
        self.show_mini_window(captured_text=text)

    def _on_capture_failed(self, message: str) -> None:
        """Не удалось захватить выделение — мягко сообщаем через трей."""
        self.tray.showMessage(
            APP_NAME, message, QSystemTrayIcon.MessageIcon.Warning, 3000
        )

    def _refresh_tray_tooltip(self) -> None:
        """Тултип иконки трея показывает текущий хоткей (если он есть)."""
        tip = f"{APP_NAME} — помощник переводчика"
        hotkey = self.hotkey_manager.hotkey
        if hotkey:
            tip += f"\nХоткей мини-окна: {hotkey}"
        self.tray.setToolTip(tip)

    # ----------------------------------------------------------------- выход
    def quit_app(self) -> None:
        """«Выход»: снимаем хоткей, прячем иконку, закрываем приложение."""
        self.hotkey_manager.stop()
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

    _controller = TrayApp(app)  # noqa: F841 — держим ссылку, пока работает app.exec()
    exit_code = app.exec()
    # Даём фоновым потокам перевода пару секунд корректно завершиться.
    wait_for_workers()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
