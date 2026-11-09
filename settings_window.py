"""
settings_window.py — главное окно настроек «Комбайн» (ШАГ 4).

Вкладки QTabWidget:
  1. «Модели и Параметры ИИ» — адрес API (кнопки Ollama/OpenRouter/OpenAI),
     ключ, модель (+ загрузка списка из Ollama), ползунки Temperature и
     Top-P с подробными подсказками простым языком.
  2. «Мои Промпты (Пресеты)» — список слева, редактор справа, добавление /
     удаление / сохранение, шпаргалка по промптам.
  3. «Хоткеи и Обычный переводчик» — запись сочетания клавиш кнопкой,
     движок Google/DeepL, целевой язык.

Всё пишется в config.json; смена хоткея перерегистрируется сразу — без
перезапуска. Сигналы prompts_changed / hotkey_changed сообщают TrayApp,
что мини-окно и тултип трея пора обновить.
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QCloseEvent, QIcon, QShowEvent
from PyQt6.QtWidgets import (QComboBox, QFrame, QHBoxLayout, QLabel,
                             QLineEdit, QListWidget, QMainWindow,
                             QMessageBox, QPushButton, QSlider, QTabWidget,
                             QTextEdit, QVBoxLayout, QWidget)

from config import ConfigManager
from styles import apply_dark_title_bar
from workers import HotkeyRecorder, ModelListWorker

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
    "• OpenRouter / OpenAI — например gpt-4o-mini или google/gemini-2.0-flash-001."
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
HINT_TARGET_LANG = (
    "На какой язык переводить по умолчанию.\n"
    "Язык исходника определяется автоматически. Если текст уже на целевом "
    "языке, направление переворачивается: англ. → рус. и наоборот "
    "(работает в обоих режимах — и в «ИИ», и в «Обычном»)."
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
    label.setCursor(Qt.CursorShape.WhatsThisCursor)
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

        self.setWindowTitle("Truniversal — настройки («Комбайн»)")
        self.setWindowIcon(app_icon)
        self.setMinimumSize(680, 540)
        self.resize(780, 620)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_ai_tab(), "Модели и Параметры ИИ")
        self.tabs.addTab(self._build_prompts_tab(), "Мои Промпты (Пресеты)")
        self.tabs.addTab(self._build_hotkeys_tab(), "Хоткеи и Обычный переводчик")
        self.setCentralWidget(self.tabs)

        # Любое ручное изменение помечает окно «грязным» (защита от потери
        # несохранённых правок при закрытии). Программные установки
        # делаются с blockSignals, поэтому сюда не попадают.
        self.api_url_edit.textChanged.connect(self._mark_dirty)
        self.api_key_edit.textChanged.connect(self._mark_dirty)
        self.model_combo.currentTextChanged.connect(self._mark_dirty)
        self.temp_slider.valueChanged.connect(self._mark_dirty)
        self.top_p_slider.valueChanged.connect(self._mark_dirty)
        self.preset_name_edit.textChanged.connect(self._mark_dirty)
        self.preset_text_edit.textChanged.connect(self._mark_dirty)
        self.hotkey_edit.textChanged.connect(self._mark_dirty)
        self.deepl_key_edit.textChanged.connect(self._mark_dirty)
        self.engine_combo.currentIndexChanged.connect(self._mark_dirty)
        self.lang_combo.currentTextChanged.connect(self._mark_dirty)

        self.statusBar().showMessage("Все настройки хранятся в config.json", 8000)

    # --------------------------------------------------------------- утилиты
    @staticmethod
    def _row_with_hint(text: str, hint: str) -> QWidget:
        """Строка «Название параметра» + значок «[?]» с подробной подсказкой."""
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        label = QLabel(text)
        label.setToolTip(hint)
        lay.addWidget(label)
        lay.addWidget(_hint(hint))
        lay.addStretch(1)
        return row

    @staticmethod
    def _caption(text: str) -> QLabel:
        """Приглушённая пояснительная строка под параметром."""
        lbl = QLabel(text)
        lbl.setObjectName("CaptionLabel")
        return lbl

    def _mark_dirty(self, *_) -> None:
        self._dirty = True

    # ================== ВКЛАДКА 1: Модели и Параметры ИИ =====================
    def _build_ai_tab(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(10)

        # --- Адрес API + быстрые кнопки
        lay.addWidget(self._row_with_hint("Адрес API (URL):", HINT_API_URL))
        self.api_url_edit = QLineEdit(self.config.get("api_url", ""))
        self.api_url_edit.setPlaceholderText(
            "http://localhost:11434/v1/chat/completions"
        )
        lay.addWidget(self.api_url_edit)

        quick = QHBoxLayout()
        quick.addWidget(QLabel("Быстрое заполнение:"))
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
        lay.addLayout(quick)

        # --- API-ключ
        lay.addWidget(self._row_with_hint(
            "API-ключ (облаку нужен, локальной Ollama — нет):", HINT_API_KEY
        ))
        self.api_key_edit = QLineEdit(self.config.get("api_key", ""))
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        lay.addWidget(self.api_key_edit)

        # --- Модель и загрузка списка
        lay.addWidget(self._row_with_hint("Имя модели:", HINT_MODEL))
        model_row = QHBoxLayout()
        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        self.model_combo.setCurrentText(self.config.get("model_name", ""))
        model_row.addWidget(self.model_combo, stretch=1)
        self.load_models_btn = QPushButton("Загрузить список моделей")
        self.load_models_btn.setToolTip(HINT_LOAD_MODELS)
        self.load_models_btn.clicked.connect(self._load_models)
        model_row.addWidget(self.load_models_btn)
        lay.addLayout(model_row)

        # --- Temperature
        lay.addSpacing(8)
        t_head = QHBoxLayout()
        t_label = QLabel("Temperature — Креативность:")
        t_label.setToolTip(TEMPERATURE_HINT)
        t_head.addWidget(t_label)
        t_head.addWidget(_hint(TEMPERATURE_HINT))
        t_head.addStretch(1)
        lay.addLayout(t_head)

        t_row = QHBoxLayout()
        self.temp_slider = QSlider(Qt.Orientation.Horizontal)
        self.temp_slider.setRange(0, 150)  # 0.00–1.50
        self.temp_slider.setValue(
            int(round(float(self.config.get("temperature", 0.3)) * 100))
        )
        self.temp_value_label = QLabel(f"{self.temp_slider.value() / 100:.2f}")
        self.temp_value_label.setObjectName("ValueLabel")
        self.temp_slider.valueChanged.connect(
            lambda value: self.temp_value_label.setText(f"{value / 100:.2f}")
        )
        t_row.addWidget(self.temp_slider, stretch=1)
        t_row.addWidget(self.temp_value_label)
        lay.addLayout(t_row)
        lay.addWidget(self._caption(
            "0.1–0.3 — строго и точно · 0.6–0.8 — живой литературный язык · выше 1.0 — фантазии"
        ))

        # --- Top-P
        p_head = QHBoxLayout()
        p_label = QLabel("Top-P — Словарь выборки:")
        p_label.setToolTip(TOP_P_HINT)
        p_head.addWidget(p_label)
        p_head.addWidget(_hint(TOP_P_HINT))
        p_head.addStretch(1)
        lay.addLayout(p_head)

        p_row = QHBoxLayout()
        self.top_p_slider = QSlider(Qt.Orientation.Horizontal)
        self.top_p_slider.setRange(10, 100)  # 0.10–1.00
        self.top_p_slider.setValue(
            int(round(float(self.config.get("top_p", 0.9)) * 100))
        )
        self.top_p_value_label = QLabel(f"{self.top_p_slider.value() / 100:.2f}")
        self.top_p_value_label.setObjectName("ValueLabel")
        self.top_p_slider.valueChanged.connect(
            lambda value: self.top_p_value_label.setText(f"{value / 100:.2f}")
        )
        p_row.addWidget(self.top_p_slider, stretch=1)
        p_row.addWidget(self.top_p_value_label)
        lay.addLayout(p_row)
        lay.addWidget(self._caption(
            "0.9 — баланс качества и разнообразия · 0.5 — только обычные слова"
        ))

        # --- Сохранить
        lay.addStretch(1)
        save_row = QHBoxLayout()
        save_row.addStretch(1)
        save_btn = QPushButton("Сохранить параметры ИИ")
        save_btn.clicked.connect(self._save_ai_tab)
        save_row.addWidget(save_btn)
        lay.addLayout(save_row)
        return page

    def _apply_api_preset(self, title: str) -> None:
        """Кнопки быстрого заполнения: подставить адрес сервиса."""
        url = API_PRESETS.get(title)
        if url:
            self.api_url_edit.setText(url)
            self._status(f"Подставлен адрес: {title}. Нажмите «Сохранить параметры ИИ».")

    def _save_ai_tab(self) -> None:
        """Сохраняет параметры ИИ из вкладки 1 в config.json."""
        api_url = self.api_url_edit.text().strip()
        model = self.model_combo.currentText().strip()
        if not api_url:
            self._status("Адрес API не может быть пустым.", error=True)
            return
        if not model:
            self._status("Укажите имя модели.", error=True)
            return
        self.config.update({
            "api_url": api_url,
            "api_key": self.api_key_edit.text().strip(),
            "model_name": model,
            "temperature": self.temp_slider.value() / 100,
            "top_p": self.top_p_slider.value() / 100,
        })
        self._dirty = False
        self._status("Параметры ИИ сохранены ✓")

    # ================== ВКЛАДКА 2: Мои Промпты (Пресеты) ======================
    def _build_prompts_tab(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(10)

        body = QHBoxLayout()
        body.setSpacing(14)

        # Слева — список пресетов и кнопки работы с ними.
        left_col = QVBoxLayout()
        left_col.setSpacing(8)
        left_col.addWidget(QLabel("Список пресетов:"))
        self.preset_list = QListWidget()
        self.preset_list.itemSelectionChanged.connect(self._load_selected_preset)
        left_col.addWidget(self.preset_list, stretch=1)
        add_btn = QPushButton("Добавить пресет")
        add_btn.clicked.connect(self._add_preset)
        del_btn = QPushButton("Удалить")
        del_btn.setObjectName("ClearButton")
        del_btn.clicked.connect(self._delete_preset)
        left_col.addWidget(add_btn)
        left_col.addWidget(del_btn)

        # Справа — редактор названия и текста системного промпта.
        right_col = QVBoxLayout()
        right_col.setSpacing(8)
        right_col.addWidget(QLabel("Название пресета:"))
        self.preset_name_edit = QLineEdit()
        right_col.addWidget(self.preset_name_edit)
        right_col.addWidget(
            QLabel("Системный промпт (модель читает его перед переводом):")
        )
        self.preset_text_edit = QTextEdit()
        self.preset_text_edit.setPlaceholderText(
            "Ты — профессиональный переводчик. Опиши здесь, как именно переводить…"
        )
        right_col.addWidget(self.preset_text_edit, stretch=1)
        save_btn = QPushButton("Сохранить")
        save_btn.clicked.connect(self._save_current_preset)
        right_col.addWidget(save_btn, 0, Qt.AlignmentFlag.AlignRight)

        body.addLayout(left_col, stretch=1)
        body.addLayout(right_col, stretch=2)
        lay.addLayout(body, stretch=1)
        lay.addWidget(self._build_cheat_sheet())

        self._populate_preset_list()
        return page

    @staticmethod
    def _build_cheat_sheet() -> QFrame:
        """Шпаргалка: как писать хорошие промпты (прямо в интерфейсе)."""
        frame = QFrame()
        frame.setObjectName("CheatSheet")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(4)
        title = QLabel("Шпаргалка: как писать хорошие промпты для перевода и рерайта")
        title.setObjectName("CheatSheetTitle")
        lay.addWidget(title)
        body = QLabel(CHEAT_SHEET)
        body.setObjectName("CheatSheetBody")
        body.setWordWrap(True)
        lay.addWidget(body)
        return frame

    def _populate_preset_list(self) -> None:
        """Заполняет список пресетов и выделяет активный."""
        self.preset_list.blockSignals(True)
        self.preset_list.clear()
        self.preset_list.addItems(list(self.config.get("prompts", {}).keys()))
        active = self.config.get("active_prompt_name", "")
        row = 0
        for i in range(self.preset_list.count()):
            if self.preset_list.item(i).text() == active:
                row = i
                break
        if self.preset_list.count():
            self.preset_list.setCurrentRow(row)
        self.preset_list.blockSignals(False)
        self._load_selected_preset()

    def _load_selected_preset(self) -> None:
        """Выбор пресета в списке — загружаем его в редактор справа."""
        item = self.preset_list.currentItem()
        if item is None:
            name, text = "", ""
        else:
            name = item.text()
            text = self.config.get_prompt(name) or ""
        # Программная установка не должна помечать окно «грязным».
        self.preset_name_edit.blockSignals(True)
        self.preset_text_edit.blockSignals(True)
        self.preset_name_edit.setText(name)
        self.preset_text_edit.setPlainText(text)
        self.preset_name_edit.blockSignals(False)
        self.preset_text_edit.blockSignals(False)

    def _add_preset(self) -> None:
        """«Добавить пресет»: создаём черновик с уникальным именем."""
        names = set(self.config.get("prompts", {}).keys())
        name, n = "Новый пресет", 2
        while name in names:
            name = f"Новый пресет {n}"
            n += 1
        self.config.set_prompt(
            name,
            "Ты — профессиональный переводчик. Опиши здесь, как переводить: "
            "язык, тон и что вернуть в ответе.",
        )
        self.preset_list.addItem(name)
        self.preset_list.setCurrentRow(self.preset_list.count() - 1)
        self.prompts_changed.emit()
        self._status(f"Пресет «{name}» добавлен — отредактируйте и нажмите «Сохранить».")

    def _delete_preset(self) -> None:
        """«Удалить»: убираем выбранный пресет из config.json."""
        item = self.preset_list.currentItem()
        if item is None:
            self._status("Сначала выберите пресет в списке.", error=True)
            return
        name = item.text()
        prompts = dict(self.config.get("prompts", {}))
        if name not in prompts:
            return
        if len(prompts) == 1:
            self._status("Нельзя удалить последний пресет.", error=True)
            return
        del prompts[name]
        updates = {"prompts": prompts}
        if self.config.get("active_prompt_name") == name:
            updates["active_prompt_name"] = next(iter(prompts))
        self.config.update(updates)
        row = self.preset_list.currentRow()
        self.preset_list.takeItem(row)
        if self.preset_list.count():
            self.preset_list.setCurrentRow(min(row, self.preset_list.count() - 1))
        self.prompts_changed.emit()
        self._status(f"Пресет «{name}» удалён.")

    def _save_current_preset(self) -> None:
        """«Сохранить»: записываем название и текст пресета в config.json."""
        name = self.preset_name_edit.text().strip()
        text = self.preset_text_edit.toPlainText().strip()
        if not name:
            self._status("Укажите название пресета.", error=True)
            return
        if not text:
            self._status("Промпт не может быть пустым.", error=True)
            return
        item = self.preset_list.currentItem()
        old_name = item.text() if item else ""
        prompts = dict(self.config.get("prompts", {}))
        if name != old_name and name in prompts:
            self._status(f"Пресет с именем «{name}» уже существует.", error=True)
            return
        if old_name and old_name in prompts and name != old_name:
            del prompts[old_name]  # переименовали — старое имя убираем
        prompts[name] = text
        updates = {"prompts": prompts}
        if self.config.get("active_prompt_name") == old_name:
            updates["active_prompt_name"] = name  # активный переименован
        self.config.update(updates)
        if item:
            item.setText(name)
        self.prompts_changed.emit()
        self._dirty = False
        self._status(f"Пресет «{name}» сохранён ✓")

    # ============ ВКЛАДКА 3: Хоткеи и Обычный переводчик ======================
    def _build_hotkeys_tab(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(10)

        # --- Глобальный хоткей
        lay.addWidget(self._row_with_hint("Глобальный хоткей мини-окна:", HINT_HOTKEY))
        hot_row = QHBoxLayout()
        self.hotkey_edit = QLineEdit(self.config.get("hotkey", "alt+q"))
        hot_row.addWidget(self.hotkey_edit, stretch=1)
        self.record_btn = QPushButton("Записать нажатие")
        self.record_btn.clicked.connect(self._toggle_recording)
        hot_row.addWidget(self.record_btn)
        lay.addLayout(hot_row)
        lay.addWidget(self._caption(
            "Нажмите «Записать нажатие», затем — нужное сочетание клавиш "
            "(запись работает в любом месте системы)"
        ))

        # --- Движок обычного перевода
        lay.addSpacing(8)
        lay.addWidget(self._row_with_hint("Движок обычного перевода:", HINT_ENGINE))
        self.engine_combo = QComboBox()
        self.engine_combo.addItem("Google (бесплатно, без ключа)", "google")
        self.engine_combo.addItem("DeepL (качественнее, нужен API-ключ)", "deepl")
        current_engine = self.config.get("standard_engine", "google")
        index = self.engine_combo.findData(current_engine)
        self.engine_combo.setCurrentIndex(max(index, 0))
        self.engine_combo.currentIndexChanged.connect(self._on_engine_changed)
        lay.addWidget(self.engine_combo)

        self.deepl_key_edit = QLineEdit(self.config.get("deepl_api_key", ""))
        self.deepl_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.deepl_key_edit.setPlaceholderText(
            "DeepL API-ключ (бесплатный тариф на deepl.com)"
        )
        self.deepl_key_edit.setToolTip(
            "Ключ используется только движком DeepL.\n"
            "Получите бесплатно: deepl.com → «API для разработчиков»."
        )
        lay.addWidget(self.deepl_key_edit)
        self._on_engine_changed()  # поле ключа активно только при движке DeepL

        # --- Целевой язык
        lay.addWidget(self._row_with_hint("Целевой язык перевода:", HINT_TARGET_LANG))
        self.lang_combo = QComboBox()
        self.lang_combo.setEditable(True)
        self.lang_combo.addItems(LANGUAGES)
        self.lang_combo.setCurrentText(self.config.get("target_lang", "ru"))
        lay.addWidget(self.lang_combo)

        lay.addStretch(1)
        save_row = QHBoxLayout()
        save_row.addStretch(1)
        save_btn = QPushButton("Сохранить настройки")
        save_btn.setToolTip("Хоткей перерегистрируется сразу — без перезапуска программы")
        save_btn.clicked.connect(self._save_common_tab)
        save_row.addWidget(save_btn)
        lay.addLayout(save_row)
        return page

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

    # ============ Сохранение, модели, статусы и события окна ==================
    def _save_common_tab(self) -> None:
        """Сохраняет хоткей и настройки обычного перевода (вкладка 3)."""
        engine = self.engine_combo.currentData() or "google"
        target = self.lang_combo.currentText().strip().lower()
        if not target:
            self._status("Укажите целевой язык перевода.", error=True)
            return
        self.config.update({
            "standard_engine": engine,
            "target_lang": target,
            "deepl_api_key": self.deepl_key_edit.text().strip(),
        })

        new_hotkey = self.hotkey_edit.text().strip().lower()
        old_hotkey = self.config.get("hotkey", "")
        if new_hotkey and new_hotkey != old_hotkey:
            if self.hotkey_manager is None:
                # Менеджера нет (тестовое окружение) — пишем только в конфиг.
                self.config.set("hotkey", new_hotkey)
                self._status("Сохранено ✓. Хоткей применится после перезапуска.")
            elif self.hotkey_manager.set_hotkey(new_hotkey):
                # Перерегистрируем СРАЗУ — без перезапуска приложения.
                self.config.set("hotkey", new_hotkey)
                self.hotkey_changed.emit(new_hotkey)
                self._status(f"Сохранено ✓. Хоткей «{new_hotkey}» уже активен.")
            else:
                self.hotkey_edit.setText(old_hotkey)
                self._status(
                    f"Сочетание «{new_hotkey}» не зарегистрировалось — "
                    "оставил прежний хоткей.",
                    error=True,
                )
                return
        else:
            self._status("Настройки сохранены ✓")
        self._dirty = False

    def _load_models(self) -> None:
        """Кнопка «Загрузить список моделей»: GET /api/tags локальной Ollama."""
        api_url = self.api_url_edit.text().strip()
        if "localhost" in api_url or "127.0.0.1" in api_url:
            base = api_url.split("/v1")[0].rstrip("/")
        else:
            base = "http://localhost:11434"
        self.load_models_btn.setEnabled(False)
        self._status(f"Запрашиваю модели Ollama: {base}/api/tags…")
        self._model_worker = ModelListWorker(base)
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
        """Тёмный заголовок окна сразу после показа (Windows 10/11)."""
        super().showEvent(event)
        apply_dark_title_bar(self)

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
        # Прерываем незавершённую запись хоткея и фоновую загрузку моделей.
        if self._recorder is not None and self._recorder.isRunning():
            self._recorder.cancel()
            self._recorder.wait(1000)
        if self._model_worker is not None and self._model_worker.isRunning():
            self._model_worker.wait(2000)
        super().closeEvent(event)
