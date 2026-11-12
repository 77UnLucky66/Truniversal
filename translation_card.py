"""
translation_card.py — карточка с результатом в ленте мини-окна (Этапы 2–6).

Карточка (QFrame) содержит:
  • исходный текст (с возможностью редактирования перед повтором);
  • бейджи применённого действия и ручной правки, кнопку удаления «x»;
  • результат перевода/рерайта (с поддержкой ручного редактирования);
  • панель нескольких вариантов (Вариант 1, 2, 3 с индивидуальными кнопками действий);
  • панель пословного сравнения оригинала и результата (Diff);
  • панель изменения промпта на лету;
  • компактную строку действий: направление (RU → EN, ⇄), «Сравнить»,
    «Повторить», «Заменить в тексте», «Скопировать», меню «⋯» (дополнительно),
    а также кнопку «Отмена» во время выполнения запроса.
"""

from __future__ import annotations

import os
import time
from typing import List, Optional, Tuple

import pyperclip
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QLineEdit, QMenu,
                             QPushButton, QTextEdit, QVBoxLayout, QWidget)

from languages import get_supported_languages
from styles import repolish
from text_diff import extract_text_variants, generate_word_diff_html

# Сколько символов исходника показывать в компактном превью (~2 строки)
MAX_SOURCE_PREVIEW_CHARS = 120

# Кадры текстовой анимации загрузки
LOADING_FRAMES = ("Думаю", "Думаю.", "Думаю..", "Думаю...")


