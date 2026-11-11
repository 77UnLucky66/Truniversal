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
import re
from typing import Optional
import uuid

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QCloseEvent, QIcon, QShowEvent
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QFrame, QGridLayout,
                             QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                             QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPushButton,
                             QScrollArea, QSlider, QSpinBox, QTabWidget,
                             QTextEdit, QVBoxLayout, QWidget)

from config import ConfigManager
from languages import get_supported_languages, AUTO_LANG_CODE
from hotkey_manager import validate_hotkey
from styles import apply_dark_title_bar
from workers import HotkeyRecorder, ModelListWorker, ConnectionCheckWorker
from api_helpers import normalize_chat_url, get_models_url
from credentials import mask_key

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

class SettingsWindow(QMainWindow):
    """Окно настроек «Комбайн»: модели, промпты, хоткеи и обычный переводчик."""

    #: Пресеты пересохранены — TrayApp обновит панель мини-окна.
    prompts_changed = pyqtSignal()

    #: Хоткей перерегистрирован — TrayApp обновит тултип трея и мини-окно.
    hotkey_changed = pyqtSignal(str)

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

        self.setWindowTitle("Truniversal — настройки («Комбайн»)")
        self.setWindowIcon(app_icon)
        self.setMinimumSize(720, 580)
        self.resize(840, 680)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_ai_tab(), "Модели и Параметры ИИ")
        self.tabs.addTab(self._build_prompts_tab(), "Мои Промпты (Пресеты)")
        self.tabs.addTab(self._build_hotkeys_tab(), "Хоткеи и Обычный переводчик")
        self.setCentralWidget(self.tabs)

        self._apply_interactive_cursors()
        self._populate_profiles_combo()

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
        badge = QLabel("🛡 Windows Credential Manager")
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
        conn_box.setStyleSheet("background-color: #141720; border: 1px solid #282E3C; border-radius: 8px;")
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
        adv_grid.addWidget(self.timeout_connect_spin, 0, 1)

        lbl2 = QLabel("Таймаут ответа (с):")
        lbl2.setObjectName("FieldLabel")
        adv_grid.addWidget(lbl2, 0, 2)
        self.timeout_request_spin = QSpinBox()
        self.timeout_request_spin.setRange(5, 300)
        self.timeout_request_spin.setValue(90)
        adv_grid.addWidget(self.timeout_request_spin, 0, 3)

        lbl3 = QLabel("Повторов при сбоях:")
        lbl3.setObjectName("FieldLabel")
        adv_grid.addWidget(lbl3, 1, 0)
        self.max_retries_spin = QSpinBox()
        self.max_retries_spin.setRange(0, 5)
        self.max_retries_spin.setValue(2)
        adv_grid.addWidget(self.max_retries_spin, 1, 1)

        lbl4 = QLabel("Макс. токенов (0=авто):")
        lbl4.setObjectName("FieldLabel")
        adv_grid.addWidget(lbl4, 1, 2)
        self.max_tokens_spin = QSpinBox()
        self.max_tokens_spin.setRange(0, 32768)
        self.max_tokens_spin.setValue(0)
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
                display_name = f"★ {display_name} (активен)"
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
            self._status("Создана копия профиля ✓")

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
        self.check_status_label.setText("⏳ Проверка подключения…")

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
            self.check_status_label.setText(f"✓ {message}")
            self._status(f"Подключение успешно ({latency_ms:.0f} мс) ✓")
        else:
            self.check_status_label.setStyleSheet("color: #FF6E73; font-weight: bold; padding: 2px 6px;")
            self.check_status_label.setText(f"✕ {message}")
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
        self._status(f"Профиль «{name}» сохранён ✓ (ключ защищён в Credential Manager)")

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
        up_btn = QPushButton("▲ Вверх")
        up_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        up_btn.setToolTip("Переместить выбранное действие выше в списке")
        up_btn.clicked.connect(self._move_preset_up)
        btn_row2.addWidget(up_btn)

        down_btn = QPushButton("▼ Вниз")
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

        self.action_pinned_check = QCheckBox("★ Закрепить в панели быстрого доступа мини-окна (1 клик)")
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
                tooltip_parts.append("★ Закреплено в панели быстрого доступа")
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
            self._status("Стартовые действия ИИ успешно восстановлены ✓")

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
        self._status(f"Действие «{name}» сохранено ✓")

    def _save_project_context(self) -> None:
        """Сохраняет контекст проекта и глоссарий терминов."""
        ctx = self.project_context_edit.text().strip()
        glo = self.glossary_edit.toPlainText().strip()
        self.config.set("project_context", ctx, autosave=False)
        self.config.set("glossary", glo, autosave=True)
        self._status("Контекст проекта и глоссарий успешно сохранены ✓")

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
        hot_row.addWidget(self.hotkey_edit, stretch=1)
        self.record_btn = QPushButton("Записать нажатие")
        self.record_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.record_btn.setToolTip("Нажмите кнопку и затем нажмите нужное сочетание клавиш")
        self.record_btn.clicked.connect(self._toggle_recording)
        hot_row.addWidget(self.record_btn)
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
        self.source_lang_combo.addItem("✨ Автоопределение (auto)", "auto")
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

        # === КАРТОЧКА 3: Диагностика и Журнал ===
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
                self._status("Все настройки сброшены к заводским ✓")
            else:
                self._status(
                    "Настройки сброшены, но хоткей не зарегистрировался — "
                    "проверьте сочетание.",
                    error=True,
                )
            self.hotkey_changed.emit(default_hotkey)
        else:
            # Менеджера нет (тестовое окружение) — применится после перезапуска.
            self._status("Все настройки сброшены к заводским ✓")
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

        if not self.config.update({
            "standard_engine": engine,
            "source_lang": source_val,
            "target_lang": target_val,
            "fallback_target_lang": fallback_val,
            "deepl_api_key": self.deepl_key_edit.text().strip(),
            "hotkey": new_hotkey,
            "hotkey_enabled": hotkey_enabled,
            "diagnostics": diagnostics_on,
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
            self._status("Сохранено ✓. Глобальный хоткей отключён.")
        elif not new_hotkey:
            self._status("Сохранено ✓. Хоткей не задан — захват по хоткею отключён.")
        elif self.hotkey_manager is None:
            self._status("Сохранено ✓. Хоткей применится после перезапуска.")
        else:
            self._status(f"Сохранено ✓. Хоткей «{new_hotkey}» уже активен.")

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
        prefix = "⚠ " if error else ""
        self.statusBar().showMessage(prefix + message, 4000)

    def showEvent(self, event: QShowEvent) -> None:
        """Тёмный заголовок окна сразу после показа (Windows 10/11) и курсоры."""
        super().showEvent(event)
        apply_dark_title_bar(self)
        self._apply_interactive_cursors()

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
