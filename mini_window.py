"""
mini_window.py — мини-окно (Quick Popup): лента карточек с переводами (ШАГИ 2–5).

Свойства окна:
  • всегда поверх всех окон (WindowStaysOnTopHint), тёмный минимализм;
  • поля ввода НЕТ — только чтение и кнопки действий;
  • верхняя панель: переключатель «ИИ / Обычный», выпадающий список пресетов
    промптов, кнопка «Очистить историю»;
  • карточки добавляются в QScrollArea: если окно уже открыто — новая
    карточка просто дописывается в конец, и лента плавно скроллится вниз;
  • если окно было закрыто — оно открывается около курсора мыши
    (или в правом нижнем углу экрана) с первой карточкой;
  • пока идёт запрос, в карточке крутится текстовая анимация «Думаю…»; готовый
    текст или понятная ошибка приходят из TranslationWorker (workers.py,
    Шаг 3) — сеть работает только в QThread, GUI не зависает;
  • кнопки карточки (Шаг 5): «Повторить» — перегенерировать перевод;
    «Заменить в тексте» — окно прячется, фокус возвращается в ваше
    приложение и нажимается Ctrl+V (результат встаёт на место выделения).

При закрытии окна лента очищается: следующий захват откроет окно заново.
"""

from __future__ import annotations

from typing import List, Optional

import pyperclip

from PyQt6.QtCore import (QAbstractAnimation, QEasingCurve, Qt, QTimer,
                          QVariantAnimation)
from PyQt6.QtGui import QCloseEvent, QCursor, QIcon, QShowEvent
from PyQt6.QtWidgets import (QApplication, QComboBox, QFrame, QHBoxLayout,
                             QLabel, QMainWindow, QPushButton, QScrollArea,
                             QVBoxLayout, QWidget)

from config import ConfigManager
from styles import apply_dark_title_bar, repolish
from translation_card import TranslationCard
from workers import TranslationWorker

POPUP_WIDTH = 500               # фиксированная ширина Quick Popup
MIN_POPUP_HEIGHT = 220          # минимальная высота окна
MAX_POPUP_SCREEN_PART = 0.8     # не выше 80% высоты экрана