class TranslationCard(QFrame):
    """Многофункциональная карточка результата в мини-окне (Этапы 2–6, 9)."""

    #: Запрос на повторный запуск перевода
    regenerate_requested = pyqtSignal()

    #: Запрос на вставку текста в исходное окно (может передавать выбранный вариант)
    replace_requested = pyqtSignal()

    #: Запрос на отмену выполняющегося запроса (Этап 6.6)
    cancel_requested = pyqtSignal()

    #: Запрос на удаление карточки (Этап 6.4)
    delete_requested = pyqtSignal()

    #: Запрос на повтор с изменённым промптом (Этап 6.4)
    prompt_regenerate_requested = pyqtSignal(str)

    #: Результат был отредактирован вручную пользователем (Этап 6, 7)
    result_edited = pyqtSignal(str)

    #: Для совместимости со старыми вызовами
    action_menu_requested = pyqtSignal()

    def __init__(self, source_text: str, result_text: Optional[str], parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")

        self.source_text: str = source_text or ""
        self.result_text: Optional[str] = result_text
        self.edited_text: Optional[str] = None
        self.history_id: Optional[int] = None
        self.action_id: str = ""
        self.action_name: str = ""
        self._variants: List[Tuple[str, str]] = []
        self._comparison_mode: bool = False
        self.technical_details: str = ""

        self._start_time: float = 0.0
        self._current_status: str = "idle"

        self.action_btn = None  # для обратной совместимости

        # Анимация загрузки
        self._loading = False
        self._frame_index = 0
        self._loading_timer = QTimer(self)
        self._loading_timer.setInterval(400)
        self._loading_timer.timeout.connect(self._advance_loading_frame)

        # Таймер возврата кнопки копирования
        self._copy_timer = QTimer(self)
        self._copy_timer.setSingleShot(True)
        self._copy_timer.setInterval(1000)
        self._copy_timer.timeout.connect(self._restore_copy_button)

        # Таймер прошедшего времени запроса (Этап 9.3)
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(200)
        self._status_timer.timeout.connect(self._update_status_elapsed)

        # Главный layout карточки
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(14, 12, 14, 12)
        self._layout.setSpacing(8)

        # ---------------- 1. Контейнер исходного текста (Этап 9.2) ------------
        self.source_container = QFrame()
        self.source_container.setObjectName("SourceContainer")
        src_cont_layout = QVBoxLayout(self.source_container)
        src_cont_layout.setContentsMargins(10, 8, 10, 8)
        src_cont_layout.setSpacing(6)

        # Верхняя строка контейнера (Оригинал, бейджи, кнопки ред. и удалить)
        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(6)

        self.source_header_label = QLabel("ОРИГИНАЛ")
        self.source_header_label.setObjectName("SourceHeaderLabel")
        top_row.addWidget(self.source_header_label)

        self.status_badge = QLabel("Ожидание")
        self.status_badge.setObjectName("CardStatusIdle")
        top_row.addWidget(self.status_badge)

        self.project_badge = QLabel("")
        self.project_badge.setObjectName("CardProjectBadge")
        self.project_badge.hide()
        top_row.addWidget(self.project_badge)

        self.action_badge = QLabel("")
        self.action_badge.setObjectName("CardActionBadge")
        self.action_badge.hide()
        top_row.addWidget(self.action_badge)

        self.edited_badge = QLabel("изменено")
        self.edited_badge.setObjectName("CardEditedBadge")
        self.edited_badge.setToolTip("Результат был отредактирован вручную")
        self.edited_badge.hide()
        top_row.addWidget(self.edited_badge)

        top_row.addStretch(1)

        self.edit_source_btn = QPushButton("ред.")
        self.edit_source_btn.setObjectName("CardSmallIconBtn")
        self.edit_source_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.edit_source_btn.setToolTip("Редактировать исходный текст перед повторным запросом (Этап 6.1)")
        self.edit_source_btn.clicked.connect(self.toggle_edit_source)
        top_row.addWidget(self.edit_source_btn)

        self.delete_btn = QPushButton("x")
        self.delete_btn.setObjectName("DeleteCardBtn")
        self.delete_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.delete_btn.setToolTip("Удалить эту карточку из ленты (Этап 6.4)")
        self.delete_btn.clicked.connect(self.delete_requested.emit)
        top_row.addWidget(self.delete_btn)

        src_cont_layout.addLayout(top_row)

        self.source_label = QLabel(self._preview(self.source_text))
        self.source_label.setObjectName("CardSourceLabel")
        self.source_label.setWordWrap(True)
        src_cont_layout.addWidget(self.source_label)

        self._layout.addWidget(self.source_container)

        # ---------------- 2. Панель редактирования исходного текста (6.1) ------
        self.source_edit_bar = QFrame()
        self.source_edit_bar.setObjectName("InlineEditorBar")
        src_edit_layout = QVBoxLayout(self.source_edit_bar)
        src_edit_layout.setContentsMargins(8, 8, 8, 8)
        src_edit_layout.setSpacing(6)

        self.source_edit_field = QTextEdit()
        self.source_edit_field.setObjectName("InlineTextEdit")
        self.source_edit_field.setPlaceholderText("Отредактируйте исходный текст...")
        self.source_edit_field.setMaximumHeight(80)
        src_edit_layout.addWidget(self.source_edit_field)

        src_btn_row = QHBoxLayout()
        src_btn_row.setSpacing(6)
        src_btn_row.addStretch(1)

        self.source_save_btn = QPushButton("Применить")
        self.source_save_btn.setObjectName("PrimaryButton")
        self.source_save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.source_save_btn.clicked.connect(self._save_source_text)
        src_btn_row.addWidget(self.source_save_btn)

        self.source_regen_btn = QPushButton("Повторить с этим текстом")
        self.source_regen_btn.setObjectName("SecondaryButton")
        self.source_regen_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.source_regen_btn.clicked.connect(self._save_source_and_regenerate)
        src_btn_row.addWidget(self.source_regen_btn)

        self.source_cancel_btn = QPushButton("Закрыть")
        self.source_cancel_btn.setObjectName("SecondaryButton")
        self.source_cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.source_cancel_btn.clicked.connect(lambda: self.source_edit_bar.hide())
        src_btn_row.addWidget(self.source_cancel_btn)

        src_edit_layout.addLayout(src_btn_row)
        self.source_edit_bar.hide()
        self._layout.addWidget(self.source_edit_bar)

        # ---------------- 3. Панель изменения промпта (6.4) --------------------
        self.prompt_edit_bar = QFrame()
        self.prompt_edit_bar.setObjectName("InlineEditorBar")
        prompt_edit_layout = QHBoxLayout(self.prompt_edit_bar)
        prompt_edit_layout.setContentsMargins(8, 6, 8, 6)
        prompt_edit_layout.setSpacing(6)

        self.prompt_edit_field = QLineEdit()
        self.prompt_edit_field.setObjectName("InlineLineEdit")
        self.prompt_edit_field.setPlaceholderText("Введите или измените инструкцию для модели...")
        self.prompt_edit_field.returnPressed.connect(self._submit_prompt_regenerate)
        prompt_edit_layout.addWidget(self.prompt_edit_field, stretch=1)

        self.prompt_submit_btn = QPushButton("Отправить")
        self.prompt_submit_btn.setObjectName("PrimaryButton")
        self.prompt_submit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.prompt_submit_btn.clicked.connect(self._submit_prompt_regenerate)
        prompt_edit_layout.addWidget(self.prompt_submit_btn)

        self.prompt_cancel_btn = QPushButton("x")
        self.prompt_cancel_btn.setObjectName("SecondaryButton")
        self.prompt_cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.prompt_cancel_btn.clicked.connect(lambda: self.prompt_edit_bar.hide())
        prompt_edit_layout.addWidget(self.prompt_cancel_btn)

        self.prompt_edit_bar.hide()
        self._layout.addWidget(self.prompt_edit_bar)

        # ---------------- 4. Результат: стандартный просмотр -------------------
        self.result_label = QLabel(
            result_text if result_text is not None else LOADING_FRAMES[0]
        )
        self.result_label.setObjectName("CardResultLabel")
        self.result_label.setWordWrap(True)
        self.result_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._layout.addWidget(self.result_label)

        # ---------------- 5. Панель редактирования результата (6.1) ------------
        self.result_edit_bar = QFrame()
        self.result_edit_bar.setObjectName("InlineEditorBar")
        res_edit_layout = QVBoxLayout(self.result_edit_bar)
        res_edit_layout.setContentsMargins(8, 8, 8, 8)
        res_edit_layout.setSpacing(6)

        self.result_edit_field = QTextEdit()
        self.result_edit_field.setObjectName("InlineTextEdit")
        self.result_edit_field.setPlaceholderText("Отредактируйте полученный ответ...")
        self.result_edit_field.setMaximumHeight(110)
        res_edit_layout.addWidget(self.result_edit_field)

        res_btn_row = QHBoxLayout()
        res_btn_row.setSpacing(6)
        res_btn_row.addStretch(1)

        self.result_save_btn = QPushButton("Сохранить правку")
        self.result_save_btn.setObjectName("PrimaryButton")
        self.result_save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.result_save_btn.clicked.connect(self._save_result_edit)
        res_btn_row.addWidget(self.result_save_btn)

        self.result_cancel_edit_btn = QPushButton("Отмена")
        self.result_cancel_edit_btn.setObjectName("SecondaryButton")
        self.result_cancel_edit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.result_cancel_edit_btn.clicked.connect(self._cancel_result_edit)
        res_btn_row.addWidget(self.result_cancel_edit_btn)

        res_edit_layout.addLayout(res_btn_row)
        self.result_edit_bar.hide()
        self._layout.addWidget(self.result_edit_bar)

        # ---------------- 6. Контейнер вариантов (6.2) -------------------------
        self.variants_container = QFrame()
        self.variants_container.setObjectName("VariantsContainer")
        self.variants_layout = QVBoxLayout(self.variants_container)
        self.variants_layout.setContentsMargins(0, 0, 0, 0)
        self.variants_layout.setSpacing(8)
        self.variants_container.hide()
        self._layout.addWidget(self.variants_container)

        # ---------------- 7. Панель сравнения оригинала и результата (6.3) ----
        self.comparison_panel = QFrame()
        self.comparison_panel.setObjectName("ComparisonPanel")
        comp_layout = QVBoxLayout(self.comparison_panel)
        comp_layout.setContentsMargins(10, 10, 10, 10)
        comp_layout.setSpacing(8)

        # Две колонки: оригинал и результат
        cols_row = QHBoxLayout()
        cols_row.setSpacing(8)

        orig_col = QVBoxLayout()
        self.comp_orig_title = QLabel("Оригинал:")
        self.comp_orig_title.setObjectName("DiffColHeader")
        orig_col.addWidget(self.comp_orig_title)
        self.comp_orig_box = QLabel("")
        self.comp_orig_box.setObjectName("DiffTextBox")
        self.comp_orig_box.setWordWrap(True)
        self.comp_orig_box.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        orig_col.addWidget(self.comp_orig_box)
        cols_row.addLayout(orig_col, stretch=1)

        res_col = QVBoxLayout()
        self.comp_res_title = QLabel("Результат:")
        self.comp_res_title.setObjectName("DiffColHeader")
        res_col.addWidget(self.comp_res_title)
        self.comp_res_box = QLabel("")
        self.comp_res_box.setObjectName("DiffTextBox")
        self.comp_res_box.setWordWrap(True)
        self.comp_res_box.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        res_col.addWidget(self.comp_res_box)
        cols_row.addLayout(res_col, stretch=1)

        comp_layout.addLayout(cols_row)

        # Блок пословных различий
        diff_hdr_row = QHBoxLayout()
        self.diff_header_label = QLabel("Пословные различия (Diff):")
        self.diff_header_label.setObjectName("DiffSectionHeader")
        diff_hdr_row.addWidget(self.diff_header_label)

        self.diff_stats_badge = QLabel("")
        self.diff_stats_badge.setObjectName("DiffStatsBadge")
        diff_hdr_row.addWidget(self.diff_stats_badge)
        diff_hdr_row.addStretch(1)
        comp_layout.addLayout(diff_hdr_row)

        self.diff_html_view = QLabel("")
        self.diff_html_view.setObjectName("DiffHtmlView")
        self.diff_html_view.setWordWrap(True)
        self.diff_html_view.setTextFormat(Qt.TextFormat.RichText)
        self.diff_html_view.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        comp_layout.addWidget(self.diff_html_view)

        self.comparison_panel.hide()
        self._layout.addWidget(self.comparison_panel)

        # Направление перевода (Этап 4)
        self.source_lang: Optional[str] = None
        self.target_lang: Optional[str] = None
        self.direction_badge: str = ""

        # ---------------- 8. Нижняя строка: кнопки действий --------------------
        row = QHBoxLayout()
        row.setSpacing(6)

        self.direction_btn = QPushButton("")
        self.direction_btn.setObjectName("DirectionBadge")
        self.direction_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.direction_btn.setToolTip("Текущее направление перевода. Кликните для выбора целевого языка.")
        self.direction_btn.clicked.connect(self._open_target_lang_menu)
        self.direction_btn.hide()
        row.addWidget(self.direction_btn)

        self.swap_btn = QPushButton("⇄")
        self.swap_btn.setObjectName("DirectionSwapBtn")
        self.swap_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.swap_btn.setToolTip("Поменять языки местами (перед нажатием «Повторить»)")
        self.swap_btn.clicked.connect(self.swap_direction)
        self.swap_btn.hide()
        row.addWidget(self.swap_btn)

        row.addStretch(1)

        # Кнопка отмены активного запроса (Этап 6.6)
        self.cancel_button = QPushButton("Отмена")
        self.cancel_button.setObjectName("CancelLoadingBtn")
        self.cancel_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_button.setToolTip("Отменить выполняющийся запрос к модели")
        self.cancel_button.clicked.connect(self.cancel_requested.emit)
        self.cancel_button.hide()
        row.addWidget(self.cancel_button)

        # Кнопка переключения сравнения (Этап 6.3)
        self.diff_btn = QPushButton("Сравнить")
        self.diff_btn.setObjectName("DiffToggleBtn")
        self.diff_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.diff_btn.setToolTip("Переключить отображение: Компактный вид ↔ Сравнение оригинала и результата с различиями")
        self.diff_btn.clicked.connect(self.toggle_comparison)
        self.diff_btn.hide()
        row.addWidget(self.diff_btn)

        self.regenerate_button = QPushButton("Повторить")
        self.regenerate_button.setObjectName("RegenerateButton")
        self.regenerate_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.regenerate_button.setToolTip("Сгенерировать результат заново")
        self.regenerate_button.clicked.connect(self.regenerate_requested.emit)
        row.addWidget(self.regenerate_button)

        self.replace_button = QPushButton("Заменить в тексте")
        self.replace_button.setObjectName("ReplaceButton")
        self.replace_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.replace_button.setToolTip("Безопасно вернуть фокус в исходное окно и вставить результат на место выделения (Ctrl+V)")
        self.replace_button.clicked.connect(lambda: self.replace_requested.emit())
        row.addWidget(self.replace_button)

        self.copy_button = QPushButton("Скопировать")
        self.copy_button.setObjectName("CopyButton")
        self.copy_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.copy_button.setToolTip("Скопировать результат в буфер обмена")
        self.copy_button.clicked.connect(self._copy_result)
        row.addWidget(self.copy_button)

        self.details_btn = QPushButton("Подробнее")
        self.details_btn.setObjectName("CardDetailsBtn")
        self.details_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.details_btn.setToolTip("Показать технические подробности ошибки (диагностика)")
        self.details_btn.clicked.connect(self._toggle_tech_details)
        self.details_btn.hide()
        row.addWidget(self.details_btn)

        self.more_menu_btn = QPushButton("⋯")
        self.more_menu_btn.setObjectName("MoreMenuBtn")
        self.more_menu_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.more_menu_btn.setToolTip("Дополнительные действия с карточкой (Этап 6.4)")
        self.more_menu_btn.clicked.connect(self._open_more_menu)
        row.addWidget(self.more_menu_btn)

        self._layout.addLayout(row)

        # Диагностическая панель подробностей (Этап 9.6)
        self.tech_details_frame = QFrame()
        self.tech_details_frame.setObjectName("CardTechnicalDetails")
        tech_lay = QVBoxLayout(self.tech_details_frame)
        tech_lay.setContentsMargins(10, 8, 10, 8)
        tech_lay.setSpacing(6)

        self.tech_details_text = QLabel("")
        self.tech_details_text.setObjectName("CardTechnicalDetailsText")
        self.tech_details_text.setWordWrap(True)
        self.tech_details_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        tech_lay.addWidget(self.tech_details_text)

        log_row = QHBoxLayout()
        log_row.addStretch(1)
        self.open_log_btn = QPushButton("Открыть файл журнала")
        self.open_log_btn.setObjectName("SecondaryButton")
        self.open_log_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.open_log_btn.clicked.connect(self._open_diag_log)
        log_row.addWidget(self.open_log_btn)
        tech_lay.addLayout(log_row)

        self.tech_details_frame.hide()
        self._layout.addWidget(self.tech_details_frame)

        if result_text is None:
            self.start_loading()

    # ----------------------------------------------------------------- превью
    @staticmethod
    def _preview(text: str) -> str:
        """Компактное превью исходника: склеиваем строки, обрезаем до ~2 строк."""
        flattened = " ".join(text.split())
        if len(flattened) > MAX_SOURCE_PREVIEW_CHARS:
            flattened = flattened[: MAX_SOURCE_PREVIEW_CHARS - 1].rstrip() + "…"
        return flattened

    def get_active_text(self) -> str:
        """Возвращает актуальный текст: отредактированный пользователем либо ответ модели."""
        if self.edited_text is not None:
            return self.edited_text
        return self.result_text or ""

    # ------------------------------------------------------------- копирование
    def _copy_result(self) -> None:
        """Копирует активный результат в буфер обмена."""
        text = self.get_active_text()
        self.copy_text(text)

    def copy_text(self, text: str) -> None:
        """Копирует указанный текст в буфер и показывает индикацию «Скопировано»."""
        if not text:
            return
        try:
            pyperclip.copy(text)
        except Exception:
            pass
        self.copy_button.setText("Скопировано")
        self.copy_button.setObjectName("CopyButtonDone")
        repolish(self.copy_button)
        self._copy_timer.start()

    def _restore_copy_button(self) -> None:
        self.copy_button.setText("Скопировать")
        self.copy_button.setObjectName("CopyButton")
        repolish(self.copy_button)

    # -------------------------------------------------- статусы и таймер (9.3)
    def _start_elapsed_timer(self) -> None:
        if self._start_time <= 0:
            self._start_time = time.monotonic()
        if not self._status_timer.isActive():
            self._status_timer.start()

    def _stop_elapsed_timer(self) -> None:
        self._status_timer.stop()

    def _update_status_elapsed(self) -> None:
        if self._start_time <= 0:
            return
        elapsed = time.monotonic() - self._start_time
        if self._current_status in ("generating", "генерация ответа", "генерация"):
            self.status_badge.setText(f"Генерация ответа ({elapsed:.1f} с)...")
        elif self._current_status in ("sending", "отправка запроса", "отправка"):
            self.status_badge.setText(f"Отправка запроса ({elapsed:.1f} с)...")
        elif self._current_status in ("capturing", "получение текста"):
            self.status_badge.setText(f"Получение текста ({elapsed:.1f} с)...")

    def set_status(self, state: str, details: str = "") -> None:
        """Обновляет статус операции в соответствии с этапами конвейера (Этап 9.3)."""
        raw = (state or "").lower().strip()
        self._current_status = raw

        if raw in ("idle", "ожидание"):
            self._stop_elapsed_timer()
            self._start_time = 0.0
            self.status_badge.setText("Ожидание")
            self.status_badge.setObjectName("CardStatusIdle")
        elif raw in ("capturing", "получение текста", "получение"):
            self._start_elapsed_timer()
            self.status_badge.setText("Получение текста...")
            self.status_badge.setObjectName("CardStatusCapturing")
        elif raw in ("sending", "отправка запроса", "отправка"):
            self._start_elapsed_timer()
            self.status_badge.setText("Отправка запроса...")
            self.status_badge.setObjectName("CardStatusSending")
        elif raw in ("generating", "генерация ответа", "генерация"):
            self._start_elapsed_timer()
            elapsed = time.monotonic() - self._start_time if self._start_time > 0 else 0.0
            if elapsed >= 1.5:
                self.status_badge.setText(f"Генерация ответа ({elapsed:.1f} с)...")
            else:
                self.status_badge.setText("Генерация ответа...")
            self.status_badge.setObjectName("CardStatusGenerating")
        elif raw in ("ready", "готово", "выполнено"):
            elapsed = time.monotonic() - self._start_time if self._start_time > 0 else 0.0
            self._stop_elapsed_timer()
            if elapsed >= 1.0:
                self.status_badge.setText(f"Готово ({elapsed:.1f} с)")
            else:
                self.status_badge.setText("Готово")
            self.status_badge.setObjectName("CardStatusReady")
        elif raw in ("error", "ошибка"):
            self._stop_elapsed_timer()
            self.status_badge.setText("Ошибка")
            self.status_badge.setObjectName("CardStatusError")
        elif raw in ("cancelled", "отменено", "отмена"):
            self._stop_elapsed_timer()
            self.status_badge.setText("Отменено")
            self.status_badge.setObjectName("CardStatusCancelled")
        else:
            self.status_badge.setText(state)
            self.status_badge.setObjectName("CardStatusIdle")

        repolish(self.status_badge)

    def _toggle_tech_details(self) -> None:
        """Переключает видимость панели технических подробностей ошибки (Этап 9.6)."""
        vis = not self.tech_details_frame.isVisible()
        self.tech_details_frame.setVisible(vis)
        self.details_btn.setText("Скрыть" if vis else "Подробнее")

    def _open_diag_log(self) -> None:
        """Открывает файл truniversal_diag.log в системном редакторе (Этап 9.6)."""
        try:
            from diagnostics import _log_path
            path = _log_path()
            if not path.exists():
                path.write_text("Лог диагностики Truniversal\n", encoding="utf-8")
            os.startfile(str(path))
        except Exception:
            pass

    # -------------------------------------------------- загрузка/результат
    def start_loading(self) -> None:
        """Карточка переходит в режим ожидания ответа."""
        self._loading = True
        self._frame_index = 0
        self.set_status("sending")
        self.result_label.setObjectName("CardResultLabel")
        repolish(self.result_label)
        self.result_label.setText(LOADING_FRAMES[0])
        self.result_label.show()
        self.result_edit_bar.hide()
        self.variants_container.hide()
        self.comparison_panel.hide()
        self.details_btn.hide()
        self.tech_details_frame.hide()

        # Кнопки при загрузке: показываем «Отмена», отключаем действия с результатом
        self.cancel_button.show()
        self.cancel_button.setEnabled(True)
        self.diff_btn.hide()
        self.copy_button.setVisible(True)
        self.copy_button.setEnabled(False)
        self.replace_button.setVisible(True)
        self.replace_button.setEnabled(False)
        self.regenerate_button.setVisible(True)
        self.regenerate_button.setEnabled(False)
        self._loading_timer.start()

    def _advance_loading_frame(self) -> None:
        self._frame_index = (self._frame_index + 1) % len(LOADING_FRAMES)
        self.result_label.setText(LOADING_FRAMES[self._frame_index])

    def set_result(self, text: str) -> None:
        """Обработка готового ответа модели: проверка вариантов, обновление интерфейса."""
        self._loading = False
        self._loading_timer.stop()
        self.set_status("ready")
        self.result_text = text
        self.edited_text = None
        self.edited_badge.hide()
        self.details_btn.hide()
        self.tech_details_frame.hide()

        # Прячем кнопку отмены
        self.cancel_button.hide()

        # Проверяем, вернула ли модель несколько вариантов (Этап 6.2)
        variants = extract_text_variants(text)
        self._variants = variants

        if len(variants) >= 2:
            self._render_variants(variants)
            self.result_label.hide()
            self.variants_container.show()
        else:
            self.variants_container.hide()
            self.result_label.setObjectName("CardResultLabel")
            repolish(self.result_label)
            self.result_label.setText(text)
            self.result_label.show()

        # Показываем основные кнопки
        self.copy_button.setVisible(True)
        self.copy_button.setEnabled(True)
        self.replace_button.setVisible(True)
        self.replace_button.setEnabled(True)
        self.regenerate_button.setVisible(True)
        self.regenerate_button.setEnabled(True)
        self.diff_btn.show()

        # Если был открыт режим сравнения — обновляем данные
        if self._comparison_mode:
            self._update_comparison_data()

    def set_error(self, message: str, details: str = "") -> None:
        """Понятная ошибка выполнения запроса с диагностикой (Этап 9.6)."""
        self._loading = False
        self._loading_timer.stop()
        self.set_status("error")
        self.result_text = None
        self.edited_text = None
        self.edited_badge.hide()

        self.cancel_button.hide()
        self.variants_container.hide()
        self.comparison_panel.hide()

        self.result_label.setObjectName("CardErrorLabel")
        repolish(self.result_label)
        self.result_label.setText(message)
        self.result_label.show()

        self.copy_button.setVisible(False)
        self.replace_button.setVisible(False)
        self.regenerate_button.setVisible(True)
        self.regenerate_button.setEnabled(True)
        self.diff_btn.hide()

        self.technical_details = (details or "").strip()
        if self.technical_details:
            self.tech_details_text.setText(self.technical_details)
            self.details_btn.setText("Подробнее")
            self.details_btn.show()
        else:
            self.details_btn.hide()
            self.tech_details_frame.hide()

    def set_cancelled(self) -> None:
        """Запрос был отменён пользователем (Этап 6.6)."""
        self._loading = False
        self._loading_timer.stop()
        self.set_status("cancelled")
        self.result_text = None
        self.edited_text = None
        self.edited_badge.hide()
        self.details_btn.hide()
        self.tech_details_frame.hide()

        self.cancel_button.hide()
        self.variants_container.hide()
        self.comparison_panel.hide()

        self.result_label.setObjectName("CardCancelledLabel")
        repolish(self.result_label)
        self.result_label.setText("Запрос отменён пользователем.")
        self.result_label.show()

        self.copy_button.setVisible(False)
        self.replace_button.setVisible(False)
        self.regenerate_button.setVisible(True)
        self.regenerate_button.setEnabled(True)
        self.diff_btn.hide()

    # ---------------- 6.1. Редактирование исходного текста и результата -----
    def toggle_edit_source(self) -> None:
        """Показывает или скрывает строку редактирования исходника."""
        is_shown = self.source_edit_bar.isVisible()
        if not is_shown:
            self.source_edit_field.setPlainText(self.source_text)
            self.source_edit_bar.show()
            self.source_edit_field.setFocus()
        else:
            self.source_edit_bar.hide()

    def _save_source_text(self) -> None:
        new_text = self.source_edit_field.toPlainText().strip()
        if new_text:
            self.source_text = new_text
            self.source_label.setText(self._preview(self.source_text))
        self.source_edit_bar.hide()

    def _save_source_and_regenerate(self) -> None:
        self._save_source_text()
        self.regenerate_requested.emit()

    def toggle_edit_result(self) -> None:
        """Включает режим редактирования текущего результата."""
        if not self.result_text and not self.edited_text:
            return
        if self.result_edit_bar.isVisible():
            self._cancel_result_edit()
            return

        current_val = self.get_active_text()
        self.result_edit_field.setPlainText(current_val)
        self.result_label.hide()
        self.variants_container.hide()
        self.result_edit_bar.show()
        self.result_edit_field.setFocus()

    def _save_result_edit(self) -> None:
        val = self.result_edit_field.toPlainText().strip()
        if val:
            self.edited_text = val
            self.result_label.setText(val)
            self.edited_badge.show()
            self.result_edited.emit(val)
        self.result_edit_bar.hide()
        self.result_label.show()
        if self._comparison_mode:
            self._update_comparison_data()

    def _cancel_result_edit(self) -> None:
        self.result_edit_bar.hide()
        if self._variants and len(self._variants) >= 2:
            self.variants_container.show()
        else:
            self.result_label.show()

    # ---------------- 6.2. Несколько вариантов результата -------------------
    def _render_variants(self, variants: List[Tuple[str, str]]) -> None:
        """Отрисовывает каждый вариант в отдельном независимом блоке со своими кнопками."""
        # Очищаем старые виджеты вариантов
        while self.variants_layout.count() > 0:
            item = self.variants_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        for idx, (title, content) in enumerate(variants):
            block = QFrame()
            block.setObjectName("VariantBlock")
            b_lay = QVBoxLayout(block)
            b_lay.setContentsMargins(10, 8, 10, 8)
            b_lay.setSpacing(6)

            # Шапка варианта
            hdr = QHBoxLayout()
            t_lbl = QLabel(title)
            t_lbl.setObjectName("VariantTitle")
            hdr.addWidget(t_lbl, stretch=1)

            # Кнопка замены в тексте именно этого варианта
            rep_btn = QPushButton("Заменить")
            rep_btn.setObjectName("VariantActionBtn")
            rep_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            rep_btn.setToolTip("Вставить этот конкретный вариант на место выделения (Ctrl+V)")
            rep_btn.clicked.connect(lambda checked=False, t=content: self._replace_variant(t))
            hdr.addWidget(rep_btn)

            # Кнопка копирования именно этого варианта
            cp_btn = QPushButton("Скопировать")
            cp_btn.setObjectName("VariantActionBtn")
            cp_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            cp_btn.setToolTip("Скопировать этот вариант в буфер обмена")
            cp_btn.clicked.connect(lambda checked=False, t=content, b=cp_btn: self._copy_variant(t, b))
            hdr.addWidget(cp_btn)

            b_lay.addLayout(hdr)

            # Текст варианта
            c_lbl = QLabel(content)
            c_lbl.setObjectName("VariantText")
            c_lbl.setWordWrap(True)
            c_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            b_lay.addWidget(c_lbl)

            self.variants_layout.addWidget(block)

    def _replace_variant(self, text: str) -> None:
        """Замена текста с явной передачей выбранного варианта."""
        self.edited_text = text
        self.replace_requested.emit()

    def _copy_variant(self, text: str, btn: QPushButton) -> None:
        """Копирует конкретный вариант и на секунду меняет текст на кнопке варианта."""
        try:
            pyperclip.copy(text)
        except Exception:
            pass
        orig_text = btn.text()
        btn.setText("Скопировано")
        QTimer.singleShot(1000, lambda: btn.setText(orig_text))

    # ---------------- 6.3. Сравнение оригинала и результата (Diff) -----------
    def toggle_comparison(self) -> None:
        """Переключает отображение: компактный вид ↔ панель сравнения с пословным diff."""
        self._comparison_mode = not self._comparison_mode
        self.comparison_panel.setVisible(self._comparison_mode)
        self.diff_btn.setProperty("active", "true" if self._comparison_mode else "false")
        repolish(self.diff_btn)

        if self._comparison_mode:
            # Скрываем обычные результаты, чтобы карточка не раздувалась
            self.result_label.hide()
            self.variants_container.hide()
            self._update_comparison_data()
        else:
            # Возвращаем стандартное отображение
            if self._variants and len(self._variants) >= 2:
                self.variants_container.show()
            else:
                self.result_label.show()

    def _update_comparison_data(self) -> None:
        """Обновляет side-by-side и пословный diff между оригиналом и результатом."""
        active_res = self.get_active_text()
        self.comp_orig_box.setText(self.source_text)
        self.comp_res_box.setText(active_res)

        # Вычисляем пословный diff
        html_diff, added_c, deleted_c = generate_word_diff_html(self.source_text, active_res)
        self.diff_html_view.setText(html_diff)
        self.diff_stats_badge.setText(f"+{added_c} / -{deleted_c} слов")

    # ---------------- 6.4. Действия с карточками (промпт на лету, меню) ------
    def toggle_edit_prompt(self) -> None:
        """Показывает поле ввода для правки промпта перед повторным запуском."""
        is_shown = self.prompt_edit_bar.isVisible()
        if not is_shown:
            self.prompt_edit_field.setText(self.action_name or "")
            self.prompt_edit_bar.show()
            self.prompt_edit_field.setFocus()
            self.prompt_edit_field.selectAll()
        else:
            self.prompt_edit_bar.hide()

    def _submit_prompt_regenerate(self) -> None:
        p = self.prompt_edit_field.text().strip()
        if not p:
            return
        self.prompt_edit_bar.hide()
        self.prompt_regenerate_requested.emit(p)

    def _open_more_menu(self) -> None:
        """Выпадающее меню дополнительных действий карточки."""
        menu = QMenu(self)
        menu.setObjectName("CardMoreMenu")

        act_edit = menu.addAction("Редактировать результат")
        act_edit.triggered.connect(self.toggle_edit_result)

        act_src = menu.addAction("Редактировать исходный текст")
        act_src.triggered.connect(self.toggle_edit_source)

        act_prm = menu.addAction("Изменить промпт и повторить...")
        act_prm.triggered.connect(self.toggle_edit_prompt)

        act_diff = menu.addAction("Сравнить оригинал и результат")
        act_diff.triggered.connect(self.toggle_comparison)

        menu.addSeparator()

        act_del = menu.addAction("Удалить карточку")
        act_del.triggered.connect(self.delete_requested.emit)

        menu.exec(QCursor.pos())

    # ---------------- Проект (Этап 8)
    def set_project(self, project_name: str) -> None:
        """Отображает бейдж активного проекта."""
        name = (project_name or "").strip()
        if name:
            self.project_badge.setText(f"Проект: {name}")
            self.project_badge.setToolTip(f"Операция в рамках проекта «{name}»")
            self.project_badge.show()
        else:
            self.project_badge.hide()

    # ---------------- AI-действие (Этап 5)
    def set_action(self, action_id: str, action_name: str) -> None:
        """Отображает бейдж применённого AI-действия."""
        self.action_id = action_id
        self.action_name = action_name
        if action_name:
            self.action_badge.setText(action_name)
            self.action_badge.show()
        else:
            self.action_badge.hide()

    # ---------------- Направление перевода (Этап 4)
    def set_direction(self, source: str, target: str, badge: str) -> None:
        """Обновляет бейдж направления перевода."""
        self.source_lang = (source or "auto").strip().lower()
        self.target_lang = (target or "ru").strip().lower()
        self.direction_badge = badge or f"{self.source_lang.upper()} → {self.target_lang.upper()}"
        self.direction_btn.setText(self.direction_badge)
        self.direction_btn.show()
        self.swap_btn.show()

    def swap_direction(self) -> None:
        """Меняет местами исходный и целевой языки прямо в карточке."""
        if not self.source_lang or not self.target_lang:
            return
        cur_src = self.source_lang
        cur_tgt = self.target_lang
        if cur_src == "auto":
            parts = self.direction_badge.split("→")
            if len(parts) == 2:
                cur_src = parts[0].strip().lower()
            else:
                cur_src = "en" if cur_tgt == "ru" else "ru"

        self.source_lang, self.target_lang = cur_tgt, cur_src
        self.direction_badge = f"{self.source_lang.upper()} → {self.target_lang.upper()}"
        self.direction_btn.setText(self.direction_badge)

    def _open_target_lang_menu(self) -> None:
        """Всплывающее меню выбора целевого языка."""
        menu = QMenu(self)
        for lang in get_supported_languages():
            code = lang.code
            action = menu.addAction(f"{lang.name_ru} ({code.upper()})")
            action.triggered.connect(lambda checked=False, c=code: self._select_target_lang(c))
        menu.exec(QCursor.pos())

    def _select_target_lang(self, code: str) -> None:
        """Выбор нового целевого языка в карточке."""
        self.target_lang = code.strip().lower()
        src = (self.source_lang or "auto").upper()
        if src == "AUTO":
            parts = self.direction_badge.split("→")
            if len(parts) == 2:
                src = parts[0].strip()
        self.direction_badge = f"{src} → {self.target_lang.upper()}"
        self.direction_btn.setText(self.direction_badge)
