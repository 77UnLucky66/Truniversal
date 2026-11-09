"""
translation_card.py — карточка с результатом в ленте мини-окна (ШАГИ 2–5).

Карточка (QFrame) содержит:
  • исходный текст — мелким серым шрифтом, обрезанный до ~2 строк;
  • результат перевода/рерайта — крупным удобочитаемым шрифтом; пока запрос
    идёт, здесь крутится текстовая анимация «Думаю…», а при ошибке —
    понятное сообщение (⚠ …) красноватым цветом;
  • кнопку «Скопировать»: копирует РЕЗУЛЬТАТ в буфер обмена и на 1 секунду
    меняет надпись на «Скопировано ✓» (потом возвращает как было).
"""

from __future__ import annotations

import pyperclip
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton,
                              QVBoxLayout)

from styles import repolish

# Сколько символов исходника показывать в превью (примерно две строки).
MAX_SOURCE_PREVIEW_CHARS = 120

# Кадры текстовой анимации загрузки, пока идёт запрос перевода.
LOADING_FRAMES = ("Думаю", "Думаю.", "Думаю..", "Думаю...")


class TranslationCard(QFrame):
    """Карточка ленты мини-окна: исходник, результат и кнопки действий.

    Кнопки: «Повторить» (перегенерировать перевод), «Заменить в тексте»
    (вставить результат на место исходного выделения) и «Скопировать».
    Карточка общается с мини-окном через pyqtSignal — напрямую виджеты
    друг у друга не трогаем.
    """

    #: Пользователь просит перегенерировать перевод (перезапуск воркера).
    regenerate_requested = pyqtSignal()

    #: Пользователь просит вставить результат в исходное окно (Ctrl+V).
    replace_requested = pyqtSignal()

    def __init__(self, source_text: str, result_text: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")

        # Полные тексты (превью в label может быть обрезано).
        self.source_text = source_text
        self.result_text = result_text  # None → карточка в режиме загрузки

        # Анимация загрузки «Думаю…», пока идёт запрос перевода.
        self._loading = False
        self._frame_index = 0
        self._loading_timer = QTimer(self)
        self._loading_timer.setInterval(400)
        self._loading_timer.timeout.connect(self._advance_loading_frame)

        # Таймер возврата надписи кнопки через 1 секунду после копирования.
        self._copy_timer = QTimer(self)
        self._copy_timer.setSingleShot(True)
        self._copy_timer.setInterval(1000)
        self._copy_timer.timeout.connect(self._restore_copy_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        # --- Исходный текст: мелким серым, до ~2 строк ----------------------
        self.source_label = QLabel(self._preview(source_text))
        self.source_label.setObjectName("CardSourceLabel")
        self.source_label.setWordWrap(True)
        layout.addWidget(self.source_label)

        # --- Результат: крупным удобочитаемым --------------------------------
        self.result_label = QLabel(
            result_text if result_text is not None else LOADING_FRAMES[0]
        )
        self.result_label.setObjectName("CardResultLabel")
        self.result_label.setWordWrap(True)
        # Текст можно выделять мышью (это не «поле ввода» — читать не мешает).
        self.result_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self.result_label)

        # --- Кнопки действий справа -------------------------------------------
        row = QHBoxLayout()
        row.addStretch(1)

        self.regenerate_button = QPushButton("Повторить")
        self.regenerate_button.setObjectName("RegenerateButton")
        self.regenerate_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.regenerate_button.setToolTip(
            "Сгенерировать перевод заново — если вариант скучный, "
            "неполный или была ошибка"
        )
        self.regenerate_button.clicked.connect(self.regenerate_requested.emit)
        row.addWidget(self.regenerate_button)

        self.replace_button = QPushButton("Заменить в тексте")
        self.replace_button.setObjectName("ReplaceButton")
        self.replace_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.replace_button.setToolTip(
            "Скопировать перевод, вернуться в ваше окно и вставить его "
            "на место выделенного текста (Ctrl+V)"
        )
        self.replace_button.clicked.connect(self.replace_requested.emit)
        row.addWidget(self.replace_button)

        self.copy_button = QPushButton("Скопировать")
        self.copy_button.setObjectName("CopyButton")
        self.copy_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.copy_button.setToolTip("Скопировать результат в буфер обмена")
        self.copy_button.clicked.connect(self._copy_result)
        row.addWidget(self.copy_button)
        layout.addLayout(row)

        # Результата нет — карточка сразу в режиме «Думаю…» (запрос ещё идёт).
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

    # ------------------------------------------------------------- копирование
    def _copy_result(self) -> None:
        """Копирует результат в буфер; кнопка на секунду становится зелёной."""
        try:
            pyperclip.copy(self.result_text)
        except Exception:
            pass  # буфер недоступен — не роняем GUI из-за копирования
        self.copy_button.setText("Скопировано ✓")
        self.copy_button.setObjectName("CopyButtonDone")
        repolish(self.copy_button)
        self._copy_timer.start()

    def _restore_copy_button(self) -> None:
        self.copy_button.setText("Скопировать")
        self.copy_button.setObjectName("CopyButton")
        repolish(self.copy_button)

    # -------------------------------------------------- загрузка/результат
    def start_loading(self) -> None:
        """Пока идёт запрос — крутится текстовая анимация «Думаю…»."""
        self._loading = True
        self._frame_index = 0
        self.result_label.setObjectName("CardResultLabel")
        self.result_label.setText(LOADING_FRAMES[0])
        # Результата ещё нет — действия с ним выключены.
        self.copy_button.setVisible(True)
        self.copy_button.setEnabled(False)
        self.replace_button.setVisible(True)
        self.replace_button.setEnabled(False)
        self.regenerate_button.setEnabled(False)
        self._loading_timer.start()

    def _advance_loading_frame(self) -> None:
        self._frame_index = (self._frame_index + 1) % len(LOADING_FRAMES)
        self.result_label.setText(LOADING_FRAMES[self._frame_index])

    def set_result(self, text: str) -> None:
        """Перевод готов: стоп анимации, показываем результат, действия активны."""
        self._loading = False
        self._loading_timer.stop()
        self.result_text = text
        self.result_label.setObjectName("CardResultLabel")
        repolish(self.result_label)
        self.result_label.setText(text)
        self.copy_button.setVisible(True)
        self.copy_button.setEnabled(True)
        self.replace_button.setVisible(True)
        self.replace_button.setEnabled(True)
        self.regenerate_button.setEnabled(True)

    def set_error(self, message: str) -> None:
        """Понятная ошибка прямо в карточке (не запущена Ollama и т.п.)."""
        self._loading = False
        self._loading_timer.stop()
        self.result_text = None
        self.result_label.setObjectName("CardErrorLabel")
        repolish(self.result_label)
        self.result_label.setText("⚠ " + message)
        # Ошибку нечего копировать и заменять, а вот «Повторить» — можно.
        self.copy_button.setVisible(False)
        self.replace_button.setVisible(False)
        self.regenerate_button.setEnabled(True)