class MiniPopupWindow(QMainWindow):
    """Мини-окно (Quick Popup) — вертикальная лента карточек с результатами."""

    def __init__(self, config: ConfigManager, app_icon: QIcon,
                 hotkey_manager=None) -> None:
        super().__init__()
        self.config = config
        self.hotkey_manager = hotkey_manager  # для «Заменить в тексте»

        self.setWindowTitle("Truniversal — мини-окно")
        self.setWindowIcon(app_icon)
        # Quick Popup всегда поверх остальных окон.
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setFixedWidth(POPUP_WIDTH)
        self.setMinimumHeight(MIN_POPUP_HEIGHT)

        self._cards: List[TranslationCard] = []
        self._scroll_anim: Optional[QVariantAnimation] = None
        # Фоновые потоки перевода: держим ссылки, пока потоки живы.
        self._workers: set = set()

        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # --- Верхняя панель: режим, пресет, очистка ---------------------------
        self.header = QFrame()
        self.header.setObjectName("HeaderPanel")
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(12, 8, 12, 8)
        header_layout.setSpacing(8)

        self.mode_button = QPushButton()
        self.mode_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.mode_button.setToolTip(
            "Режим перевода.\n"
            "«ИИ» — нейросеть по активному промпту (Ollama / OpenAI-совместимый API).\n"
            "«Обычный» — обычный переводчик (Google / DeepL).\n"
            "Кликните, чтобы переключить."
        )
        self.mode_button.clicked.connect(self._toggle_mode)
        header_layout.addWidget(self.mode_button)

        self.preset_combo = QComboBox()
        self.preset_combo.setToolTip(
            "Активный пресет системного промпта для режима «ИИ».\n"
            "Редактировать пресеты можно будет в окне настроек."
        )
        self.preset_combo.setMinimumWidth(150)
        header_layout.addWidget(self.preset_combo, stretch=1)

        self.clear_button = QPushButton("Очистить историю")
        self.clear_button.setObjectName("ClearButton")
        self.clear_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_button.setToolTip("Удалить все карточки из ленты.")
        self.clear_button.clicked.connect(self.clear_history)
        header_layout.addWidget(self.clear_button)

        root.addWidget(self.header)

        # --- Лента карточек в QScrollArea --------------------------------------
        self.scroll = QScrollArea()
        self.scroll.setObjectName("CardsScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)

        self.container = QWidget()
        self.container.setObjectName("CardsContainer")
        self.cards_layout = QVBoxLayout(self.container)
        self.cards_layout.setContentsMargins(12, 12, 12, 12)
        self.cards_layout.setSpacing(10)

        self.empty_label = QLabel(
            "Лента пуста.\n"
            f"Выделите текст в любом приложении и нажмите «{config.get('hotkey')}»."
        )
        self.empty_label.setObjectName("EmptyStateLabel")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setWordWrap(True)
        self.cards_layout.addWidget(self.empty_label)
        self.cards_layout.addStretch(1)  # карточки выравниваются по верху

        self.scroll.setWidget(self.container)
        root.addWidget(self.scroll, stretch=1)

        self.setCentralWidget(central)

        # Подписка на выбор пресета — один раз: _populate_presets вызывается
        # повторно при обновлении из окна настроек и не должен плодить подписки.
        self.preset_combo.currentTextChanged.connect(self._on_preset_changed)
        self._populate_presets()
        self._refresh_mode_button()

    # ---------------------------------------------------------------- карточки
    def handle_new_text(self, source_text: str) -> None:
        """Новый захваченный текст → карточка «Думаю…» + фоновый перевод.

        Вся сеть — только в TranslationWorker (QThread), GUI не зависает:
        результат или понятная ошибка прилетают в карточку через pyqtSignal.
        """
        card = self.add_card(source_text, None)  # None = режим загрузки
        self._start_translation(card, source_text)

    def _start_translation(self, card: TranslationCard, source_text: str) -> None:
        """Запускает фоновый поток перевода и подключает его сигналы к карточке."""
        worker = TranslationWorker(self.config, source_text)
        worker.finished_ok.connect(card.set_result)
        worker.failed.connect(card.set_error)
        worker.finished.connect(lambda w=worker: self._worker_finished(w))
        self._workers.add(worker)  # держим ссылку — поток жив, пока нужен
        worker.start()

    def _worker_finished(self, worker: TranslationWorker) -> None:
        """Поток завершился: чистим реестр, подгоняем высоту и скроллим."""
        self._workers.discard(worker)
        self._adjust_height()
        self._scroll_to_bottom_smoothly()

    def regenerate_card(self, card: TranslationCard) -> None:
        """«Повторить»: карточка возвращается в «Думаю…», стартует новый воркер."""
        source = card.source_text
        if not source:
            return
        card.start_loading()
        self._start_translation(card, source)

    def replace_in_source(self, card: TranslationCard) -> None:
        """«Заменить в тексте»: вставить результат на место исходного выделения.

        Прячем окно (транзакция завершена, лента очищается), возвращаем
        фокус в приложение пользователя и нажимаем Ctrl+V — всё это делает
        HotkeyManager в фоновом потоке, GUI не зависает.
        """
        result = card.result_text
        if not result:
            return
        self.hide()
        self.clear_history()
        if self.hotkey_manager is not None:
            self.hotkey_manager.paste_to_window(result)
        else:
            # Менеджера нет (тестовое окружение) — хотя бы кладём в буфер.
            try:
                pyperclip.copy(result)
            except Exception:
                pass

    def add_card(self, source_text: str, result_text: str) -> TranslationCard:
        """Добавляет карточку в конец ленты; открывает окно, если оно скрыто."""
        was_visible = self.isVisible()
        card = TranslationCard(source_text, result_text)
        # Кнопки карточки общаются сигналами — мини-окно решает, что делать.
        card.regenerate_requested.connect(lambda c=card: self.regenerate_card(c))
        card.replace_requested.connect(lambda c=card: self.replace_in_source(c))
        self.cards_layout.removeWidget(self.empty_label)
        self.empty_label.hide()
        # Вставляем перед финальной растяжкой — карточка оказывается в конце.
        self.cards_layout.insertWidget(self.cards_layout.count() - 1, card)
        self._cards.append(card)
        card.show()
        self._adjust_height()
        # Скролл запускаем после прохода по layout.
        QTimer.singleShot(0, self._scroll_to_bottom_smoothly)
        if not was_visible:
            self._place_near_cursor()
        self.show()
        self.raise_()
        return card

    def clear_history(self) -> None:
        """«Очистить историю»: убрать все карточки, вернуть пустое состояние."""
        for card in self._cards:
            self.cards_layout.removeWidget(card)
            card.deleteLater()
        self._cards.clear()
        if self.cards_layout.indexOf(self.empty_label) == -1:
            self.cards_layout.insertWidget(0, self.empty_label)
        self.empty_label.show()
        self._adjust_height()

    # ------------------------------------------------------------ верхняя панель
    def _populate_presets(self) -> None:
        """Наполняет выпадающий список пресетами промптов из конфига.

        Подписка currentTextChanged создаётся один раз в __init__ — этот
        метод вызывается повторно при обновлении из окна настроек.
        """
        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()
        self.preset_combo.addItems(list(self.config.get("prompts", {}).keys()))
        self.preset_combo.setCurrentText(self.config.get("active_prompt_name", ""))
        self.preset_combo.blockSignals(False)

    def _on_preset_changed(self, name: str) -> None:
        """Пользователь выбрал пресет — сразу сохраняем в config.json."""
        if name and name != self.config.get("active_prompt_name"):
            self.config.set("active_prompt_name", name)

    def _toggle_mode(self) -> None:
        """Переключатель «ИИ / Обычный» — сохраняется в config.json."""
        new_mode = "standard" if self.config.get("mode") == "ai" else "ai"
        self.config.set("mode", new_mode)
        self._refresh_mode_button()

    def _refresh_mode_button(self) -> None:
        """Обновляет вид кнопки режима; пресеты актуальны только для ИИ."""
        is_ai = self.config.get("mode") == "ai"
        if is_ai:
            self.mode_button.setText("ИИ")
            self.mode_button.setObjectName("ModeButtonAi")
        else:
            self.mode_button.setText("Обычный")
            self.mode_button.setObjectName("ModeButtonStd")
        self.preset_combo.setEnabled(is_ai)
        repolish(self.mode_button)

    def refresh_from_config(self) -> None:
        """Обновить панель после изменений в окне настроек.

        Вызывается TrayApp по сигналам prompts_changed / hotkey_changed:
        освежаем список пресетов, кнопку режима и подсказку с хоткеем.
        """
        self._populate_presets()
        self._refresh_mode_button()
        self.empty_label.setText(
            "Лента пуста.\n"
            f"Выделите текст в любом приложении и нажмите «{self.config.get('hotkey')}»."
        )

    # -------------------------------------------------------- позиционирование
    def _place_near_cursor(self) -> None:
        """Открывает окно рядом с курсором, не выходя за пределы экрана."""
        cursor = QCursor.pos()
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        # По умолчанию — чуть правее и выше курсора.
        x = min(cursor.x() + 18, geo.right() - self.width())
        y = cursor.y() - self.height() - 18
        if y < geo.top():  # сверху не влезаем — размещаем под курсором
            y = min(cursor.y() + 24, geo.bottom() - self.height())
        self.move(max(int(x), geo.left()), max(int(y), geo.top()))

    def show_bottom_right(self) -> None:
        """Открытие из меню трея — в правом нижнем углу экрана."""
        self._adjust_height()
        screen = self.screen() or QApplication.primaryScreen()
        if screen is not None:
            geo = screen.availableGeometry()
            self.move(
                max(geo.right() - self.width() - 24, geo.left()),
                max(geo.bottom() - self.height() - 24, geo.top()),
            )
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _adjust_height(self) -> None:
        """Подгоняет высоту окна под содержимое (в пределах 80% экрана)."""
        content_h = self.container.sizeHint().height()
        header_h = self.header.sizeHint().height()
        target = content_h + header_h + 4  # небольшой запас на скроллбар/рамку
        screen = self.screen() or QApplication.primaryScreen()
        if screen is not None:
            max_h = int(screen.availableGeometry().height() * MAX_POPUP_SCREEN_PART)
            target = min(target, max_h)
        self.resize(POPUP_WIDTH, max(MIN_POPUP_HEIGHT, target))

    # ------------------------------------------------------------------ скролл
    def _scroll_to_bottom_smoothly(self) -> None:
        """Плавно прокручивает ленту к самой свежей карточке (~350 мс)."""
        bar = self.scroll.verticalScrollBar()
        target = bar.maximum()
        if target <= bar.value():
            return
        self._scroll_anim = QVariantAnimation(self)
        self._scroll_anim.setDuration(350)
        self._scroll_anim.setStartValue(bar.value())
        self._scroll_anim.setEndValue(target)
        self._scroll_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._scroll_anim.valueChanged.connect(bar.setValue)
        self._scroll_anim.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)

    # ----------------------------------------------------------- события окна
    def showEvent(self, event: QShowEvent) -> None:
        """Тёмный заголовок окна сразу после показа (Windows 10/11)."""
        super().showEvent(event)
        apply_dark_title_bar(self)

    def closeEvent(self, event: QCloseEvent) -> None:
        """История живёт, пока окно открыто; при закрытии лента очищается —
        следующий захват откроет окно заново, с первой карточкой."""
        self.clear_history()
        super().closeEvent(event)
