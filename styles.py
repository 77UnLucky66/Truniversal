"""
styles.py — тёмная минималистичная тема приложения (QSS).

Единый стиль для всех окон и меню. Палитра вынесена в константы: на
следующих шагах окна настроек и мини-окно будут использовать те же цвета,
чтобы интерфейс оставался согласованным. Здесь же — вспомогательная
функция тёмного заголовка окна (Windows 10/11, через DWM API).
"""

from __future__ import annotations

import sys

from PyQt6.QtWidgets import QWidget

# --- Палитра (тёмная тема) ----------------------------------------------------
BG_WINDOW = "#17181D"       # фон окон
BG_SURFACE = "#1F2128"      # фон панелей и меню
BG_SURFACE_ALT = "#262933"  # фон всплывающих подсказок
BORDER = "#33363F"          # тонкие рамки
ACCENT = "#6C7CFF"          # основной акцент (индиго)
ACCENT_HOVER = "#8493FF"   # акцент при наведении
ACCENT_PRESSED = "#5A68E0"  # акцент при нажатии
TEXT_PRIMARY = "#ECEEF4"    # основной текст
TEXT_SECONDARY = "#9BA1B5"  # приглушённый текст
DANGER = "#E5484D"          # опасные действия («Очистить историю» при наведении)
SUCCESS = "#3FB970"         # подтверждение («Скопировано ✓»)

