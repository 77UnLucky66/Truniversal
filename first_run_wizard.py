"""
first_run_wizard.py — Мастер первоначальной настройки (Этап 9.4).

Пошаговый мастер для новых пользователей:
  1. Выбор сценария: Локальная Ollama / Облачный ИИ / Обычный переводчик.
  2. Настройка подключения и модели с проверкой связи.
  3. Выбор языков по умолчанию (исходный, целевой, резервный).
  4. Краткое обучение: хоткей, работа в трее, вызов мини-окна.
  
Без эмодзи, с возможностью пропуска на любом этапе и флагом first_run_completed.
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (QButtonGroup, QComboBox, QDialog, QFrame,
                             QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                             QMessageBox, QPushButton, QRadioButton,
                             QStackedWidget, QVBoxLayout, QWidget)

from api_helpers import normalize_chat_url
from config import ConfigManager
from languages import get_supported_languages
from styles import repolish
from workers import ConnectionCheckWorker, ModelListWorker

CLOUD_PROVIDERS = {
    "OpenRouter": {
        "url": "https://openrouter.ai/api/v1/chat/completions",
        "models": ["deepseek/deepseek-chat", "openai/gpt-4o-mini", "anthropic/claude-3.5-sonnet", "meta-llama/llama-3.1-8b-instruct"],
        "type": "custom",
    },
    "OpenAI": {
        "url": "https://api.openai.com/v1/chat/completions",
        "models": ["gpt-4o-mini", "gpt-4o"],
        "type": "openai",
    },
    "DeepSeek": {
        "url": "https://api.deepseek.com/chat/completions",
        "models": ["deepseek-chat", "deepseek-reasoner"],
        "type": "deepseek",
    },
    "Groq": {
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "models": ["llama-3.1-8b-instant", "llama-3.3-70b-versatile"],
        "type": "custom",
    },
}


class FirstRunWizard(QDialog):
    """Мастер первоначальной настройки Truniversal."""

    wizard_finished = pyqtSignal()

    def __init__(self, config: ConfigManager, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("Truniversal — Первоначальная настройка")
        self.resize(680, 520)
        self.setMinimumSize(600, 480)
        self.setModal(True)

        self._check_worker: Optional[ConnectionCheckWorker] = None
        self._models_worker: Optional[ModelListWorker] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)

        # Стек шагов
        self.stack = QStackedWidget(self)
        self.stack.addWidget(self._create_step1_scenario())
        self.stack.addWidget(self._create_step2_connection())
        self.stack.addWidget(self._create_step3_languages())
        self.stack.addWidget(self._create_step4_guide())
        layout.addWidget(self.stack, stretch=1)

        # Нижняя панель навигации
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        self.skip_btn = QPushButton("Пропустить")
        self.skip_btn.setObjectName("SecondaryButton")
        self.skip_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.skip_btn.setToolTip("Завершить мастер сейчас с настройками по умолчанию")
        self.skip_btn.clicked.connect(self._skip_wizard)
        btn_row.addWidget(self.skip_btn)

        btn_row.addStretch(1)

        self.back_btn = QPushButton("Назад")
        self.back_btn.setObjectName("SecondaryButton")
        self.back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.back_btn.clicked.connect(self._prev_step)
        self.back_btn.setEnabled(False)
        btn_row.addWidget(self.back_btn)

        self.next_btn = QPushButton("Далее")
        self.next_btn.setObjectName("PrimaryButton")
        self.next_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.next_btn.clicked.connect(self._next_step)
        btn_row.addWidget(self.next_btn)

        layout.addLayout(btn_row)

    # ---------------- 1. Шаг 1: Сценарий использования ---------------------
    def _create_step1_scenario(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(14)

        title = QLabel("Добро пожаловать в Truniversal")
        title.setObjectName("SectionTitle")
        lay.addWidget(title)

        desc = QLabel(
            "Truniversal — это быстрый помощник переводчика для Windows. Выделите текст в любой программе, "
            "нажмите хоткей и мгновенно получите качественный перевод или редактирование от ИИ.\n\n"
            "Выберите предпочтительный вариант работы для быстрого старта:"
        )
        desc.setObjectName("CaptionLabel")
        desc.setWordWrap(True)
        lay.addWidget(desc)

        self.scenario_group = QButtonGroup(self)

        # Опция 1: Ollama
        self.sc_ollama = QRadioButton("Локальный ИИ (Ollama)")
        self.sc_ollama.setChecked(True)
        self.scenario_group.addButton(self.sc_ollama, 0)
        lay.addWidget(self.sc_ollama)

        sc_ollama_desc = QLabel("  Полная конфиденциальность: текст не покидает ваш компьютер, без ключей и абонентской платы.")
        sc_ollama_desc.setObjectName("CaptionLabel")
        lay.addWidget(sc_ollama_desc)

        # Опция 2: Облачный ИИ
        self.sc_cloud = QRadioButton("Облачный ИИ (OpenRouter, OpenAI, DeepSeek, Groq)")
        self.scenario_group.addButton(self.sc_cloud, 1)
        lay.addWidget(self.sc_cloud)

        sc_cloud_desc = QLabel("  Максимальное качество и скорость. Требуется API-ключ выбранного провайдера.")
        sc_cloud_desc.setObjectName("CaptionLabel")
        lay.addWidget(sc_cloud_desc)

        # Опция 3: Обычный переводчик
        self.sc_std = QRadioButton("Обычный переводчик (Google / DeepL)")
        self.scenario_group.addButton(self.sc_std, 2)
        lay.addWidget(self.sc_std)

        sc_std_desc = QLabel("  Классический строчный перевод без нейросетей. Бесплатно и не требует настройки ИИ.")
        sc_std_desc.setObjectName("CaptionLabel")
        lay.addWidget(sc_std_desc)

        lay.addStretch(1)
        return w

    # ---------------- 2. Шаг 2: Подключение и модель ----------------------
    def _create_step2_connection(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(12)

        title = QLabel("Параметры подключения и модель")
        title.setObjectName("SectionTitle")
        lay.addWidget(title)

        # Блок для Ollama
        self.ollama_box = QFrame()
        ollama_lay = QVBoxLayout(self.ollama_box)
        ollama_lay.setContentsMargins(0, 0, 0, 0)
        ollama_lay.setSpacing(8)

        ollama_lay.addWidget(QLabel("Адрес сервера Ollama:"))
        self.ollama_url_edit = QLineEdit("http://localhost:11434/v1/chat/completions")
        ollama_lay.addWidget(self.ollama_url_edit)

        ollama_lay.addWidget(QLabel("Установленная модель:"))
        model_row = QHBoxLayout()
        self.ollama_model_combo = QComboBox()
        self.ollama_model_combo.setEditable(True)
        self.ollama_model_combo.addItem("llama3")
        self.ollama_model_combo.addItem("qwen2.5:7b")
        model_row.addWidget(self.ollama_model_combo, stretch=1)

        self.refresh_models_btn = QPushButton("Найти модели")
        self.refresh_models_btn.setObjectName("SecondaryButton")
        self.refresh_models_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.refresh_models_btn.clicked.connect(self._fetch_ollama_models)
        model_row.addWidget(self.refresh_models_btn)
        ollama_lay.addLayout(model_row)

        lay.addWidget(self.ollama_box)

        # Блок для Cloud
        self.cloud_box = QFrame()
        cloud_lay = QVBoxLayout(self.cloud_box)
        cloud_lay.setContentsMargins(0, 0, 0, 0)
        cloud_lay.setSpacing(8)

        cloud_lay.addWidget(QLabel("Облачный провайдер:"))
        self.cloud_provider_combo = QComboBox()
        for p in CLOUD_PROVIDERS.keys():
            self.cloud_provider_combo.addItem(p)
        self.cloud_provider_combo.currentTextChanged.connect(self._on_cloud_provider_changed)
        cloud_lay.addWidget(self.cloud_provider_combo)

        cloud_lay.addWidget(QLabel("API-ключ:"))
        self.cloud_key_edit = QLineEdit()
        self.cloud_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.cloud_key_edit.setPlaceholderText("Вставьте ваш API-ключ...")
        cloud_lay.addWidget(self.cloud_key_edit)

        cloud_lay.addWidget(QLabel("Модель:"))
        self.cloud_model_combo = QComboBox()
        self.cloud_model_combo.setEditable(True)
        self._populate_cloud_models("OpenRouter")
        cloud_lay.addWidget(self.cloud_model_combo)

        self.cloud_box.hide()
        lay.addWidget(self.cloud_box)

        # Блок для Обычного переводчика
        self.std_box = QFrame()
        std_lay = QVBoxLayout(self.std_box)
        std_lay.setContentsMargins(0, 0, 0, 0)
        std_lay.setSpacing(8)

        std_lay.addWidget(QLabel("Движок:"))
        self.std_engine_combo = QComboBox()
        self.std_engine_combo.addItem("Google (бесплатно, без ограничений)", "google")
        self.std_engine_combo.addItem("DeepL (требуется API-ключ)", "deepl")
        std_lay.addWidget(self.std_engine_combo)

        std_info = QLabel("Движок Google работает сразу и не требует ввода ключей.")
        std_info.setObjectName("CaptionLabel")
        std_lay.addWidget(std_info)

        self.std_box.hide()
        lay.addWidget(self.std_box)

        # Кнопка проверки связи
        chk_row = QHBoxLayout()
        self.check_conn_btn = QPushButton("Проверить подключение")
        self.check_conn_btn.setObjectName("SecondaryButton")
        self.check_conn_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.check_conn_btn.clicked.connect(self._test_connection)
        chk_row.addWidget(self.check_conn_btn)

        self.conn_status_label = QLabel("")
        self.conn_status_label.setObjectName("CaptionLabel")
        self.conn_status_label.setWordWrap(True)
        chk_row.addWidget(self.conn_status_label, stretch=1)
        lay.addLayout(chk_row)

        lay.addStretch(1)
        return w

    def _on_cloud_provider_changed(self, provider: str) -> None:
        self._populate_cloud_models(provider)

    def _populate_cloud_models(self, provider: str) -> None:
        self.cloud_model_combo.clear()
        cfg = CLOUD_PROVIDERS.get(provider, {})
        for m in cfg.get("models", []):
            self.cloud_model_combo.addItem(m)

    def _fetch_ollama_models(self) -> None:
        url = self.ollama_url_edit.text().strip()
        self.refresh_models_btn.setEnabled(False)
        self.conn_status_label.setText("Поиск локальных моделей...")
        self._models_worker = ModelListWorker(url, api_key="", provider_type="custom")
        self._models_worker.models_loaded.connect(self._on_models_loaded)
        self._models_worker.models_failed.connect(self._on_models_failed)
        self._models_worker.start()

    def _on_models_loaded(self, models: list) -> None:
        self.refresh_models_btn.setEnabled(True)
        self.ollama_model_combo.clear()
        for m in models:
            self.ollama_model_combo.addItem(m)
        self.conn_status_label.setText(f"Найдено моделей: {len(models)}")

    def _on_models_failed(self, err: str) -> None:
        self.refresh_models_btn.setEnabled(True)
        self.conn_status_label.setText(f"Не удалось получить список: {err}")

    def _test_connection(self) -> None:
        sc_id = self.scenario_group.checkedId()
        if sc_id == 2:
            self.conn_status_label.setText("Обычный переводчик готов к работе.")
            return

        if sc_id == 0:
            url = normalize_chat_url(self.ollama_url_edit.text().strip())
            key = ""
            model = self.ollama_model_combo.currentText().strip()
            ptype = "custom"
        else:
            pname = self.cloud_provider_combo.currentText()
            pdata = CLOUD_PROVIDERS.get(pname, {})
            url = pdata.get("url", "")
            key = self.cloud_key_edit.text().strip()
            model = self.cloud_model_combo.currentText().strip()
            ptype = pdata.get("type", "custom")

        self.check_conn_btn.setEnabled(False)
        self.conn_status_label.setText("Проверка связи...")
        self._check_worker = ConnectionCheckWorker(
            api_url=url,
            api_key=key,
            model_name=model,
            provider_type=ptype,
            timeout_connect=8,
            timeout_request=12,
        )
        self._check_worker.check_finished.connect(self._on_check_finished)
        self._check_worker.start()

    def _on_check_finished(self, success: bool, msg: str, latency: float) -> None:
        self.check_conn_btn.setEnabled(True)
        if success:
            self.conn_status_label.setText(f"Подключение успешно ({int(latency)} мс): {msg}")
        else:
            self.conn_status_label.setText(f"Ошибка проверки: {msg}")

    # ---------------- 3. Шаг 3: Языки по умолчанию ------------------------
    def _create_step3_languages(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(14)

        title = QLabel("Направление перевода по умолчанию")
        title.setObjectName("SectionTitle")
        lay.addWidget(title)

        desc = QLabel(
            "Truniversal умеет автоматически определять исходный язык текста. "
            "Если текст уже на целевом языке, сработает автоматический переворот на резервный язык."
        )
        desc.setObjectName("CaptionLabel")
        desc.setWordWrap(True)
        lay.addWidget(desc)

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(10)

        grid.addWidget(QLabel("Исходный язык:"), 0, 0)
        self.lang_src_combo = QComboBox()
        self.lang_src_combo.addItem("Автоопределение (auto)", "auto")
        for lang in get_supported_languages():
            self.lang_src_combo.addItem(f"{lang.name_ru} ({lang.code})", lang.code)
        grid.addWidget(self.lang_src_combo, 0, 1)

        grid.addWidget(QLabel("Целевой язык:"), 1, 0)
        self.lang_tgt_combo = QComboBox()
        for lang in get_supported_languages():
            self.lang_tgt_combo.addItem(f"{lang.name_ru} ({lang.code})", lang.code)
        grid.addWidget(self.lang_tgt_combo, 1, 1)

        grid.addWidget(QLabel("Резервный язык:"), 2, 0)
        self.lang_fallback_combo = QComboBox()
        for lang in get_supported_languages():
            self.lang_fallback_combo.addItem(f"{lang.name_ru} ({lang.code})", lang.code)
        grid.addWidget(self.lang_fallback_combo, 2, 1)

        # Выставим значения из текущей конфигурации
        cur_src = self.config.get("source_lang", "auto")
        cur_tgt = self.config.get("target_lang", "ru")
        cur_fb = self.config.get("fallback_target_lang", "en")

        idx_src = self.lang_src_combo.findData(cur_src)
        if idx_src >= 0:
            self.lang_src_combo.setCurrentIndex(idx_src)

        idx_tgt = self.lang_tgt_combo.findData(cur_tgt)
        if idx_tgt >= 0:
            self.lang_tgt_combo.setCurrentIndex(idx_tgt)

        idx_fb = self.lang_fallback_combo.findData(cur_fb)
        if idx_fb >= 0:
            self.lang_fallback_combo.setCurrentIndex(idx_fb)

        lay.addLayout(grid)
        lay.addStretch(1)
        return w

    # ---------------- 4. Шаг 4: Быстрый старт и подсказки -----------------
    def _create_step4_guide(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(14)

        title = QLabel("Готово! Как пользоваться Truniversal")
        title.setObjectName("SectionTitle")
        lay.addWidget(title)

        hotkey = self.config.get("hotkey", "alt+q")

        steps = [
            f"1. Выделение текста: Выделите фрагмент в браузере, редакторе кода или мессенджере.",
            f"2. Вызов перевода: Нажмите сочетание клавиш «{hotkey}».",
            f"3. Вставка результата: Нажмите «Заменить в тексте», чтобы вставить готовый ответ на место выделения.",
            f"4. Значок в трее: Приложение работает в фоне возле часов. Правый клик по иконке открывает меню быстрых действий.",
        ]

        for s in steps:
            lbl = QLabel(s)
            lbl.setObjectName("CaptionLabel")
            lbl.setWordWrap(True)
            lay.addWidget(lbl)

        note = QLabel(
            "Вы в любой момент можете изменить эти параметры, создать профили моделей и настроить проекты в окне настроек."
        )
        note.setObjectName("CaptionLabel")
        note.setWordWrap(True)
        lay.addWidget(note)

        lay.addStretch(1)
        return w

    # ---------------- Навигация -------------------------------------------
    def _next_step(self) -> None:
        idx = self.stack.currentIndex()
        if idx == 0:
            # Обновляем видимость блоков подключения на шаге 2
            sc_id = self.scenario_group.checkedId()
            self.ollama_box.setVisible(sc_id == 0)
            self.cloud_box.setVisible(sc_id == 1)
            self.std_box.setVisible(sc_id == 2)
            self.check_conn_btn.setVisible(sc_id != 2)
            self.conn_status_label.setText("")
            self.stack.setCurrentIndex(1)
            self.back_btn.setEnabled(True)
        elif idx == 1:
            self.stack.setCurrentIndex(2)
        elif idx == 2:
            self.stack.setCurrentIndex(3)
            self.next_btn.setText("Завершить и начать работу")
        elif idx == 3:
            self._save_and_finish()

    def _prev_step(self) -> None:
        idx = self.stack.currentIndex()
        if idx > 0:
            self.stack.setCurrentIndex(idx - 1)
            self.next_btn.setText("Далее")
            if idx - 1 == 0:
                self.back_btn.setEnabled(False)

    def _skip_wizard(self) -> None:
        """Пользователь решил пропустить настройку — отмечаем флаг и закрываем."""
        self.config.set_first_run_completed(True)
        self.wizard_finished.emit()
        self.accept()

    def _save_and_finish(self) -> None:
        """Сохраняем выбранные настройки и завершаем мастер."""
        sc_id = self.scenario_group.checkedId()

        if sc_id == 0:
            # Ollama
            self.config.set("mode", "ai")
            self.config.set("api_url", normalize_chat_url(self.ollama_url_edit.text().strip()))
            self.config.set("model_name", self.ollama_model_combo.currentText().strip() or "llama3")
            self.config.set("provider_type", "custom")
        elif sc_id == 1:
            # Cloud
            pname = self.cloud_provider_combo.currentText()
            pdata = CLOUD_PROVIDERS.get(pname, {})
            self.config.set("mode", "ai")
            self.config.set("api_url", pdata.get("url", ""))
            self.config.set("model_name", self.cloud_model_combo.currentText().strip())
            self.config.set("provider_type", pdata.get("type", "custom"))
            key = self.cloud_key_edit.text().strip()
            if key:
                self.config.set_api_key(key)
        else:
            # Standard
            self.config.set("mode", "standard")
            self.config.set("standard_engine", self.std_engine_combo.currentData())

        # Языки
        src_data = self.lang_src_combo.currentData()
        tgt_data = self.lang_tgt_combo.currentData()
        fb_data = self.lang_fallback_combo.currentData()

        if src_data:
            self.config.set("source_lang", src_data)
        if tgt_data:
            self.config.set("target_lang", tgt_data)
        if fb_data:
            self.config.set("fallback_target_lang", fb_data)

        self.config.set_first_run_completed(True)
        self.wizard_finished.emit()
        self.accept()
