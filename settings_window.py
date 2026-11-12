"""
settings_window.py — главное окно настроек «Комбайн» (ШАГ 4).

Вкладки QTabWidget:
  1. «Модели и Параметры ИИ» — адрес API (кнопки Ollama/OpenRouter/OpenAI),
     ключ, модель (+ загрузка списка из Ollama), ползунки Temperature и
     Top-P с подробными подсказками простым языком.
  2. «Мои Промпты (Пресеты)» — список слева, редактор справа, добавление /
     удаление / сохранение, шпаргалка по промптам.
  3. «Хоткеи и Обычный переводчик» — запись сочетания клавиш кнопкой,
     движок Google/DeepL, целевой язык, полный сброс к заводским настройкам.

Всё пишется в config.json; смена хоткея перерегистрируется сразу — без
перезапуска. Сигналы prompts_changed / hotkey_changed сообщают TrayApp,
что мини-окно и тултип трея пора обновить.
"""

from __future__ import annotations

from copy import deepcopy
import json
import re
from typing import Any, Dict, List, Optional, Tuple
import uuid

from PyQt6.QtCore import Qt, pyqtSignal, QDate
from PyQt6.QtGui import QCloseEvent, QIcon, QShowEvent, QCursor
from PyQt6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDateEdit,
                             QDialog, QFileDialog, QFrame, QGridLayout, QGroupBox,
                             QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                             QListWidget, QListWidgetItem, QMainWindow, QMenu,
                             QMessageBox, QPlainTextEdit, QPushButton,
                             QScrollArea, QSizePolicy, QSlider, QSpinBox, QSplitter,
                             QStyle, QStyleOptionSlider,
                             QTabWidget, QTableWidget, QTableWidgetItem,
                             QTextEdit, QVBoxLayout, QWidget)

from config import ConfigManager
from languages import get_supported_languages, AUTO_LANG_CODE
from hotkey_manager import validate_hotkey
from styles import apply_dark_title_bar, apply_title_bar_theme, detect_system_theme, repolish
from workers import HotkeyRecorder, ModelListWorker, ConnectionCheckWorker
from api_helpers import normalize_chat_url, get_models_url
from credentials import mask_key
from history_manager import get_history_manager, HistoryManager
from project_manager import get_project_manager, ProjectManager, STANDARD_CATEGORIES


class ClickJumpSlider(QSlider):
    """QSlider с мгновенным перемещением ползунка в точку клика мыши (без ступенчатого шага)."""

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            opt = QStyleOptionSlider()
            self.initStyleOption(opt)
            groove = self.style().subControlRect(
                QStyle.ComplexControl.CC_Slider, opt, QStyle.SubControl.SC_SliderGroove, self
            )
            handle = self.style().subControlRect(
                QStyle.ComplexControl.CC_Slider, opt, QStyle.SubControl.SC_SliderHandle, self
            )
            if self.orientation() == Qt.Orientation.Horizontal:
                slider_len = handle.width()
                slider_min = groove.x() + slider_len // 2
                slider_max = groove.right() - slider_len // 2
                pos_x = event.position().x()
                if slider_max > slider_min:
                    pos_x = max(slider_min, min(slider_max, pos_x))
                    ratio = (pos_x - slider_min) / float(slider_max - slider_min)
                    if self.invertedAppearance():
                        val = self.maximum() - ratio * (self.maximum() - self.minimum())
                    else:
                        val = self.minimum() + ratio * (self.maximum() - self.minimum())
                    self.setValue(int(round(val)))
                    event.accept()
                    super().mousePressEvent(event)
                    return
        super().mousePressEvent(event)

# Кнопки быстрого заполнения адреса API.
API_PRESETS = {
    "Локальная Ollama": "http://localhost:11434/v1/chat/completions",
    "OpenRouter": "https://openrouter.ai/api/v1/chat/completions",
    "OpenAI": "https://api.openai.com/v1/chat/completions",
}

# Языки для списка «Целевой язык» (список открытый — можно вписать свой код).
LANGUAGES = ("ru", "en", "uk", "de", "fr", "es", "it", "pl", "tr", "zh-cn", "ja", "ko")

# --- Подсказки простым языком (для переводчика, не для инженера) --------------
HINT_API_URL = (
    "Адрес сервера, у которого приложение спрашивает перевод "
    "(OpenAI-совместимый формат):\n"
    "• Локальная Ollama: http://localhost:11434/v1/chat/completions\n"
    "• OpenRouter: https://openrouter.ai/api/v1/chat/completions\n"
    "• OpenAI: https://api.openai.com/v1/chat/completions"
)
HINT_API_KEY = (
    "Секретный ключ доступа к облачному сервису (OpenRouter, OpenAI и т.п.).\n"
    "Для локальной Ollama ключ не нужен — оставьте поле пустым."
)
HINT_MODEL = (
    "Точное имя модели, у которой спрашиваем перевод:\n"
    "• Ollama — как в «ollama list» (llama3, qwen2.5:7b…);\n"
    "• OpenRouter / OpenAI — например deepseek/deepseek-chat или gpt-4o-mini."
)
HINT_PROXY = (
    "HTTP/HTTPS/SOCKS5 прокси для обхода сетевых ограничений и блокировок Cloudflare (OpenRouter, OpenAI).\n"
    "Например: http://127.0.0.1:10809 (Xray/V2Ray), http://127.0.0.1:7890 (Clash).\n"
    "Если оставить пустым, программа автоматически проверит запущенный локальный прокси."
)
HINT_LOAD_MODELS = (
    "Работает с локальной Ollama: подтягивает список установленных моделей "
    "(GET /api/tags) — не нужно вспоминать имена вручную."
)
TEMPERATURE_HINT = (
    "Креативность.\n"
    "Отвечает за смелость выбора слов. 0.1–0.3 — строгий, точный технический "
    "или юридический перевод без отсебятины. 0.6–0.8 — живой литературный "
    "язык, отлично подходит для перефразирования и поиска красивых "
    "синонимов. Выше 1.0 — модель начнет фантазировать."
)
TOP_P_HINT = (
    "Словарь выборки.\n"
    "Ограничивает пул слов, из которых выбирает модель. Оставь 0.9 для "
    "баланса, или снизь до 0.5, чтобы исключить редкие и странные речевые "
    "обороты."
)
HINT_HOTKEY = (
    "Глобальное сочетание клавиш, по которому открывается мини-окно с "
    "переводом выделенного текста. Работает в любой программе Windows.\n"
    "Например: alt+q, ctrl+shift+t, win+f1.\n"
    "Нажмите «Записать нажатие» и просто нажмите нужное сочетание."
)
HINT_ENGINE = (
    "Каким сервисом переводить в режиме «Обычный» (переключатель режима — "
    "в шапке мини-окна).\n"
    "Google — бесплатно и без ключа. DeepL — качественнее, но нужен "
    "API-ключ (бесплатный тариф есть на deepl.com)."
)
HINT_SOURCE_LANG = (
    "Язык оригинала текста.\n"
    "«Автоопределение» — программа сама распознает язык по алфавиту, диакритике и словарю.\n"
    "Можно зафиксировать конкретный исходный язык, если вы всегда переводите с одного языка."
)
HINT_TARGET_LANG = (
    "Основной язык, на который переводить текст.\n"
    "Если исходный текст уже на этом языке, программа автоматически переключится "
    "на резервный язык (например, русский ↔ английский)."
)
HINT_FALLBACK_LANG = (
    "Резервный язык перевода при авто-перевороте.\n"
    "Используется, если исходный текст уже написан на выбранном целевом языке "
    "(например, если цель — русский, и текст на русском — перевод пойдёт на этот язык)."
)

# Шпаргалка по промптам (показывается на вкладке «Мои Промпты»).
CHEAT_SHEET = (
    "• Называйте роль: «Ты — профессиональный переводчик…» — модель держит планку и не уходит в сторону.\n"
    "• Говорите, что вернуть: «в ответе только готовый перевод, без комментариев и кавычек» — иначе модель добавит пояснения.\n"
    "• Задавайте тон: «живой литературный язык», «строгий технический стиль», «сохраняй термины как есть».\n"
    "• Для рерайта просите конкретику: «ровно 3 варианта: нейтральный, разговорный, выразительный».\n"
    "• Плейсхолдер {target_lang} автоматически заменяется языком перевода из настроек.\n"
    "• Короткий точный промпт работает лучше длинного расплывчатого."
)


def _hint(text: str) -> QLabel:
    """Маленький значок «[?]» с подробной подсказкой (по наведению курсора)."""
    label = QLabel("[?]")
    label.setObjectName("HintLabel")
    label.setToolTip(text)
    label.setCursor(Qt.CursorShape.PointingHandCursor)
    return label

class TermEditDialog(QDialog):
    """Диалог создания или редактирования термина глоссария проекта (Этап 8.2)."""

    def __init__(self, parent=None, term_data: Optional[Dict[str, Any]] = None):
        super().__init__(parent)
        self.term_data = term_data or {}
        is_edit = bool(term_data and term_data.get("id"))
        self.setWindowTitle("Редактировать термин" if is_edit else "Добавить термин в глоссарий")
        self.setMinimumWidth(500)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        form = QGridLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)

        # 1. Исходный термин
        lbl1 = QLabel("Исходный термин (оригинал):*")
        lbl1.setObjectName("FieldLabel")
        form.addWidget(lbl1, 0, 0)
        self.source_edit = QLineEdit(str(self.term_data.get("source_term", "")))
        self.source_edit.setPlaceholderText("например: Subaru, Shadow Garden, Mana...")
        form.addWidget(self.source_edit, 0, 1)

        # 2. Утверждённый перевод
        lbl2 = QLabel("Утверждённый перевод:*")
        lbl2.setObjectName("FieldLabel")
        form.addWidget(lbl2, 1, 0)
        self.target_edit = QLineEdit(str(self.term_data.get("target_term", "")))
        self.target_edit.setPlaceholderText("например: Субару, Сад Теней, Мана...")
        form.addWidget(self.target_edit, 1, 1)

        # 3. Категория
        lbl3 = QLabel("Категория:")
        lbl3.setObjectName("FieldLabel")
        form.addWidget(lbl3, 2, 0)
        self.category_combo = QComboBox()
        self.category_combo.setEditable(True)
        self.category_combo.addItems(STANDARD_CATEGORIES)
        curr_cat = str(self.term_data.get("category") or "Другое")
        idx = self.category_combo.findText(curr_cat)
        if idx >= 0:
            self.category_combo.setCurrentIndex(idx)
        else:
            self.category_combo.setEditText(curr_cat)
        form.addWidget(self.category_combo, 2, 1)

        # 4. Комментарий
        lbl4 = QLabel("Комментарий / Примечание:")
        lbl4.setObjectName("FieldLabel")
        form.addWidget(lbl4, 3, 0)
        self.comment_edit = QLineEdit(str(self.term_data.get("comment", "")))
        self.comment_edit.setPlaceholderText("например: Не переводить буквально, официальный термин")
        form.addWidget(self.comment_edit, 3, 1)

        # 5. Примеры использования
        lbl5 = QLabel("Примеры использования:")
        lbl5.setObjectName("FieldLabel")
        form.addWidget(lbl5, 4, 0)
        self.examples_edit = QLineEdit(str(self.term_data.get("examples", "")))
        self.examples_edit.setPlaceholderText("например: He rode the Dragon Carriage into the capital.")
        form.addWidget(self.examples_edit, 4, 1)

        # 6. Учитывать регистр
        self.case_cb = QCheckBox("Учитывать регистр символов при поиске")
        self.case_cb.setChecked(bool(self.term_data.get("case_sensitive", False)))
        form.addWidget(self.case_cb, 5, 1)

        layout.addLayout(form)

        # Кнопки
        btn_box = QHBoxLayout()
        btn_box.addStretch(1)
        self.cancel_btn = QPushButton("Отмена")
        self.cancel_btn.clicked.connect(self.reject)
        btn_box.addWidget(self.cancel_btn)

        self.save_btn = QPushButton("Сохранить")
        self.save_btn.setObjectName("PrimaryButton")
        self.save_btn.clicked.connect(self._validate_and_accept)
        btn_box.addWidget(self.save_btn)
        layout.addLayout(btn_box)

    def _validate_and_accept(self) -> None:
        src = self.source_edit.text().strip()
        tgt = self.target_edit.text().strip()
        if not src or not tgt:
            QMessageBox.warning(self, "Ошибка", "Исходный термин и утверждённый перевод обязательны для заполнения.")
            return
        self.accept()

    def get_data(self) -> Dict[str, Any]:
        return {
            "source_term": self.source_edit.text().strip(),
            "target_term": self.target_edit.text().strip(),
            "category": self.category_combo.currentText().strip() or "Другое",
            "comment": self.comment_edit.text().strip(),
            "examples": self.examples_edit.text().strip(),
            "case_sensitive": self.case_cb.isChecked(),
        }


class DuplicatesDialog(QDialog):
    """Диалог просмотра повторяющихся терминов глоссария (Этап 8.2)."""

    def __init__(self, parent=None, duplicates: Optional[List[Dict[str, Any]]] = None, project_id: str = ""):
        super().__init__(parent)
        self.project_id = project_id
        self.duplicates = duplicates or []
        self.setWindowTitle("Повторяющиеся термины в глоссарии")
        self.setMinimumSize(600, 360)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        info = QLabel(
            f"В глоссарии найдено {len(self.duplicates)} записей с повторяющимися терминами оригинала.\n"
            "Повторение исходных терминов может вызывать неоднозначность при авто-подстановке."
        )
        info.setObjectName("FieldLabel")
        info.setWordWrap(True)
        layout.addWidget(info)

        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["ID", "Исходный термин", "Перевод", "Категория"])
        self.table.setColumnHidden(0, True)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)

        self.table.setRowCount(len(self.duplicates))
        for row, t in enumerate(self.duplicates):
            self.table.setItem(row, 0, QTableWidgetItem(str(t.get("id"))))
            self.table.setItem(row, 1, QTableWidgetItem(str(t.get("source_term", ""))))
            self.table.setItem(row, 2, QTableWidgetItem(str(t.get("target_term", ""))))
            self.table.setItem(row, 3, QTableWidgetItem(str(t.get("category", "Другое"))))
        layout.addWidget(self.table)

        btn_box = QHBoxLayout()
        btn_box.addStretch(1)
        close_btn = QPushButton("Закрыть")
        close_btn.clicked.connect(self.accept)
        btn_box.addWidget(close_btn)
        layout.addLayout(btn_box)