APP_QSS = f"""
/* ============================================================
   Truniversal — тёмная минималистичная тема (QSS)
   ============================================================ */

QWidget {{
    color: {TEXT_PRIMARY};
    font-family: "Segoe UI", "Inter", sans-serif;
    font-size: 10pt;
}}

QMainWindow, QDialog, QMessageBox {{
    background-color: {BG_WINDOW};
}}

QLabel {{
    background: transparent;
    color: {TEXT_PRIMARY};
}}

QLabel#TitleLabel {{
    font-size: 16pt;
    font-weight: 700;
}}

QLabel#MutedLabel {{
    color: {TEXT_SECONDARY};
}}

/* --- Контекстное меню трея ------------------------------------------ */
QMenu {{
    background-color: {BG_SURFACE};
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 6px;
}}

QMenu::item {{
    color: {TEXT_PRIMARY};
    padding: 8px 30px 8px 16px;
    border-radius: 6px;
    margin: 1px 2px;
}}

QMenu::item:selected {{
    background-color: {ACCENT};
    color: #FFFFFF;
}}

QMenu::item:disabled {{
    color: {TEXT_SECONDARY};
}}

QMenu::separator {{
    height: 1px;
    background: {BORDER};
    margin: 6px 8px;
}}

/* --- Всплывающие подсказки ------------------------------------------ */
QToolTip {{
    background-color: {BG_SURFACE_ALT};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 6px 8px;
}}

/* --- Кнопки (понадобятся на следующих шагах) ------------------------- */
QPushButton {{
    background-color: {ACCENT};
    color: #FFFFFF;
    border: none;
    border-radius: 8px;
    padding: 8px 18px;
    font-weight: 600;
}}

QPushButton:hover  {{ background-color: {ACCENT_HOVER}; }}
QPushButton:pressed {{ background-color: {ACCENT_PRESSED}; }}
QPushButton:disabled {{ background-color: {BORDER}; color: {TEXT_SECONDARY}; }}

/* --- Скроллбары (для «ленты» карточек в мини-окне) -------------------- */
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 2px;
}}

QScrollBar::handle:vertical {{
    background: {BORDER};
    border-radius: 5px;
    min-height: 30px;
}}

QScrollBar::handle:vertical:hover {{ background: {ACCENT}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 2px;
}}

QScrollBar::handle:horizontal {{
    background: {BORDER};
    border-radius: 5px;
    min-width: 30px;
}}

/* ============================================================
   ШАГ 2: мини-окно (Quick Popup)
   ============================================================ */

/* Верхняя панель мини-окна */
QFrame#HeaderPanel {{
    background-color: {BG_SURFACE};
    border: none;
    border-bottom: 1px solid {BORDER};
}}

/* Кнопка-переключатель режима «ИИ / Обычный» */
QPushButton#ModeButtonAi {{
    background-color: {ACCENT};
    color: #FFFFFF;
    border: none;
    border-radius: 7px;
    padding: 6px 14px;
    font-weight: 600;
}}
QPushButton#ModeButtonAi:hover {{ background-color: {ACCENT_HOVER}; }}

QPushButton#ModeButtonStd {{
    background-color: {BG_SURFACE_ALT};
    color: {TEXT_SECONDARY};
    border: 1px solid {BORDER};
    border-radius: 7px;
    padding: 5px 13px;
    font-weight: 600;
}}
QPushButton#ModeButtonStd:hover {{ color: {TEXT_PRIMARY}; border-color: {ACCENT}; }}

/* Кнопка «Очистить историю» */
QPushButton#ClearButton {{
    background-color: transparent;
    color: {TEXT_SECONDARY};
    border: 1px solid {BORDER};
    border-radius: 7px;
    padding: 6px 12px;
}}
QPushButton#ClearButton:hover {{ color: {DANGER}; border-color: {DANGER}; }}

/* Кнопки быстрого заполнения (Ollama / OpenRouter / OpenAI) */
QPushButton#GhostButton {{
    background-color: transparent;
    color: {TEXT_SECONDARY};
    border: 1px solid {BORDER};
    border-radius: 7px;
    padding: 5px 10px;
}}
QPushButton#GhostButton:hover {{ color: {TEXT_PRIMARY}; border-color: {ACCENT}; }}

/* Выпадающий список пресетов промптов */
QComboBox {{
    background-color: {BG_SURFACE_ALT};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 7px;
    padding: 6px 12px;
}}
QComboBox:hover {{ border-color: {ACCENT}; }}
QComboBox:disabled {{ color: {TEXT_SECONDARY}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background-color: {BG_SURFACE_ALT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    color: {TEXT_PRIMARY};
    selection-background-color: {ACCENT};
    selection-color: #FFFFFF;
    outline: none;
    padding: 4px;
}}

/* Лента карточек */
QScrollArea#CardsScroll {{ background: transparent; border: none; }}
QWidget#CardsContainer {{ background: transparent; }}

/* Карточка с результатом */
QFrame#Card {{
    background-color: {BG_SURFACE};
    border: 1px solid {BORDER};
    border-radius: 12px;
}}

QLabel#CardSourceLabel {{
    color: {TEXT_SECONDARY};
    font-size: 8.5pt;
}}

QLabel#CardResultLabel {{
    color: {TEXT_PRIMARY};
    font-size: 11pt;
}}

/* Ошибка перевода прямо в карточке (⚠ …) */
QLabel#CardErrorLabel {{
    color: {DANGER};
    font-size: 10pt;
}}

/* Кнопка «Скопировать» и её состояние «Скопировано ✓» */
QPushButton#CopyButton {{
    background-color: {BG_SURFACE_ALT};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 7px;
    padding: 5px 14px;
    font-size: 9pt;
}}
QPushButton#CopyButton:hover {{ border-color: {ACCENT}; }}

QPushButton#CopyButtonDone {{
    background-color: {SUCCESS};
    color: #FFFFFF;
    border: 1px solid {SUCCESS};
    border-radius: 7px;
    padding: 5px 14px;
    font-size: 9pt;
}}

/* Кнопка «Повторить» на карточке */
QPushButton#RegenerateButton {{
    background-color: {BG_SURFACE_ALT};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 7px;
    padding: 5px 12px;
    font-size: 9pt;
}}
QPushButton#RegenerateButton:hover {{ border-color: {ACCENT}; }}
QPushButton#RegenerateButton:disabled {{ color: {TEXT_SECONDARY}; }}

/* Кнопка «Заменить в тексте» — главное действие карточки */
QPushButton#ReplaceButton {{
    background-color: {ACCENT};
    color: #FFFFFF;
    border: none;
    border-radius: 7px;
    padding: 5px 14px;
    font-size: 9pt;
    font-weight: 600;
}}
QPushButton#ReplaceButton:hover {{ background-color: {ACCENT_HOVER}; }}
QPushButton#ReplaceButton:disabled {{
    background-color: {BORDER};
    color: {TEXT_SECONDARY};
}}

/* Пустое состояние мини-окна */
QLabel#EmptyStateLabel {{
    color: {TEXT_SECONDARY};
    font-size: 10pt;
    padding: 24px 12px;
}}

/* ============================================================
   ШАГ 4: окно настроек «Комбайн»
   ============================================================ */

/* Вкладки */
QTabWidget::pane {{
    border: 1px solid {BORDER};
    border-radius: 8px;
    background-color: {BG_SURFACE};
}}

QTabBar::tab {{
    background: transparent;
    color: {TEXT_SECONDARY};
    padding: 8px 18px;
    margin-right: 4px;
    border: 1px solid transparent;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
}}

QTabBar::tab:selected {{
    background-color: {BG_SURFACE};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-bottom: none;
}}

QTabBar::tab:hover:!selected {{ color: {TEXT_PRIMARY}; }}

/* Поля ввода */
QLineEdit, QTextEdit {{
    background-color: {BG_SURFACE_ALT};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 7px 10px;
    selection-background-color: {ACCENT};
    selection-color: #FFFFFF;
}}

QLineEdit:focus, QTextEdit:focus {{ border-color: {ACCENT}; }}
QLineEdit:disabled {{ color: {TEXT_SECONDARY}; }}

/* Ползунки Temperature / Top-P */
QSlider::groove:horizontal {{
    height: 6px;
    background: {BORDER};
    border-radius: 3px;
}}

QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 3px; }}

QSlider::handle:horizontal {{
    width: 16px;
    height: 16px;
    margin: -5px 0;
    border-radius: 8px;
    background: #FFFFFF;
}}

QSlider::handle:horizontal:hover {{ background: {ACCENT_HOVER}; }}

QLabel#ValueLabel {{
    color: {ACCENT};
    font-weight: 700;
    font-size: 11pt;
}}

/* Значок «[?]» с подробной подсказкой */
QLabel#HintLabel {{
    background-color: {BG_SURFACE_ALT};
    color: {ACCENT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 0 7px;
    font-weight: 700;
}}

/* Приглушённая подпись под параметром */
QLabel#CaptionLabel {{
    color: {TEXT_SECONDARY};
    font-size: 8.5pt;
}}

/* Список пресетов */
QListWidget {{
    background-color: {BG_SURFACE_ALT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 4px;
    color: {TEXT_PRIMARY};
}}

QListWidget::item {{ padding: 8px; border-radius: 6px; }}
QListWidget::item:selected {{ background-color: {ACCENT}; color: #FFFFFF; }}
QListWidget::item:hover:!selected {{ background-color: {BG_SURFACE_ALT}; }}

/* Шпаргалка по промптам */
QFrame#CheatSheet {{
    background-color: {BG_SURFACE};
    border: 1px solid {BORDER};
    border-radius: 10px;
}}

QLabel#CheatSheetTitle {{ color: {ACCENT}; font-weight: 600; }}
QLabel#CheatSheetBody {{ color: {TEXT_SECONDARY}; }}

/* Строка состояния */
QStatusBar {{
    background-color: {BG_SURFACE};
    color: {TEXT_SECONDARY};
    border-top: 1px solid {BORDER};
}}
"""


