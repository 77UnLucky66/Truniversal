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

from typing import List, Optional, Tuple

import pyperclip

from PyQt6.QtCore import (QAbstractAnimation, QEasingCurve, QPoint, Qt, QTimer,
                          QVariantAnimation, pyqtSignal)
from PyQt6.QtGui import (QCloseEvent, QCursor, QIcon, QKeyEvent, QMoveEvent,
                         QResizeEvent, QScreen, QShowEvent)
from PyQt6.QtWidgets import (QApplication, QComboBox, QFrame, QHBoxLayout,
                             QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox,
                             QPushButton, QScrollArea, QSizePolicy, QVBoxLayout,
                             QWidget)

from config import ConfigManager
from styles import apply_dark_title_bar, apply_title_bar_theme, detect_system_theme, repolish
from translation_card import TranslationCard
from workers import TranslationWorker

POPUP_WIDTH = 760               # ширина Quick Popup по умолчанию (Этап 9.1)
DEFAULT_POPUP_WIDTH = 760       # ширина по умолчанию
MIN_POPUP_WIDTH = 580           # минимальная ширина окна
MIN_POPUP_HEIGHT = 220          # минимальная высота окна
MAX_POPUP_SCREEN_PART = 0.8     # не выше 80% высоты экрана


class MiniPopupWindow(QMainWindow):
    """Мини-окно (Quick Popup) — вертикальная лента карточек с результатами."""

    #: Запрос на открытие раздела постоянной истории (Этап 7.2)
    history_requested = pyqtSignal()
    #: Сигнал смены активного проекта (Этап 8)
    project_changed = pyqtSignal(str)
    #: Запрос на открытие вкладки проектов в настройках (Этап 8)
    projects_requested = pyqtSignal()

    def __init__(self, config: ConfigManager, app_icon: QIcon,
                 hotkey_manager=None) -> None:
        super().__init__()
        self.config = config
        self.hotkey_manager = hotkey_manager  # для «Заменить в тексте»

        self.setWindowTitle("Truniversal — мини-окно")
        self.setWindowIcon(app_icon)

        # Quick Popup поверх остальных окон (Этап 9.1: переключаемый pin)
        stays_on_top = bool(self.config.is_popup_stays_on_top() if hasattr(self.config, "is_popup_stays_on_top") else self.config.get("popup_stays_on_top", True))
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, stays_on_top)
        self.setMinimumSize(MIN_POPUP_WIDTH, MIN_POPUP_HEIGHT)

        # Прозрачность окна (Этап 9.1)
        opacity = self.config.get_popup_opacity() if hasattr(self.config, "get_popup_opacity") else 1.0
        self.setWindowOpacity(opacity)

        # Восстановление сохранённых размеров
        saved_w = self.config.get("popup_width")
        saved_h = self.config.get("popup_height")
        self._user_width = saved_w if (saved_w and saved_w >= MIN_POPUP_WIDTH) else DEFAULT_POPUP_WIDTH
        init_h = saved_h if (saved_h and saved_h >= MIN_POPUP_HEIGHT) else MIN_POPUP_HEIGHT
        self.resize(self._user_width, init_h)

        self._cards: List[TranslationCard] = []
        self._scroll_anim: Optional[QVariantAnimation] = None
        # Фоновые потоки перевода: держим ссылки, пока потоки живы.
        self._workers: set = set()
        self._card_workers: dict = {}

        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # --- Верхняя панель: режим, действия, пресет, очистка, пин ------------
        self.header = QFrame()
        self.header.setObjectName("HeaderPanel")
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(8, 6, 8, 6)
        header_layout.setSpacing(5)

        self.mode_button = QPushButton()
        self.mode_button.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        self.mode_button.setFixedHeight(30)
        self.mode_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.mode_button.setToolTip(
            "Режим перевода.\n"
            "«ИИ» — нейросеть по активному промпту (Ollama / OpenAI-совместимый API).\n"
            "«Обычный» — обычный переводчик (Google / DeepL).\n"
            "Кликните, чтобы переключить."
        )
        self.mode_button.clicked.connect(self._toggle_mode)
        header_layout.addWidget(self.mode_button)

        self.actions_menu_btn = QPushButton("Действия")
        self.actions_menu_btn.setObjectName("QuickActionsMenuBtn")
        self.actions_menu_btn.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        self.actions_menu_btn.setFixedHeight(30)
        self.actions_menu_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.actions_menu_btn.setToolTip("Меню AI Quick Actions: перефразировать, грамматика, стили, объяснение и др.")
        self.actions_menu_btn.clicked.connect(self._open_quick_actions_menu)
        header_layout.addWidget(self.actions_menu_btn)

        self.preset_combo = QComboBox()
        self.preset_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.preset_combo.setFixedHeight(30)
        self.preset_combo.setToolTip(
            "Активный пресет системного промпта для режима «ИИ».\n"
            "Редактировать пресеты можно в окне настроек."
        )
        self.preset_combo.setMinimumWidth(90)
        header_layout.addWidget(self.preset_combo, stretch=1)

        self.custom_prompt_btn = QPushButton("Свой запрос")
        self.custom_prompt_btn.setObjectName("CustomPromptToggleBtn")
        self.custom_prompt_btn.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        self.custom_prompt_btn.setFixedHeight(30)
        self.custom_prompt_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.custom_prompt_btn.setToolTip("Ввести произвольный промпт / инструкцию для ИИ к выделенному тексту")
        self.custom_prompt_btn.clicked.connect(self._toggle_custom_prompt_bar)
        header_layout.addWidget(self.custom_prompt_btn)

        self.history_browser_btn = QPushButton("История")
        self.history_browser_btn.setObjectName("HistoryBrowserBtn")
        self.history_browser_btn.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        self.history_browser_btn.setFixedHeight(30)
        self.history_browser_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.history_browser_btn.setToolTip("Открыть постоянную историю всех операций (SQLite)")
        self.history_browser_btn.clicked.connect(self.history_requested.emit)
        header_layout.addWidget(self.history_browser_btn)

        self.clear_button = QPushButton("Очистить")
        self.clear_button.setObjectName("ClearButton")
        self.clear_button.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        self.clear_button.setFixedHeight(30)
        self.clear_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_button.setToolTip("Удалить все текущие карточки из этого окна.")
        self.clear_button.clicked.connect(self.clear_history)
        header_layout.addWidget(self.clear_button)

        self.pin_btn = QPushButton("Закрепить")
        self.pin_btn.setObjectName("PinTopBtn")
        self.pin_btn.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        self.pin_btn.setFixedHeight(30)
        self.pin_btn.setCheckable(True)
        self.pin_btn.setChecked(stays_on_top)
        self.pin_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pin_btn.setToolTip("Закрепить мини-окно поверх всех остальных окон Windows (Этап 9.1)")
        self.pin_btn.toggled.connect(self._toggle_stay_on_top)
        header_layout.addWidget(self.pin_btn)

        root.addWidget(self.header)

        # --- Панель проекта и конфиденциальности (Этап 8) ---------------------
        self.project_bar = QFrame()
        self.project_bar.setObjectName("ProjectBar")
        proj_layout = QHBoxLayout(self.project_bar)
        proj_layout.setContentsMargins(10, 4, 10, 4)
        proj_layout.setSpacing(8)

        self.project_combo = QComboBox()
        self.project_combo.setObjectName("ProjectSelector")
        self.project_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.project_combo.setFixedHeight(28)
        self.project_combo.setToolTip("Активный проект перевода (глоссарий, правила, контекст произведения)")
        self.project_combo.currentIndexChanged.connect(self._on_project_combo_changed)
        proj_layout.addWidget(self.project_combo, stretch=1)

        self.ad_hoc_btn = QPushButton("+ Заметка")
        self.ad_hoc_btn.setObjectName("ProjectBarBtn")
        self.ad_hoc_btn.setFixedHeight(28)
        self.ad_hoc_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.ad_hoc_btn.setToolTip("Добавить разовое примечание / контекст к следующему переводу")
        self.ad_hoc_btn.clicked.connect(self._toggle_ad_hoc_bar)
        proj_layout.addWidget(self.ad_hoc_btn)

        self.memory_btn = QPushButton("Память: 0")
        self.memory_btn.setObjectName("ProjectBarBtn")
        self.memory_btn.setFixedHeight(28)
        self.memory_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.memory_btn.setToolTip("Краткосрочная контекстная память проекта. Кликните для управления или сброса.")
        self.memory_btn.clicked.connect(self._on_memory_btn_clicked)
        proj_layout.addWidget(self.memory_btn)

        # Жёлтый бейдж "Облако..." вырезан из интерфейса по требованию пользователя
        self.privacy_badge = QLabel("Локально")
        self.privacy_badge.setObjectName("PrivacyBadgeLocal")
        self.privacy_badge.setVisible(False)

        root.addWidget(self.project_bar)

        # --- Подпанель ввода разовой заметки (ad-hoc контекст) ----------------
        self.ad_hoc_bar = QFrame()
        self.ad_hoc_bar.setObjectName("AdHocBar")
        ad_hoc_lay = QHBoxLayout(self.ad_hoc_bar)
        ad_hoc_lay.setContentsMargins(10, 4, 10, 4)
        ad_hoc_lay.setSpacing(6)

        self.ad_hoc_edit = QLineEdit()
        self.ad_hoc_edit.setObjectName("AdHocEdit")
        self.ad_hoc_edit.setPlaceholderText("Разовая заметка к следующему переводу (напр. «Это сарказм», «Говорит рыцарь»)...")
        self.ad_hoc_edit.returnPressed.connect(self._save_ad_hoc_context)
        ad_hoc_lay.addWidget(self.ad_hoc_edit, stretch=1)

        self.ad_hoc_apply_btn = QPushButton("Задать")
        self.ad_hoc_apply_btn.setObjectName("PrimaryButton")
        self.ad_hoc_apply_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.ad_hoc_apply_btn.clicked.connect(self._save_ad_hoc_context)
        ad_hoc_lay.addWidget(self.ad_hoc_apply_btn)

        self.ad_hoc_close_btn = QPushButton("x")
        self.ad_hoc_close_btn.setObjectName("CloseSubBarBtn")
        self.ad_hoc_close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.ad_hoc_close_btn.clicked.connect(lambda: (self.ad_hoc_bar.hide(), self._adjust_height()))
        ad_hoc_lay.addWidget(self.ad_hoc_close_btn)

        self.ad_hoc_bar.hide()
        root.addWidget(self.ad_hoc_bar)

        # --- Панель ввода пользовательского промпта (скрыта по умолчанию) ------
        self.custom_prompt_bar = QFrame()
        self.custom_prompt_bar.setObjectName("CustomPromptBar")
        custom_layout = QHBoxLayout(self.custom_prompt_bar)
        custom_layout.setContentsMargins(12, 6, 12, 6)
        custom_layout.setSpacing(6)

        self.custom_prompt_edit = QLineEdit()
        self.custom_prompt_edit.setObjectName("CustomPromptEdit")
        self.custom_prompt_edit.setPlaceholderText("Введите инструкцию для ИИ (напр. «Сделай стихами», «Найди ошибки»)...")
        self.custom_prompt_edit.returnPressed.connect(self._run_custom_prompt)
        custom_layout.addWidget(self.custom_prompt_edit, stretch=1)

        self.custom_prompt_run_btn = QPushButton("Выполнить")
        self.custom_prompt_run_btn.setObjectName("PrimaryButton")
        self.custom_prompt_run_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.custom_prompt_run_btn.clicked.connect(self._run_custom_prompt)
        custom_layout.addWidget(self.custom_prompt_run_btn)

        self.custom_prompt_close_btn = QPushButton("x")
        self.custom_prompt_close_btn.setObjectName("CloseSubBarBtn")
        self.custom_prompt_close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.custom_prompt_close_btn.clicked.connect(lambda: (self.custom_prompt_bar.hide(), self._adjust_height()))
        custom_layout.addWidget(self.custom_prompt_close_btn)

        self.custom_prompt_bar.hide()
        root.addWidget(self.custom_prompt_bar)

        # --- Панель быстрых действий (Закреплённые действия / Pills) ------------
        self.pinned_bar = QFrame()
        self.pinned_bar.setObjectName("PinnedActionsBar")
        self.pinned_layout = QHBoxLayout(self.pinned_bar)
        self.pinned_layout.setContentsMargins(12, 4, 12, 4)
        self.pinned_layout.setSpacing(6)
        root.addWidget(self.pinned_bar)

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
        self._refresh_pinned_actions()
        self._refresh_mode_button()
        self._refresh_projects_combo()
        self._refresh_privacy_badge()
        self._refresh_memory_status()

    # ---------------------------------------------------------------- карточки
    def handle_new_text(self, source_text: str, action_id: Optional[str] = None,
                        custom_prompt: Optional[str] = None) -> None:
        """Новый захваченный текст → карточка «Думаю…» + фоновый перевод.

        Вся сеть — только в TranslationWorker (QThread), GUI не зависает:
        результат или понятная ошибка прилетают в карточку через pyqtSignal.
        """
        card = self.add_card(source_text, None)  # None = режим загрузки
        self._start_translation(card, source_text, action_id=action_id, custom_prompt=custom_prompt)

    def _start_translation(self, card: TranslationCard, source_text: str,
                           action_id: Optional[str] = None,
                           custom_prompt: Optional[str] = None) -> None:
        """Запускает фоновый поток перевода и подключает его сигналы к карточке."""
        # Устанавливаем бейдж активного проекта на карточке (Этап 8)
        try:
            from project_manager import get_project_manager
            pm = get_project_manager()
            act_p = pm.get_active_project()
            if act_p:
                card.set_project(act_p.get("name", ""))
        except Exception:
            pass

        worker = TranslationWorker(
            self.config,
            source_text,
            source_lang=card.source_lang,
            target_lang=card.target_lang,
            action_id=action_id,
            custom_prompt=custom_prompt,
        )
        worker.direction_resolved.connect(card.set_direction)
        worker.action_resolved.connect(card.set_action)
        worker.status_changed.connect(card.set_status)
        worker.finished_ok.connect(lambda res, c=card, w=worker: self._on_worker_finished_ok(c, w, res))
        worker.failed_with_details.connect(lambda msg, det, c=card: c.set_error(msg, det))
        worker.failed.connect(lambda msg, c=card: c.set_error(msg))
        worker.finished.connect(lambda w=worker: self._worker_finished(w))
        card.result_edited.connect(lambda new_text, c=card: self._on_card_result_edited(c, new_text))
        self._workers.add(worker)  # держим ссылку — поток жив, пока нужен
        self._card_workers[card] = worker
        worker.start()

    def _on_worker_finished_ok(self, card: TranslationCard, worker: TranslationWorker, result_text: str) -> None:
        """Успешное завершение перевода: отображение в карточке + сохранение в SQLite-историю."""
        card.set_result(result_text)

        # Сохранение в постоянную историю (Этап 7.1, 7.3)
        history_enabled = True
        if hasattr(self.config, "is_history_enabled"):
            history_enabled = self.config.is_history_enabled()
        elif hasattr(self.config, "get"):
            history_enabled = bool(self.config.get("history_enabled", True))

        if history_enabled:
            try:
                from history_manager import get_history_manager
                hm = get_history_manager()
                meta = getattr(worker, "operation_meta", {}) or {}

                # Проверяем наличие вариантов для JSON-сохранения
                variants_json = ""
                try:
                    from text_diff import extract_text_variants
                    variants = extract_text_variants(result_text)
                    if variants and len(variants) >= 2:
                        import json
                        variants_json = json.dumps([{"label": v[0], "text": v[1]} for v in variants], ensure_ascii=False)
                except Exception:
                    pass

                record_id = hm.add_record(
                    source_text=meta.get("source_text") or card.source_text,
                    result_text=result_text,
                    action_id=meta.get("action_id") or card.action_id or "",
                    action_name=meta.get("action_name") or card.action_name or "",
                    prompt_text=meta.get("prompt_text", ""),
                    provider_type=meta.get("provider_type", ""),
                    model_name=meta.get("model_name", ""),
                    source_lang=meta.get("source_lang") or card.source_lang,
                    target_lang=meta.get("target_lang") or card.target_lang,
                    direction=meta.get("direction") or f"{card.source_lang} → {card.target_lang}",
                    project_context=meta.get("project_context", ""),
                    variants_json=variants_json,
                )
                if record_id > 0:
                    card.history_id = record_id
            except Exception as exc:
                pass

        # Обновляем счётчик памяти контекста проекта
        self._refresh_memory_status()

    def _on_card_result_edited(self, card: TranslationCard, new_text: str) -> None:
        """Пользователь вручную отредактировал результат — обновляем в SQLite (Этап 7.1)."""
        if card.history_id:
            try:
                from history_manager import get_history_manager
                hm = get_history_manager()
                hm.update_result_text(card.history_id, new_text, is_edited=True)
            except Exception:
                pass

    def display_history_card(self, record: Dict[str, Any]) -> TranslationCard:
        """Отображает карточку из постоянной истории в мини-окне (Этап 7.2)."""
        source = str(record.get("source_text", ""))
        result = str(record.get("result_text", ""))
        card = self.add_card(source, result)
        card.history_id = record.get("id")
        card.source_lang = str(record.get("source_lang", "auto"))
        card.target_lang = str(record.get("target_lang", "ru"))
        direction = str(record.get("direction") or f"{card.source_lang} → {card.target_lang}")
        card.set_direction(card.source_lang, card.target_lang, direction)
        action_id = str(record.get("action_id", ""))
        action_name = str(record.get("action_name", ""))
        if action_id or action_name:
            card.set_action(action_id, action_name)
        if record.get("is_edited"):
            card.edited_badge.show()
        if record.get("project_context"):
            card.set_project(str(record.get("project_context")))

        card.result_edited.connect(lambda new_text, c=card: self._on_card_result_edited(c, new_text))

        was_visible = self.isVisible()
        if not was_visible:
            self._place_near_cursor()
        self.show()
        self.raise_()
        self.activateWindow()
        self._adjust_height()
        self._scroll_to_bottom_smoothly()
        return card

    def _worker_finished(self, worker: TranslationWorker) -> None:
        """Поток завершился: чистим реестр, подгоняем высоту и скроллим."""
        self._workers.discard(worker)
        for c, w in list(self._card_workers.items()):
            if w is worker:
                del self._card_workers[c]
        self._adjust_height()
        self._scroll_to_bottom_smoothly()

    def _cancel_card_request(self, card: TranslationCard) -> None:
        """Отменяет активный фоновый запрос перевода для конкретной карточки (Этап 6.6)."""
        worker = self._card_workers.pop(card, None)
        if worker is not None:
            if hasattr(worker, "cancel"):
                try:
                    worker.cancel()
                except Exception:
                    pass
            self._workers.discard(worker)
        card.set_cancelled()
        self._adjust_height()

    def _delete_card(self, card: TranslationCard) -> None:
        """Удаляет карточку из ленты мини-окна (Этап 6.4)."""
        self._cancel_card_request(card)
        if card in self._cards:
            self._cards.remove(card)
        self.cards_layout.removeWidget(card)
        card.deleteLater()
        if not self._cards:
            if self.cards_layout.indexOf(self.empty_label) == -1:
                self.cards_layout.insertWidget(0, self.empty_label)
            self.empty_label.show()
        self._adjust_height()

    def _regenerate_card_with_custom_prompt(self, card: TranslationCard, prompt: str) -> None:
        """Повторный запуск для карточки с отредактированным промптом (Этап 6.4)."""
        source = card.source_text
        if not source or not prompt:
            return
        if self.config.get("mode") != "ai":
            self.config.set("mode", "ai")
            self._refresh_mode_button()
        card.start_loading()
        self._start_translation(card, source, custom_prompt=prompt)

    def regenerate_card(self, card: TranslationCard) -> None:
        """«Повторить»: карточка возвращается в «Думаю…», стартует новый воркер."""
        source = card.source_text
        if not source:
            return
        card.start_loading()
        self._start_translation(card, source, action_id=card.action_id or None)

    def _open_card_action_menu(self, card: TranslationCard) -> None:
        """Открывает меню действий для конкретной карточки в ленте."""
        menu = QMenu(self)
        menu.setObjectName("QuickActionsMenu")
        actions = self.config.get_actions() if hasattr(self.config, "get_actions") else []
        for act in actions:
            aid = act["id"]
            name = act["name"]
            menu_action = menu.addAction(name)
            menu_action.triggered.connect(
                lambda checked=False, a_id=aid, c=card: self._reapply_action_to_card(c, a_id)
            )
        menu.exec(QCursor.pos())

    def _reapply_action_to_card(self, card: TranslationCard, action_id: str) -> None:
        """Перегенерирует перевод для карточки с выбранным AI-действием."""
        source = card.source_text
        if not source:
            return
        card.start_loading()
        self._start_translation(card, source, action_id=action_id)

    def replace_in_source(self, card: TranslationCard) -> None:
        """«Заменить в тексте»: безопасная вставка результата на место выделения (Этап 6.5)."""
        result = card.get_active_text()
        if not result:
            return

        if self.hotkey_manager is not None:
            can_replace, message_or_warning, target_info = self.hotkey_manager.check_can_replace()
            if not can_replace:
                reply = QMessageBox.warning(
                    self,
                    "Замена текста невозможна",
                    f"Не удалось безопасно заменить текст в исходном окне:\n{message_or_warning}\n\n"
                    "Скопировать готовый результат в буфер обмена?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.Yes,
                )
                if reply == QMessageBox.StandardButton.Yes:
                    card.copy_text(result)
                return

            if message_or_warning:
                proc_name = (target_info or {}).get("process", "приложении")
                reply = QMessageBox.question(
                    self,
                    "Подтверждение замены текста",
                    f"{message_or_warning}\n\n"
                    f"Вы уверены, что хотите выполнить вставку в «{proc_name}»?\n"
                    "Нажмите «Да» для вставки (Ctrl+V) или «Нет», чтобы просто скопировать результат в буфер обмена.",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
                    QMessageBox.StandardButton.Yes,
                )
                if reply == QMessageBox.StandardButton.No:
                    card.copy_text(result)
                    return
                elif reply == QMessageBox.StandardButton.Cancel:
                    return

            self.hide()
            self.clear_history()
            self.hotkey_manager.paste_to_window(result)
        else:
            # Менеджера нет (тестовое окружение) — хотя бы кладём в буфер.
            try:
                pyperclip.copy(result)
            except Exception:
                pass
            self.hide()
            self.clear_history()

    def add_card(self, source_text: str, result_text: Optional[str]) -> TranslationCard:
        """Добавляет карточку в конец ленты; открывает окно, если оно скрыто."""
        # Ограничение максимального количества карточек в сессии (Этап 9.1)
        max_cards = 10
        if hasattr(self.config, "get_popup_max_cards"):
            max_cards = self.config.get_popup_max_cards()
        elif hasattr(self.config, "get"):
            max_cards = int(self.config.get("popup_max_cards", 10))

        while len(self._cards) >= max_cards and self._cards:
            self._delete_card(self._cards[0])

        was_visible = self.isVisible()
        card = TranslationCard(source_text, result_text)
        # Сигналы карточки: повтор, замена, отмена, удаление, правка промпта
        card.regenerate_requested.connect(lambda c=card: self.regenerate_card(c))
        card.replace_requested.connect(lambda c=card: self.replace_in_source(c))
        card.cancel_requested.connect(lambda c=card: self._cancel_card_request(c))
        card.delete_requested.connect(lambda c=card: self._delete_card(c))
        card.prompt_regenerate_requested.connect(lambda p, c=card: self._regenerate_card_with_custom_prompt(c, p))

        if hasattr(card, "action_menu_requested") and card.action_menu_requested is not None:
            try:
                card.action_menu_requested.connect(lambda c=card: self._open_card_action_menu(c))
            except Exception:
                pass
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
        """«Очистить историю»: отменить активные воркеры, убрать карточки."""
        for worker in list(self._workers):
            if hasattr(worker, "cancel"):
                try:
                    worker.cancel()
                except Exception:
                    pass
        self._workers.clear()
        self._card_workers.clear()

        for card in self._cards:
            try:
                card.regenerate_requested.disconnect()
                card.replace_requested.disconnect()
                card.cancel_requested.disconnect()
                card.delete_requested.disconnect()
                card.prompt_regenerate_requested.disconnect()
                if hasattr(card, "action_menu_requested") and card.action_menu_requested is not None:
                    card.action_menu_requested.disconnect()
            except Exception:
                pass
            self.cards_layout.removeWidget(card)
            card.deleteLater()
        self._cards.clear()
        if self.cards_layout.indexOf(self.empty_label) == -1:
            self.cards_layout.insertWidget(0, self.empty_label)
        self.empty_label.show()
        self._adjust_height()
        if self.cards_layout.indexOf(self.empty_label) == -1:
            self.cards_layout.insertWidget(0, self.empty_label)
        self.empty_label.show()
        self._adjust_height()

    def shutdown(self) -> None:
        """Останавливает все фоновые воркеры мини-окна при закрытии/выходе."""
        for worker in list(self._workers):
            if hasattr(worker, "cancel"):
                try:
                    worker.cancel()
                except Exception:
                    pass
        for worker in list(self._workers):
            try:
                worker.wait(1000)
            except Exception:
                pass
        self._workers.clear()

    # ------------------------------------------------------------ действия ИИ
    def _refresh_pinned_actions(self) -> None:
        """Пересоздаёт кнопки закреплённых действий (1-click Quick Actions)."""
        while self.pinned_layout.count() > 0:
            item = self.pinned_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        is_ai = self.config.get("mode") == "ai"
        pinned_actions = self.config.get_pinned_actions() if hasattr(self.config, "get_pinned_actions") else []
        if not pinned_actions or not is_ai:
            self.pinned_bar.hide()
            return

        self.pinned_bar.show()

        for idx, act in enumerate(pinned_actions[:6]):
            aid = act["id"]
            name = act["name"]
            hotkey = act.get("hotkey", "")
            short_name = name
            if "Литературный" in name:
                short_name = "Перевести"
            elif "Естественный" in name:
                short_name = "Разговорный"
            elif "Три варианта" in name:
                short_name = "3 варианта"
            elif "Перефразирование" in name:
                short_name = "Перефразировать"
            elif "грамматик" in name:
                short_name = "Грамматика"
            elif "стилистик" in name or "Редактура" in name:
                short_name = "Редактура"

            hk_hint = f" [{hotkey}]" if hotkey else f" [{idx + 1}]"
            btn = QPushButton(short_name)
            btn.setObjectName("QuickActionPill")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip(f"{name}{hk_hint}\nНажмите, чтобы применить к тексту (в 1 клик).")
            btn.clicked.connect(lambda checked=False, a_id=aid: self._apply_quick_action(a_id))
            self.pinned_layout.addWidget(btn)

        self.pinned_layout.addStretch(1)

    def _open_quick_actions_menu(self) -> None:
        """Выпадающее меню AI Quick Actions в заголовке мини-окна."""
        menu = QMenu(self)
        menu.setObjectName("QuickActionsMenu")
        actions = self.config.get_actions() if hasattr(self.config, "get_actions") else []

        for act in actions:
            aid = act["id"]
            name = act["name"]
            pinned = act.get("pinned", False)
            hotkey = act.get("hotkey", "")
            icon_str = "[+] " if pinned else "    "
            hk_text = f" ({hotkey})" if hotkey else ""
            menu_action = menu.addAction(f"{icon_str}{name}{hk_text}")
            menu_action.triggered.connect(
                lambda checked=False, a_id=aid: self._apply_quick_action(a_id)
            )

        menu.addSeparator()
        custom_act = menu.addAction("Пользовательский промпт...")
        custom_act.triggered.connect(self._toggle_custom_prompt_bar)

        pos = self.actions_menu_btn.mapToGlobal(self.actions_menu_btn.rect().bottomLeft())
        menu.exec(pos)

    def _toggle_custom_prompt_bar(self) -> None:
        """Показывает/скрывает строку ввода произвольного промпта."""
        if self.config.get("mode") != "ai":
            self.config.set("mode", "ai")
            self._refresh_mode_button()
        is_visible = self.custom_prompt_bar.isVisible()
        self.custom_prompt_bar.setVisible(not is_visible)
        if not is_visible:
            self.custom_prompt_edit.setFocus()
            self.custom_prompt_edit.selectAll()
        self._adjust_height()

    def _run_custom_prompt(self) -> None:
        """Запускает ИИ с пользовательским текстом промпта."""
        prompt = self.custom_prompt_edit.text().strip()
        if not prompt:
            return
        if self.config.get("mode") != "ai":
            self.config.set("mode", "ai")
            self._refresh_mode_button()
        if not self._cards:
            return
        last_source = self._cards[-1].source_text
        if not last_source:
            return
        self.custom_prompt_bar.hide()
        new_card = self.add_card(last_source, None)
        self._start_translation(new_card, last_source, custom_prompt=prompt)

    def _apply_quick_action(self, action_id: str) -> None:
        """Применяет выбранное действие к тексту последней карточки."""
        if self.config.get("mode") != "ai":
            self.config.set("mode", "ai")
            self._refresh_mode_button()
        if hasattr(self.config, "set_active_action"):
            self.config.set_active_action(action_id)
        if not self._cards:
            return
        last_source = self._cards[-1].source_text
        if not last_source:
            return
        new_card = self.add_card(last_source, None)
        self._start_translation(new_card, last_source, action_id=action_id)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Быстрые клавиши 1..9 для закреплённых действий при фокусе мини-окна."""
        key = event.key()
        if Qt.Key.Key_1 <= key <= Qt.Key.Key_9:
            idx = key - Qt.Key.Key_1
            pinned = self.config.get_pinned_actions() if hasattr(self.config, "get_pinned_actions") else []
            if 0 <= idx < len(pinned):
                self._apply_quick_action(pinned[idx]["id"])
                event.accept()
                return
        if key == Qt.Key.Key_Escape and self.custom_prompt_bar.isVisible():
            self.custom_prompt_bar.hide()
            self._adjust_height()
            event.accept()
            return
        super().keyPressEvent(event)

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
        """Обновляет вид кнопки режима; действия доступны всегда с авто-переключением."""
        is_ai = self.config.get("mode") == "ai"
        if is_ai:
            self.mode_button.setText("ИИ")
            self.mode_button.setObjectName("ModeButtonAi")
        else:
            self.mode_button.setText("Обычный")
            self.mode_button.setObjectName("ModeButtonStd")
        self.preset_combo.setEnabled(is_ai)
        # Кнопки быстрых действий и своего запроса ВСЕГДА кликабельны:
        # при нажатии в режиме «Обычный» они автоматически включают режим ИИ.
        self.actions_menu_btn.setEnabled(True)
        self.custom_prompt_btn.setEnabled(True)
        self.pinned_bar.setVisible(is_ai)
        repolish(self.mode_button)

    def refresh_from_config(self) -> None:
        """Обновить панель после изменений в окне настроек.

        Вызывается TrayApp по сигналам prompts_changed / hotkey_changed:
        освежаем список пресетов, закреплённые действия, кнопку режима и подсказку с хоткеем.
        """
        self._populate_presets()
        self._refresh_pinned_actions()
        self._refresh_mode_button()
        self._refresh_projects_combo()
        self._refresh_privacy_badge()
        self._refresh_memory_status()
        self.empty_label.setText(f"Лента пуста.\n{self._hotkey_hint()}")

        # Обновляем прозрачность и закрепление (Этап 9.1)
        opacity = self.config.get_popup_opacity() if hasattr(self.config, "get_popup_opacity") else 1.0
        self.setWindowOpacity(opacity)
        stays_on_top = bool(self.config.is_popup_stays_on_top() if hasattr(self.config, "is_popup_stays_on_top") else True)
        if self.pin_btn.isChecked() != stays_on_top:
            self.pin_btn.blockSignals(True)
            self.pin_btn.setChecked(stays_on_top)
            self.pin_btn.blockSignals(False)
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, stays_on_top)
            if self.isVisible():
                self.show()

    def _hotkey_hint(self) -> str:
        """Подсказка про хоткей с учётом его включённости и заданности."""
        hotkey = (self.config.get("hotkey") or "").strip()
        if not bool(self.config.get("hotkey_enabled", True)):
            return "Хоткей отключён — включите его в меню трея или в настройках."
        if not hotkey:
            return "Хоткей не задан — настройте его в окне настроек."
        return f"Выделите текст в любом приложении и нажмите «{hotkey}»."

    # -------------------------------------------------------- позиционирование
    def resizeEvent(self, event: QResizeEvent) -> None:
        """Запоминает ширину и размер окна при ручном изменении пользователем (Этап 9.1)."""
        super().resizeEvent(event)
        w = event.size().width()
        h = event.size().height()
        if w >= MIN_POPUP_WIDTH:
            self._user_width = w
            if bool(self.config.get("popup_remember_position", False)):
                self.config.set("popup_width", w)
                self.config.set("popup_height", h)

    def moveEvent(self, event: QMoveEvent) -> None:
        """Запоминает координаты окна при ручном перемещении (Этап 9.1)."""
        super().moveEvent(event)
        if self.isVisible() and bool(self.config.get("popup_remember_position", False)):
            pos = self.pos()
            self.config.set("popup_x", pos.x())
            self.config.set("popup_y", pos.y())

    def _get_active_screen(self, ref_pos: Optional[QPoint] = None) -> Optional[QScreen]:
        """Определяет активный монитор для указанной позиции или курсора мыши (Этап 9.1)."""
        pos = ref_pos if ref_pos is not None else QCursor.pos()
        screen = QApplication.screenAt(pos)
        if screen is None:
            screen = self.screen() or QApplication.primaryScreen()
        return screen

    def _clamp_to_screen(self, x: int, y: int, w: int, h: int, screen: Optional[QScreen] = None) -> Tuple[int, int]:
        """Удерживает окно строго в пределах видимой рабочей области монитора (Этап 9.1)."""
        if screen is None:
            screen = self._get_active_screen(QPoint(x, y))
        if screen is None:
            return int(x), int(y)
        geo = screen.availableGeometry()
        cx = min(max(x, geo.left()), max(geo.left(), geo.right() - w))
        cy = min(max(y, geo.top()), max(geo.top(), geo.bottom() - h))
        return int(cx), int(cy)

    def _toggle_stay_on_top(self, checked: bool) -> None:
        """Переключает закрепление окна поверх остальных окон (Этап 9.1)."""
        if hasattr(self.config, "set_popup_stays_on_top"):
            self.config.set_popup_stays_on_top(checked)
        else:
            self.config.set("popup_stays_on_top", checked)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, checked)
        self.show()

    def _place_near_cursor(self) -> None:
        """Открывает окно рядом с курсором либо по сохранённой позиции (Этапы 2, 9.1)."""
        # Если включено запоминание позиции — восстанавливаем её
        if bool(self.config.get("popup_remember_position", False)):
            saved_x = self.config.get("popup_x")
            saved_y = self.config.get("popup_y")
            if saved_x is not None and saved_y is not None:
                w = max(self.width(), getattr(self, "_user_width", DEFAULT_POPUP_WIDTH))
                h = self.height()
                screen = self._get_active_screen(QPoint(saved_x, saved_y))
                cx, cy = self._clamp_to_screen(saved_x, saved_y, w, h, screen)
                self.move(cx, cy)
                return

        cursor = QCursor.pos()
        screen = self._get_active_screen(cursor)
        if screen is None:
            return
        geo = screen.availableGeometry()
        w = max(self.width(), getattr(self, "_user_width", DEFAULT_POPUP_WIDTH))
        # По умолчанию — чуть правее и выше курсора.
        x = min(cursor.x() + 18, geo.right() - w)
        y = cursor.y() - self.height() - 18
        if y < geo.top():  # сверху не влезаем — размещаем под курсором
            y = min(cursor.y() + 24, geo.bottom() - self.height())
        cx, cy = self._clamp_to_screen(int(x), int(y), w, self.height(), screen)
        self.move(cx, cy)

    def show_bottom_right(self) -> None:
        """Открытие из меню трея — в правом нижнем углу или по сохранённой позиции (Этап 9.1)."""
        self._adjust_height()
        if bool(self.config.get("popup_remember_position", False)):
            saved_x = self.config.get("popup_x")
            saved_y = self.config.get("popup_y")
            if saved_x is not None and saved_y is not None:
                w = max(self.width(), getattr(self, "_user_width", DEFAULT_POPUP_WIDTH))
                h = self.height()
                screen = self._get_active_screen(QPoint(saved_x, saved_y))
                cx, cy = self._clamp_to_screen(saved_x, saved_y, w, h, screen)
                self.move(cx, cy)
                self.showNormal()
                self.raise_()
                self.activateWindow()
                return

        screen = self._get_active_screen(QCursor.pos())
        if screen is not None:
            geo = screen.availableGeometry()
            w = max(self.width(), getattr(self, "_user_width", DEFAULT_POPUP_WIDTH))
            cx, cy = self._clamp_to_screen(
                geo.right() - w - 24,
                geo.bottom() - self.height() - 24,
                w,
                self.height(),
                screen,
            )
            self.move(cx, cy)
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _adjust_height(self) -> None:
        """Подгоняет высоту окна под содержимое (в пределах 80% экрана), сохраняя ширину."""
        content_h = self.container.sizeHint().height()
        header_h = self.header.sizeHint().height()
        subbar_h = self.custom_prompt_bar.sizeHint().height() if self.custom_prompt_bar.isVisible() else 0
        pinned_h = self.pinned_bar.sizeHint().height() if self.pinned_bar.isVisible() else 0
        target = content_h + header_h + subbar_h + pinned_h + 8  # запас на скроллбар/рамку
        screen = self.screen() or QApplication.primaryScreen()
        if screen is not None:
            max_h = int(screen.availableGeometry().height() * MAX_POPUP_SCREEN_PART)
            target = min(target, max_h)
        w = max(getattr(self, "_user_width", DEFAULT_POPUP_WIDTH), MIN_POPUP_WIDTH)
        self.resize(w, max(MIN_POPUP_HEIGHT, target))

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

    # -------------------------------------------------- проекты и контекст (Этап 8)
    def _refresh_projects_combo(self) -> None:
        """Обновляет список проектов в выпадающем списке мини-окна."""
        try:
            from project_manager import get_project_manager
            pm = get_project_manager()
            self.project_combo.blockSignals(True)
            self.project_combo.clear()
            self.project_combo.addItem("Без проекта (общий)", "")
            projects = pm.list_projects()
            active_id = pm.get_active_project_id()
            sel_idx = 0
            for idx, p in enumerate(projects, 1):
                p_id = p.get("id", "")
                p_name = p.get("name", "Проект")
                terms_count = len(p.get("glossary", []))
                label = f"{p_name} ({terms_count} т.)"
                self.project_combo.addItem(label, p_id)
                if p_id == active_id:
                    sel_idx = idx
            self.project_combo.addItem("Управление проектами...", "__manage__")
            self.project_combo.setCurrentIndex(sel_idx)
            self.project_combo.blockSignals(False)
        except Exception:
            pass

    def _on_project_combo_changed(self, index: int) -> None:
        """Переключение активного проекта из комбобокса мини-окна."""
        val = self.project_combo.currentData()
        if val == "__manage__":
            # Открываем вкладку проектов в настройках
            self.projects_requested.emit()
            self._refresh_projects_combo()
            return

        try:
            from project_manager import get_project_manager
            pm = get_project_manager()
            pm.set_active_project_id(str(val or ""))
            if hasattr(self.config, "set_active_project_id"):
                self.config.set_active_project_id(str(val or ""))
            self.project_changed.emit(str(val or ""))
            self._refresh_privacy_badge()
            self._refresh_memory_status()
        except Exception:
            pass

    def _refresh_privacy_badge(self) -> None:
        """Индикатор конфиденциальности скрыт из интерфейса по требованию пользователя."""
        try:
            if hasattr(self, "privacy_badge") and self.privacy_badge is not None:
                self.privacy_badge.hide()
        except Exception:
            pass

    def _refresh_memory_status(self) -> None:
        """Обновляет счётчик фрагментов в буфере памяти."""
        try:
            from project_manager import get_project_manager
            pm = get_project_manager()
            pid = pm.get_active_project_id()
            if not pid:
                self.memory_btn.setText("Память: 0")
                self.memory_btn.setEnabled(False)
                return

            chunks = pm.get_memory_chunks(pid)
            proj = pm.get_project(pid)
            is_enabled = bool(proj.get("context_memory_enabled", False)) if proj else False
            cnt = len(chunks)
            if not is_enabled:
                self.memory_btn.setText("Память: выкл")
                self.memory_btn.setEnabled(True)
            else:
                self.memory_btn.setText(f"Память: {cnt}")
                self.memory_btn.setEnabled(True)
        except Exception:
            pass

    def _toggle_ad_hoc_bar(self) -> None:
        """Переключает видимость подпанели ввода разовой заметки."""
        vis = not self.ad_hoc_bar.isVisible()
        self.ad_hoc_bar.setVisible(vis)
        if vis:
            try:
                from project_manager import get_project_manager
                pm = get_project_manager()
                self.ad_hoc_edit.setText(pm.get_ad_hoc_context())
            except Exception:
                pass
            self.ad_hoc_edit.setFocus()
            self.ad_hoc_edit.selectAll()
        self._adjust_height()

    def _save_ad_hoc_context(self) -> None:
        """Сохраняет разовое примечание для ближайшего перевода."""
        text = self.ad_hoc_edit.text().strip()
        try:
            from project_manager import get_project_manager
            pm = get_project_manager()
            pm.set_ad_hoc_context(text)
        except Exception:
            pass
        self.ad_hoc_bar.hide()
        self._adjust_height()

    def _on_memory_btn_clicked(self) -> None:
        """Клик по кнопке памяти: просмотр или сброс накопленного контекста."""
        try:
            from project_manager import get_project_manager
            pm = get_project_manager()
            pid = pm.get_active_project_id()
            if not pid:
                QMessageBox.information(
                    self,
                    "Контекстная память",
                    "Контекстная память активна только внутри проекта.\n"
                    "Выберите или создайте проект для использования связного контекста.",
                )
                return
            chunks = pm.get_memory_chunks(pid)
            if not chunks:
                QMessageBox.information(
                    self,
                    "Контекстная память",
                    "Буфер контекстной памяти проекта пуст.\n"
                    "При переводах фрагменты будут сохраняться автоматически.",
                )
                return

            res = QMessageBox.question(
                self,
                "Память фрагментов проекта",
                f"В буфере проекта накоплено {len(chunks)} фрагм. контекста.\n\n"
                "Очистить (сбросить) накопленную память прямо сейчас?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if res == QMessageBox.StandardButton.Yes:
                pm.clear_memory(pid)
                self._refresh_memory_status()
        except Exception:
            pass

    # ----------------------------------------------------------- события окна
    def showEvent(self, event: QShowEvent) -> None:
        """Тема заголовка окна сразу после показа (Windows 10/11)."""
        super().showEvent(event)
        th = getattr(self.config, "theme", "dark")
        is_dark = (th != "light") if th != "system" else (detect_system_theme() != "light")
        apply_title_bar_theme(self, dark=is_dark)

    def closeEvent(self, event: QCloseEvent) -> None:
        """История живёт, пока окно открыто; при закрытии лента очищается —
        следующий захват откроет окно заново, с первой карточкой."""
        self.clear_history()
        super().closeEvent(event)