class SettingsWindow(QMainWindow):
    """Окно настроек «Комбайн»: модели, промпты, хоткеи и обычный переводчик."""

    #: Пресеты пересохранены — TrayApp обновит панель мини-окна.
    prompts_changed = pyqtSignal()

    #: Хоткей перерегистрирован — TrayApp обновит тултип трея и мини-окно.
    hotkey_changed = pyqtSignal(str)

    #: Запрос на открытие карточки в мини-окне из истории (Этап 7.2)
    open_card_requested = pyqtSignal(dict)

    #: Запрос на повторный запуск перевода из истории (Этап 7.2)
    repeat_request_requested = pyqtSignal(dict)

    #: Проекты или глоссарий изменены (Этап 8)
    projects_changed = pyqtSignal()

    def __init__(self, config: ConfigManager, app_icon: QIcon,
                 hotkey_manager=None) -> None:
        super().__init__()
        self.config = config
        self.hotkey_manager = hotkey_manager  # None → хоткей только в конфиг
        self._dirty = False                   # есть несохранённые изменения
        self._recorder: Optional[HotkeyRecorder] = None
        self._model_worker: Optional[ModelListWorker] = None
        self._conn_worker: Optional[ConnectionCheckWorker] = None
        self._current_profile_id: str = self.config.get_active_profile_id() if hasattr(self.config, "get_active_profile_id") else ""

        # Состояние истории (Этап 7)
        self._history_page: int = 1
        self._history_page_size: int = 50
        self._history_total_count: int = 0
        self._history_records: List[Dict[str, Any]] = []
        self._history_selected_record: Optional[Dict[str, Any]] = None

        # Состояние проектов (Этап 8)
        self._selected_project_id: Optional[str] = None
        self._current_glossary_terms: List[Dict[str, Any]] = []

        self.setWindowTitle("Truniversal — настройки")
        self.setWindowIcon(app_icon)
        self.setMinimumSize(820, 620)
        self.resize(960, 720)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_ai_tab(), "Модели и Параметры ИИ")
        self.tabs.addTab(self._build_prompts_tab(), "Мои Промпты")
        self.tabs.addTab(self._build_history_tab(), "История операций")
        self.tabs.addTab(self._build_projects_tab(), "Проекты")
        self.tabs.addTab(self._build_hotkeys_tab(), "Настройки")
        self.setCentralWidget(self.tabs)

        self._apply_interactive_cursors()
        self._populate_profiles_combo()
        self._refresh_projects_list()

        # Любое ручное изменение помечает окно «грязным» (защита от потери
        # несохранённых правок при закрытии). Программные установки
        # делаются с blockSignals, поэтому сюда не попадают.
        self.profile_combo.currentIndexChanged.connect(self._on_profile_combo_changed)
        self.profile_name_edit.textChanged.connect(self._mark_dirty)
        self.provider_combo.currentIndexChanged.connect(self._mark_dirty)
        self.api_url_edit.textChanged.connect(self._mark_dirty)
        self.api_key_edit.textChanged.connect(self._mark_dirty)
        self.model_combo.currentTextChanged.connect(self._mark_dirty)
        self.proxy_edit.textChanged.connect(self._mark_dirty)
        self.temp_slider.valueChanged.connect(self._mark_dirty)
        self.top_p_slider.valueChanged.connect(self._mark_dirty)
        self.timeout_connect_spin.valueChanged.connect(self._mark_dirty)
        self.timeout_request_spin.valueChanged.connect(self._mark_dirty)
        self.max_retries_spin.valueChanged.connect(self._mark_dirty)
        self.max_tokens_spin.valueChanged.connect(self._mark_dirty)
        self.preset_name_edit.textChanged.connect(self._mark_dirty)
        self.preset_text_edit.textChanged.connect(self._mark_dirty)
        self.hotkey_edit.textChanged.connect(self._mark_dirty)
        self.deepl_key_edit.textChanged.connect(self._mark_dirty)
        self.engine_combo.currentIndexChanged.connect(self._mark_dirty)
        self.source_lang_combo.currentTextChanged.connect(self._mark_dirty)
        self.lang_combo.currentTextChanged.connect(self._mark_dirty)
        self.fallback_lang_combo.currentTextChanged.connect(self._mark_dirty)

        self.statusBar().showMessage("Все настройки хранятся в config.json", 8000)

    # --------------------------------------------------------------- утилиты
    def _create_card(self, title: str = "", subtitle: str = "") -> tuple[QFrame, QVBoxLayout]:
        """Создаёт стилизованную карточку-контейнер для секции настроек."""
        card = QFrame()
        card.setObjectName("SettingsCard")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(12)
        if title:
            header_box = QVBoxLayout()
            header_box.setSpacing(3)
            t_lbl = QLabel(title)
            t_lbl.setObjectName("CardTitle")
            header_box.addWidget(t_lbl)
            if subtitle:
                s_lbl = QLabel(subtitle)
                s_lbl.setObjectName("CardSubtitle")
                s_lbl.setWordWrap(True)
                header_box.addWidget(s_lbl)
            lay.addLayout(header_box)
        return card, lay

    def _apply_interactive_cursors(self) -> None:
        """Назначает курсор-указатель (pointer / hand) всем кнопкам и элементам управления."""
        for btn in self.findChildren(QPushButton):
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
        for combo in self.findChildren(QComboBox):
            combo.setCursor(Qt.CursorShape.PointingHandCursor)
        for chk in self.findChildren(QCheckBox):
            chk.setCursor(Qt.CursorShape.PointingHandCursor)
        for hint in self.findChildren(QLabel, "HintLabel"):
            hint.setCursor(Qt.CursorShape.PointingHandCursor)

    @staticmethod
    def _row_with_hint(text: str, hint: str) -> QWidget:
        """Строка «Название параметра» + значок «[?]» с подробной подсказкой."""
        row = QWidget()
        row.setStyleSheet("background: transparent;")
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        label = QLabel(text)
        label.setObjectName("FieldLabel")
        label.setToolTip(hint)
        lay.addWidget(label)
        if hint:
            lay.addWidget(_hint(hint))
        lay.addStretch(1)
        return row

    @staticmethod
    def _caption(text: str) -> QLabel:
        """Приглушённая пояснительная строка под параметром."""
        lbl = QLabel(text)
        lbl.setObjectName("CaptionLabel")
        lbl.setWordWrap(True)
        return lbl

    def _mark_dirty(self, *_) -> None:
        self._dirty = True

    # ================== ВКЛАДКА 1: Модели и Параметры ИИ =====================
    def _build_ai_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setObjectName("SettingsScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.viewport().setAutoFillBackground(False)

        page = QWidget()
        page.setObjectName("SettingsPage")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(14)
        scroll.setWidget(page)

        # === КАРТОЧКА 1: AI-профиль подключения ===
        card_prof, prof_lay = self._create_card(
            "AI-профиль подключения",
            "Объединяет адрес сервера, модель, ключ и параметры запроса. Переключайтесь между ними в один клик."
        )

        prof_row = QHBoxLayout()
        self.profile_combo = QComboBox()
        self.profile_combo.setToolTip("Выберите активный профиль для работы и редактирования")
        self.profile_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        prof_row.addWidget(self.profile_combo, stretch=2)

        self.add_profile_btn = QPushButton("+ Создать")
        self.add_profile_btn.setToolTip("Создать новый независимый AI-профиль")
        self.add_profile_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_profile_btn.clicked.connect(self._create_new_profile)
        prof_row.addWidget(self.add_profile_btn)

        self.duplicate_profile_btn = QPushButton("Копировать")
        self.duplicate_profile_btn.setToolTip("Создать копию текущего профиля")
        self.duplicate_profile_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.duplicate_profile_btn.clicked.connect(self._duplicate_current_profile)
        prof_row.addWidget(self.duplicate_profile_btn)

        self.delete_profile_btn = QPushButton("Удалить")
        self.delete_profile_btn.setObjectName("DangerButton")
        self.delete_profile_btn.setToolTip("Удалить выбранный профиль")
        self.delete_profile_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.delete_profile_btn.clicked.connect(self._delete_current_profile)
        prof_row.addWidget(self.delete_profile_btn)
        prof_lay.addLayout(prof_row)

        fields_grid = QGridLayout()
        fields_grid.setHorizontalSpacing(14)
        fields_grid.setVerticalSpacing(6)

        fields_grid.addWidget(self._row_with_hint("Название профиля:", "Отображаемое имя текущего профиля"), 0, 0)
        self.profile_name_edit = QLineEdit()
        fields_grid.addWidget(self.profile_name_edit, 1, 0)

        fields_grid.addWidget(self._row_with_hint(
            "Тип AI-провайдера:",
            "Определяет протокол и особенности эндпоинтов:\n"
            "• Ollama — локальный сервер (GET /api/tags для моделей)\n"
            "• OpenRouter / OpenAI — облачные API (GET /v1/models)\n"
            "• Пользовательский — любой совместимый API или прокси"
        ), 0, 1)
        self.provider_combo = QComboBox()
        self.provider_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        self.provider_combo.addItem("Ollama (локальная модель)", "ollama")
        self.provider_combo.addItem("OpenRouter (облачные модели)", "openrouter")
        self.provider_combo.addItem("OpenAI (GPT-4o / mini)", "openai")
        self.provider_combo.addItem("Пользовательский API / Прокси", "custom")
        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        fields_grid.addWidget(self.provider_combo, 1, 1)

        prof_lay.addLayout(fields_grid)
        lay.addWidget(card_prof)

        # === КАРТОЧКА 2: Сервер и Модель ===
        card_srv, srv_lay = self._create_card(
            "Сервер и Модель",
            "Настройка OpenAI-совместимого эндпоинта, безопасное хранение ключей и выбор рабочей модели"
        )

        srv_lay.addWidget(self._row_with_hint("Адрес API (URL):", HINT_API_URL))
        self.api_url_edit = QLineEdit(self.config.get("api_url", ""))
        self.api_url_edit.setPlaceholderText("http://localhost:11434/v1/chat/completions")
        self.api_url_edit.editingFinished.connect(self._normalize_api_url_field)
        srv_lay.addWidget(self.api_url_edit)

        quick = QHBoxLayout()
        quick_lbl = QLabel("Быстрое заполнение:")
        quick_lbl.setObjectName("CaptionLabel")
        quick.addWidget(quick_lbl)
        for title, url in API_PRESETS.items():
            btn = QPushButton(title)
            btn.setObjectName("GhostButton")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip(f"Подставить адрес:\n{url}")
            btn.clicked.connect(
                lambda _=False, name=title: self._apply_api_preset(name)
            )
            quick.addWidget(btn)
        quick.addStretch(1)
        srv_lay.addLayout(quick)

        key_head = QHBoxLayout()
        key_label = QLabel("API-ключ (облаку нужен, локальной Ollama — нет):")
        key_label.setObjectName("FieldLabel")
        key_label.setToolTip(HINT_API_KEY)
        key_head.addWidget(key_label)
        key_head.addWidget(_hint(HINT_API_KEY))
        key_head.addStretch(1)
        badge = QLabel("Windows Credential Manager")
        badge.setObjectName("SecurityBadge")
        key_head.addWidget(badge)
        srv_lay.addLayout(key_head)

        key_row = QHBoxLayout()
        self.api_key_edit = QLineEdit(self.config.get("api_key", ""))
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        key_row.addWidget(self.api_key_edit, stretch=1)

        self.toggle_key_btn = QPushButton("Показать")
        self.toggle_key_btn.setObjectName("GhostButton")
        self.toggle_key_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle_key_btn.setFixedWidth(84)
        self.toggle_key_btn.clicked.connect(self._toggle_api_key_visibility)
        key_row.addWidget(self.toggle_key_btn)
        srv_lay.addLayout(key_row)

        srv_lay.addWidget(self._row_with_hint("Имя модели:", HINT_MODEL))
        model_row = QHBoxLayout()
        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        self.model_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        self.model_combo.setCurrentText(self.config.get("model_name", ""))
        model_row.addWidget(self.model_combo, stretch=1)
        self.load_models_btn = QPushButton("Загрузить список моделей")
        self.load_models_btn.setToolTip(HINT_LOAD_MODELS)
        self.load_models_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.load_models_btn.clicked.connect(self._load_models)
        model_row.addWidget(self.load_models_btn)
        srv_lay.addLayout(model_row)

        srv_lay.addWidget(self._row_with_hint("Прокси (для обхода блокировок, необязательно):", HINT_PROXY))
        self.proxy_edit = QLineEdit("")
        self.proxy_edit.setPlaceholderText("Автоопределение или http://127.0.0.1:10809")
        self.proxy_edit.setToolTip(HINT_PROXY)
        srv_lay.addWidget(self.proxy_edit)

        conn_box = QFrame()
        conn_box.setObjectName("ConnectionBox")
        conn_lay = QHBoxLayout(conn_box)
        conn_lay.setContentsMargins(10, 8, 10, 8)
        self.check_conn_btn = QPushButton("Проверить подключение")
        self.check_conn_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.check_conn_btn.setToolTip("Проверить доступность сервера, валидность ключа и ответ модели")
        self.check_conn_btn.clicked.connect(self._check_connection)
        conn_lay.addWidget(self.check_conn_btn)

        self.check_status_label = QLabel("")
        self.check_status_label.setWordWrap(True)
        conn_lay.addWidget(self.check_status_label, stretch=1)
        srv_lay.addWidget(conn_box)

        lay.addWidget(card_srv)

        # === КАРТОЧКА 3: Параметры генерации ===
        card_gen, gen_lay = self._create_card(
            "Параметры генерации",
            "Управление креативностью и разнообразием словарного запаса модели"
        )

        t_head = QHBoxLayout()
        t_label = QLabel("Temperature — Креативность:")
        t_label.setObjectName("FieldLabel")
        t_label.setToolTip(TEMPERATURE_HINT)
        t_head.addWidget(t_label)
        t_head.addWidget(_hint(TEMPERATURE_HINT))
        t_head.addStretch(1)
        self.temp_value_label = QLabel(f"{self.config.get('temperature', 0.3):.2f}")
        self.temp_value_label.setObjectName("ValueLabel")
        t_head.addWidget(self.temp_value_label)
        gen_lay.addLayout(t_head)

        self.temp_slider = QSlider(Qt.Orientation.Horizontal)
        self.temp_slider.setRange(0, 200)
        self.temp_slider.setValue(int(round(float(self.config.get("temperature", 0.3)) * 100)))
        self.temp_slider.valueChanged.connect(
            lambda value: self.temp_value_label.setText(f"{value / 100:.2f}")
        )
        gen_lay.addWidget(self.temp_slider)
        gen_lay.addWidget(self._caption(
            "0.1–0.3 — строго и точно · 0.6–0.8 — живой литературный язык · выше 1.0 — фантазии"
        ))

        gen_lay.addSpacing(6)
        p_head = QHBoxLayout()
        p_label = QLabel("Top-P — Словарь выборки:")
        p_label.setObjectName("FieldLabel")
        p_label.setToolTip(TOP_P_HINT)
        p_head.addWidget(p_label)
        p_head.addWidget(_hint(TOP_P_HINT))
        p_head.addStretch(1)
        self.top_p_value_label = QLabel(f"{self.config.get('top_p', 0.9):.2f}")
        self.top_p_value_label.setObjectName("ValueLabel")
        p_head.addWidget(self.top_p_value_label)
        gen_lay.addLayout(p_head)

        self.top_p_slider = QSlider(Qt.Orientation.Horizontal)
        self.top_p_slider.setRange(10, 100)
        self.top_p_slider.setValue(int(round(float(self.config.get("top_p", 0.9)) * 100)))
        self.top_p_slider.valueChanged.connect(
            lambda value: self.top_p_value_label.setText(f"{value / 100:.2f}")
        )
        gen_lay.addWidget(self.top_p_slider)
        gen_lay.addWidget(self._caption(
            "0.9 — баланс качества и разнообразия · 0.5 — только частоупотребимые слова"
        ))

        lay.addWidget(card_gen)

        # === КАРТОЧКА 4: Сетевые таймауты и Надежность ===
        card_net, net_lay = self._create_card(
            "Сетевые таймауты и Надежность",
            "Ограничения по времени соединения, повторные попытки при сбоях и лимит токенов"
        )
        adv_grid = QGridLayout()
        adv_grid.setHorizontalSpacing(16)
        adv_grid.setVerticalSpacing(10)

        lbl1 = QLabel("Таймаут подключения (с):")
        lbl1.setObjectName("FieldLabel")
        adv_grid.addWidget(lbl1, 0, 0)
        self.timeout_connect_spin = QSpinBox()
        self.timeout_connect_spin.setRange(1, 60)
        self.timeout_connect_spin.setValue(10)
        self.timeout_connect_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        adv_grid.addWidget(self.timeout_connect_spin, 0, 1)

        lbl2 = QLabel("Таймаут ответа (с):")
        lbl2.setObjectName("FieldLabel")
        adv_grid.addWidget(lbl2, 0, 2)
        self.timeout_request_spin = QSpinBox()
        self.timeout_request_spin.setRange(5, 300)
        self.timeout_request_spin.setValue(90)
        self.timeout_request_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        adv_grid.addWidget(self.timeout_request_spin, 0, 3)

        lbl3 = QLabel("Повторов при сбоях:")
        lbl3.setObjectName("FieldLabel")
        adv_grid.addWidget(lbl3, 1, 0)
        self.max_retries_spin = QSpinBox()
        self.max_retries_spin.setRange(0, 5)
        self.max_retries_spin.setValue(2)
        self.max_retries_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        adv_grid.addWidget(self.max_retries_spin, 1, 1)

        lbl4 = QLabel("Макс. токенов (0=авто):")
        lbl4.setObjectName("FieldLabel")
        adv_grid.addWidget(lbl4, 1, 2)
        self.max_tokens_spin = QSpinBox()
        self.max_tokens_spin.setRange(0, 32768)
        self.max_tokens_spin.setValue(0)
        self.max_tokens_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        adv_grid.addWidget(self.max_tokens_spin, 1, 3)

        net_lay.addLayout(adv_grid)
        lay.addWidget(card_net)

        # === Нижняя панель действий ===
        save_row = QHBoxLayout()
        save_row.addStretch(1)
        save_btn = QPushButton("Сохранить профиль")
        save_btn.setObjectName("PrimaryButton")
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.clicked.connect(self._save_ai_tab)
        save_row.addWidget(save_btn)
        lay.addLayout(save_row)

        return scroll

    def _populate_profiles_combo(self) -> None:
        """Заполняет выпадающий список профилей."""
        if not hasattr(self, "profile_combo"):
            return
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        profiles = self.config.get_profiles() if hasattr(self.config, "get_profiles") else {}
        active_id = self.config.get_active_profile_id() if hasattr(self.config, "get_active_profile_id") else ""
        selected_idx = 0
        for i, (pid, pdata) in enumerate(profiles.items()):
            display_name = pdata.get("name") or pid
            if pid == active_id:
                display_name = f"{display_name} (активен)"
            self.profile_combo.addItem(display_name, pid)
            if pid == active_id:
                selected_idx = i
        if self.profile_combo.count():
            self.profile_combo.setCurrentIndex(selected_idx)
            self._current_profile_id = self.profile_combo.currentData()
        self.profile_combo.blockSignals(False)
        self._load_profile_into_form(self._current_profile_id)

    def _block_ai_tab_signals(self, blocked: bool) -> None:
        """Блокирует или разблокирует сигналы полей вкладки ИИ."""
        for w in (
            getattr(self, "profile_name_edit", None),
            getattr(self, "provider_combo", None),
            getattr(self, "api_url_edit", None),
            getattr(self, "api_key_edit", None),
            getattr(self, "model_combo", None),
            getattr(self, "proxy_edit", None),
            getattr(self, "temp_slider", None),
            getattr(self, "top_p_slider", None),
            getattr(self, "timeout_connect_spin", None),
            getattr(self, "timeout_request_spin", None),
            getattr(self, "max_retries_spin", None),
            getattr(self, "max_tokens_spin", None),
        ):
            if w is not None:
                w.blockSignals(blocked)

    def _load_profile_into_form(self, profile_id: str) -> None:
        """Загружает данные выбранного профиля в форму."""
        if not hasattr(self.config, "get_profile"):
            return
        prof = self.config.get_profile(profile_id)
        if not prof:
            return

        self._block_ai_tab_signals(True)
        self.profile_name_edit.setText(prof.get("name", ""))

        ptype = str(prof.get("provider_type") or "custom").lower()
        idx = self.provider_combo.findData(ptype)
        if idx >= 0:
            self.provider_combo.setCurrentIndex(idx)
        else:
            self.provider_combo.setCurrentIndex(self.provider_combo.findData("custom"))

        self.api_url_edit.setText(prof.get("api_url", ""))
        self.api_key_edit.setText(prof.get("api_key", ""))
        self.model_combo.setCurrentText(prof.get("model_name", ""))
        self.proxy_edit.setText(prof.get("proxy", ""))

        temp = int(round(float(prof.get("temperature", 0.3)) * 100))
        self.temp_slider.setValue(temp)
        self.temp_value_label.setText(f"{temp / 100:.2f}")

        top_p = int(round(float(prof.get("top_p", 0.9)) * 100))
        self.top_p_slider.setValue(top_p)
        self.top_p_value_label.setText(f"{top_p / 100:.2f}")

        self.timeout_connect_spin.setValue(int(prof.get("timeout_connect", 10)))
        self.timeout_request_spin.setValue(int(prof.get("timeout_request", 90)))
        self.max_retries_spin.setValue(int(prof.get("max_retries", 2)))
        self.max_tokens_spin.setValue(int(prof.get("max_tokens", 0)))
        self.check_status_label.setText("")
        self._block_ai_tab_signals(False)

    def _on_profile_combo_changed(self, idx: int) -> None:
        """Пользователь переключил профиль в выпадающем списке."""
        new_id = self.profile_combo.currentData()
        if not new_id or new_id == self._current_profile_id:
            return
        self.config.set_active_profile(new_id)
        self._current_profile_id = new_id
        self._populate_profiles_combo()
        self._dirty = False
        self._status(f"Активный профиль переключён: {self.profile_name_edit.text()}")

    def _create_new_profile(self) -> None:
        """Создает новый независимый AI-профиль."""
        new_prof = {
            "name": "Новый профиль",
            "provider_type": "custom",
            "api_url": "http://localhost:11434/v1/chat/completions",
            "model_name": "llama3",
            "temperature": 0.3,
            "top_p": 0.9,
            "max_tokens": 0,
            "timeout_connect": 10,
            "timeout_request": 90,
            "max_retries": 2,
        }
        self.config.save_profile(new_prof, api_key="")
        new_id = new_prof["id"]
        self.config.set_active_profile(new_id)
        self._current_profile_id = new_id
        self._populate_profiles_combo()
        self._dirty = False
        self._status("Создан новый профиль — настройте параметры и нажмите «Сохранить профиль».")

    def _duplicate_current_profile(self) -> None:
        """Создает копию текущего профиля."""
        if not self._current_profile_id:
            return
        new_id = self.config.duplicate_profile(self._current_profile_id)
        if new_id:
            self.config.set_active_profile(new_id)
            self._current_profile_id = new_id
            self._populate_profiles_combo()
            self._dirty = False
            self._status("Создана копия профиля")

    def _delete_current_profile(self) -> None:
        """Удаляет текущий профиль (если он не единственный)."""
        profiles = self.config.get_profiles()
        if len(profiles) <= 1:
            self._status("Нельзя удалить единственный оставшийся профиль.", error=True)
            return
        prof_name = self.profile_name_edit.text()
        answer = QMessageBox.question(
            self,
            "Truniversal — Удаление профиля",
            f"Вы уверены, что хотите удалить профиль «{prof_name}»?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.config.delete_profile(self._current_profile_id)
        self._current_profile_id = self.config.get_active_profile_id()
        self._populate_profiles_combo()
        self._dirty = False
        self._status(f"Профиль «{prof_name}» удалён.")

    def _normalize_api_url_field(self) -> None:
        """Нормализует адрес API при завершении редактирования."""
        raw_url = self.api_url_edit.text().strip()
        if raw_url:
            ptype = self.provider_combo.currentData() or "custom"
            normalized = normalize_chat_url(raw_url, ptype)
            if normalized != raw_url:
                self.api_url_edit.setText(normalized)

    def _on_provider_changed(self, idx: int) -> None:
        """При смене типа провайдера предлагает подходящий URL по умолчанию."""
        self._mark_dirty()
        ptype = self.provider_combo.currentData() or "custom"
        current_url = self.api_url_edit.text().strip()
        default_urls = {
            "ollama": "http://localhost:11434/v1/chat/completions",
            "openrouter": "https://openrouter.ai/api/v1/chat/completions",
            "openai": "https://api.openai.com/v1/chat/completions",
        }
        if not current_url or any(current_url == u for u in default_urls.values()):
            if ptype in default_urls:
                self.api_url_edit.setText(default_urls[ptype])

    def _toggle_api_key_visibility(self) -> None:
        """Переключает видимость API-ключа в поле."""
        if self.api_key_edit.echoMode() == QLineEdit.EchoMode.Password:
            self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Normal)
            self.toggle_key_btn.setText("Скрыть")
        else:
            self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
            self.toggle_key_btn.setText("Показать")

    def _check_connection(self) -> None:
        """Фоновая проверка подключения к серверу AI."""
        api_url = self.api_url_edit.text().strip()
        model = self.model_combo.currentText().strip()
        if not api_url:
            self._status("Сначала укажите адрес API.", error=True)
            return
        if not model:
            self._status("Сначала укажите имя модели.", error=True)
            return

        ptype = self.provider_combo.currentData() or "custom"
        api_key = self.api_key_edit.text().strip()
        to_conn = self.timeout_connect_spin.value()
        to_req = self.timeout_request_spin.value()

        self.check_conn_btn.setEnabled(False)
        self.check_status_label.setStyleSheet("color: #F5A623; font-weight: 600; padding: 2px 6px;")
        self.check_status_label.setText("Проверка подключения…")

        if self._conn_worker is not None and self._conn_worker.isRunning():
            self._conn_worker.cancel()
            self._conn_worker.wait(1000)

        self._conn_worker = ConnectionCheckWorker(
            api_url=api_url,
            api_key=api_key,
            model_name=model,
            provider_type=ptype,
            timeout_connect=to_conn,
            timeout_request=to_req,
            proxy=self.proxy_edit.text().strip(),
        )
        self._conn_worker.check_finished.connect(self._on_check_finished)
        self._conn_worker.start()

    def _on_check_finished(self, success: bool, message: str, latency_ms: float) -> None:
        """Результат проверки подключения."""
        self.check_conn_btn.setEnabled(True)
        if success:
            self.check_status_label.setStyleSheet("color: #4ADE80; font-weight: bold; padding: 2px 6px;")
            self.check_status_label.setText(f"{message}")
            self._status(f"Подключение успешно ({latency_ms:.0f} мс)")
        else:
            self.check_status_label.setStyleSheet("color: #FF6E73; font-weight: bold; padding: 2px 6px;")
            self.check_status_label.setText(f"{message}")
            self._status(f"Ошибка подключения: {message}", error=True)

    def _apply_api_preset(self, title: str) -> None:
        """Кнопки быстрого заполнения: подставить адрес сервиса."""
        url = API_PRESETS.get(title)
        if url:
            self.api_url_edit.setText(url)
            self._status(f"Подставлен адрес: {title}. Нажмите «Сохранить профиль».")

    def _save_ai_tab(self) -> None:
        """Сохраняет параметры AI-профиля в config.json и Credential Manager."""
        name = self.profile_name_edit.text().strip() or "Безымянный профиль"
        api_url = self.api_url_edit.text().strip()
        model = self.model_combo.currentText().strip()
        if not api_url:
            self._status("Адрес API не может быть пустым.", error=True)
            return
        if not model:
            self._status("Укажите имя модели.", error=True)
            return

        ptype = self.provider_combo.currentData() or "custom"
        norm_url = normalize_chat_url(api_url, ptype)
        self.api_url_edit.setText(norm_url)

        prof_data = {
            "id": self._current_profile_id,
            "name": name,
            "provider_type": ptype,
            "api_url": norm_url,
            "model_name": model,
            "proxy": self.proxy_edit.text().strip(),
            "temperature": self.temp_slider.value() / 100,
            "top_p": self.top_p_slider.value() / 100,
            "timeout_connect": self.timeout_connect_spin.value(),
            "timeout_request": self.timeout_request_spin.value(),
            "max_retries": self.max_retries_spin.value(),
            "max_tokens": self.max_tokens_spin.value(),
        }

        api_key = self.api_key_edit.text().strip()
        saved = self.config.save_profile(prof_data, api_key=api_key)
        if not saved:
            self._status(
                "Не удалось записать config.json — проверьте диск и права.",
                error=True,
            )
            return

        self.config.set_active_profile(self._current_profile_id)
        self._populate_profiles_combo()
        self._dirty = False
        self._status(f"Профиль «{name}» сохранён (ключ защищён в Credential Manager)")

    # ================== ВКЛАДКА 2: Быстрые действия и Промпты ================
    def _build_prompts_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setObjectName("SettingsScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.viewport().setAutoFillBackground(False)

        page = QWidget()
        page.setObjectName("SettingsPage")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(14)
        scroll.setWidget(page)

        body = QHBoxLayout()
        body.setSpacing(14)

        # Слева — карточка со списком действий
        card_list, list_lay = self._create_card(
            "Список действий (AI Quick Actions)",
            "Готовые задачи, стили и пресеты для выделенного текста"
        )
        self.preset_list = QListWidget()
        self.preset_list.itemSelectionChanged.connect(self._load_selected_preset)
        list_lay.addWidget(self.preset_list, stretch=1)

        btn_row1 = QHBoxLayout()
        add_btn = QPushButton("+ Добавить")
        add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_btn.setToolTip("Создать новое действие с черновиком промпта")
        add_btn.clicked.connect(self._add_preset)
        btn_row1.addWidget(add_btn)

        dup_btn = QPushButton("Копировать")
        dup_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        dup_btn.setToolTip("Сдублировать выбранное действие")
        dup_btn.clicked.connect(self._duplicate_preset)
        btn_row1.addWidget(dup_btn)

        del_btn = QPushButton("Удалить")
        del_btn.setObjectName("ClearButton")
        del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        del_btn.setToolTip("Удалить выбранное действие из конфигурации")
        del_btn.clicked.connect(self._delete_preset)
        btn_row1.addWidget(del_btn)
        list_lay.addLayout(btn_row1)

        btn_row2 = QHBoxLayout()
        up_btn = QPushButton("Вверх")
        up_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        up_btn.setToolTip("Переместить выбранное действие выше в списке")
        up_btn.clicked.connect(self._move_preset_up)
        btn_row2.addWidget(up_btn)

        down_btn = QPushButton("Вниз")
        down_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        down_btn.setToolTip("Переместить выбранное действие ниже в списке")
        down_btn.clicked.connect(self._move_preset_down)
        btn_row2.addWidget(down_btn)

        reset_btn = QPushButton("Сброс")
        reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        reset_btn.setToolTip("Восстановить исходные стартовые пресеты")
        reset_btn.clicked.connect(self._reset_presets_to_default)
        btn_row2.addWidget(reset_btn)
        list_lay.addLayout(btn_row2)

        # Справа — карточка редактора действия
        card_edit, edit_lay = self._create_card(
            "Редактор действия",
            "Название, промпт, выбор AI-профиля, хоткей и закрепление"
        )

        edit_lay.addWidget(self._row_with_hint("Название действия:", "Имя действия в меню и ленте"))
        self.preset_name_edit = QLineEdit()
        edit_lay.addWidget(self.preset_name_edit)

        edit_lay.addWidget(self._row_with_hint("AI-профиль для этого действия:", "Можно выбрать конкретный профиль/модель или использовать общий активный профиль"))
        self.action_profile_combo = QComboBox()
        edit_lay.addWidget(self.action_profile_combo)

        self.action_pinned_check = QCheckBox("Закрепить в панели быстрого доступа мини-окна (1 клик)")
        self.action_pinned_check.setToolTip("Закреплённые действия отображаются отдельными кнопками под шапкой мини-окна и вызываются цифрами 1..9")
        edit_lay.addWidget(self.action_pinned_check)

        edit_lay.addWidget(self._row_with_hint("Горячая клавиша действия (опционально):", "Отдельный глобальный хоткей для вызова этого действия сразу к выделению (напр. alt+1, alt+shift+t)"))
        self.action_hotkey_edit = QLineEdit()
        self.action_hotkey_edit.setPlaceholderText("например: alt+1, alt+shift+t (или пусто)")
        edit_lay.addWidget(self.action_hotkey_edit)

        edit_lay.addWidget(self._row_with_hint(
            "Системный промпт (модель читает его перед переводом):",
            "Инструкция, которую модель читает перед обработкой текста. Поддерживаются переменные {target_lang}, {source_lang}, {text}, {project_context}, {glossary}."
        ))
        self.preset_text_edit = QTextEdit()
        self.preset_text_edit.setPlaceholderText(
            "Ты — профессиональный переводчик. Опиши здесь, как именно обрабатывать текст…"
        )
        edit_lay.addWidget(self.preset_text_edit, stretch=1)

        save_row = QHBoxLayout()
        save_row.addStretch(1)
        save_btn = QPushButton("Сохранить действие")
        save_btn.setObjectName("PrimaryButton")
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.setToolTip("Сохранить изменения в текущем действии")
        save_btn.clicked.connect(self._save_current_preset)
        save_row.addWidget(save_btn)
        edit_lay.addLayout(save_row)

        body.addWidget(card_list, stretch=1)
        body.addWidget(card_edit, stretch=2)
        lay.addLayout(body, stretch=1)

        # Нижняя карточка: Переменные и Контекст проекта
        card_context, ctx_lay = self._create_card(
            "Переменные промпта и контекст проекта",
            "Использование переменных в шаблонах и настройки активного проекта"
        )

        var_info = QLabel(
            "<b>Как использовать переменные в системных промптах:</b><br>"
            "Вы можете вставлять эти теги прямо в текст промпта выше. При выполнении действия программа автоматически подставит в них нужные данные:<br><br>"
            "• <code>{target_lang}</code> — язык, на который нужно перевести (например: <i>русский</i>, <i>английский</i>);<br>"
            "• <code>{source_lang}</code> — язык исходного выделенного текста;<br>"
            "• <code>{text}</code> — сам выделенный пользователем текст (передаётся модели для обработки);<br>"
            "• <code>{project_context}</code> — тема или контекст вашей работы (берётся из поля «Контекст проекта» ниже). Помогает модели точнее понять специфику текста;<br>"
            "• <code>{glossary}</code> — словарь обязательных терминов (берётся из поля «Глоссарий терминов» ниже). Модель будет строго следовать вашим переводам терминов."
        )
        var_info.setTextFormat(Qt.TextFormat.RichText)
        var_info.setWordWrap(True)
        ctx_lay.addWidget(var_info)

        ctx_lay.addWidget(self._row_with_hint("Контекст проекта (project_context):", "Описание проекта, тональности или предметной области, передаваемое в переменную {project_context}"))
        self.project_context_edit = QLineEdit(self.config.get("project_context", ""))
        self.project_context_edit.setPlaceholderText("например: Техническая документация криптографического протокола")
        ctx_lay.addWidget(self.project_context_edit)

        ctx_lay.addWidget(self._row_with_hint("Глоссарий терминов (glossary):", "Словарь терминов проекта, передаваемый в переменную {glossary}"))
        self.glossary_edit = QTextEdit()
        self.glossary_edit.setPlaceholderText("например:\nИИ -> AI\nнейросеть -> neural network\nхоткей -> shortcut")
        self.glossary_edit.setPlainText(self.config.get("glossary", ""))
        self.glossary_edit.setMaximumHeight(90)
        ctx_lay.addWidget(self.glossary_edit)

        ctx_save_row = QHBoxLayout()
        ctx_save_row.addStretch(1)
        save_ctx_btn = QPushButton("Сохранить контекст и глоссарий")
        save_ctx_btn.setObjectName("PrimaryButton")
        save_ctx_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_ctx_btn.clicked.connect(self._save_project_context)
        ctx_save_row.addWidget(save_ctx_btn)
        ctx_lay.addLayout(ctx_save_row)

        lay.addWidget(card_context)

        lay.addWidget(self._build_cheat_sheet())

        self._populate_preset_list()
        return scroll

    @staticmethod
    def _build_cheat_sheet() -> QFrame:
        """Шпаргалка: как писать хорошие промпты (прямо в интерфейсе)."""
        frame = QFrame()
        frame.setObjectName("CheatSheet")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(6)
        title = QLabel("Шпаргалка: как писать хорошие промпты для перевода и рерайта")
        title.setObjectName("CheatSheetTitle")
        lay.addWidget(title)
        body = QLabel(CHEAT_SHEET)
        body.setObjectName("CheatSheetBody")
        body.setWordWrap(True)
        lay.addWidget(body)
        return frame

    def _populate_preset_list(self) -> None:
        """Заполняет список действий и выделяет активное."""
        self.preset_list.blockSignals(True)
        self.preset_list.clear()

        # Заполняем combo профилей ИИ
        self.action_profile_combo.blockSignals(True)
        self.action_profile_combo.clear()
        self.action_profile_combo.addItem("Использовать активный AI-профиль (по умолчанию)", "")
        if hasattr(self.config, "get_profiles"):
            for pid, prof in self.config.get_profiles().items():
                self.action_profile_combo.addItem(prof.get("name", pid), pid)
        self.action_profile_combo.blockSignals(False)

        actions = self.config.get_actions() if hasattr(self.config, "get_actions") else []
        active_id = self.config.get("active_action_id", "")
        active_name = self.config.get("active_prompt_name", "")

        row = 0
        for i, act in enumerate(actions):
            aid = act["id"]
            name = act["name"]
            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, aid)
            pinned = act.get("pinned", False)
            hotkey = act.get("hotkey", "")
            tooltip_parts = []
            if pinned:
                tooltip_parts.append("Закреплено в панели быстрого доступа")
            if hotkey:
                tooltip_parts.append(f"Хоткей: {hotkey}")
            if tooltip_parts:
                item.setToolTip(" | ".join(tooltip_parts))
            self.preset_list.addItem(item)
            if aid == active_id or name == active_name:
                row = i

        if self.preset_list.count():
            self.preset_list.setCurrentRow(row)
        self.preset_list.blockSignals(False)
        self._load_selected_preset()

    def _load_selected_preset(self) -> None:
        """Выбор действия в списке — загружаем его в редактор справа."""
        item = self.preset_list.currentItem()
        if item is None:
            name = ""
            act = {}
        else:
            aid = item.data(Qt.ItemDataRole.UserRole)
            name = item.text()
            act = self.config.get_action(aid or name) or {}
            if not act and hasattr(self.config, "get_prompt"):
                p_text = self.config.get_prompt(name) or ""
                act = {"name": name, "prompt": p_text, "profile_id": "", "pinned": False, "hotkey": ""}

        self.preset_name_edit.blockSignals(True)
        self.preset_text_edit.blockSignals(True)
        self.action_profile_combo.blockSignals(True)
        self.action_pinned_check.blockSignals(True)
        self.action_hotkey_edit.blockSignals(True)

        self.preset_name_edit.setText(act.get("name", name))
        self.preset_text_edit.setPlainText(act.get("prompt", ""))
        self.action_pinned_check.setChecked(bool(act.get("pinned", False)))
        self.action_hotkey_edit.setText(str(act.get("hotkey", "")))

        target_pid = str(act.get("profile_id", ""))
        idx = self.action_profile_combo.findData(target_pid)
        if idx >= 0:
            self.action_profile_combo.setCurrentIndex(idx)
        else:
            self.action_profile_combo.setCurrentIndex(0)

        self.preset_name_edit.blockSignals(False)
        self.preset_text_edit.blockSignals(False)
        self.action_profile_combo.blockSignals(False)
        self.action_pinned_check.blockSignals(False)
        self.action_hotkey_edit.blockSignals(False)

    def _add_preset(self) -> None:
        """«Добавить пресет / действие»: создаём черновик с уникальным именем."""
        names = {a["name"] for a in self.config.get_actions()} if hasattr(self.config, "get_actions") else set(self.config.get("prompts", {}).keys())
        name, n = "Новый пресет", 2
        while name in names:
            name = f"Новый пресет {n}"
            n += 1
        draft = (
            "Ты — профессиональный переводчик. Опиши здесь, как переводить: "
            "язык, тон и что вернуть в ответе."
        )
        new_act = {
            "name": name,
            "prompt": draft,
            "profile_id": "",
            "pinned": False,
            "hotkey": "",
            "order": self.preset_list.count(),
        }
        if hasattr(self.config, "save_action"):
            if not self.config.save_action(new_act):
                self._status("Не удалось записать config.json — действие не добавлено.", error=True)
                return
        else:
            if not self.config.set_prompt(name, draft):
                self._status("Не удалось записать config.json — пресет не добавлен.", error=True)
                return
        self._populate_preset_list()
        self.preset_list.setCurrentRow(self.preset_list.count() - 1)
        self.prompts_changed.emit()
        self._status(f"Действие «{name}» добавлено — отредактируйте и нажмите «Сохранить».")

    def _duplicate_preset(self) -> None:
        """«Копировать действие»: создаёт точную копию выбранного действия."""
        item = self.preset_list.currentItem()
        if not item:
            return
        aid = item.data(Qt.ItemDataRole.UserRole)
        act = self.config.get_action(aid) if hasattr(self.config, "get_action") else None
        if not act:
            return
        dup_act = deepcopy(act)
        dup_act["id"] = f"action_{uuid.uuid4().hex[:8]}"
        dup_act["name"] = f"{act['name']} (копия)"
        dup_act["hotkey"] = ""
        dup_act["order"] = self.preset_list.count()
        if self.config.save_action(dup_act):
            self._populate_preset_list()
            self.preset_list.setCurrentRow(self.preset_list.count() - 1)
            self.prompts_changed.emit()
            self._status(f"Действие сдублировано: «{dup_act['name']}».")

    def _delete_preset(self) -> None:
        """«Удалить»: убираем выбранное действие из config.json."""
        item = self.preset_list.currentItem()
        if item is None:
            self._status("Сначала выберите действие в списке.", error=True)
            return
        aid = item.data(Qt.ItemDataRole.UserRole)
        name = item.text()
        if hasattr(self.config, "get_actions") and len(self.config.get_actions()) <= 1:
            self._status("Нельзя удалить последнее оставшееся действие.", error=True)
            return
        if hasattr(self.config, "delete_action"):
            if not self.config.delete_action(aid or name):
                self._status("Не удалось удалить действие.", error=True)
                return
        else:
            prompts = dict(self.config.get("prompts", {}))
            if name in prompts:
                del prompts[name]
                self.config.set("prompts", prompts)

        row = self.preset_list.currentRow()
        self._populate_preset_list()
        if self.preset_list.count():
            self.preset_list.setCurrentRow(min(row, self.preset_list.count() - 1))
        self.prompts_changed.emit()
        self._status(f"Действие «{name}» удалено.")

    def _move_preset_up(self) -> None:
        """Перемещает действие выше в списке."""
        row = self.preset_list.currentRow()
        if row <= 0:
            return
        item = self.preset_list.takeItem(row)
        self.preset_list.insertItem(row - 1, item)
        self.preset_list.setCurrentRow(row - 1)
        order_ids = [self.preset_list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.preset_list.count())]
        if hasattr(self.config, "reorder_actions"):
            self.config.reorder_actions(order_ids)
        self.prompts_changed.emit()

    def _move_preset_down(self) -> None:
        """Перемещает действие ниже в списке."""
        row = self.preset_list.currentRow()
        if row < 0 or row >= self.preset_list.count() - 1:
            return
        item = self.preset_list.takeItem(row)
        self.preset_list.insertItem(row + 1, item)
        self.preset_list.setCurrentRow(row + 1)
        order_ids = [self.preset_list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.preset_list.count())]
        if hasattr(self.config, "reorder_actions"):
            self.config.reorder_actions(order_ids)
        self.prompts_changed.emit()

    def _reset_presets_to_default(self) -> None:
        """Сбрасывает действия к исходному стартовому набору."""
        from config import DEFAULT_ACTIONS
        if hasattr(self.config, "save"):
            self.config.data["actions"] = deepcopy(DEFAULT_ACTIONS)
            self.config.save()
            self._populate_preset_list()
            self.prompts_changed.emit()
            self._status("Стартовые действия ИИ успешно восстановлены")

    def _save_current_preset(self) -> None:
        """«Сохранить»: записывает название, промпт и параметры действия."""
        name = self.preset_name_edit.text().strip()
        text = self.preset_text_edit.toPlainText().strip()
        if not name:
            self._status("Укажите название действия.", error=True)
            return
        if not text:
            self._status("Промпт не может быть пустым.", error=True)
            return

        item = self.preset_list.currentItem()
        aid = item.data(Qt.ItemDataRole.UserRole) if item else ""
        act = self.config.get_action(aid) if (aid and hasattr(self.config, "get_action")) else None

        profile_id = self.action_profile_combo.currentData() or ""
        pinned = self.action_pinned_check.isChecked()
        hotkey = self.action_hotkey_edit.text().strip().lower()

        action_data = {
            "id": aid or f"action_{uuid.uuid4().hex[:8]}",
            "name": name,
            "prompt": text,
            "profile_id": profile_id,
            "pinned": pinned,
            "hotkey": hotkey,
            "order": act.get("order", self.preset_list.currentRow()) if act else self.preset_list.currentRow(),
        }

        if hasattr(self.config, "save_action"):
            if not self.config.save_action(action_data):
                self._status("Не удалось записать config.json — действие не сохранено.", error=True)
                return
        else:
            self.config.set_prompt(name, text)

        if item:
            item.setText(name)
            item.setData(Qt.ItemDataRole.UserRole, action_data["id"])

        self.prompts_changed.emit()
        self._dirty = False
        self._status(f"Действие «{name}» сохранено")

    def _save_project_context(self) -> None:
        """Сохраняет контекст проекта и глоссарий терминов."""
        ctx = self.project_context_edit.text().strip()
        glo = self.glossary_edit.toPlainText().strip()
        self.config.set("project_context", ctx, autosave=False)
        self.config.set("glossary", glo, autosave=True)
        self._status("Контекст проекта и глоссарий успешно сохранены")

    # ============ ВКЛАДКА 3: Хоткеи и Обычный переводчик ======================
    def _build_hotkeys_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setObjectName("SettingsScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.viewport().setAutoFillBackground(False)

        page = QWidget()
        page.setObjectName("SettingsPage")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(14)
        scroll.setWidget(page)

        # === КАРТОЧКА 1: Глобальный хоткей ===
        card_hot, hot_lay = self._create_card(
            "Глобальное сочетание клавиш",
            "Вызов мини-окна перевода поверх любого активного приложения Windows"
        )
        hot_lay.addWidget(self._row_with_hint("Сочетание клавиш:", HINT_HOTKEY))
        hot_row = QHBoxLayout()
        self.hotkey_edit = QLineEdit(self.config.get("hotkey", "alt+q"))
        self.hotkey_edit.setReadOnly(True)
        self.hotkey_edit.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.hotkey_edit.setCursor(Qt.CursorShape.ArrowCursor)
        self.hotkey_edit.setPlaceholderText("Нажмите «Записать нажатие»")
        hot_row.addWidget(self.hotkey_edit, stretch=1)

        self.record_btn = QPushButton("Записать нажатие")
        self.record_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.record_btn.setToolTip("Нажмите кнопку и затем нажмите нужное сочетание клавиш")
        self.record_btn.clicked.connect(self._toggle_recording)
        hot_row.addWidget(self.record_btn)

        self.btn_clear_hotkey = QPushButton("Очистить")
        self.btn_clear_hotkey.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_clear_hotkey.setToolTip("Очистить (отключить) сочетание клавиш")
        self.btn_clear_hotkey.clicked.connect(self._clear_hotkey_clicked)
        hot_row.addWidget(self.btn_clear_hotkey)
        hot_lay.addLayout(hot_row)
        hot_lay.addWidget(self._caption(
            "Нажмите «Записать нажатие», затем — нужное сочетание клавиш в любом месте системы. Пустое поле = хоткей отключён."
        ))

        self.hotkey_enabled_cb = QCheckBox("Глобальный хоткей включён")
        self.hotkey_enabled_cb.setCursor(Qt.CursorShape.PointingHandCursor)
        self.hotkey_enabled_cb.setChecked(bool(self.config.get("hotkey_enabled", True)))
        self.hotkey_enabled_cb.setToolTip(
            "Снимите галочку, чтобы временно отключить хоткей без потери комбинации"
        )
        self.hotkey_enabled_cb.toggled.connect(self._mark_dirty)
        self.hotkey_enabled_cb.toggled.connect(self._update_hotkey_widgets_state)
        hot_lay.addWidget(self.hotkey_enabled_cb)
        self._update_hotkey_widgets_state()
        lay.addWidget(card_hot)

        # === КАРТОЧКА 2: Обычный переводчик и Языки ===
        card_std, std_lay = self._create_card(
            "Обычный переводчик и Языки",
            "Выбор движка перевода, исходного и целевого языков, а также резервного языка"
        )
        std_grid = QGridLayout()
        std_grid.setHorizontalSpacing(14)
        std_grid.setVerticalSpacing(10)

        # Ряд 0-1: Движок перевода и Исходный язык
        std_grid.addWidget(self._row_with_hint("Движок перевода:", HINT_ENGINE), 0, 0)
        self.engine_combo = QComboBox()
        self.engine_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        self.engine_combo.addItem("Google (бесплатно, без ключа)", "google")
        self.engine_combo.addItem("DeepL (качественнее, нужен API-ключ)", "deepl")
        current_engine = self.config.get("standard_engine", "google")
        index = self.engine_combo.findData(current_engine)
        self.engine_combo.setCurrentIndex(max(index, 0))
        self.engine_combo.currentIndexChanged.connect(self._on_engine_changed)
        std_grid.addWidget(self.engine_combo, 1, 0)

        std_grid.addWidget(self._row_with_hint("Исходный язык текста:", HINT_SOURCE_LANG), 0, 1)
        self.source_lang_combo = QComboBox()
        self.source_lang_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        self.source_lang_combo.addItem("Автоопределение (auto)", "auto")
        for lang in get_supported_languages():
            self.source_lang_combo.addItem(f"{lang.name_ru} ({lang.code})", lang.code)
        std_grid.addWidget(self.source_lang_combo, 1, 1)

        # Ряд 2-3: Целевой язык и Резервный целевой язык
        std_grid.addWidget(self._row_with_hint("Целевой язык перевода:", HINT_TARGET_LANG), 2, 0)
        self.lang_combo = QComboBox()
        self.lang_combo.setEditable(True)
        self.lang_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        for lang in get_supported_languages():
            self.lang_combo.addItem(f"{lang.name_ru} ({lang.code})", lang.code)
        std_grid.addWidget(self.lang_combo, 3, 0)

        std_grid.addWidget(self._row_with_hint("Резервный язык (при авто-перевороте):", HINT_FALLBACK_LANG), 2, 1)
        self.fallback_lang_combo = QComboBox()
        self.fallback_lang_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        for lang in get_supported_languages():
            self.fallback_lang_combo.addItem(f"{lang.name_ru} ({lang.code})", lang.code)
        std_grid.addWidget(self.fallback_lang_combo, 3, 1)

        std_lay.addLayout(std_grid)

        std_lay.addWidget(self._row_with_hint("DeepL API-ключ:", "Ключ используется только при выборе движка DeepL"))
        self.deepl_key_edit = QLineEdit(self.config.get("deepl_api_key", ""))
        self.deepl_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.deepl_key_edit.setPlaceholderText("DeepL API-ключ (бесплатный тариф на deepl.com)")
        self.deepl_key_edit.setToolTip("Получите бесплатно: deepl.com → «API для разработчиков».")
        std_lay.addWidget(self.deepl_key_edit)
        self._on_engine_changed()
        lay.addWidget(card_std)

        # === КАРТОЧКА 3: Оформление и мини-окно (Этапы 9.1, 9.2, 9.4) ===
        card_app, app_lay = self._create_card(
            "Оформление и мини-окно",
            "Выбор темы оформления, масштаба интерфейса и параметров всплывающего окна"
        )
        app_grid = QGridLayout()
        app_grid.setHorizontalSpacing(14)
        app_grid.setVerticalSpacing(10)

        # Тема оформления
        app_grid.addWidget(self._row_with_hint("Тема интерфейса:", "Тёмная, светлая или автоматически по системной теме Windows"), 0, 0)
        self.theme_combo = QComboBox()
        self.theme_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        self.theme_combo.addItem("Тёмная", "dark")
        self.theme_combo.addItem("Светлая", "light")
        self.theme_combo.addItem("Системная (Windows)", "system")
        cur_th = self.config.get_theme() if hasattr(self.config, "get_theme") else "dark"
        idx_th = self.theme_combo.findData(cur_th)
        self.theme_combo.setCurrentIndex(max(idx_th, 0))
        self.theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        app_grid.addWidget(self.theme_combo, 1, 0)

        # Масштаб шрифта
        app_grid.addWidget(self._row_with_hint("Масштаб шрифта:", "Размер текста для комфортного чтения больших объёмов"), 0, 1)
        self.font_size_combo = QComboBox()
        self.font_size_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        self.font_size_combo.addItem("Компактный (-1 пт)", "small")
        self.font_size_combo.addItem("Стандартный", "medium")
        self.font_size_combo.addItem("Крупный (+1.5 пт)", "large")
        cur_fs = self.config.get_font_size() if hasattr(self.config, "get_font_size") else "medium"
        idx_fs = self.font_size_combo.findData(cur_fs)
        self.font_size_combo.setCurrentIndex(max(idx_fs, 0))
        self.font_size_combo.currentIndexChanged.connect(self._on_font_size_changed)
        app_grid.addWidget(self.font_size_combo, 1, 1)

        # Прозрачность мини-окна
        app_grid.addWidget(self._row_with_hint("Прозрачность мини-окна:", "Непрозрачность окна от 70% до 100%"), 2, 0)
        op_box = QHBoxLayout()
        self.opacity_slider = ClickJumpSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setRange(70, 100)
        cur_op = self.config.get_popup_opacity() if hasattr(self.config, "get_popup_opacity") else 1.0
        self.opacity_slider.setValue(int(cur_op * 100))
        self.opacity_slider.setCursor(Qt.CursorShape.PointingHandCursor)
        self.opacity_val_lbl = QLabel(f"{self.opacity_slider.value()}%")
        self.opacity_val_lbl.setFixedWidth(45)
        self.opacity_slider.valueChanged.connect(lambda v: (self.opacity_val_lbl.setText(f"{v}%"), self._mark_dirty()))
        op_box.addWidget(self.opacity_slider, stretch=1)
        op_box.addWidget(self.opacity_val_lbl)
        app_grid.addLayout(op_box, 3, 0)

        # Лимит карточек в сессии
        app_grid.addWidget(self._row_with_hint("Максимум карточек в ленте:", "Старые карточки автоматически удаляются при превышении лимита"), 2, 1)
        self.max_cards_spin = QSpinBox()
        self.max_cards_spin.setRange(5, 50)
        self.max_cards_spin.setValue(self.config.get_popup_max_cards() if hasattr(self.config, "get_popup_max_cards") else 10)
        self.max_cards_spin.valueChanged.connect(self._mark_dirty)
        app_grid.addWidget(self.max_cards_spin, 3, 1)

        app_lay.addLayout(app_grid)

        # Чекбоксы мини-окна
        self.remember_pos_cb = QCheckBox("Запоминать последнее положение и размер мини-окна на экране")
        self.remember_pos_cb.setCursor(Qt.CursorShape.PointingHandCursor)
        self.remember_pos_cb.setChecked(bool(self.config.get("popup_remember_position", False)))
        self.remember_pos_cb.toggled.connect(self._mark_dirty)
        app_lay.addWidget(self.remember_pos_cb)

        self.stays_on_top_cb = QCheckBox("Закреплять мини-окно поверх всех остальных окон Windows")
        self.stays_on_top_cb.setCursor(Qt.CursorShape.PointingHandCursor)
        self.stays_on_top_cb.setChecked(bool(self.config.is_popup_stays_on_top() if hasattr(self.config, "is_popup_stays_on_top") else True))
        self.stays_on_top_cb.toggled.connect(self._mark_dirty)
        app_lay.addWidget(self.stays_on_top_cb)

        # Кнопка мастера первого запуска
        wiz_row = QHBoxLayout()
        wiz_lbl = QLabel("Первоначальная настройка:")
        wiz_lbl.setObjectName("CaptionLabel")
        wiz_row.addWidget(wiz_lbl)
        self.open_wizard_btn = QPushButton("Пройти мастер первого запуска...")
        self.open_wizard_btn.setObjectName("SecondaryButton")
        self.open_wizard_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.open_wizard_btn.clicked.connect(self._open_first_run_wizard)
        wiz_row.addWidget(self.open_wizard_btn)
        wiz_row.addStretch(1)
        app_lay.addLayout(wiz_row)

        lay.addWidget(card_app)

        # === КАРТОЧКА 4: Диагностика и Журнал ===
        card_diag, diag_lay = self._create_card(
            "Диагностика и Журнал",
            "Подробное логирование этапов захвата текста для решения проблем"
        )
        self.diagnostics_cb = QCheckBox("Диагностический режим (журнал захвата)")
        self.diagnostics_cb.setCursor(Qt.CursorShape.PointingHandCursor)
        self.diagnostics_cb.setChecked(bool(self.config.get("diagnostics", False)))
        self.diagnostics_cb.setToolTip(
            "Включите, если захват выделения работает нестабильно.\n"
            "Журнал truniversal_diag.log (рядом с программой) покажет шаги захвата.\n"
            "Выделенный текст в журнал НЕ записывается."
        )
        self.diagnostics_cb.toggled.connect(self._mark_dirty)
        diag_lay.addWidget(self.diagnostics_cb)
        diag_lay.addWidget(self._caption(
            "Помогает понять, почему захват не работает: включите, повторите выделение и проверьте файл truniversal_diag.log."
        ))
        lay.addWidget(card_diag)

        # === КАРТОЧКА 4: Сброс настроек (Опасная зона) ===
        card_reset, reset_lay = self._create_card(
            "Опасная зона",
            "Возврат программы к первоначальному состоянию"
        )
        reset_row = QHBoxLayout()
        reset_info = QLabel("Сбросить все параметры, AI-профили и промпты к исходным заводским настройкам.")
        reset_info.setObjectName("CaptionLabel")
        reset_row.addWidget(reset_info, stretch=1)

        self.reset_btn = QPushButton("Сбросить все настройки")
        self.reset_btn.setObjectName("DangerButton")
        self.reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.reset_btn.setToolTip(
            "Вернуть ВСЕ настройки к заводским: хоткей, режим, адрес API,\n"
            "ключи, модель, параметры генерации; промпты заменятся стандартными."
        )
        self.reset_btn.clicked.connect(self._reset_all_settings)
        reset_row.addWidget(self.reset_btn)
        reset_lay.addLayout(reset_row)
        lay.addWidget(card_reset)

        # === Нижняя панель действий ===
        save_row = QHBoxLayout()
        save_row.addStretch(1)
        save_btn = QPushButton("Сохранить настройки")
        save_btn.setObjectName("PrimaryButton")
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.setToolTip("Хоткей перерегистрируется сразу — без перезапуска программы")
        save_btn.clicked.connect(self._save_common_tab)
        save_row.addWidget(save_btn)
        lay.addLayout(save_row)

        return scroll

    def _on_engine_changed(self, *_args) -> None:
        """Поле DeepL-ключа активно только при движке DeepL."""
        self.deepl_key_edit.setEnabled(self.engine_combo.currentData() == "deepl")

    def _clear_hotkey_clicked(self) -> None:
        """Очищает поле сочетания клавиш (отключает хоткей)."""
        if self._recorder is not None and self._recorder.isRunning():
            self._recorder.cancel()
            self.record_btn.setText("Записать нажатие")
        self.hotkey_edit.setText("")
        self._mark_dirty()
        self._status("Сочетание клавиш очищено (отключено). Нажмите «Сохранить настройки».")

    def _toggle_recording(self) -> None:
        """«Записать нажатие» → ждём сочетание; повторный клик — «Отмена»."""
        if self._recorder is not None and self._recorder.isRunning():
            self._recorder.cancel()
            self.record_btn.setText("Записать нажатие")
            self._status("Запись отменена.")
            return
        self.record_btn.setText("Отмена записи…")
        self._status("Нажмите новое сочетание клавиш…")
        self._recorder = HotkeyRecorder()
        self._recorder.done.connect(self._on_hotkey_recorded)
        self._recorder.start()

    def _on_hotkey_recorded(self, hotkey: str) -> None:
        """Запись завершилась: подставляем сочетание в поле."""
        self.record_btn.setText("Записать нажатие")
        if not hotkey:
            self._status("Запись отменена.")
            return
        self.hotkey_edit.setText(hotkey.lower())
        self._status(f"Записано: «{hotkey}». Нажмите «Сохранить настройки».")

    # ================== Сброс к заводским настройкам (Этап 1) ==================
    def _reset_all_settings(self) -> None:
        """Возвращает ВСЕ настройки к заводским значениям (с подтверждением).

        Предупреждение честно перечисляет, что именно пропадёт: пользовательские
        промпты — это данные пользователя, их потеря должна быть осознанной.
        """
        answer = QMessageBox.question(
            self,
            "Truniversal",
            "Вернуть все настройки к заводским значениям?\n\n"
            "Будут сброшены: хоткей, режим перевода, адрес API, ключи, модель,\n"
            "параметры генерации, целевой язык, а все пользовательские промпты\n"
            "заменятся стандартными пресетами.\n"
            "Действие нельзя отменить.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        if not self.config.reset_to_defaults():
            self._status("Не удалось записать config.json — сброс не завершён.",
                         error=True)
            return

        # Хоткей перерегистрируем сразу; окно перечитываем из нового конфига.
        default_hotkey = self.config.get("hotkey", "")
        if self.hotkey_manager is not None:
            if self.hotkey_manager.set_hotkey(default_hotkey):
                self._status("Все настройки сброшены к заводским")
            else:
                self._status(
                    "Настройки сброшены, но хоткей не зарегистрировался — "
                    "проверьте сочетание.",
                    error=True,
                )
            self.hotkey_changed.emit(default_hotkey)
        else:
            # Менеджера нет (тестовое окружение) — применится после перезапуска.
            self._status("Все настройки сброшены к заводским")
        self._refresh_all_from_config()
        self.prompts_changed.emit()
        self._dirty = False

    def _refresh_all_from_config(self) -> None:
        """Перечитывает текущий конфиг во все виджеты окна (после сброса).

        Программные установки делаются с blockSignals — иначе каждое
        обновление пометило бы окно «грязным» (см. _mark_dirty).
        """
        # Вкладка 1: Модели и Параметры ИИ.
        self._populate_profiles_combo()

        # Вкладка 2: Мои Промпты (список + редактор активного пресета).
        self._populate_preset_list()

        # Вкладка 3: Хоткеи и Обычный переводчик.
        self.hotkey_edit.blockSignals(True)
        self.hotkey_edit.setText(self.config.get("hotkey", ""))
        self.hotkey_edit.blockSignals(False)

        self.hotkey_enabled_cb.blockSignals(True)
        self.hotkey_enabled_cb.setChecked(
            bool(self.config.get("hotkey_enabled", True))
        )
        self.hotkey_enabled_cb.blockSignals(False)
        self._update_hotkey_widgets_state()

        self.diagnostics_cb.blockSignals(True)
        self.diagnostics_cb.setChecked(bool(self.config.get("diagnostics", False)))
        self.diagnostics_cb.blockSignals(False)

        self.engine_combo.blockSignals(True)
        index = self.engine_combo.findData(
            self.config.get("standard_engine", "google")
        )
        self.engine_combo.setCurrentIndex(max(index, 0))
        self.engine_combo.blockSignals(False)
        self._on_engine_changed()  # сигнал был заблокирован — обновляем руками

        self.deepl_key_edit.blockSignals(True)
        self.deepl_key_edit.setText(self.config.get("deepl_api_key", ""))
        self.deepl_key_edit.blockSignals(False)

        # Исходный язык (Этап 4)
        self.source_lang_combo.blockSignals(True)
        src = str(self.config.get("source_lang", "auto")).strip().lower()
        idx_src = self.source_lang_combo.findData(src)
        if idx_src >= 0:
            self.source_lang_combo.setCurrentIndex(idx_src)
        else:
            self.source_lang_combo.setCurrentText(src)
        self.source_lang_combo.blockSignals(False)

        # Целевой язык (Этап 4)
        self.lang_combo.blockSignals(True)
        tgt = str(self.config.get("target_lang", "ru")).strip().lower()
        idx_tgt = self.lang_combo.findData(tgt)
        if idx_tgt >= 0:
            self.lang_combo.setCurrentIndex(idx_tgt)
        else:
            self.lang_combo.setCurrentText(tgt)
        self.lang_combo.blockSignals(False)

        # Резервный целевой язык (Этап 4)
        self.fallback_lang_combo.blockSignals(True)
        fb = str(self.config.get("fallback_target_lang", "en")).strip().lower()
        idx_fb = self.fallback_lang_combo.findData(fb)
        if idx_fb >= 0:
            self.fallback_lang_combo.setCurrentIndex(idx_fb)
        else:
            self.fallback_lang_combo.setCurrentText(fb)
        self.fallback_lang_combo.blockSignals(False)

        # Оформление и интерфейс (Этап 9)
        if hasattr(self, "theme_combo"):
            self.theme_combo.blockSignals(True)
            cur_th = self.config.get_theme() if hasattr(self.config, "get_theme") else "dark"
            idx_th = self.theme_combo.findData(cur_th)
            self.theme_combo.setCurrentIndex(max(idx_th, 0))
            self.theme_combo.blockSignals(False)

        if hasattr(self, "font_size_combo"):
            self.font_size_combo.blockSignals(True)
            cur_fs = self.config.get_font_size() if hasattr(self.config, "get_font_size") else "medium"
            idx_fs = self.font_size_combo.findData(cur_fs)
            self.font_size_combo.setCurrentIndex(max(idx_fs, 0))
            self.font_size_combo.blockSignals(False)

        if hasattr(self, "opacity_slider"):
            self.opacity_slider.blockSignals(True)
            cur_op = self.config.get_popup_opacity() if hasattr(self.config, "get_popup_opacity") else 1.0
            self.opacity_slider.setValue(int(cur_op * 100))
            self.opacity_val_lbl.setText(f"{self.opacity_slider.value()}%")
            self.opacity_slider.blockSignals(False)

        if hasattr(self, "max_cards_spin"):
            self.max_cards_spin.blockSignals(True)
            self.max_cards_spin.setValue(self.config.get_popup_max_cards() if hasattr(self.config, "get_popup_max_cards") else 10)
            self.max_cards_spin.blockSignals(False)

        if hasattr(self, "remember_pos_cb"):
            self.remember_pos_cb.blockSignals(True)
            self.remember_pos_cb.setChecked(bool(self.config.get("popup_remember_position", False)))
            self.remember_pos_cb.blockSignals(False)

        if hasattr(self, "stays_on_top_cb"):
            self.stays_on_top_cb.blockSignals(True)
            self.stays_on_top_cb.setChecked(bool(self.config.is_popup_stays_on_top() if hasattr(self.config, "is_popup_stays_on_top") else True))
            self.stays_on_top_cb.blockSignals(False)

        # Проекты и глоссарий (Этап 8)
        if hasattr(self, "_populate_project_combos"):
            self._populate_project_combos()
        if hasattr(self, "_refresh_projects_list"):
            self._refresh_projects_list()

    def refresh_from_config(self) -> None:
        """Публичный метод обновления данных окна из конфига и менеджера проектов."""
        self._refresh_all_from_config()

    def _on_theme_changed(self) -> None:
        """Динамическое переключение темы оформления (Этап 9.2)."""
        th = self.theme_combo.currentData() or "dark"
        fs = self.font_size_combo.currentData() or "medium"
        from styles import apply_theme, apply_title_bar_theme
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance()
        actual_theme = "dark"
        if app is not None:
            actual_theme = apply_theme(app, th, fs)
        apply_title_bar_theme(self, dark=(actual_theme == "dark"))
        self._mark_dirty()

    def _on_font_size_changed(self) -> None:
        """Динамическое масштабирование шрифтов (Этап 9.2)."""
        self._on_theme_changed()

    def _open_first_run_wizard(self) -> None:
        """Запуск мастера первоначальной настройки из настроек (Этап 9.4)."""
        try:
            from first_run_wizard import FirstRunWizard
            dlg = FirstRunWizard(self.config, self)
            if dlg.exec() == QDialog.DialogCode.Accepted:
                self.refresh_from_config()
                self._status("Настройки мастера первоначальной настройки применены.")
        except Exception as exc:
            self._status(f"Ошибка вызова мастера: {exc}", error=True)

    # ============ Сохранение, модели, статусы и события окна ==================
    def _update_hotkey_widgets_state(self, *_) -> None:
        """Поле хоткея активно только при включённой галочке."""
        enabled = self.hotkey_enabled_cb.isChecked()
        self.hotkey_edit.setEnabled(enabled)
        self.record_btn.setEnabled(enabled)

    def _save_common_tab(self) -> None:
        """Сохраняет хоткей и настройки обычного перевода (вкладка 3)."""
        engine = self.engine_combo.currentData() or "google"

        # Исходный язык
        source_val = ""
        idx_src = self.source_lang_combo.currentIndex()
        if idx_src >= 0 and self.source_lang_combo.currentText() == self.source_lang_combo.itemText(idx_src):
            source_val = self.source_lang_combo.itemData(idx_src)
        if not source_val:
            source_val = self.source_lang_combo.currentText().strip().lower()
        if "(" in source_val and ")" in source_val:
            m = re.search(r'\(([^)]+)\)', source_val)
            if m:
                source_val = m.group(1).strip().lower()
        if not source_val:
            source_val = "auto"

        # Целевой язык
        target_val = ""
        idx_tgt = self.lang_combo.currentIndex()
        if idx_tgt >= 0 and self.lang_combo.currentText() == self.lang_combo.itemText(idx_tgt):
            target_val = self.lang_combo.itemData(idx_tgt)
        if not target_val:
            target_val = self.lang_combo.currentText().strip().lower()
        if "(" in target_val and ")" in target_val:
            m = re.search(r'\(([^)]+)\)', target_val)
            if m:
                target_val = m.group(1).strip().lower()
        if not target_val:
            self._status("Укажите целевой язык перевода.", error=True)
            return

        # Резервный целевой язык
        fallback_val = ""
        idx_fb = self.fallback_lang_combo.currentIndex()
        if idx_fb >= 0 and self.fallback_lang_combo.currentText() == self.fallback_lang_combo.itemText(idx_fb):
            fallback_val = self.fallback_lang_combo.itemData(idx_fb)
        if not fallback_val:
            fallback_val = self.fallback_lang_combo.currentText().strip().lower()
        if "(" in fallback_val and ")" in fallback_val:
            m = re.search(r'\(([^)]+)\)', fallback_val)
            if m:
                fallback_val = m.group(1).strip().lower()
        if not fallback_val:
            fallback_val = "en"

        new_hotkey = self.hotkey_edit.text().strip().lower()
        hotkey_error = validate_hotkey(new_hotkey)
        if hotkey_error:
            self._status(
                f"Сочетание «{new_hotkey}» непонятно: {hotkey_error}", error=True
            )
            return
        hotkey_enabled = self.hotkey_enabled_cb.isChecked()
        diagnostics_on = self.diagnostics_cb.isChecked()

        theme_val = self.theme_combo.currentData() or "dark"
        font_size_val = self.font_size_combo.currentData() or "medium"
        opacity_val = round(self.opacity_slider.value() / 100.0, 2)
        max_cards_val = self.max_cards_spin.value()
        rem_pos = self.remember_pos_cb.isChecked()
        stays_top = self.stays_on_top_cb.isChecked()

        if not self.config.update({
            "standard_engine": engine,
            "source_lang": source_val,
            "target_lang": target_val,
            "fallback_target_lang": fallback_val,
            "deepl_api_key": self.deepl_key_edit.text().strip(),
            "hotkey": new_hotkey,
            "hotkey_enabled": hotkey_enabled,
            "diagnostics": diagnostics_on,
            "theme": theme_val,
            "font_size": font_size_val,
            "popup_opacity": opacity_val,
            "popup_max_cards": max_cards_val,
            "popup_remember_position": rem_pos,
            "popup_stays_on_top": stays_top,
        }):
            self._status(
                "Не удалось записать config.json — настройки не сохранены.",
                error=True,
            )
            return

        # Хоткей применяем СРАЗУ (если менеджер есть) — без перезапуска.
        if self.hotkey_manager is not None:
            applied = self.hotkey_manager.set_enabled(hotkey_enabled)
            self.hotkey_changed.emit(new_hotkey)
            if hotkey_enabled and new_hotkey and not applied:
                self._status(
                    f"Сочетание «{new_hotkey}» не зарегистрировалось — "
                    "возможно, его перехватила другая программа. "
                    "Проверьте сочетание и сохраните снова.",
                    error=True,
                )
                self._dirty = False
                return
        self._dirty = False
        if not hotkey_enabled:
            self._status("Сохранено. Глобальный хоткей отключён.")
        elif not new_hotkey:
            self._status("Сохранено. Хоткей не задан — захват по хоткею отключён.")
        elif self.hotkey_manager is None:
            self._status("Сохранено. Хоткей применится после перезапуска.")
        else:
            self._status(f"Сохранено. Хоткей «{new_hotkey}» уже активен.")

    def _load_models(self) -> None:
        """Кнопка «Загрузить список моделей»: опрашивает сервер в фоне."""
        api_url = self.api_url_edit.text().strip()
        if not api_url:
            self._status("Сначала укажите адрес API.", error=True)
            return

        ptype = self.provider_combo.currentData() or "custom"
        api_key = self.api_key_edit.text().strip()
        proxy = self.proxy_edit.text().strip()

        self.load_models_btn.setEnabled(False)
        self._status("Запрашиваю список моделей с сервера…")

        if self._model_worker is not None and self._model_worker.isRunning():
            if hasattr(self._model_worker, "cancel"):
                self._model_worker.cancel()
            self._model_worker.wait(1000)

        self._model_worker = ModelListWorker(
            base_url=api_url,
            api_key=api_key,
            provider_type=ptype,
            proxy=proxy,
        )
        self._model_worker.models_loaded.connect(self._on_models_loaded)
        self._model_worker.failed.connect(self._on_models_failed)
        self._model_worker.start()

    def _on_models_loaded(self, names: list) -> None:
        """Список моделей получен — заполняем выпадающий список."""
        self.load_models_btn.setEnabled(True)
        current = self.model_combo.currentText().strip()
        if current and current not in names:
            names = [current] + names  # не теряем вручную введённую модель
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        self.model_combo.addItems(names)
        if current in names:
            self.model_combo.setCurrentText(current)
        elif names:
            self.model_combo.setCurrentIndex(0)
        self.model_combo.blockSignals(False)
        self._status(f"Загружено моделей: {len(names)} — выберите нужную в списке.")

    def _on_models_failed(self, message: str) -> None:
        self.load_models_btn.setEnabled(True)
        self._status(message, error=True)

    def _status(self, message: str, error: bool = False) -> None:
        """Короткое сообщение в строке состояния (4 секунды)."""
        prefix = "[!] " if error else ""
        self.statusBar().showMessage(prefix + message, 4000)

    def showEvent(self, event: QShowEvent) -> None:
        """Тема заголовка окна сразу после показа (Windows 10/11) и курсоры."""
        super().showEvent(event)
        th = getattr(self.config, "theme", "dark")
        is_dark = (th != "light") if th != "system" else (detect_system_theme() != "light")
        apply_title_bar_theme(self, dark=is_dark)
        self._apply_interactive_cursors()

    # =========================================================================
    # ВКЛАДКА 3: «История операций» (ЭТАП 7)
    # =========================================================================
    def open_history_tab(self) -> None:
        """Переключает окно настроек на вкладку истории и обновляет данные."""
        self.tabs.setCurrentIndex(2)
        self._refresh_history_tab()
        self.show()
        self.raise_()
        self.activateWindow()

    def _build_history_tab(self) -> QWidget:
        """Строит интерфейс вкладки постоянной истории (SQLite)."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        # --- 1. Верхняя панель: управление базой данных и хранением ----------
        top_box = QFrame()
        top_box.setObjectName("SectionBox")
        top_box_layout = QVBoxLayout(top_box)
        top_box_layout.setContentsMargins(12, 10, 12, 10)
        top_box_layout.setSpacing(8)

        # Строка 1: Параметры ведения истории
        row_settings = QHBoxLayout()
        row_settings.setSpacing(10)

        self.history_enabled_cb = QCheckBox("Вести историю операций")
        self.history_enabled_cb.setCursor(Qt.CursorShape.PointingHandCursor)
        self.history_enabled_cb.setChecked(self.config.is_history_enabled())
        self.history_enabled_cb.toggled.connect(self._on_history_enabled_toggled)
        row_settings.addWidget(self.history_enabled_cb)

        retention_lbl = QLabel("Срок хранения:")
        retention_lbl.setObjectName("FieldLabel")
        row_settings.addWidget(retention_lbl)

        self.history_retention_combo = QComboBox()
        self.history_retention_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        retention_options = [
            ("Бессрочно", 0),
            ("7 дней", 7),
            ("30 дней", 30),
            ("90 дней", 90),
            ("180 дней", 180),
            ("1 год (365 дней)", 365),
        ]
        curr_days = self.config.get_history_retention_days()
        sel_idx = 0
        for idx, (label, days) in enumerate(retention_options):
            self.history_retention_combo.addItem(label, days)
            if days == curr_days:
                sel_idx = idx
        self.history_retention_combo.setCurrentIndex(sel_idx)
        self.history_retention_combo.currentIndexChanged.connect(self._on_history_retention_changed)
        row_settings.addWidget(self.history_retention_combo)

        row_settings.addStretch(1)

        # Строка 2: Действия с базой данных
        row_actions = QHBoxLayout()
        row_actions.setSpacing(8)

        lbl_db_ops = QLabel("Операции с базой данных:")
        lbl_db_ops.setObjectName("FieldLabel")
        row_actions.addWidget(lbl_db_ops)

        row_actions.addStretch(1)

        self.btn_history_export = QPushButton("Экспорт...")
        self.btn_history_export.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_history_export.setToolTip("Экспортировать историю в TXT, JSON или CSV")
        self.btn_history_export.clicked.connect(self._show_export_menu)
        row_actions.addWidget(self.btn_history_export)

        self.btn_history_backup = QPushButton("Резервная копия БД")
        self.btn_history_backup.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_history_backup.setToolTip("Создать моментальную резервную копию базы данных history.db")
        self.btn_history_backup.clicked.connect(self._backup_history_db)
        row_actions.addWidget(self.btn_history_backup)

        self.btn_history_clear_period = QPushButton("За период...")
        self.btn_history_clear_period.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_history_clear_period.setToolTip("Удалить записи старше выбранного периода")
        self.btn_history_clear_period.clicked.connect(self._clear_history_period_dialog)
        row_actions.addWidget(self.btn_history_clear_period)

        self.btn_history_clear_all = QPushButton("Очистить всё")
        self.btn_history_clear_all.setObjectName("DangerBtn")
        self.btn_history_clear_all.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_history_clear_all.setToolTip("Полная очистка базы данных истории")
        self.btn_history_clear_all.clicked.connect(self._clear_all_history_dialog)
        row_actions.addWidget(self.btn_history_clear_all)

        top_box_layout.addLayout(row_settings)
        top_box_layout.addLayout(row_actions)

        layout.addWidget(top_box)

        # --- 2. Панель поиска и фильтрации -----------------------------------
        filter_box = QFrame()
        filter_box.setObjectName("SectionBox")
        filter_layout = QVBoxLayout(filter_box)
        filter_layout.setContentsMargins(12, 10, 12, 10)
        filter_layout.setSpacing(8)

        # Строка 1: Поисковая строка и кнопки действий
        row1 = QHBoxLayout()
        row1.setSpacing(8)

        self.hist_search_edit = QLineEdit()
        self.hist_search_edit.setPlaceholderText("Поиск по тексту оригинала, результату или контексту проекта...")
        self.hist_search_edit.setClearButtonEnabled(True)
        self.hist_search_edit.returnPressed.connect(self._apply_history_filters)
        row1.addWidget(self.hist_search_edit, stretch=1)

        self.btn_hist_search = QPushButton("Найти")
        self.btn_hist_search.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_hist_search.clicked.connect(self._apply_history_filters)
        row1.addWidget(self.btn_hist_search)

        self.btn_hist_fav = QPushButton("Только избранное")
        self.btn_hist_fav.setCheckable(True)
        self.btn_hist_fav.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_hist_fav.toggled.connect(self._apply_history_filters)
        row1.addWidget(self.btn_hist_fav)

        self.btn_hist_refresh = QPushButton("Обновить")
        self.btn_hist_refresh.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_hist_refresh.clicked.connect(self._refresh_history_tab)
        row1.addWidget(self.btn_hist_refresh)

        self.btn_hist_reset = QPushButton("Сбросить")
        self.btn_hist_reset.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_hist_reset.clicked.connect(self._reset_history_filters)
        row1.addWidget(self.btn_hist_reset)

        filter_layout.addLayout(row1)

        # Строка 2: Фильтры (период, действие, модель, проект) с равномерным распределением
        row2 = QHBoxLayout()
        row2.setSpacing(8)

        lbl_date = QLabel("Период:")
        lbl_date.setObjectName("FieldLabel")
        row2.addWidget(lbl_date)

        self.hist_date_combo = QComboBox()
        self.hist_date_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        self.hist_date_combo.addItems([
            "Все даты",
            "Сегодня",
            "Вчера",
            "Последние 7 дней",
            "Последние 30 дней",
            "Выбрать диапазон...",
        ])
        self.hist_date_combo.currentIndexChanged.connect(self._on_date_filter_changed)
        row2.addWidget(self.hist_date_combo, stretch=1)

        lbl_act = QLabel("Действие:")
        lbl_act.setObjectName("FieldLabel")
        row2.addWidget(lbl_act)

        self.hist_action_combo = QComboBox()
        self.hist_action_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        self.hist_action_combo.addItem("Все действия", "all")
        self.hist_action_combo.currentIndexChanged.connect(self._apply_history_filters)
        row2.addWidget(self.hist_action_combo, stretch=1)

        lbl_model = QLabel("Модель:")
        lbl_model.setObjectName("FieldLabel")
        row2.addWidget(lbl_model)

        self.hist_model_combo = QComboBox()
        self.hist_model_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        self.hist_model_combo.addItem("Все модели", "all")
        self.hist_model_combo.currentIndexChanged.connect(self._apply_history_filters)
        row2.addWidget(self.hist_model_combo, stretch=1)

        lbl_proj = QLabel("Проект:")
        lbl_proj.setObjectName("FieldLabel")
        row2.addWidget(lbl_proj)

        self.hist_project_combo = QComboBox()
        self.hist_project_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        self.hist_project_combo.addItem("Все проекты", "all")
        self.hist_project_combo.currentIndexChanged.connect(self._apply_history_filters)
        row2.addWidget(self.hist_project_combo, stretch=1)

        filter_layout.addLayout(row2)

        # Строка 3: Подпанель произвольного диапазона дат (скрыта по умолчанию)
        self.hist_custom_date_bar = QWidget()
        custom_date_lay = QHBoxLayout(self.hist_custom_date_bar)
        custom_date_lay.setContentsMargins(0, 4, 0, 0)
        custom_date_lay.setSpacing(8)

        lbl_range_hint = QLabel("Диапазон дат — с:")
        lbl_range_hint.setObjectName("FieldLabel")
        custom_date_lay.addWidget(lbl_range_hint)

        self.hist_date_from = QDateEdit(QDate.currentDate().addDays(-7))
        self.hist_date_from.setCalendarPopup(True)
        self.hist_date_from.setDisplayFormat("yyyy-MM-dd")
        self.hist_date_from.dateChanged.connect(self._apply_history_filters)
        custom_date_lay.addWidget(self.hist_date_from)

        lbl_to = QLabel("по:")
        lbl_to.setObjectName("FieldLabel")
        custom_date_lay.addWidget(lbl_to)

        self.hist_date_to = QDateEdit(QDate.currentDate())
        self.hist_date_to.setCalendarPopup(True)
        self.hist_date_to.setDisplayFormat("yyyy-MM-dd")
        self.hist_date_to.dateChanged.connect(self._apply_history_filters)
        custom_date_lay.addWidget(self.hist_date_to)

        custom_date_lay.addStretch(1)
        self.hist_custom_date_bar.hide()
        filter_layout.addWidget(self.hist_custom_date_bar)

        layout.addWidget(filter_box)

        # --- 3. Центральная часть: Сплиттер (Таблица + Панель деталей) --------
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setHandleWidth(5)
        splitter.setChildrenCollapsible(False)

        # 3.1. Таблица записей
        self.history_table = QTableWidget()
        self.history_table.setObjectName("HistoryTable")
        self.history_table.setColumnCount(8)
        self.history_table.setHorizontalHeaderLabels([
            "ID", "Избр.", "Дата/Время", "Действие", "Направление", "Модель", "Оригинал", "Результат"
        ])
        self.history_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.history_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.history_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.history_table.verticalHeader().setVisible(False)
        self.history_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.history_table.customContextMenuRequested.connect(self._show_history_context_menu)
        self.history_table.itemSelectionChanged.connect(self._on_history_selection_changed)
        self.history_table.cellDoubleClicked.connect(self._on_history_double_clicked)

        # Настройка ширин колонок
        self.history_table.setColumnHidden(0, True)  # ID скрыт
        self.history_table.setColumnWidth(1, 45)     # Избранное
        self.history_table.setColumnWidth(2, 120)    # Дата
        self.history_table.setColumnWidth(3, 140)    # Действие
        self.history_table.setColumnWidth(4, 90)     # Направление
        self.history_table.setColumnWidth(5, 120)    # Модель
        header = self.history_table.horizontalHeader()
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)  # Оригинал
        header.setSectionResizeMode(7, QHeaderView.ResizeMode.Stretch)  # Результат

        splitter.addWidget(self.history_table)

        # 3.2. Панель детального просмотра и действий
        detail_panel = QFrame()
        detail_panel.setObjectName("HistoryDetailPanel")
        detail_layout = QVBoxLayout(detail_panel)
        detail_layout.setContentsMargins(12, 10, 12, 10)
        detail_layout.setSpacing(8)

        # Шапка панели деталей
        det_head = QHBoxLayout()
        det_head.setSpacing(8)
        self.hist_detail_title = QLabel("Выберите запись для просмотра")
        self.hist_detail_title.setObjectName("HistoryDetailTitle")
        det_head.addWidget(self.hist_detail_title)

        self.hist_detail_badges = QHBoxLayout()
        self.hist_detail_badges.setSpacing(6)
        det_head.addLayout(self.hist_detail_badges)

        det_head.addStretch(1)

        self.btn_detail_open_card = QPushButton("В мини-окно")
        self.btn_detail_open_card.setObjectName("AccentBtn")
        self.btn_detail_open_card.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_detail_open_card.setToolTip("Открыть этот результат в плавающем мини-окне")
        self.btn_detail_open_card.setEnabled(False)
        self.btn_detail_open_card.clicked.connect(self._on_history_open_card_clicked)
        det_head.addWidget(self.btn_detail_open_card)

        self.btn_detail_repeat = QPushButton("Повторить")
        self.btn_detail_repeat.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_detail_repeat.setToolTip("Запустить повторный перевод с этими же параметрами")
        self.btn_detail_repeat.setEnabled(False)
        self.btn_detail_repeat.clicked.connect(self._on_history_repeat_clicked)
        det_head.addWidget(self.btn_detail_repeat)

        self.btn_detail_fav = QPushButton("В избранное")
        self.btn_detail_fav.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_detail_fav.setEnabled(False)
        self.btn_detail_fav.clicked.connect(lambda: self._toggle_star_selected())
        det_head.addWidget(self.btn_detail_fav)

        self.btn_detail_delete = QPushButton("Удалить")
        self.btn_detail_delete.setObjectName("DangerBtn")
        self.btn_detail_delete.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_detail_delete.setEnabled(False)
        self.btn_detail_delete.clicked.connect(self._on_history_delete_clicked)
        det_head.addWidget(self.btn_detail_delete)

        detail_layout.addLayout(det_head)

        # Текстовые поля: исходный текст и результат side-by-side
        texts_layout = QHBoxLayout()
        texts_layout.setSpacing(10)

        # Исходник
        src_box = QVBoxLayout()
        src_head = QHBoxLayout()
        src_lbl = QLabel("Исходный текст:")
        src_lbl.setObjectName("FieldLabel")
        src_head.addWidget(src_lbl)
        src_head.addStretch(1)
        self.btn_copy_source = QPushButton("Скопировать")
        self.btn_copy_source.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_copy_source.clicked.connect(self._on_copy_detail_source)
        src_head.addWidget(self.btn_copy_source)
        src_box.addLayout(src_head)

        self.hist_detail_source = QPlainTextEdit()
        self.hist_detail_source.setObjectName("HistoryDetailEdit")
        self.hist_detail_source.setReadOnly(True)
        self.hist_detail_source.setPlaceholderText("Исходный текст появится здесь...")
        src_box.addWidget(self.hist_detail_source)
        texts_layout.addLayout(src_box, stretch=1)

        # Результат
        res_box = QVBoxLayout()
        res_head = QHBoxLayout()
        res_lbl = QLabel("Результат:")
        res_lbl.setObjectName("FieldLabel")
        res_head.addWidget(res_lbl)
        res_head.addStretch(1)

        self.btn_save_detail_edit = QPushButton("Сохранить правку")
        self.btn_save_detail_edit.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_save_detail_edit.setToolTip("Сохранить отредактированный текст в базе данных")
        self.btn_save_detail_edit.clicked.connect(self._on_save_detail_result_clicked)
        res_head.addWidget(self.btn_save_detail_edit)

        self.btn_copy_result = QPushButton("Скопировать")
        self.btn_copy_result.setObjectName("AccentBtn")
        self.btn_copy_result.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_copy_result.clicked.connect(self._on_copy_detail_result)
        res_head.addWidget(self.btn_copy_result)
        res_box.addLayout(res_head)

        self.hist_detail_result = QPlainTextEdit()
        self.hist_detail_result.setObjectName("HistoryDetailEdit")
        self.hist_detail_result.setPlaceholderText("Результат операции появится здесь (вы можете отредактировать его и сохранить)...")
        res_box.addWidget(self.hist_detail_result)
        texts_layout.addLayout(res_box, stretch=1)

        detail_layout.addLayout(texts_layout)

        # Метаданные (промпт, провайдер)
        self.hist_detail_meta = QLabel("")
        self.hist_detail_meta.setObjectName("FieldHint")
        self.hist_detail_meta.setWordWrap(True)
        detail_layout.addWidget(self.hist_detail_meta)

        splitter.addWidget(detail_panel)
        splitter.setSizes([320, 220])
        layout.addWidget(splitter, stretch=1)

        # --- 4. Нижняя панель: Пагинация -------------------------------------
        nav_box = QHBoxLayout()
        nav_box.setSpacing(10)

        self.hist_pagination_label = QLabel("Всего: 0 записей | Страница 1 из 1")
        self.hist_pagination_label.setObjectName("FieldHint")
        nav_box.addWidget(self.hist_pagination_label)

        nav_box.addStretch(1)

        self.btn_hist_prev = QPushButton("Назад")
        self.btn_hist_prev.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_hist_prev.clicked.connect(self._on_hist_prev_page)
        nav_box.addWidget(self.btn_hist_prev)

        self.hist_page_label = QLabel("1")
        self.hist_page_label.setObjectName("FieldLabel")
        nav_box.addWidget(self.hist_page_label)

        self.btn_hist_next = QPushButton("Вперёд")
        self.btn_hist_next.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_hist_next.clicked.connect(self._on_hist_next_page)
        nav_box.addWidget(self.btn_hist_next)

        lbl_ps = QLabel("Записей на стр.:")
        lbl_ps.setObjectName("FieldHint")
        nav_box.addWidget(lbl_ps)

        self.hist_page_size_combo = QComboBox()
        self.hist_page_size_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        self.hist_page_size_combo.addItems(["25", "50", "100"])
        self.hist_page_size_combo.setCurrentText("50")
        self.hist_page_size_combo.currentTextChanged.connect(self._on_hist_page_size_changed)
        nav_box.addWidget(self.hist_page_size_combo)

        layout.addLayout(nav_box)

        # Первичная загрузка списка и фильтров
        self._populate_history_filter_combos()
        self._load_history_page(page=1)

        return tab

    # -------------------------------------------------------------------------
    # Обработчики вкладки «История»
    # -------------------------------------------------------------------------
    def _on_history_enabled_toggled(self, checked: bool) -> None:
        """Включение/отключение записи новых операций в историю."""
        if hasattr(self.config, "set_history_enabled"):
            self.config.set_history_enabled(checked)
        else:
            self.config.set("history_enabled", checked)
            self.config.save()
        status_msg = "История операций включена." if checked else "История операций отключена (новые записи не сохраняются)."
        self.statusBar().showMessage(status_msg, 4000)

    def _on_history_retention_changed(self, index: int) -> None:
        """Смена срока хранения записей."""
        days = self.history_retention_combo.currentData()
        if days is None:
            return
        if hasattr(self.config, "set_history_retention_days"):
            self.config.set_history_retention_days(days)
        else:
            self.config.set("history_retention_days", days)
            self.config.save()

        if days > 0:
            hm = get_history_manager()
            cleaned = hm.apply_retention_policy(days)
            if cleaned > 0:
                self.statusBar().showMessage(f"Срок хранения: {days} дн. Очищено устаревших записей: {cleaned}.", 4000)
                self._load_history_page(self._history_page)
                return
        self.statusBar().showMessage("Настройки срока хранения сохранены.", 3000)

    def _on_date_filter_changed(self, index: int) -> None:
        """Переключение фильтра даты (показ или скрытие диапазона)."""
        is_custom = (index == 5)  # "Выбрать диапазон..."
        if hasattr(self, "hist_custom_date_bar"):
            self.hist_custom_date_bar.setVisible(is_custom)
        self.hist_date_from.setVisible(is_custom)
        self.hist_date_to.setVisible(is_custom)
        self._apply_history_filters()

    def _reset_history_filters(self) -> None:
        """Сброс всех фильтров и поиска к начальным значениям."""
        self.hist_search_edit.blockSignals(True)
        self.hist_search_edit.clear()
        self.hist_search_edit.blockSignals(False)

        self.btn_hist_fav.blockSignals(True)
        self.btn_hist_fav.setChecked(False)
        self.btn_hist_fav.blockSignals(False)

        self.hist_date_combo.blockSignals(True)
        self.hist_date_combo.setCurrentIndex(0)
        self.hist_date_from.hide()
        self.hist_date_to.hide()
        self.hist_date_combo.blockSignals(False)

        self.hist_action_combo.blockSignals(True)
        self.hist_action_combo.setCurrentIndex(0)
        self.hist_action_combo.blockSignals(False)

        self.hist_model_combo.blockSignals(True)
        self.hist_model_combo.setCurrentIndex(0)
        self.hist_model_combo.blockSignals(False)

        self.hist_project_combo.blockSignals(True)
        self.hist_project_combo.setCurrentIndex(0)
        self.hist_project_combo.blockSignals(False)

        self._load_history_page(page=1)

    def _refresh_history_tab(self) -> None:
        """Обновление фильтров и текущей страницы."""
        self._populate_history_filter_combos()
        self._load_history_page(self._history_page)

    def _populate_history_filter_combos(self) -> None:
        """Заполнение выпадающих списков фильтров уникальными значениями из БД."""
        hm = get_history_manager()
        opts = hm.get_filter_options()

        # 1. Действия
        curr_act = self.hist_action_combo.currentData() or "all"
        self.hist_action_combo.blockSignals(True)
        self.hist_action_combo.clear()
        self.hist_action_combo.addItem("Все действия", "all")
        for a in opts.get("actions", []):
            self.hist_action_combo.addItem(a["name"], a["id"])
        # Восстанавливаем выбор
        idx = self.hist_action_combo.findData(curr_act)
        if idx >= 0:
            self.hist_action_combo.setCurrentIndex(idx)
        self.hist_action_combo.blockSignals(False)

        # 2. Модели
        curr_mod = self.hist_model_combo.currentData() or "all"
        self.hist_model_combo.blockSignals(True)
        self.hist_model_combo.clear()
        self.hist_model_combo.addItem("Все модели", "all")
        for m in opts.get("models", []):
            self.hist_model_combo.addItem(m, m)
        idx = self.hist_model_combo.findData(curr_mod)
        if idx >= 0:
            self.hist_model_combo.setCurrentIndex(idx)
        self.hist_model_combo.blockSignals(False)

        # 3. Проекты
        curr_proj = self.hist_project_combo.currentData() or "all"
        self.hist_project_combo.blockSignals(True)
        self.hist_project_combo.clear()
        self.hist_project_combo.addItem("Все проекты", "all")
        for p in opts.get("projects", []):
            self.hist_project_combo.addItem(p, p)
        idx = self.hist_project_combo.findData(curr_proj)
        if idx >= 0:
            self.hist_project_combo.setCurrentIndex(idx)
        self.hist_project_combo.blockSignals(False)

    def _apply_history_filters(self) -> None:
        """Применение фильтров и переход на 1-ю страницу."""
        self._load_history_page(page=1)

    def _get_filter_params(self) -> Dict[str, Any]:
        """Собирает текущие параметры фильтрации для запроса к SQLite."""
        search_text = self.hist_search_edit.text().strip() or None
        is_fav = True if self.btn_hist_fav.isChecked() else None

        date_from = None
        date_to = None
        date_mode = self.hist_date_combo.currentIndex()
        today = QDate.currentDate()

        if date_mode == 1:  # Сегодня
            date_from = today.toString("yyyy-MM-dd")
            date_to = today.toString("yyyy-MM-dd")
        elif date_mode == 2:  # Вчера
            yst = today.addDays(-1).toString("yyyy-MM-dd")
            date_from = yst
            date_to = yst
        elif date_mode == 3:  # 7 дней
            date_from = today.addDays(-7).toString("yyyy-MM-dd")
            date_to = today.toString("yyyy-MM-dd")
        elif date_mode == 4:  # 30 дней
            date_from = today.addDays(-30).toString("yyyy-MM-dd")
            date_to = today.toString("yyyy-MM-dd")
        elif date_mode == 5:  # Диапазон
            date_from = self.hist_date_from.date().toString("yyyy-MM-dd")
            date_to = self.hist_date_to.date().toString("yyyy-MM-dd")

        action_id = self.hist_action_combo.currentData()
        model_name = self.hist_model_combo.currentData()
        project_context = self.hist_project_combo.currentData()

        return {
            "search_text": search_text,
            "date_from": date_from,
            "date_to": date_to,
            "action_id": action_id,
            "model_name": model_name,
            "project_context": project_context,
            "is_favorite": is_fav,
        }

    def _load_history_page(self, page: int = 1) -> None:
        """Загрузка страницы данных из SQLite (Этап 7.4 Производительность)."""
        hm = get_history_manager()
        params = self._get_filter_params()
        limit = self._history_page_size
        offset = max(page - 1, 0) * limit

        records, total_count = hm.list_records(
            limit=limit,
            offset=offset,
            search_text=params["search_text"],
            date_from=params["date_from"],
            date_to=params["date_to"],
            action_id=params["action_id"],
            model_name=params["model_name"],
            project_context=params["project_context"],
            is_favorite=params["is_favorite"],
        )

        self._history_page = page
        self._history_total_count = total_count
        self._history_records = records

        # Заполняем таблицу
        self.history_table.setRowCount(len(records))
        for row, rec in enumerate(records):
            rec_id = rec["id"]
            is_fav = bool(rec.get("is_favorite"))

            # 0: ID (скрыт)
            self.history_table.setItem(row, 0, QTableWidgetItem(str(rec_id)))

            # 1: Кнопка избранного
            star_btn = QPushButton("[+]" if is_fav else "[ ]")
            star_btn.setObjectName("StarBtnActive" if is_fav else "StarBtn")
            star_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            star_btn.setToolTip("Убрать из избранного" if is_fav else "Добавить в избранное")
            star_btn.clicked.connect(lambda checked=False, rid=rec_id: self._toggle_star(rid))
            self.history_table.setCellWidget(row, 1, star_btn)

            # 2: Дата
            dt = str(rec.get("created_at", ""))
            dt_short = dt[5:16] if len(dt) >= 16 else dt
            item_dt = QTableWidgetItem(dt_short)
            item_dt.setToolTip(dt)
            self.history_table.setItem(row, 2, item_dt)

            # 3: Действие
            act_name = rec.get("action_name") or rec.get("action_id") or "Перевод"
            self.history_table.setItem(row, 3, QTableWidgetItem(act_name))

            # 4: Направление
            dir_text = rec.get("direction") or f"{rec.get('source_lang', '')} → {rec.get('target_lang', '')}"
            self.history_table.setItem(row, 4, QTableWidgetItem(dir_text))

            # 5: Модель
            mod_text = rec.get("model_name") or rec.get("provider_type") or "—"
            self.history_table.setItem(row, 5, QTableWidgetItem(mod_text))

            # 6: Исходный текст (однострочный превью)
            src_prev = str(rec.get("source_text", "")).replace("\n", " ").strip()
            item_src = QTableWidgetItem(src_prev)
            item_src.setToolTip(rec.get("source_text", ""))
            self.history_table.setItem(row, 6, item_src)

            # 7: Результат (однострочный превью)
            res_prev = str(rec.get("result_text", "")).replace("\n", " ").strip()
            item_res = QTableWidgetItem(res_prev)
            item_res.setToolTip(rec.get("result_text", ""))
            self.history_table.setItem(row, 7, item_res)

        # Обновляем навигацию
        total_pages = max((total_count + limit - 1) // limit, 1)
        self.hist_pagination_label.setText(f"Всего записей: {total_count} | Страница {page} из {total_pages}")
        self.hist_page_label.setText(str(page))
        self.btn_hist_prev.setEnabled(page > 1)
        self.btn_hist_next.setEnabled(page < total_pages)

        # Выбираем первую строку или очищаем детали
        if records:
            self.history_table.selectRow(0)
        else:
            self._display_record_details(None)

    def _on_hist_prev_page(self) -> None:
        """Переход на предыдущую страницу."""
        if self._history_page > 1:
            self._load_history_page(self._history_page - 1)

    def _on_hist_next_page(self) -> None:
        """Переход на следующую страницу."""
        limit = self._history_page_size
        total_pages = max((self._history_total_count + limit - 1) // limit, 1)
        if self._history_page < total_pages:
            self._load_history_page(self._history_page + 1)

    def _on_hist_page_size_changed(self, text: str) -> None:
        """Изменение размера страницы (25/50/100)."""
        try:
            self._history_page_size = max(int(text), 10)
            self._load_history_page(page=1)
        except Exception:
            pass

    def _on_history_selection_changed(self) -> None:
        """Выбор строки в таблице истории."""
        selected = self.history_table.selectedItems()
        if not selected:
            self._display_record_details(None)
            return
        row = selected[0].row()
        if 0 <= row < len(self._history_records):
            record = self._history_records[row]
            self._display_record_details(record)

    def _on_history_double_clicked(self, row: int, col: int) -> None:
        """Двойной клик по строке: быстрое открытие карточки в мини-окне."""
        if 0 <= row < len(self._history_records):
            self._history_selected_record = self._history_records[row]
            self._on_history_open_card_clicked()

    def _show_history_context_menu(self, pos) -> None:
        """Контекстное меню правой кнопки мыши по таблице истории."""
        item = self.history_table.itemAt(pos)
        if not item:
            return
        row = item.row()
        if not (0 <= row < len(self._history_records)):
            return
        rec = self._history_records[row]

        menu = QMenu(self)
        a_open = menu.addAction("Открыть в мини-окне")
        a_repeat = menu.addAction("Повторить запрос")
        menu.addSeparator()
        is_fav = bool(rec.get("is_favorite"))
        a_fav = menu.addAction("Убрать из избранного" if is_fav else "Добавить в избранное")
        a_copy_res = menu.addAction("Скопировать результат")
        a_copy_src = menu.addAction("Скопировать исходник")
        menu.addSeparator()
        a_del = menu.addAction("Удалить запись")

        action = menu.exec(self.history_table.viewport().mapToGlobal(pos))
        if action == a_open:
            self.open_card_requested.emit(rec)
        elif action == a_repeat:
            self.repeat_request_requested.emit(rec)
        elif action == a_fav:
            self._toggle_star(rec["id"])
        elif action == a_copy_res:
            import pyperclip
            pyperclip.copy(rec.get("result_text", ""))
            self.statusBar().showMessage("Результат скопирован в буфер обмена.", 2000)
        elif action == a_copy_src:
            import pyperclip
            pyperclip.copy(rec.get("source_text", ""))
            self.statusBar().showMessage("Исходный текст скопирован в буфер обмена.", 2000)
        elif action == a_del:
            self._delete_record_by_id(rec["id"])

    def _display_record_details(self, record: Optional[Dict[str, Any]]) -> None:
        """Отображение подробной информации о выбранной записи в нижней панели."""
        self._history_selected_record = record

        # Очищаем бейджи
        while self.hist_detail_badges.count() > 0:
            item = self.hist_detail_badges.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        if not record:
            self.hist_detail_title.setText("Выберите запись для просмотра")
            self.hist_detail_source.setPlainText("")
            self.hist_detail_result.setPlainText("")
            self.hist_detail_meta.setText("")
            self.btn_detail_open_card.setEnabled(False)
            self.btn_detail_repeat.setEnabled(False)
            self.btn_detail_fav.setEnabled(False)
            self.btn_detail_delete.setEnabled(False)
            self.btn_copy_source.setEnabled(False)
            self.btn_copy_result.setEnabled(False)
            self.btn_save_detail_edit.setEnabled(False)
            return

        rec_id = record.get("id")
        created = str(record.get("created_at") or "")
        self.hist_detail_title.setText(f"Запись #{rec_id} — {created}")

        # Добавляем бейджи
        dir_text = str(record.get("direction") or f"{record.get('source_lang') or ''} → {record.get('target_lang') or ''}")
        badge_dir = QLabel(dir_text)
        badge_dir.setObjectName("HistoryBadge")
        self.hist_detail_badges.addWidget(badge_dir)

        act_name = str(record.get("action_name") or record.get("action_id") or "Перевод")
        badge_act = QLabel(f"{act_name}")
        badge_act.setObjectName("HistoryBadge")
        self.hist_detail_badges.addWidget(badge_act)

        model_name = str(record.get("model_name") or record.get("provider_type") or "")
        if model_name:
            badge_mod = QLabel(f"{model_name}")
            badge_mod.setObjectName("HistoryBadge")
            self.hist_detail_badges.addWidget(badge_mod)

        proj = str(record.get("project_context") or "")
        if proj:
            badge_proj = QLabel(f"{proj}")
            badge_proj.setObjectName("HistoryBadge")
            self.hist_detail_badges.addWidget(badge_proj)

        if record.get("is_edited"):
            badge_ed = QLabel("изменено")
            badge_ed.setObjectName("HistoryBadge")
            self.hist_detail_badges.addWidget(badge_ed)

        # Тексты
        self.hist_detail_source.setPlainText(str(record.get("source_text") or ""))
        self.hist_detail_result.setPlainText(str(record.get("result_text") or ""))

        prompt_info = str(record.get("prompt_text") or "").strip()
        if prompt_info:
            p_snippet = prompt_info[:120] + "..." if len(prompt_info) > 120 else prompt_info
            self.hist_detail_meta.setText(f"Использованный промпт: {p_snippet}")
        else:
            self.hist_detail_meta.setText("")

        # Кнопки
        self.btn_detail_open_card.setEnabled(True)
        self.btn_detail_repeat.setEnabled(True)
        self.btn_detail_fav.setEnabled(True)
        is_fav = bool(record.get("is_favorite"))
        self.btn_detail_fav.setText("В избранном" if is_fav else "В избранное")
        self.btn_detail_delete.setEnabled(True)
        self.btn_copy_source.setEnabled(True)
        self.btn_copy_result.setEnabled(True)
        self.btn_save_detail_edit.setEnabled(True)

    def _toggle_star(self, record_id: int) -> None:
        """Переключение избранного по ID записи."""
        hm = get_history_manager()
        new_state = hm.toggle_favorite(record_id)
        # Обновляем в текущем списке
        for r in self._history_records:
            if r["id"] == record_id:
                r["is_favorite"] = 1 if new_state else 0
                break
        # Обновляем ячейку в таблице
        for row in range(self.history_table.rowCount()):
            item_id = self.history_table.item(row, 0)
            if item_id and item_id.text() == str(record_id):
                btn = self.history_table.cellWidget(row, 1)
                if isinstance(btn, QPushButton):
                    btn.setText("[+]" if new_state else "[ ]")
                    btn.setObjectName("StarBtnActive" if new_state else "StarBtn")
                    from styles import repolish
                    repolish(btn)
                break
        if self._history_selected_record and self._history_selected_record.get("id") == record_id:
            self._history_selected_record["is_favorite"] = 1 if new_state else 0
            self.btn_detail_fav.setText("В избранном" if new_state else "В избранное")

    def _toggle_star_selected(self) -> None:
        """Переключение избранного для выбранной записи."""
        if self._history_selected_record:
            self._toggle_star(self._history_selected_record["id"])

    def _on_history_open_card_clicked(self) -> None:
        """Открытие выбранной карточки в мини-окне."""
        if self._history_selected_record:
            self.open_card_requested.emit(self._history_selected_record)
            self.statusBar().showMessage("Карточка открыта в мини-окне.", 2000)

    def _on_history_repeat_clicked(self) -> None:
        """Повторный запрос для выбранной записи."""
        if self._history_selected_record:
            self.repeat_request_requested.emit(self._history_selected_record)
            self.statusBar().showMessage("Запущен повторный запрос...", 2000)

    def _on_save_detail_result_clicked(self) -> None:
        """Сохранение отредактированного результата записи в SQLite."""
        if not self._history_selected_record:
            return
        rec_id = self._history_selected_record["id"]
        new_text = self.hist_detail_result.toPlainText().strip()
        if not new_text:
            return
        hm = get_history_manager()
        hm.update_result_text(rec_id, new_text, is_edited=True)
        self._history_selected_record["result_text"] = new_text
        self._history_selected_record["is_edited"] = 1
        self._load_history_page(self._history_page)
        self.statusBar().showMessage("Правка успешно сохранена в истории.", 2500)

    def _on_copy_detail_source(self) -> None:
        """Копирование исходного текста выбранной записи."""
        if self._history_selected_record:
            import pyperclip
            pyperclip.copy(self.hist_detail_source.toPlainText())
            self.statusBar().showMessage("Исходный текст скопирован в буфер обмена.", 2000)

    def _on_copy_detail_result(self) -> None:
        """Копирование результата выбранной записи."""
        if self._history_selected_record:
            import pyperclip
            pyperclip.copy(self.hist_detail_result.toPlainText())
            self.statusBar().showMessage("Результат скопирован в буфер обмена.", 2000)

    def _delete_record_by_id(self, record_id: int) -> None:
        """Удаление записи с подтверждением."""
        ans = QMessageBox.question(
            self,
            "Удаление записи",
            f"Вы уверены, что хотите удалить запись #{record_id} из истории?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ans == QMessageBox.StandardButton.Yes:
            hm = get_history_manager()
            hm.delete_record(record_id)
            self.statusBar().showMessage(f"Запись #{record_id} удалена.", 2500)
            self._load_history_page(self._history_page)

    def _on_history_delete_clicked(self) -> None:
        """Удаление выбранной записи."""
        if self._history_selected_record:
            self._delete_record_by_id(self._history_selected_record["id"])

    def _clear_all_history_dialog(self) -> None:
        """Диалог полной очистки истории."""
        ans = QMessageBox.question(
            self,
            "Очистить всю историю",
            "Вы действительно хотите удалить ВСЮ историю операций?\n\n(Избранные записи будут сохранены).",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ans == QMessageBox.StandardButton.Yes:
            hm = get_history_manager()
            deleted = hm.clear_all(keep_favorites=True)
            self.statusBar().showMessage(f"История очищена. Удалено записей: {deleted}.", 4000)
            self._populate_history_filter_combos()
            self._load_history_page(page=1)

    def _clear_history_period_dialog(self) -> None:
        """Диалог очистки истории за период."""
        periods = [
            ("Старше 7 дней", 7),
            ("Старше 30 дней", 30),
            ("Старше 90 дней", 90),
            ("Старше 180 дней", 180),
        ]
        menu = QMenu(self)
        for label, days in periods:
            action = menu.addAction(label)
            action.triggered.connect(lambda checked=False, d=days, l=label: self._do_clear_older_than(d, l))
        menu.exec(QCursor.pos())

    def _do_clear_older_than(self, days: int, label: str) -> None:
        ans = QMessageBox.question(
            self,
            "Очистка за период",
            f"Удалить все записи {label.lower()}?\n(Избранные записи будут сохранены).",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ans == QMessageBox.StandardButton.Yes:
            hm = get_history_manager()
            deleted = hm.clear_older_than(days, keep_favorites=True)
            self.statusBar().showMessage(f"Очистка выполнена ({label}). Удалено записей: {deleted}.", 4000)
            self._populate_history_filter_combos()
            self._load_history_page(page=1)

    def _show_export_menu(self) -> None:
        """Меню выбора формата экспорта (TXT, JSON, CSV)."""
        menu = QMenu(self)
        a_txt = menu.addAction("Экспорт в TXT (текстовый файл)...")
        a_json = menu.addAction("Экспорт в JSON (структурированный)...")
        a_csv = menu.addAction("Экспорт в CSV (таблица Excel)...")

        action = menu.exec(QCursor.pos())
        if action == a_txt:
            self._export_history("txt")
        elif action == a_json:
            self._export_history("json")
        elif action == a_csv:
            self._export_history("csv")

    def _export_history(self, fmt: str) -> None:
        """Экспорт отфильтрованных данных в файл."""
        from datetime import datetime
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        ext_map = {"txt": "TXT файлы (*.txt)", "json": "JSON файлы (*.json)", "csv": "CSV файлы (*.csv)"}
        default_name = f"truniversal_history_{ts}.{fmt}"

        file_path, _ = QFileDialog.getSaveFileName(
            self, f"Экспорт истории в {fmt.upper()}", default_name, ext_map.get(fmt, "Все файлы (*.*)")
        )
        if not file_path:
            return

        hm = get_history_manager()
        params = self._get_filter_params()
        try:
            saved_path = hm.export_data(
                format_type=fmt,
                target_path=file_path,
                search_text=params["search_text"],
                date_from=params["date_from"],
                date_to=params["date_to"],
                action_id=params["action_id"],
                model_name=params["model_name"],
                project_context=params["project_context"],
                is_favorite=params["is_favorite"],
            )
            QMessageBox.information(
                self, "Экспорт завершён", f"История успешно экспортирована в файл:\n\n{saved_path}"
            )
        except Exception as exc:
            QMessageBox.critical(self, "Ошибка экспорта", f"Не удалось экспортировать данные:\n{exc}")

    def _backup_history_db(self) -> None:
        """Создание резервной копии базы данных SQLite."""
        from datetime import datetime
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"history_backup_{ts}.db"

        file_path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить резервную копию базы данных", default_name, "Базы данных SQLite (*.db *.sqlite)"
        )
        if not file_path:
            return

        hm = get_history_manager()
        try:
            saved_path = hm.backup_database(backup_path=file_path)
            size_kb = Path(saved_path).stat().st_size // 1024
            QMessageBox.information(
                self,
                "Резервная копия создана",
                f"Резервная копия базы данных успешно сохранена:\n\n{saved_path}\nРазмер: {size_kb} КБ",
            )
        except Exception as exc:
            QMessageBox.critical(
                self, "Ошибка резервного копирования", f"Не удалось создать резервную копию базы данных:\n{exc}"
            )

    # -------------------------------------------------------------------------
    # Закрытие и завершение
    # -------------------------------------------------------------------------
    def closeEvent(self, event: QCloseEvent) -> None:
        """Не теряем несохранённые правки: если «грязно» — спрашиваем."""
        if self._dirty:
            answer = QMessageBox.question(
                self,
                "Truniversal",
                "Есть несохранённые изменения. Закрыть окно без сохранения?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            # Пользователь решил сбросить несохранённые правки — возвращаем виджеты к конфигу
            self._refresh_all_from_config()
            self._dirty = False
        self.shutdown()  # прерываем запись хоткея и фоновую загрузку моделей
        super().closeEvent(event)

    def shutdown(self) -> None:
        """Останавливает фоновые задачи окна (запись хоткея, загрузку моделей).

        Вызывается при закрытии окна и при выходе из приложения
        (TrayApp.quit_app): у уничтожаемого QThread поток обязан быть
        остановлен — иначе завершение приложения падает с qFatal.
        """
        if self._recorder is not None and self._recorder.isRunning():
            self._recorder.cancel()
            self._recorder.wait(1000)
        if self._model_worker is not None and self._model_worker.isRunning():
            if hasattr(self._model_worker, "cancel"):
                self._model_worker.cancel()
            self._model_worker.wait(2000)
        if self._conn_worker is not None and self._conn_worker.isRunning():
            if hasattr(self._conn_worker, "cancel"):
                self._conn_worker.cancel()
            self._conn_worker.wait(2000)

    # =========================================================================
    # ВКЛАДКА 4: «Проекты» (ЭТАП 8)
    # =========================================================================
    def open_projects_tab(self) -> None:
        """Переключает окно настроек на вкладку проектов и глоссария."""
        self.tabs.setCurrentIndex(3)
        self._refresh_projects_list()
        self.show()
        self.raise_()
        self.activateWindow()

    def _build_projects_tab(self) -> QWidget:
        """Строит интерфейс вкладки управления проектами, контекстом и глоссарием (Этап 8)."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        # Сплиттер: слева список проектов, справа редактор и глоссарий
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(5)
        splitter.setChildrenCollapsible(False)

        # ---------------- 1. Левая панель: список проектов ----------------
        left_widget = QWidget()
        left_widget.setMinimumWidth(260)
        left_lay = QVBoxLayout(left_widget)
        left_lay.setContentsMargins(0, 0, 8, 0)
        left_lay.setSpacing(8)

        self.proj_search_edit = QLineEdit()
        self.proj_search_edit.setPlaceholderText("Поиск проектов...")
        self.proj_search_edit.setClearButtonEnabled(True)
        self.proj_search_edit.textChanged.connect(self._refresh_projects_list)
        left_lay.addWidget(self.proj_search_edit)

        self.projects_list = QListWidget()
        self.projects_list.setObjectName("ProjectsList")
        self.projects_list.itemSelectionChanged.connect(self._on_project_selected)
        left_lay.addWidget(self.projects_list, stretch=1)

        btn_proj_row = QHBoxLayout()
        btn_proj_row.setSpacing(6)

        self.btn_new_proj = QPushButton("+ Создать")
        self.btn_new_proj.setObjectName("PrimaryButton")
        self.btn_new_proj.setStyleSheet("padding: 4px 6px; font-size: 8.5pt;")
        self.btn_new_proj.setMinimumWidth(65)
        self.btn_new_proj.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_new_proj.clicked.connect(self._on_create_project_clicked)
        btn_proj_row.addWidget(self.btn_new_proj)

        self.btn_dup_proj = QPushButton("Копия")
        self.btn_dup_proj.setStyleSheet("padding: 4px 6px; font-size: 8.5pt;")
        self.btn_dup_proj.setMinimumWidth(60)
        self.btn_dup_proj.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_dup_proj.clicked.connect(self._on_duplicate_project_clicked)
        btn_proj_row.addWidget(self.btn_dup_proj)

        self.btn_del_proj = QPushButton("Удалить")
        self.btn_del_proj.setObjectName("DangerBtn")
        self.btn_del_proj.setStyleSheet("padding: 4px 6px; font-size: 8.5pt;")
        self.btn_del_proj.setMinimumWidth(65)
        self.btn_del_proj.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_del_proj.clicked.connect(self._on_delete_project_clicked)
        btn_proj_row.addWidget(self.btn_del_proj)

        left_lay.addLayout(btn_proj_row)
        splitter.addWidget(left_widget)

        # ---------------- 2. Правая панель: параметры проекта и глоссарий -
        self.proj_right_container = QWidget()
        self.proj_right_container.setMinimumWidth(320)
        right_lay = QVBoxLayout(self.proj_right_container)
        right_lay.setContentsMargins(8, 0, 0, 0)
        right_lay.setSpacing(10)

        # Шапка проекта
        proj_hdr_box = QFrame()
        proj_hdr_box.setObjectName("SectionBox")
        proj_hdr_lay = QVBoxLayout(proj_hdr_box)
        proj_hdr_lay.setContentsMargins(12, 10, 12, 10)
        proj_hdr_lay.setSpacing(8)

        hdr_row1 = QHBoxLayout()
        hdr_row1.setSpacing(8)

        lbl_pname = QLabel("Проект:")
        lbl_pname.setObjectName("FieldLabel")
        hdr_row1.addWidget(lbl_pname)

        self.proj_name_edit = QLineEdit()
        self.proj_name_edit.setPlaceholderText("Название проекта (напр. Новелла «Re:Zero», Локализация RPG)...")
        self.proj_name_edit.textChanged.connect(self._mark_dirty)
        hdr_row1.addWidget(self.proj_name_edit, stretch=1)

        self.btn_set_active_proj = QPushButton("Сделать активным")
        self.btn_set_active_proj.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_set_active_proj.clicked.connect(self._on_set_active_project_clicked)
        hdr_row1.addWidget(self.btn_set_active_proj)

        proj_hdr_lay.addLayout(hdr_row1)

        hdr_row2 = QHBoxLayout()
        lbl_pdesc = QLabel("Описание:")
        lbl_pdesc.setObjectName("FieldLabel")
        hdr_row2.addWidget(lbl_pdesc)

        self.proj_desc_edit = QLineEdit()
        self.proj_desc_edit.setPlaceholderText("Краткое описание специфики, сеттинга или назначения проекта...")
        self.proj_desc_edit.textChanged.connect(self._mark_dirty)
        hdr_row2.addWidget(self.proj_desc_edit, stretch=1)
        proj_hdr_lay.addLayout(hdr_row2)

        right_lay.addWidget(proj_hdr_box)

        # Вкладки проекта: «Контекст и Правила» и «Глоссарий терминов»
        self.proj_subtabs = QTabWidget()

        # --- Подвкладка 1: Параметры и Контекст ---
        ctx_tab = QWidget()
        ctx_tab_lay = QVBoxLayout(ctx_tab)
        ctx_tab_lay.setContentsMargins(4, 8, 4, 4)
        ctx_tab_lay.setSpacing(10)

        ctx_scroll = QScrollArea()
        ctx_scroll.setWidgetResizable(True)
        ctx_scroll.setFrameShape(QFrame.Shape.NoFrame)
        ctx_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        ctx_scroll_content = QWidget()
        scroll_lay = QVBoxLayout(ctx_scroll_content)
        scroll_lay.setContentsMargins(0, 0, 4, 0)
        scroll_lay.setSpacing(10)

        # Карточка языков и модели
        card_params = QFrame()
        card_params.setObjectName("SectionBox")
        card_params_lay = QGridLayout(card_params)
        card_params_lay.setContentsMargins(12, 10, 12, 10)
        card_params_lay.setHorizontalSpacing(12)
        card_params_lay.setVerticalSpacing(8)

        lbl_sl = QLabel("Исходный язык:")
        lbl_sl.setObjectName("FieldLabel")
        card_params_lay.addWidget(lbl_sl, 0, 0)
        self.proj_src_lang_combo = QComboBox()
        self.proj_src_lang_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        card_params_lay.addWidget(self.proj_src_lang_combo, 0, 1)

        lbl_tl = QLabel("Целевой язык:")
        lbl_tl.setObjectName("FieldLabel")
        card_params_lay.addWidget(lbl_tl, 0, 2)
        self.proj_tgt_lang_combo = QComboBox()
        self.proj_tgt_lang_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        card_params_lay.addWidget(self.proj_tgt_lang_combo, 0, 3)

        lbl_pr = QLabel("AI-профиль:")
        lbl_pr.setObjectName("FieldLabel")
        card_params_lay.addWidget(lbl_pr, 1, 0)
        self.proj_profile_combo = QComboBox()
        self.proj_profile_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        self.proj_profile_combo.currentIndexChanged.connect(self._update_privacy_card)
        card_params_lay.addWidget(self.proj_profile_combo, 1, 1)

        lbl_ac = QLabel("Действие:")
        lbl_ac.setObjectName("FieldLabel")
        card_params_lay.addWidget(lbl_ac, 1, 2)
        self.proj_action_combo = QComboBox()
        self.proj_action_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        card_params_lay.addWidget(self.proj_action_combo, 1, 3)

        for cb in (self.proj_src_lang_combo, self.proj_tgt_lang_combo, self.proj_profile_combo, self.proj_action_combo):
            cb.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            cb.setMinimumContentsLength(6)
            cb.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        card_params_lay.setColumnStretch(0, 0)
        card_params_lay.setColumnStretch(1, 1)
        card_params_lay.setColumnStretch(2, 0)
        card_params_lay.setColumnStretch(3, 1)

        self._populate_project_combos()
        scroll_lay.addWidget(card_params)

        # Карточка контекста произведения
        card_lore = QFrame()
        card_lore.setObjectName("SectionBox")
        card_lore_lay = QVBoxLayout(card_lore)
        card_lore_lay.setContentsMargins(12, 10, 12, 10)
        card_lore_lay.setSpacing(6)

        lbl_lore = QLabel("Контекст произведения (персонажи, мир, сеттинг, атмосфера):")
        lbl_lore.setObjectName("FieldLabel")
        card_lore_lay.addWidget(lbl_lore)

        self.proj_context_edit = QPlainTextEdit()
        self.proj_context_edit.setObjectName("HistoryDetailEdit")
        self.proj_context_edit.setPlaceholderText(
            "Опишите персонажей, их статус, взаимоотношения, особенности мира...\n"
            "Модель прочитает это перед переводом и учтёт специфику контекста."
        )
        self.proj_context_edit.setMaximumHeight(85)
        self.proj_context_edit.textChanged.connect(self._mark_dirty)
        card_lore_lay.addWidget(self.proj_context_edit)
        scroll_lay.addWidget(card_lore)

        # Карточка правил перевода
        card_rules = QFrame()
        card_rules.setObjectName("SectionBox")
        card_rules_lay = QVBoxLayout(card_rules)
        card_rules_lay.setContentsMargins(12, 10, 12, 10)
        card_rules_lay.setSpacing(6)

        lbl_rules = QLabel("Пользовательские правила перевода и локализации:")
        lbl_rules.setObjectName("FieldLabel")
        card_rules_lay.addWidget(lbl_rules)

        self.proj_rules_edit = QPlainTextEdit()
        self.proj_rules_edit.setObjectName("HistoryDetailEdit")
        self.proj_rules_edit.setPlaceholderText(
            "Например:\n"
            "- Обращение к персонажу 'Эмилия' строго на 'вы'\n"
            "- Не транслитерировать японские суффиксы (-сан, -тян), передавать интонацией\n"
            "- Названия магии брать из глоссария без изменений"
        )
        self.proj_rules_edit.setMaximumHeight(80)
        self.proj_rules_edit.textChanged.connect(self._mark_dirty)
        card_rules_lay.addWidget(self.proj_rules_edit)
        scroll_lay.addWidget(card_rules)

        # Карточка заметок
        card_notes = QFrame()
        card_notes.setObjectName("SectionBox")
        card_notes_lay = QVBoxLayout(card_notes)
        card_notes_lay.setContentsMargins(12, 10, 12, 10)
        card_notes_lay.setSpacing(6)

        lbl_notes = QLabel("Заметки переводчика (личный блокнот проекта):")
        lbl_notes.setObjectName("FieldLabel")
        card_notes_lay.addWidget(lbl_notes)

        self.proj_notes_edit = QPlainTextEdit()
        self.proj_notes_edit.setObjectName("HistoryDetailEdit")
        self.proj_notes_edit.setPlaceholderText("Рабочие заметки, идеи, нерешённые вопросы...")
        self.proj_notes_edit.setMaximumHeight(65)
        self.proj_notes_edit.textChanged.connect(self._mark_dirty)
        card_notes_lay.addWidget(self.proj_notes_edit)
        scroll_lay.addWidget(card_notes)

        # Карточка памяти фрагментов (Translation Memory)
        card_mem = QFrame()
        card_mem.setObjectName("SectionBox")
        card_mem_lay = QVBoxLayout(card_mem)
        card_mem_lay.setContentsMargins(12, 10, 12, 10)
        card_mem_lay.setSpacing(8)

        mem_row1 = QHBoxLayout()
        mem_row1.setSpacing(10)
        self.proj_mem_enabled_cb = QCheckBox("Включить память фрагментов для связности текста")
        self.proj_mem_enabled_cb.setCursor(Qt.CursorShape.PointingHandCursor)
        self.proj_mem_enabled_cb.toggled.connect(self._mark_dirty)
        mem_row1.addWidget(self.proj_mem_enabled_cb)
        mem_row1.addStretch(1)

        self.btn_clear_mem = QPushButton("Сбросить память")
        self.btn_clear_mem.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_clear_mem.clicked.connect(self._on_clear_proj_memory_clicked)
        mem_row1.addWidget(self.btn_clear_mem)
        card_mem_lay.addLayout(mem_row1)

        mem_row2 = QHBoxLayout()
        mem_row2.setSpacing(10)

        lbl_mc = QLabel("Фрагментов:")
        lbl_mc.setObjectName("FieldLabel")
        mem_row2.addWidget(lbl_mc)
        self.proj_mem_count_spin = QSpinBox()
        self.proj_mem_count_spin.setRange(1, 10)
        self.proj_mem_count_spin.setValue(3)
        self.proj_mem_count_spin.setFixedWidth(65)
        self.proj_mem_count_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.proj_mem_count_spin.valueChanged.connect(self._mark_dirty)
        mem_row2.addWidget(self.proj_mem_count_spin)

        lbl_mch = QLabel("Макс. символов:")
        lbl_mch.setObjectName("FieldLabel")
        mem_row2.addWidget(lbl_mch)
        self.proj_mem_chars_spin = QSpinBox()
        self.proj_mem_chars_spin.setRange(200, 8000)
        self.proj_mem_chars_spin.setValue(1500)
        self.proj_mem_chars_spin.setFixedWidth(75)
        self.proj_mem_chars_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.proj_mem_chars_spin.valueChanged.connect(self._mark_dirty)
        mem_row2.addWidget(self.proj_mem_chars_spin)

        mem_row2.addSpacing(10)
        self.proj_mem_include_trans_cb = QCheckBox("Передавать перевод с оригиналом")
        self.proj_mem_include_trans_cb.setChecked(True)
        self.proj_mem_include_trans_cb.setCursor(Qt.CursorShape.PointingHandCursor)
        self.proj_mem_include_trans_cb.toggled.connect(self._mark_dirty)
        mem_row2.addWidget(self.proj_mem_include_trans_cb)

        mem_row2.addStretch(1)
        card_mem_lay.addLayout(mem_row2)
        scroll_lay.addWidget(card_mem)

        # Карточка конфиденциальности
        self.privacy_card = QFrame()
        self.privacy_card.setObjectName("PrivacyWarningCard")
        self.privacy_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        priv_lay = QHBoxLayout(self.privacy_card)
        priv_lay.setContentsMargins(12, 10, 12, 10)
        self.privacy_card_lbl = QLabel("")
        self.privacy_card_lbl.setObjectName("PrivacyWarningText")
        self.privacy_card_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.privacy_card_lbl.setWordWrap(True)
        priv_lay.addWidget(self.privacy_card_lbl)
        scroll_lay.addWidget(self.privacy_card)

        ctx_scroll.setWidget(ctx_scroll_content)
        ctx_tab_lay.addWidget(ctx_scroll)

        # Нижняя кнопка сохранения
        btn_save_proj_row = QHBoxLayout()
        btn_save_proj_row.addStretch(1)
        self.btn_save_project = QPushButton("Сохранить параметры проекта")
        self.btn_save_project.setObjectName("PrimaryButton")
        self.btn_save_project.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_save_project.clicked.connect(self._save_current_project)
        btn_save_proj_row.addWidget(self.btn_save_project)
        ctx_tab_lay.addLayout(btn_save_proj_row)

        self.proj_subtabs.addTab(ctx_tab, "Параметры и Контекст")

        # --- Подвкладка 2: Глоссарий терминов ---
        glo_tab = QWidget()
        glo_tab_lay = QVBoxLayout(glo_tab)
        glo_tab_lay.setContentsMargins(4, 8, 4, 4)
        glo_tab_lay.setSpacing(8)

        # Верхняя панель управления глоссарием
        glo_mgmt_row = QHBoxLayout()
        glo_mgmt_row.setSpacing(8)

        self.btn_add_term = QPushButton("+ Добавить термин")
        self.btn_add_term.setObjectName("PrimaryButton")
        self.btn_add_term.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_add_term.clicked.connect(self._on_add_term_clicked)
        glo_mgmt_row.addWidget(self.btn_add_term)

        self.btn_import_glossary = QPushButton("Импорт...")
        self.btn_import_glossary.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_import_glossary.clicked.connect(self._on_import_glossary_clicked)
        glo_mgmt_row.addWidget(self.btn_import_glossary)

        self.btn_export_glossary = QPushButton("Экспорт...")
        self.btn_export_glossary.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_export_glossary.clicked.connect(self._on_export_glossary_clicked)
        glo_mgmt_row.addWidget(self.btn_export_glossary)

        self.btn_find_duplicates = QPushButton("Дубликаты")
        self.btn_find_duplicates.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_find_duplicates.clicked.connect(self._on_check_duplicates_clicked)
        glo_mgmt_row.addWidget(self.btn_find_duplicates)

        glo_mgmt_row.addStretch(1)

        self.proj_glossary_enabled_cb = QCheckBox("Авто-подстановка в перевод")
        self.proj_glossary_enabled_cb.setChecked(True)
        self.proj_glossary_enabled_cb.setCursor(Qt.CursorShape.PointingHandCursor)
        self.proj_glossary_enabled_cb.toggled.connect(self._save_current_project)
        glo_mgmt_row.addWidget(self.proj_glossary_enabled_cb)

        glo_tab_lay.addLayout(glo_mgmt_row)

        # Строка фильтрации терминов
        glo_filter_row = QHBoxLayout()
        glo_filter_row.setSpacing(8)

        self.term_search_edit = QLineEdit()
        self.term_search_edit.setPlaceholderText("Поиск по терминам, переводу или примечанию...")
        self.term_search_edit.setClearButtonEnabled(True)
        self.term_search_edit.textChanged.connect(self._refresh_glossary_table)
        glo_filter_row.addWidget(self.term_search_edit, stretch=1)

        lbl_cat_f = QLabel("Категория:")
        lbl_cat_f.setObjectName("FieldLabel")
        glo_filter_row.addWidget(lbl_cat_f)

        self.term_cat_combo = QComboBox()
        self.term_cat_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        self.term_cat_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.term_cat_combo.addItem("Все категории", "all")
        for cat in STANDARD_CATEGORIES:
            self.term_cat_combo.addItem(cat, cat)
        self.term_cat_combo.currentIndexChanged.connect(self._refresh_glossary_table)
        glo_filter_row.addWidget(self.term_cat_combo)

        self.term_count_lbl = QLabel("Терминов: 0")
        self.term_count_lbl.setObjectName("FieldHint")
        glo_filter_row.addWidget(self.term_count_lbl)

        glo_tab_lay.addLayout(glo_filter_row)

        # Таблица терминов
        self.glossary_table = QTableWidget()
        self.glossary_table.setObjectName("GlossaryTable")
        self.glossary_table.setColumnCount(6)
        self.glossary_table.setHorizontalHeaderLabels([
            "ID", "Исходный термин", "Утверждённый перевод", "Категория", "Комментарий", "Примеры"
        ])
        self.glossary_table.setColumnHidden(0, True)
        self.glossary_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        self.glossary_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        self.glossary_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        self.glossary_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.glossary_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self.glossary_table.horizontalHeader().setMinimumSectionSize(60)
        self.glossary_table.setColumnWidth(1, 120)
        self.glossary_table.setColumnWidth(2, 120)
        self.glossary_table.setColumnWidth(3, 100)
        self.glossary_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.glossary_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.glossary_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.glossary_table.verticalHeader().setVisible(False)
        self.glossary_table.cellDoubleClicked.connect(lambda row, col: self._on_edit_selected_term())
        self.glossary_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.glossary_table.customContextMenuRequested.connect(self._show_glossary_context_menu)
        glo_tab_lay.addWidget(self.glossary_table, stretch=1)

        # Нижняя панель действий со строками
        glo_actions_row = QHBoxLayout()
        self.btn_edit_term = QPushButton("Редактировать")
        self.btn_edit_term.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_edit_term.clicked.connect(self._on_edit_selected_term)
        glo_actions_row.addWidget(self.btn_edit_term)

        self.btn_del_term = QPushButton("Удалить")
        self.btn_del_term.setObjectName("DangerBtn")
        self.btn_del_term.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_del_term.clicked.connect(self._on_delete_selected_term)
        glo_actions_row.addWidget(self.btn_del_term)

        glo_actions_row.addStretch(1)
        glo_tab_lay.addLayout(glo_actions_row)

        self.proj_subtabs.addTab(glo_tab, "Глоссарий терминов")
        right_lay.addWidget(self.proj_subtabs, stretch=1)

        splitter.addWidget(self.proj_right_container)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([260, 680])
        layout.addWidget(splitter)

        return tab

    def _populate_project_combos(self) -> None:
        """Заполняет списки языков, профилей и действий в настройках проекта."""
        # 1. Исходный язык
        self.proj_src_lang_combo.clear()
        self.proj_src_lang_combo.addItem("Автоопределение (auto)", "auto")
        for lang in get_supported_languages():
            self.proj_src_lang_combo.addItem(f"{lang.name_ru} ({lang.code})", lang.code)

        # 2. Целевой язык
        self.proj_tgt_lang_combo.clear()
        for lang in get_supported_languages():
            self.proj_tgt_lang_combo.addItem(f"{lang.name_ru} ({lang.code})", lang.code)

        # 3. AI-профиль проекта
        self.proj_profile_combo.clear()
        self.proj_profile_combo.addItem("По умолчанию из настроек", "")
        if hasattr(self.config, "get_profiles"):
            for pid, prof in self.config.get_profiles().items():
                pname = prof.get("name") or pid
                self.proj_profile_combo.addItem(f"{pname} ({prof.get('model_name', '')})", pid)

        # 4. Действие по умолчанию
        self.proj_action_combo.clear()
        self.proj_action_combo.addItem("По умолчанию (активное действие)", "")
        if hasattr(self.config, "get_actions"):
            for act in self.config.get_actions():
                self.proj_action_combo.addItem(f"{act.get('name')}", act.get("id"))

    def _refresh_projects_list(self) -> None:
        """Обновляет левый список проектов."""
        pm = get_project_manager()
        projects = pm.list_projects()

        # Если проектов вообще нет — создаём дефолтный стартовый проект
        if not projects:
            pm.create_project(
                name="Основной проект",
                description="Универсальный проект для работы и переводов с собственным глоссарием",
                source_lang="auto",
                target_lang="ru",
            )
            projects = pm.list_projects()

        active_id = pm.get_active_project_id()
        search = self.proj_search_edit.text().strip().lower()

        self.projects_list.blockSignals(True)
        self.projects_list.clear()

        sel_row = 0
        current_row = 0
        for p in projects:
            p_id = p.get("id", "")
            p_name = p.get("name", "Проект")
            p_desc = p.get("description", "")
            if search and search not in p_name.lower() and search not in p_desc.lower():
                continue

            terms_cnt = len(p.get("glossary", []))
            s_lang = (p.get("source_lang") or "auto").upper()
            t_lang = (p.get("target_lang") or "ru").upper()

            is_active = (p_id == active_id)
            active_mark = "[активен] " if is_active else ""
            item_text = f"{active_mark}{p_name}\n[{s_lang} → {t_lang}] · {terms_cnt} терм."
            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, p_id)
            if is_active:
                item.setToolTip("Этот проект сейчас активен в программе")
            self.projects_list.addItem(item)

            if p_id == self._selected_project_id:
                sel_row = current_row
            current_row += 1

        self.projects_list.blockSignals(False)

        if self.projects_list.count() > 0:
            self.projects_list.setCurrentRow(sel_row)
        else:
            self._selected_project_id = None
            self.proj_right_container.setEnabled(False)

    def _on_project_selected(self) -> None:
        """Отображает данные выбранного проекта в правой панели."""
        item = self.projects_list.currentItem()
        if not item:
            self.proj_right_container.setEnabled(False)
            return

        p_id = str(item.data(Qt.ItemDataRole.UserRole) or "")
        self._selected_project_id = p_id
        self.proj_right_container.setEnabled(True)

        pm = get_project_manager()
        proj = pm.get_project(p_id)
        if not proj:
            return

        self.proj_name_edit.blockSignals(True)
        self.proj_name_edit.setText(proj.get("name", ""))
        self.proj_name_edit.blockSignals(False)

        self.proj_desc_edit.blockSignals(True)
        self.proj_desc_edit.setText(proj.get("description", ""))
        self.proj_desc_edit.blockSignals(False)

        # Выбор языков
        src_l = proj.get("source_lang", "auto")
        tgt_l = proj.get("target_lang", "ru")
        s_idx = self.proj_src_lang_combo.findData(src_l)
        if s_idx >= 0:
            self.proj_src_lang_combo.setCurrentIndex(s_idx)
        t_idx = self.proj_tgt_lang_combo.findData(tgt_l)
        if t_idx >= 0:
            self.proj_tgt_lang_combo.setCurrentIndex(t_idx)

        # Профиль и действие
        pr_id = proj.get("ai_profile_id", "")
        pr_idx = self.proj_profile_combo.findData(pr_id)
        if pr_idx >= 0:
            self.proj_profile_combo.setCurrentIndex(pr_idx)

        ac_id = proj.get("action_id", "")
        ac_idx = self.proj_action_combo.findData(ac_id)
        if ac_idx >= 0:
            self.proj_action_combo.setCurrentIndex(ac_idx)

        # Контекст, правила, заметки
        self.proj_context_edit.blockSignals(True)
        self.proj_context_edit.setPlainText(proj.get("context", ""))
        self.proj_context_edit.blockSignals(False)

        self.proj_rules_edit.blockSignals(True)
        self.proj_rules_edit.setPlainText(proj.get("translation_rules", ""))
        self.proj_rules_edit.blockSignals(False)

        self.proj_notes_edit.blockSignals(True)
        self.proj_notes_edit.setPlainText(proj.get("notes", ""))
        self.proj_notes_edit.blockSignals(False)

        # Память
        self.proj_mem_enabled_cb.blockSignals(True)
        self.proj_mem_enabled_cb.setChecked(bool(proj.get("context_memory_enabled", False)))
        self.proj_mem_enabled_cb.blockSignals(False)

        self.proj_mem_count_spin.blockSignals(True)
        self.proj_mem_count_spin.setValue(int(proj.get("context_memory_count", 3)))
        self.proj_mem_count_spin.blockSignals(False)

        self.proj_mem_chars_spin.blockSignals(True)
        self.proj_mem_chars_spin.setValue(int(proj.get("context_memory_max_chars", 1500)))
        self.proj_mem_chars_spin.blockSignals(False)

        self.proj_mem_include_trans_cb.blockSignals(True)
        self.proj_mem_include_trans_cb.setChecked(bool(proj.get("context_memory_include_translation", True)))
        self.proj_mem_include_trans_cb.blockSignals(False)

        # Глоссарий
        self.proj_glossary_enabled_cb.blockSignals(True)
        self.proj_glossary_enabled_cb.setChecked(bool(proj.get("glossary_enabled", True)))
        self.proj_glossary_enabled_cb.blockSignals(False)

        # Кнопка активности
        is_active = (p_id == pm.get_active_project_id())
        if is_active:
            self.btn_set_active_proj.setText("Активный проект")
            self.btn_set_active_proj.setObjectName("AccentBtn")
        else:
            self.btn_set_active_proj.setText("Сделать активным")
            self.btn_set_active_proj.setObjectName("")
        repolish(self.btn_set_active_proj)

        self._update_privacy_card()
        self._refresh_glossary_table()

    def _save_current_project(self) -> None:
        """Сохраняет текущие параметры проекта."""
        if not self._selected_project_id:
            return

        pm = get_project_manager()
        name = self.proj_name_edit.text().strip() or "Проект"
        desc = self.proj_desc_edit.text().strip()
        src_l = self.proj_src_lang_combo.currentData() or "auto"
        tgt_l = self.proj_tgt_lang_combo.currentData() or "ru"
        pr_id = self.proj_profile_combo.currentData() or ""
        ac_id = self.proj_action_combo.currentData() or ""
        ctx = self.proj_context_edit.toPlainText().strip()
        rules = self.proj_rules_edit.toPlainText().strip()
        notes = self.proj_notes_edit.toPlainText().strip()
        mem_en = self.proj_mem_enabled_cb.isChecked()
        mem_cnt = self.proj_mem_count_spin.value()
        mem_chars = self.proj_mem_chars_spin.value()
        mem_incl = self.proj_mem_include_trans_cb.isChecked()
        glo_en = self.proj_glossary_enabled_cb.isChecked()

        pm.update_project(
            self._selected_project_id,
            name=name,
            description=desc,
            source_lang=src_l,
            target_lang=tgt_l,
            ai_profile_id=pr_id,
            action_id=ac_id,
            context=ctx,
            translation_rules=rules,
            notes=notes,
            context_memory_enabled=mem_en,
            context_memory_count=mem_cnt,
            context_memory_max_chars=mem_chars,
            context_memory_include_translation=mem_incl,
            glossary_enabled=glo_en,
        )

        self._refresh_projects_list()
        self.projects_changed.emit()
        self.statusBar().showMessage(f"Параметры проекта «{name}» успешно сохранены.", 3500)

    def _on_set_active_project_clicked(self) -> None:
        """Включает или выключает статус активного проекта."""
        if not self._selected_project_id:
            return

        pm = get_project_manager()
        curr_active = pm.get_active_project_id()

        if curr_active == self._selected_project_id:
            # Отключаем (переход в общий режим без проекта)
            pm.set_active_project_id("")
            if hasattr(self.config, "set_active_project_id"):
                self.config.set_active_project_id("")
            self.statusBar().showMessage("Проект отключён. Переход в общий режим.", 3000)
        else:
            pm.set_active_project_id(self._selected_project_id)
            if hasattr(self.config, "set_active_project_id"):
                self.config.set_active_project_id(self._selected_project_id)
            p = pm.get_project(self._selected_project_id)
            pname = p.get("name", "Проект") if p else "Проект"
            self.statusBar().showMessage(f"Проект «{pname}» назначен активным.", 3000)

        self._refresh_projects_list()
        self.projects_changed.emit()

    def _on_create_project_clicked(self) -> None:
        """Создает новый проект."""
        pm = get_project_manager()
        count = len(pm.list_projects()) + 1
        new_proj = pm.create_project(
            name=f"Новый проект {count}",
            description="Описание проекта",
            source_lang="auto",
            target_lang="ru",
        )
        self._selected_project_id = new_proj["id"]
        self._refresh_projects_list()
        self.projects_changed.emit()
        self.proj_name_edit.setFocus()
        self.proj_name_edit.selectAll()

    def _on_duplicate_project_clicked(self) -> None:
        """Создает копию выбранного проекта."""
        if not self._selected_project_id:
            return
        pm = get_project_manager()
        clone = pm.duplicate_project(self._selected_project_id)
        if clone:
            self._selected_project_id = clone["id"]
            self._refresh_projects_list()
            self.projects_changed.emit()
            self.statusBar().showMessage(f"Создана копия проекта «{clone.get('name')}».", 3000)

    def _on_delete_project_clicked(self) -> None:
        """Удаляет выбранный проект после подтверждения."""
        if not self._selected_project_id:
            return
        pm = get_project_manager()
        proj = pm.get_project(self._selected_project_id)
        if not proj:
            return

        pname = proj.get("name", "Проект")
        res = QMessageBox.question(
            self,
            "Удаление проекта",
            f"Вы уверены, что хотите удалить проект «{pname}» и весь его глоссарий?\n"
            "Это действие нельзя отменить.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if res == QMessageBox.StandardButton.Yes:
            pm.delete_project(self._selected_project_id)
            self._selected_project_id = None
            self._refresh_projects_list()
            self.projects_changed.emit()
            self.statusBar().showMessage(f"Проект «{pname}» удалён.", 3000)

    def _update_privacy_card(self) -> None:
        """Обновляет предупреждение о конфиденциальности данных проекта."""
        if not hasattr(self, "privacy_card_lbl"):
            return
        prof_id = self.proj_profile_combo.currentData()
        profile: Dict[str, Any] = {}
        if prof_id and hasattr(self.config, "get_profile"):
            profile = self.config.get_profile(prof_id) or {}
        if not profile and hasattr(self.config, "get_active_profile"):
            profile = self.config.get_active_profile() or {}

        api_url = profile.get("api_url", "")
        model_name = profile.get("model_name", "")
        provider_type = profile.get("provider_type", "")

        info = ProjectManager.get_privacy_info(api_url, model_name, provider_type)
        if info["is_local"]:
            self.privacy_card.setObjectName("PrivacyLocalCard")
            self.privacy_card_lbl.setText(
                "Локальный режим (Ollama): Текст и контекст проекта обрабатываются "
                "исключительно на вашем компьютере и никуда не передаются через интернет."
            )
        else:
            self.privacy_card.setObjectName("PrivacyWarningCard")
            self.privacy_card_lbl.setText(
                f"Внимание (Облачный провайдер {model_name or ''}): "
                "Выделенный текст, заметки и правила проекта отправляются внешнему сервису. "
                "Для закрытых и конфиденциальных произведений используйте локальную Ollama."
            )
        repolish(self.privacy_card)

    def _on_clear_proj_memory_clicked(self) -> None:
        """Очищает память фрагментов выбранного проекта."""
        if not self._selected_project_id:
            return
        pm = get_project_manager()
        pm.clear_memory(self._selected_project_id)
        self.statusBar().showMessage("Память предшествующих фрагментов для проекта очищена.", 3000)

    # ---------------------------------------------------- операции с глоссарием
    def _refresh_glossary_table(self) -> None:
        """Обновляет таблицу терминов глоссария."""
        if not self._selected_project_id:
            self.glossary_table.setRowCount(0)
            self.term_count_lbl.setText("Терминов: 0")
            return

        pm = get_project_manager()
        search = self.term_search_edit.text()
        cat = self.term_cat_combo.currentData() or "all"
        terms = pm.list_glossary_terms(self._selected_project_id, search=search, category=cat)

        self.glossary_table.blockSignals(True)
        self.glossary_table.setRowCount(len(terms))

        for row, t in enumerate(terms):
            self.glossary_table.setItem(row, 0, QTableWidgetItem(str(t.get("id"))))
            self.glossary_table.setItem(row, 1, QTableWidgetItem(str(t.get("source_term", ""))))
            self.glossary_table.setItem(row, 2, QTableWidgetItem(str(t.get("target_term", ""))))
            self.glossary_table.setItem(row, 3, QTableWidgetItem(str(t.get("category", "Другое"))))
            self.glossary_table.setItem(row, 4, QTableWidgetItem(str(t.get("comment", ""))))
            self.glossary_table.setItem(row, 5, QTableWidgetItem(str(t.get("examples", ""))))

        self.glossary_table.blockSignals(False)
        self.term_count_lbl.setText(f"Терминов: {len(terms)}")

    def _on_add_term_clicked(self) -> None:
        """Добавляет новый термин в глоссарий проекта."""
        if not self._selected_project_id:
            return
        dlg = TermEditDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            data = dlg.get_data()
            pm = get_project_manager()
            pm.add_glossary_term(
                self._selected_project_id,
                source_term=data["source_term"],
                target_term=data["target_term"],
                category=data["category"],
                comment=data["comment"],
                examples=data["examples"],
                case_sensitive=data["case_sensitive"],
            )
            self._refresh_glossary_table()
            self._refresh_projects_list()
            self.projects_changed.emit()

    def _on_edit_selected_term(self) -> None:
        """Редактирует выбранный термин."""
        if not self._selected_project_id:
            return
        row = self.glossary_table.currentRow()
        if row < 0:
            return
        term_id_item = self.glossary_table.item(row, 0)
        if not term_id_item:
            return
        term_id = term_id_item.text()

        pm = get_project_manager()
        proj = pm.get_project(self._selected_project_id)
        if not proj:
            return
        term_data = None
        for t in proj.get("glossary", []):
            if t.get("id") == term_id:
                term_data = t
                break
        if not term_data:
            return

        dlg = TermEditDialog(self, term_data=term_data)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            new_data = dlg.get_data()
            pm.update_glossary_term(self._selected_project_id, term_id, **new_data)
            self._refresh_glossary_table()
            self.projects_changed.emit()

    def _on_delete_selected_term(self) -> None:
        """Удаляет выбранный термин."""
        if not self._selected_project_id:
            return
        row = self.glossary_table.currentRow()
        if row < 0:
            return
        term_id_item = self.glossary_table.item(row, 0)
        term_name_item = self.glossary_table.item(row, 1)
        if not term_id_item:
            return
        term_id = term_id_item.text()
        term_name = term_name_item.text() if term_name_item else "термин"

        res = QMessageBox.question(
            self,
            "Удаление термина",
            f"Удалить термин «{term_name}» из глоссария?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if res == QMessageBox.StandardButton.Yes:
            pm = get_project_manager()
            pm.delete_glossary_term(self._selected_project_id, term_id)
            self._refresh_glossary_table()
            self._refresh_projects_list()
            self.projects_changed.emit()

    def _show_glossary_context_menu(self, pos) -> None:
        """Контекстное меню таблицы глоссария."""
        row = self.glossary_table.rowAt(pos.y())
        if row < 0:
            return
        self.glossary_table.selectRow(row)
        menu = QMenu(self)
        act_edit = menu.addAction("Редактировать термин")
        act_del = menu.addAction("Удалить термин")
        chosen = menu.exec(self.glossary_table.viewport().mapToGlobal(pos))
        if chosen == act_edit:
            self._on_edit_selected_term()
        elif chosen == act_del:
            self._on_delete_selected_term()

    def _on_import_glossary_clicked(self) -> None:
        """Импортирует словарь из файла JSON или CSV."""
        if not self._selected_project_id:
            return
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Импортировать глоссарий",
            "",
            "Словари (*.json *.csv *.tsv *.txt);;JSON (*.json);;CSV (*.csv);;Все файлы (*.*)",
        )
        if not file_path:
            return

        pm = get_project_manager()
        imported, skipped = pm.import_glossary_file(self._selected_project_id, file_path)
        QMessageBox.information(
            self,
            "Импорт завершён",
            f"Успешно импортировано терминов: {imported}\nПропущено/некорректных: {skipped}",
        )
        self._refresh_glossary_table()
        self._refresh_projects_list()
        self.projects_changed.emit()

    def _on_export_glossary_clicked(self) -> None:
        """Экспортирует словарь проекта в JSON или CSV."""
        if not self._selected_project_id:
            return
        file_path, sel_filter = QFileDialog.getSaveFileName(
            self,
            "Экспортировать глоссарий",
            "glossary.json",
            "JSON (*.json);;CSV (Excel UTF-8 BOM) (*.csv)",
        )
        if not file_path:
            return

        fmt = "csv" if ".csv" in sel_filter.lower() or file_path.lower().endswith(".csv") else "json"
        pm = get_project_manager()
        cnt = pm.export_glossary_file(self._selected_project_id, file_path, format=fmt)
        QMessageBox.information(
            self,
            "Экспорт завершён",
            f"Экспортировано {cnt} терминов в файл:\n{file_path}",
        )

    def _on_check_duplicates_clicked(self) -> None:
        """Проверяет повторяющиеся термины оригинала."""
        if not self._selected_project_id:
            return
        pm = get_project_manager()
        dups = pm.find_duplicate_terms(self._selected_project_id)
        if not dups:
            QMessageBox.information(
                self,
                "Проверка дубликатов",
                "В глоссарии проекта нет повторяющихся исходных терминов!",
            )
            return

        dlg = DuplicatesDialog(self, duplicates=dups, project_id=self._selected_project_id)
        dlg.exec()