def repolish(widget) -> None:
    """Применяет QSS заново после смены objectName у виджета.

    QSS-селекторы по objectName вычисляются при появлении виджета; если
    objectName меняется на лету (кнопка «Скопировать» → «Скопировано ✓»,
    «ИИ» → «Обычный»), нужно «переполировать» виджет.
    """
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)


def apply_dark_title_bar(window: QWidget) -> None:
    """Тёмный заголовок окна на Windows 10 (сборка 19041+) / Windows 11.

    Вызывается из showEvent() окон после их показа. Косметика: если вызов
    не сработал (не Windows, старая сборка ОС) — молча остаётся светлый
    заголовок, приложение не падает.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes

        hwnd = int(window.winId())
        value = ctypes.c_int(1)  # TRUE → тёмная тема заголовка
        dwm = ctypes.windll.dwmapi
        result = dwm.DwmSetWindowAttribute(
            hwnd, 20, ctypes.byref(value), ctypes.sizeof(value)  # 20 = DWMWA_USE_IMMERSIVE_DARK_MODE
        )
        if result != 0:
            # На старых сборках Windows 10 тот же атрибут имеет номер 19.
            dwm.DwmSetWindowAttribute(
                hwnd, 19, ctypes.byref(value), ctypes.sizeof(value)
            )
    except Exception:  # noqa: BLE001 — это чистая косметика, не критично
        pass
