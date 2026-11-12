"""
styles.py — тёмная и светлая минималистичные темы приложения (QSS),
поддержка масштабирования шрифтов, определение системной темы Windows (Этап 9).
"""

from __future__ import annotations

import re
import sys
from typing import Dict, Any, Optional
from PyQt6.QtWidgets import QApplication, QWidget

# --- Палитра: Тёмная тема (Dark) -------------------------------------------
DARK_PALETTE: Dict[str, str] = {
    "BG_WINDOW": "#13151A",
    "BG_SURFACE": "#171A21",
    "BG_CARD": "#1D212A",
    "BG_CARD_HOVER": "#222732",
    "BG_SURFACE_ALT": "#111317",
    "BORDER": "#2A303D",
    "BORDER_LIGHT": "#384152",
    "BORDER_INPUT": "#2E3444",
    "ACCENT": "#5B6CFF",
    "ACCENT_HOVER": "#7382FF",
    "ACCENT_PRESSED": "#4B59D9",
    "TEXT_PRIMARY": "#F0F2F7",
    "TEXT_SECONDARY": "#8F97A9",
    "TEXT_MUTED": "#6B7285",
    "DANGER": "#E5484D",
    "DANGER_HOVER": "#FF6368",
    "DANGER_PRESSED": "#C23A3F",
    "SUCCESS": "#3FB970",
    "SUCCESS_HOVER": "#49CE7F",
    "WARNING": "#F5A623",
    "SPLITTER_HANDLE": "#333A4D",
    "TABLE_BG": "#12151E",
    "TABLE_HEADER_BG": "#161922",
    "PROJECT_BAR_BG": "#141720",
    "CARD_BG": "#181B23",
    "CARD_BORDER": "#262B38",
    "INLINE_BAR_BG": "#151820",
    "SOURCE_BG": "#13151C",
    "SOURCE_TEXT": "#8F97A9",
    "RESULT_TEXT": "#F0F2F7",
    "STATUS_IDLE_BG": "#222735",
    "STATUS_IDLE_TEXT": "#8F97A9",
    "STATUS_PROGRESS_BG": "#1E254A",
    "STATUS_PROGRESS_TEXT": "#93C5FD",
    "STATUS_DONE_BG": "#14281E",
    "STATUS_DONE_TEXT": "#86EFAC",
    "STATUS_ERROR_BG": "#3A1F23",
    "STATUS_ERROR_TEXT": "#FFA198",
    "STATUS_CANCEL_BG": "#2C2224",
    "STATUS_CANCEL_TEXT": "#E5A0A4",
    "BTN_BG": "#202430",
    "BTN_TEXT": "#DDE2ED",
    "BTN_BORDER": "#333948",
    "BTN_HOVER_BG": "#272C3B",
    "BTN_HOVER_TEXT": "#FFFFFF",
    "BTN_PRESSED_BG": "#1B1E26",
    "BTN_DISABLED_BG": "#16181E",
    "BTN_DISABLED_BORDER": "#232731",
    "INPUT_DISABLED_BG": "#16181E",
    "INPUT_DISABLED_BORDER": "#232731",
}

# --- Палитра: Светлая тема (Light) -----------------------------------------
LIGHT_PALETTE: Dict[str, str] = {
    "BG_WINDOW": "#F2F5F9",
    "BG_SURFACE": "#FFFFFF",
    "BG_CARD": "#FFFFFF",
    "BG_CARD_HOVER": "#F8FAFD",
    "BG_SURFACE_ALT": "#F0F3F8",
    "BORDER": "#D6DCE5",
    "BORDER_LIGHT": "#C2CAD6",
    "BORDER_INPUT": "#CCD4E2",
    "ACCENT": "#4353FF",
    "ACCENT_HOVER": "#5B6CFF",
    "ACCENT_PRESSED": "#3342E6",
    "TEXT_PRIMARY": "#181D26",
    "TEXT_SECONDARY": "#475569",
    "TEXT_MUTED": "#64748B",
    "DANGER": "#DC3545",
    "DANGER_HOVER": "#E84A59",
    "DANGER_PRESSED": "#B02A37",
    "SUCCESS": "#198754",
    "SUCCESS_HOVER": "#20A566",
    "WARNING": "#D97706",
    "SPLITTER_HANDLE": "#C4CBD6",
    "TABLE_BG": "#FFFFFF",
    "TABLE_HEADER_BG": "#EDF2F7",
    "PROJECT_BAR_BG": "#F4F7FB",
    "CARD_BG": "#FFFFFF",
    "CARD_BORDER": "#D6DCE5",
    "INLINE_BAR_BG": "#F4F7FB",
    "SOURCE_BG": "#F1F5F9",
    "SOURCE_TEXT": "#334155",
    "RESULT_TEXT": "#0F172A",
    "STATUS_IDLE_BG": "#E2E8F0",
    "STATUS_IDLE_TEXT": "#475569",
    "STATUS_PROGRESS_BG": "#DBEAFE",
    "STATUS_PROGRESS_TEXT": "#1D4ED8",
    "STATUS_DONE_BG": "#DCFCE7",
    "STATUS_DONE_TEXT": "#166534",
    "STATUS_ERROR_BG": "#FEE2E2",
    "STATUS_ERROR_TEXT": "#B91C1C",
    "STATUS_CANCEL_BG": "#F1F5F9",
    "STATUS_CANCEL_TEXT": "#64748B",
    "BTN_BG": "#F1F5F9",
    "BTN_TEXT": "#1E293B",
    "BTN_BORDER": "#CBD5E1",
    "BTN_HOVER_BG": "#E2E8F0",
    "BTN_HOVER_TEXT": "#0F172A",
    "BTN_PRESSED_BG": "#CBD5E1",
    "BTN_DISABLED_BG": "#F8FAFC",
    "BTN_DISABLED_BORDER": "#E2E8F0",
    "INPUT_DISABLED_BG": "#F1F5F9",
    "INPUT_DISABLED_BORDER": "#E2E8F0",
}

# Обратная совместимость с кодом, импортирующим константы напрямую
BG_WINDOW = DARK_PALETTE["BG_WINDOW"]
BG_SURFACE = DARK_PALETTE["BG_SURFACE"]
BG_CARD = DARK_PALETTE["BG_CARD"]
BG_CARD_HOVER = DARK_PALETTE["BG_CARD_HOVER"]
BG_SURFACE_ALT = DARK_PALETTE["BG_SURFACE_ALT"]
BORDER = DARK_PALETTE["BORDER"]
BORDER_LIGHT = DARK_PALETTE["BORDER_LIGHT"]
BORDER_INPUT = DARK_PALETTE["BORDER_INPUT"]
ACCENT = DARK_PALETTE["ACCENT"]
ACCENT_HOVER = DARK_PALETTE["ACCENT_HOVER"]
ACCENT_PRESSED = DARK_PALETTE["ACCENT_PRESSED"]
TEXT_PRIMARY = DARK_PALETTE["TEXT_PRIMARY"]
TEXT_SECONDARY = DARK_PALETTE["TEXT_SECONDARY"]
TEXT_MUTED = DARK_PALETTE["TEXT_MUTED"]
DANGER = DARK_PALETTE["DANGER"]
DANGER_HOVER = DARK_PALETTE["DANGER_HOVER"]
DANGER_PRESSED = DARK_PALETTE["DANGER_PRESSED"]
SUCCESS = DARK_PALETTE["SUCCESS"]
SUCCESS_HOVER = DARK_PALETTE["SUCCESS_HOVER"]
WARNING = DARK_PALETTE["WARNING"]


def detect_system_theme() -> str:
    """Определяет системную тему Windows (dark / light)."""
    if sys.platform == "win32":
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
            )
            val, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            winreg.CloseKey(key)
            return "light" if val == 1 else "dark"
        except Exception:
            pass
    return "dark"


def get_theme_palette(theme: str = "dark") -> Dict[str, str]:
    """Возвращает палитру для темы: dark, light или system."""
    t = theme.lower().strip()
    if t == "system":
        t = detect_system_theme()
    return LIGHT_PALETTE if t == "light" else DARK_PALETTE


def scale_font_sizes(qss: str, font_size: str = "medium") -> str:
    """Масштабирует размеры шрифтов в QSS: small (-1pt), medium (0), large (+1.5pt)."""
    delta = 0.0
    fs = (font_size or "medium").lower().strip()
    if fs == "small":
        delta = -1.0
    elif fs == "large":
        delta = 1.5

    if abs(delta) < 0.01:
        return qss

    def _replace_pt(match):
        val = float(match.group(1))
        new_val = max(7.0, val + delta)
        s = f"{new_val:.1f}".rstrip("0").rstrip(".")
        return f"font-size: {s}pt"

    return re.sub(r"font-size:\s*([0-9\.]+)pt", _replace_pt, qss)


_QSS_RAW_TEMPLATE = """
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

/* --- Кнопки (базовые стили) ------------------------------------------ */
QPushButton {{
    background-color: {BTN_BG};
    color: {BTN_TEXT};
    border: 1px solid {BTN_BORDER};
    border-radius: 8px;
    padding: 7px 16px;
    font-weight: 600;
    font-size: 9.5pt;
}}

QPushButton:hover {{
    background-color: {BTN_HOVER_BG};
    color: {BTN_HOVER_TEXT};
    border-color: {ACCENT};
}}

QPushButton:pressed {{
    background-color: {BTN_PRESSED_BG};
    border-color: {ACCENT_PRESSED};
}}

QPushButton:disabled {{
    background-color: {BTN_DISABLED_BG};
    border-color: {BTN_DISABLED_BORDER};
    color: {TEXT_MUTED};
}}

/* Вторичная кнопка */
QPushButton#SecondaryButton {{
    background-color: {BTN_BG};
    color: {TEXT_PRIMARY};
    border: 1px solid {BTN_BORDER};
    border-radius: 8px;
    padding: 7px 16px;
    font-weight: 600;
    font-size: 9.5pt;
}}

QPushButton#SecondaryButton:hover {{
    background-color: {BTN_HOVER_BG};
    color: {TEXT_PRIMARY};
    border-color: {ACCENT};
}}

QPushButton#SecondaryButton:pressed {{
    background-color: {BTN_PRESSED_BG};
    border-color: {ACCENT_PRESSED};
}}

/* Кнопки действий проекта (+ Создать, Копия, Удалить) */
QPushButton#ProjectActionBtn {{
    background-color: {BTN_BG};
    color: {BTN_TEXT};
    border: 1px solid {BTN_BORDER};
    border-radius: 7px;
    padding: 4px 6px;
    font-size: 8.5pt;
    font-weight: 600;
}}
QPushButton#ProjectActionBtn:hover {{
    background-color: {BTN_HOVER_BG};
    color: {BTN_HOVER_TEXT};
    border-color: {ACCENT};
}}
QPushButton#ProjectActionBtn:pressed {{
    background-color: {BTN_PRESSED_BG};
}}

/* Главная кнопка действия (Сохранить, Подтвердить) */
QPushButton#PrimaryButton {{
    background-color: {ACCENT};
    color: #FFFFFF;
    border: 1px solid #6E7EFF;
    border-radius: 8px;
    padding: 8px 22px;
    font-weight: 700;
    font-size: 9.5pt;
}}

QPushButton#PrimaryButton:hover {{
    background-color: {ACCENT_HOVER};
    border-color: #9AA6FF;
    color: #FFFFFF;
}}

QPushButton#PrimaryButton:pressed {{
    background-color: {ACCENT_PRESSED};
    border-color: {ACCENT_PRESSED};
    color: #FFFFFF;
}}

QPushButton#PrimaryButton:disabled {{
    background-color: {BTN_DISABLED_BG};
    border-color: {BTN_DISABLED_BORDER};
    color: {TEXT_MUTED};
}}

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
    border: 1px solid #6E7EFF;
    border-radius: 7px;
    padding: 4px 11px;
    min-height: 28px;
    font-size: 9pt;
    font-weight: 600;
}}
QPushButton#ModeButtonAi:hover {{
    background-color: {ACCENT_HOVER};
    border-color: #9AA6FF;
    color: #FFFFFF;
}}

QPushButton#ModeButtonStd {{
    background-color: {BTN_BG};
    color: {TEXT_SECONDARY};
    border: 1px solid {BORDER};
    border-radius: 7px;
    padding: 4px 11px;
    min-height: 28px;
    font-size: 9pt;
    font-weight: 600;
}}
QPushButton#ModeButtonStd:hover {{
    background-color: {BTN_HOVER_BG};
    color: {TEXT_PRIMARY};
    border-color: {ACCENT};
}}

/* Кнопка «Очистить» в мини-окне */
QPushButton#ClearButton {{
    background-color: {BTN_BG};
    color: {TEXT_SECONDARY};
    border: 1px solid {BORDER};
    border-radius: 7px;
    padding: 4px 11px;
    min-height: 28px;
    font-size: 9pt;
    font-weight: 600;
}}
QPushButton#ClearButton:hover {{
    background-color: {DANGER};
    color: #FFFFFF;
    border-color: {DANGER};
}}

/* Кнопка «Сбросить все настройки» / опасные действия (Этап 1 и 3) */
QPushButton#DangerButton {{
    background-color: rgba(229, 72, 77, 0.12);
    color: #FF6E73;
    border: 1px solid {DANGER};
    border-radius: 8px;
    padding: 7px 16px;
    font-weight: 600;
}}
QPushButton#DangerButton:hover {{
    background-color: {DANGER};
    color: #FFFFFF;
    border-color: {DANGER_HOVER};
}}
QPushButton#DangerButton:pressed {{
    background-color: {DANGER_PRESSED};
    border-color: {DANGER_PRESSED};
    color: #FFFFFF;
}}

/* Кнопки быстрого заполнения и вспомогательные действия */
QPushButton#GhostButton {{
    background-color: {BTN_BG};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 7px;
    padding: 5px 12px;
    font-size: 9pt;
    font-weight: 500;
}}
QPushButton#GhostButton:hover {{
    background-color: {BTN_HOVER_BG};
    color: {TEXT_PRIMARY};
    border-color: {ACCENT};
}}
QPushButton#GhostButton:pressed {{
    background-color: {BTN_PRESSED_BG};
    border-color: {ACCENT_PRESSED};
}}

/* Выпадающий список */
QComboBox {{
    background-color: {BG_SURFACE_ALT};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER_INPUT};
    border-radius: 8px;
    padding: 7px 12px;
    min-height: 22px;
}}
QComboBox:hover {{
    border-color: {ACCENT};
}}
QComboBox:focus {{
    border: 1.5px solid {ACCENT};
}}
QComboBox:disabled {{
    background-color: {INPUT_DISABLED_BG};
    color: {TEXT_MUTED};
    border-color: {INPUT_DISABLED_BORDER};
}}
QComboBox::drop-down {{
    border: none;
    width: 24px;
}}
QComboBox QAbstractItemView {{
    background-color: {BG_CARD};
    border: 1px solid {BORDER};
    border-radius: 8px;
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

/* Ошибка перевода прямо в карточке */
QLabel#CardErrorLabel {{
    color: {DANGER};
    font-size: 10pt;
}}

/* Отменённый запрос (Этап 6.6) */
QLabel#CardCancelledLabel {{
    color: #8B949E;
    font-size: 9.5pt;
    font-style: italic;
}}

/* Бейдж ручной правки (Этап 6.1) */
QLabel#CardEditedBadge {{
    background-color: rgba(210, 153, 34, 0.15);
    color: #E3B341;
    border: 1px solid rgba(210, 153, 34, 0.35);
    border-radius: 5px;
    padding: 2px 7px;
    font-size: 7.5pt;
    font-weight: 700;
}}

/* Кнопка отмены активного запроса (Этап 6.6) */
QPushButton#CancelLoadingBtn {{
    background-color: rgba(229, 72, 77, 0.15);
    color: {DANGER};
    border: 1px solid {DANGER};
    border-radius: 7px;
    padding: 5px 12px;
    font-size: 9pt;
    font-weight: 600;
}}
QPushButton#CancelLoadingBtn:hover {{
    background-color: {DANGER};
    color: #FFFFFF;
}}

/* Кнопка «Сравнить» / Diff (Этап 6.3) */
QPushButton#DiffToggleBtn {{
    background-color: {BTN_BG};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 7px;
    padding: 5px 10px;
    font-size: 8.5pt;
    font-weight: 600;
}}
QPushButton#DiffToggleBtn:hover {{
    background-color: {BTN_HOVER_BG};
    color: {TEXT_PRIMARY};
    border-color: {ACCENT};
}}
QPushButton#DiffToggleBtn[active="true"] {{
    background-color: {ACCENT};
    color: #FFFFFF;
    border-color: {ACCENT};
}}

/* Кнопки в карточке: удалить, редактировать исходник, меню «⋯» (Этап 6.4) */
QPushButton#CardSmallIconBtn, QPushButton#MoreMenuBtn {{
    background-color: transparent;
    color: {TEXT_MUTED};
    border: 1px solid transparent;
    border-radius: 5px;
    padding: 2px 7px;
    font-size: 9pt;
    font-weight: 600;
}}
QPushButton#CardSmallIconBtn:hover, QPushButton#MoreMenuBtn:hover {{
    background-color: {BG_CARD_HOVER};
    color: {TEXT_PRIMARY};
    border-color: {BORDER};
}}

QPushButton#DeleteCardBtn {{
    background-color: transparent;
    color: {TEXT_MUTED};
    border: 1px solid transparent;
    border-radius: 5px;
    padding: 2px 6px;
    font-size: 9pt;
    font-weight: 700;
}}
QPushButton#DeleteCardBtn:hover {{
    background-color: {DANGER};
    color: #FFFFFF;
    border-color: {DANGER};
}}

/* Блок сравнения оригинала и результата (Этап 6.3) */
QFrame#ComparisonPanel {{
    background-color: {BG_SURFACE_ALT};
    border: 1px solid {BORDER};
    border-radius: 9px;
}}
QLabel#DiffColHeader {{
    color: {ACCENT};
    font-size: 8.5pt;
    font-weight: 700;
}}
QLabel#DiffTextBox {{
    background-color: {CARD_BG};
    color: {TEXT_PRIMARY};
    border: 1px solid {CARD_BORDER};
    border-radius: 6px;
    padding: 8px;
    font-size: 9.5pt;
}}
QLabel#DiffSectionHeader {{
    color: {TEXT_PRIMARY};
    font-size: 8.5pt;
    font-weight: 700;
}}
QLabel#DiffStatsBadge {{
    background-color: rgba(94, 106, 210, 0.15);
    color: {ACCENT};
    border-radius: 4px;
    padding: 1px 6px;
    font-size: 8pt;
    font-weight: 600;
}}
QLabel#DiffHtmlView {{
    background-color: {CARD_BG};
    border: 1px solid {CARD_BORDER};
    border-radius: 6px;
    padding: 10px;
    font-size: 10pt;
    line-height: 1.4;
}}

/* Блоки отдельных вариантов (Этап 6.2) */
QFrame#VariantBlock {{
    background-color: {PROJECT_BAR_BG};
    border: 1px solid {BORDER};
    border-radius: 8px;
}}
QFrame#VariantBlock:hover {{
    border-color: {ACCENT};
}}
QLabel#VariantTitle {{
    color: {ACCENT};
    font-size: 9pt;
    font-weight: 700;
}}
QLabel#VariantText {{
    color: {TEXT_PRIMARY};
    font-size: 10pt;
    line-height: 1.35;
}}
QPushButton#VariantActionBtn {{
    background-color: {BTN_BG};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 5px;
    padding: 3px 9px;
    font-size: 8pt;
    font-weight: 600;
}}
QPushButton#VariantActionBtn:hover {{
    background-color: {BTN_HOVER_BG};
    color: {TEXT_PRIMARY};
    border-color: {ACCENT};
}}

/* Встроенные панели редактирования (Этап 6.1 и 6.4) */
QFrame#InlineEditorBar {{
    background-color: {INLINE_BAR_BG};
    border: 1px solid {BORDER};
    border-radius: 8px;
}}
QTextEdit#InlineTextEdit, QLineEdit#InlineLineEdit {{
    background-color: {BG_SURFACE_ALT};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER_INPUT};
    border-radius: 6px;
    padding: 6px 8px;
    font-size: 9.5pt;
}}
QTextEdit#InlineTextEdit:focus, QLineEdit#InlineLineEdit:focus {{
    border: 1.5px solid {ACCENT};
    background-color: {BG_SURFACE};
}}

/* Кнопка «Скопировать» и её состояние «Скопировано» */
QPushButton#CopyButton {{
    background-color: {BTN_BG};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 7px;
    padding: 5px 14px;
    font-size: 9pt;
    font-weight: 600;
}}
QPushButton#CopyButton:hover {{
    background-color: {BTN_HOVER_BG};
    border-color: {ACCENT};
    color: {BTN_HOVER_TEXT};
}}

QPushButton#CopyButtonDone {{
    background-color: {SUCCESS};
    color: #FFFFFF;
    border: 1px solid {SUCCESS};
    border-radius: 7px;
    padding: 5px 14px;
    font-size: 9pt;
    font-weight: 600;
}}
QPushButton#CopyButtonDone:hover {{
    background-color: {SUCCESS_HOVER};
    border-color: {SUCCESS_HOVER};
    color: #FFFFFF;
}}

/* Кнопка «Повторить» на карточке */
QPushButton#RegenerateButton {{
    background-color: {BTN_BG};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 7px;
    padding: 5px 12px;
    font-size: 9pt;
    font-weight: 600;
}}
QPushButton#RegenerateButton:hover {{
    background-color: {BTN_HOVER_BG};
    border-color: {ACCENT};
    color: {BTN_HOVER_TEXT};
}}
QPushButton#RegenerateButton:disabled {{
    background-color: {BTN_DISABLED_BG};
    color: {TEXT_MUTED};
    border-color: {BTN_DISABLED_BORDER};
}}

/* Бейдж направления перевода на карточке (EN → RU) (Этап 4) */
QPushButton#DirectionBadge {{
    background-color: {BG_SURFACE_ALT};
    color: {ACCENT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 4px 9px;
    font-size: 8.5pt;
    font-weight: 700;
    letter-spacing: 0.5px;
}}
QPushButton#DirectionBadge:hover {{
    background-color: {BG_CARD_HOVER};
    color: {ACCENT_HOVER};
    border-color: {ACCENT};
}}

/* Бейдж применённого действия на карточке (Этап 5) */
QLabel#CardActionBadge {{
    background-color: rgba(94, 106, 210, 0.15);
    color: {ACCENT};
    border: 1px solid rgba(94, 106, 210, 0.35);
    border-radius: 5px;
    padding: 2px 7px;
    font-size: 7.5pt;
    font-weight: 700;
    letter-spacing: 0.3px;
}}

/* Кнопка выбора действия на карточке (Этап 5) */
QPushButton#CardActionBtn {{
    background-color: {BTN_BG};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 4px 10px;
    font-size: 8.5pt;
    font-weight: 600;
}}
QPushButton#CardActionBtn:hover {{
    background-color: {BTN_HOVER_BG};
    color: {BTN_HOVER_TEXT};
    border-color: {ACCENT};
}}

/* Кнопка меню действий в заголовке мини-окна (Этап 5) */
QPushButton#QuickActionsMenuBtn {{
    background-color: {BTN_BG};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 7px;
    padding: 4px 11px;
    min-height: 28px;
    font-size: 9pt;
    font-weight: 600;
}}
QPushButton#QuickActionsMenuBtn:hover {{
    background-color: {BTN_HOVER_BG};
    color: {BTN_HOVER_TEXT};
    border-color: {ACCENT};
}}

/* Кнопка добавления своего запроса */
QPushButton#CustomPromptToggleBtn {{
    background-color: {BTN_BG};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 7px;
    padding: 4px 11px;
    min-height: 28px;
    font-size: 9pt;
    font-weight: 600;
}}
QPushButton#CustomPromptToggleBtn:hover {{
    background-color: {BTN_HOVER_BG};
    color: {BTN_HOVER_TEXT};
    border-color: {ACCENT};
}}

/* Подпанель ввода произвольного промпта */
QFrame#CustomPromptBar {{
    background-color: {PROJECT_BAR_BG};
    border-bottom: 1px solid {BORDER};
}}

QLineEdit#CustomPromptEdit {{
    background-color: {BG_SURFACE_ALT};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER_INPUT};
    border-radius: 6px;
    padding: 5px 9px;
    font-size: 9pt;
}}
QLineEdit#CustomPromptEdit:focus {{
    border: 1.5px solid {ACCENT};
    background-color: {BG_SURFACE};
}}

QPushButton#CloseSubBarBtn {{
    background-color: transparent;
    color: {TEXT_MUTED};
    border: none;
    font-size: 11pt;
    padding: 2px 8px;
}}
QPushButton#CloseSubBarBtn:hover {{
    color: {DANGER};
}}

/* Панель быстрых действий (Pills) */
QFrame#PinnedActionsBar {{
    background-color: {PROJECT_BAR_BG};
    border-bottom: 1px solid {BORDER};
}}

QLabel#PinnedBarLabel {{
    color: {TEXT_MUTED};
    font-size: 8pt;
    font-weight: 600;
    padding-right: 4px;
}}

QPushButton#QuickActionPill {{
    background-color: {BTN_BG};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 12px;
    padding: 3px 10px;
    font-size: 8pt;
    font-weight: 600;
}}
QPushButton#QuickActionPill:hover {{
    background-color: {BTN_HOVER_BG};
    color: {BTN_HOVER_TEXT};
    border-color: {ACCENT};
}}
QPushButton#QuickActionPill:pressed {{
    background-color: {BTN_PRESSED_BG};
}}

/* Кнопка смены направления ⇄ (Этап 4) */
QPushButton#DirectionSwapBtn {{
    background-color: {BTN_BG};
    color: {TEXT_SECONDARY};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 4px 8px;
    font-size: 9.5pt;
    font-weight: 700;
}}
QPushButton#DirectionSwapBtn:hover {{
    background-color: {BTN_HOVER_BG};
    color: {TEXT_PRIMARY};
    border-color: {ACCENT};
}}

/* Кнопка «Заменить в тексте» — главное действие карточки */
QPushButton#ReplaceButton {{
    background-color: {ACCENT};
    color: #FFFFFF;
    border: 1px solid #6E7EFF;
    border-radius: 7px;
    padding: 5px 14px;
    font-size: 9pt;
    font-weight: 600;
}}
QPushButton#ReplaceButton:hover {{
    background-color: {ACCENT_HOVER};
    border-color: #9AA6FF;
    color: #FFFFFF;
}}
QPushButton#ReplaceButton:disabled {{
    background-color: {BTN_DISABLED_BG};
    border-color: {BTN_DISABLED_BORDER};
    color: {TEXT_MUTED};
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
QTabWidget, QStackedWidget {{
    background-color: {BG_WINDOW};
}}

QTabWidget::pane {{
    border: 1px solid {BORDER};
    border-radius: 10px;
    background-color: {BG_SURFACE};
    top: -1px;
}}

QTabBar::tab {{
    background: transparent;
    color: {TEXT_SECONDARY};
    padding: 7px 11px;
    margin-right: 2px;
    font-weight: 600;
    font-size: 9.5pt;
    border: 1px solid transparent;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
}}

QTabBar::tab:selected {{
    background-color: {BG_SURFACE};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-bottom: 2px solid {ACCENT};
}}

QTabBar::tab:hover:!selected {{
    color: {TEXT_PRIMARY};
    background-color: {BG_CARD_HOVER};
}}

/* Разделители QSplitter (История, Проекты) */
QSplitter {{
    background: transparent;
}}

QSplitter::handle {{
    background-color: {SPLITTER_HANDLE};
    border-radius: 2px;
}}

QSplitter::handle:hover {{
    background-color: {ACCENT};
}}

QSplitter::handle:pressed {{
    background-color: {ACCENT_HOVER};
}}

QSplitter::handle:horizontal {{
    width: 5px;
    margin: 2px 0;
}}

QSplitter::handle:vertical {{
    height: 5px;
    margin: 0 2px;
}}

/* Карточки-контейнеры для группировки настроек */
QFrame#SectionBox, QFrame#SettingsCard {{
    background-color: {BG_CARD};
    border: 1px solid {BORDER};
    border-radius: 12px;
}}

QFrame#SectionBox:hover, QFrame#SettingsCard:hover {{
    border-color: {BORDER_LIGHT};
}}

QFrame#ConnectionBox {{
    background-color: {BG_SURFACE_ALT};
    border: 1px solid {BORDER};
    border-radius: 8px;
}}

QLabel#CardTitle {{
    font-size: 11pt;
    font-weight: 700;
    color: {TEXT_PRIMARY};
}}

QLabel#CardSubtitle {{
    font-size: 8.5pt;
    color: {TEXT_SECONDARY};
}}

QLabel#FieldLabel {{
    font-size: 9.5pt;
    font-weight: 600;
    color: {TEXT_PRIMARY};
}}

/* Поля ввода (выделенные контрастные боксы) */
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox {{
    background-color: {BG_SURFACE_ALT};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER_INPUT};
    border-radius: 8px;
    padding: 8px 12px;
    selection-background-color: {ACCENT};
    selection-color: #FFFFFF;
}}

QSpinBox {{
    qproperty-alignment: 'AlignCenter';
}}

QLineEdit:hover, QTextEdit:hover, QPlainTextEdit:hover, QSpinBox:hover {{
    border-color: {ACCENT};
}}

QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus {{
    border: 1.5px solid {ACCENT};
    background-color: {BG_SURFACE};
    color: {TEXT_PRIMARY};
}}

QLineEdit:disabled, QTextEdit:disabled, QPlainTextEdit:disabled, QSpinBox:disabled {{
    background-color: {INPUT_DISABLED_BG};
    color: {TEXT_MUTED};
    border-color: {INPUT_DISABLED_BORDER};
}}

QPlainTextEdit:read-only, QTextEdit:read-only {{
    background-color: {BG_SURFACE_ALT};
    color: {TEXT_PRIMARY};
}}

/* Группы параметров */
QGroupBox {{
    border: 1px solid {BORDER};
    border-radius: 10px;
    margin-top: 10px;
    padding-top: 14px;
    font-weight: 600;
    color: {TEXT_PRIMARY};
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 8px;
    color: {ACCENT};
}}

/* Области прокрутки */
QScrollArea, QScrollArea > QWidget > QWidget, QWidget#SettingsPage {{
    background: transparent;
    border: none;
}}

/* Ползунки Temperature / Top-P */
QSlider::groove:horizontal {{
    height: 6px;
    background: {BORDER};
    border-radius: 3px;
}}

QSlider::sub-page:horizontal {{
    background: {ACCENT};
    border-radius: 3px;
}}

QSlider::handle:horizontal {{
    width: 18px;
    height: 18px;
    margin: -6px 0;
    border-radius: 9px;
    background: #FFFFFF;
    border: 2px solid {ACCENT};
}}

QSlider::handle:horizontal:hover {{
    background: {ACCENT_HOVER};
    border-color: #FFFFFF;
}}

QLabel#ValueLabel {{
    background-color: {BG_SURFACE_ALT};
    color: {ACCENT};
    border: 1px solid {BORDER_INPUT};
    border-radius: 6px;
    padding: 2px 8px;
    font-weight: 700;
    font-size: 10.5pt;
    min-width: 38px;
}}

/* Значок «[?]» с подробной подсказкой */
QLabel#HintLabel {{
    background-color: {BG_SURFACE_ALT};
    color: {ACCENT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 1px 7px;
    font-weight: 700;
    font-size: 8.5pt;
}}

QLabel#HintLabel:hover {{
    background-color: {ACCENT};
    color: #FFFFFF;
    border-color: {ACCENT};
}}

/* Плашки статуса и безопасности */
QLabel#SecurityBadge {{
    background-color: rgba(63, 185, 112, 0.12);
    color: #4ADE80;
    border: 1px solid rgba(63, 185, 112, 0.3);
    border-radius: 6px;
    padding: 2px 8px;
    font-size: 8.5pt;
    font-weight: 600;
}}

QLabel#StatusBadgeOk {{
    background-color: rgba(63, 185, 112, 0.15);
    color: #4ADE80;
    border: 1px solid rgba(63, 185, 112, 0.35);
    border-radius: 6px;
    padding: 4px 10px;
    font-weight: 600;
    font-size: 9pt;
}}

QLabel#StatusBadgeErr {{
    background-color: rgba(229, 72, 77, 0.15);
    color: #FF6E73;
    border: 1px solid rgba(229, 72, 77, 0.35);
    border-radius: 6px;
    padding: 4px 10px;
    font-weight: 600;
    font-size: 9pt;
}}

/* Приглушённая подпись под параметром */
QLabel#CaptionLabel {{
    color: {TEXT_SECONDARY};
    font-size: 8.5pt;
}}

/* Чекбоксы (включённость хоткея, режим диагностики) */
QCheckBox {{
    spacing: 10px;
    color: {TEXT_PRIMARY};
    background: transparent;
    font-weight: 500;
}}

QCheckBox::indicator {{
    width: 17px;
    height: 17px;
    border: 1px solid {BORDER_INPUT};
    border-radius: 4px;
    background-color: {BG_SURFACE_ALT};
}}

QCheckBox::indicator:hover {{
    border-color: {ACCENT};
    background-color: {BG_CARD_HOVER};
}}

QCheckBox::indicator:checked {{
    background-color: {ACCENT};
    border-color: {ACCENT};
}}

QCheckBox:disabled {{
    color: {TEXT_MUTED};
}}

/* Список пресетов */
QListWidget {{
    background-color: {BG_SURFACE_ALT};
    border: 1px solid {BORDER_INPUT};
    border-radius: 8px;
    padding: 6px;
    color: {TEXT_PRIMARY};
}}

QListWidget::item {{
    padding: 8px 10px;
    border-radius: 6px;
    margin-bottom: 2px;
}}

QListWidget::item:selected {{
    background-color: {ACCENT};
    color: #FFFFFF;
    font-weight: 600;
}}

QListWidget::item:hover:!selected {{
    background-color: {BG_CARD_HOVER};
    color: {TEXT_PRIMARY};
}}

/* Шпаргалка по промптам */
QFrame#CheatSheet {{
    background-color: {BG_CARD};
    border: 1px solid {BORDER};
    border-radius: 12px;
}}

QFrame#CheatSheet:hover {{
    border-color: {BORDER_LIGHT};
}}

QLabel#CheatSheetTitle {{
    color: {ACCENT};
    font-weight: 700;
    font-size: 10pt;
}}

QLabel#CheatSheetBody {{
    color: {TEXT_SECONDARY};
    font-size: 9pt;
    line-height: 140%;
}}

/* Строка состояния */
QStatusBar {{
    background-color: {BG_WINDOW};
    color: {TEXT_SECONDARY};
    border-top: 1px solid {BORDER};
}}

/* ============================================================ */
/* Раздел «История» (ЭТАП 7)                                    */
/* ============================================================ */
QTableWidget#HistoryTable {{
    background-color: {TABLE_BG};
    border: 1px solid {BORDER};
    border-radius: 8px;
    gridline-color: {BORDER};
    selection-background-color: {ACCENT};
    selection-color: #FFFFFF;
    color: {TEXT_PRIMARY};
    font-size: 9pt;
}}
QTableWidget#HistoryTable::item {{
    padding: 6px 8px;
    border-bottom: 1px solid {BORDER};
}}
QTableWidget#HistoryTable::item:selected {{
    background-color: {ACCENT};
    color: #FFFFFF;
}}
QHeaderView::section {{
    background-color: {TABLE_HEADER_BG};
    color: {TEXT_MUTED};
    padding: 6px 8px;
    border: none;
    border-bottom: 1px solid {BORDER};
    border-right: 1px solid {BORDER};
    font-weight: 600;
    font-size: 8.5pt;
}}

QPushButton#HistoryBrowserBtn {{
    background-color: {BTN_BG};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 7px;
    padding: 4px 11px;
    min-height: 28px;
    font-size: 9pt;
    font-weight: 600;
}}
QPushButton#HistoryBrowserBtn:hover {{
    background-color: {BTN_HOVER_BG};
    border-color: {ACCENT};
    color: {BTN_HOVER_TEXT};
}}

QPushButton#StarBtn {{
    background-color: transparent;
    color: #475569;
    border: none;
    font-size: 13pt;
    padding: 0px;
}}
QPushButton#StarBtn:hover {{
    color: #FBBF24;
}}

QPushButton#StarBtnActive {{
    background-color: transparent;
    color: #F59E0B;
    border: none;
    font-size: 13pt;
    padding: 0px;
}}
QPushButton#StarBtnActive:hover {{
    color: #FCD34D;
}}

QFrame#HistoryDetailPanel {{
    background-color: {BG_CARD};
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 8px;
}}

QLabel#HistoryDetailTitle {{
    color: {TEXT_PRIMARY};
    font-weight: 700;
    font-size: 10pt;
}}

QLabel#HistoryBadge {{
    background-color: {BG_SURFACE_ALT};
    color: {ACCENT};
    border: 1px solid {BORDER};
    border-radius: 5px;
    padding: 2px 7px;
    font-size: 8.5pt;
    font-weight: 600;
}}

QPlainTextEdit#HistoryDetailEdit, QTextEdit#HistoryDetailEdit {{
    background-color: {BG_SURFACE_ALT};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER_INPUT};
    border-radius: 8px;
    padding: 10px 12px;
    font-size: 9.5pt;
    selection-background-color: {ACCENT};
    selection-color: #FFFFFF;
}}

QPlainTextEdit#HistoryDetailEdit:hover, QTextEdit#HistoryDetailEdit:hover {{
    border-color: {ACCENT};
}}

QPlainTextEdit#HistoryDetailEdit:focus, QTextEdit#HistoryDetailEdit:focus {{
    background-color: {BG_SURFACE};
    border: 1.5px solid {ACCENT};
    color: {TEXT_PRIMARY};
}}

QPlainTextEdit#HistoryDetailEdit:read-only, QTextEdit#HistoryDetailEdit:read-only {{
    background-color: {BG_SURFACE_ALT};
    color: {TEXT_PRIMARY};
}}

/* =========================================================================
   ЭТАП 8: Проекты, Контекст и Глоссарий
   ========================================================================= */

/* Панель проекта в мини-окне */
QFrame#ProjectBar {{
    background-color: {PROJECT_BAR_BG};
    border-bottom: 1px solid {BORDER};
    padding: 2px 0px;
}}

QComboBox#ProjectSelector {{
    background-color: {BG_SURFACE_ALT};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER_INPUT};
    border-radius: 6px;
    padding: 4px 8px;
    font-size: 8.5pt;
    font-weight: 600;
}}
QComboBox#ProjectSelector:hover {{
    border-color: {ACCENT};
}}

QPushButton#ProjectBarBtn {{
    background-color: {BTN_BG};
    color: {TEXT_SECONDARY};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 4px 8px;
    font-size: 8pt;
    font-weight: 500;
}}
QPushButton#ProjectBarBtn:hover {{
    background-color: {BTN_HOVER_BG};
    color: {TEXT_PRIMARY};
    border-color: {ACCENT};
}}

/* Бейджи приватности */
QLabel#PrivacyBadgeLocal {{
    background-color: rgba(34, 197, 94, 0.12);
    color: #4ADE80;
    border: 1px solid rgba(34, 197, 94, 0.3);
    border-radius: 6px;
    padding: 3px 8px;
    font-size: 8pt;
    font-weight: 600;
}}

QLabel#PrivacyBadgeCloud {{
    background-color: rgba(245, 158, 11, 0.12);
    color: #FBBF24;
    border: 1px solid rgba(245, 158, 11, 0.35);
    border-radius: 6px;
    padding: 3px 8px;
    font-size: 8pt;
    font-weight: 600;
}}

/* Подпанель ввода разового контекста (Ad-Hoc) */
QFrame#AdHocBar {{
    background-color: {PROJECT_BAR_BG};
    border-bottom: 1px solid {BORDER};
}}
QLineEdit#AdHocEdit {{
    background-color: {BG_SURFACE_ALT};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER_INPUT};
    border-radius: 6px;
    padding: 5px 8px;
    font-size: 8.5pt;
}}

/* Бейдж проекта на карточке перевода */
QLabel#CardProjectBadge {{
    background-color: {BG_SURFACE_ALT};
    color: {ACCENT};
    border: 1px solid {BORDER};
    border-radius: 5px;
    padding: 2px 7px;
    font-size: 8pt;
    font-weight: 600;
}}

/* Список проектов в окне настроек */
QListWidget#ProjectsList {{
    background-color: {BG_SURFACE_ALT};
    border: 1px solid {BORDER_INPUT};
    border-radius: 8px;
    color: {TEXT_PRIMARY};
    outline: none;
    padding: 4px;
}}
QListWidget#ProjectsList::item {{
    padding: 10px 12px;
    border-radius: 6px;
    margin-bottom: 3px;
}}
QListWidget#ProjectsList::item:hover {{
    background-color: {BG_CARD_HOVER};
}}
QListWidget#ProjectsList::item:selected {{
    background-color: {ACCENT};
    color: #FFFFFF;
    border-left: 3px solid {ACCENT_HOVER};
}}

/* Таблица глоссария */
QTableWidget#GlossaryTable {{
    background-color: {BG_SURFACE_ALT};
    border: 1px solid {BORDER_INPUT};
    border-radius: 8px;
    gridline-color: {BORDER};
    color: {TEXT_PRIMARY};
    selection-background-color: {ACCENT};
    selection-color: #FFFFFF;
}}
QTableWidget#GlossaryTable::item {{
    padding: 6px 8px;
}}

/* Карточка предупреждения о приватности */
QFrame#PrivacyWarningCard {{
    background-color: rgba(245, 158, 11, 0.08);
    border: 1px solid rgba(245, 158, 11, 0.25);
    border-radius: 8px;
    padding: 10px 14px;
}}
QLabel#PrivacyWarningText {{
    color: {WARNING};
    font-size: 8.5pt;
    line-height: 1.4;
}}
QFrame#PrivacyLocalCard {{
    background-color: rgba(34, 197, 94, 0.08);
    border: 1px solid rgba(34, 197, 94, 0.25);
    border-radius: 8px;
    padding: 10px 14px;
}}
QLabel#PrivacyLocalText {{
    color: {SUCCESS};
    font-size: 8.5pt;
    line-height: 1.4;
}}


/* ============================================================ */
/* ЭТАП 9: Статусы операций и Мастер первого запуска            */
/* ============================================================ */

/* Бейджи статусов карточки (Этап 9.3) */
QLabel#CardStatusBadge {{
    padding: 3px 9px;
    border-radius: 5px;
    font-size: 8.5pt;
    font-weight: 600;
}}

QLabel#CardStatusIdle {{
    background-color: {STATUS_IDLE_BG};
    color: {STATUS_IDLE_TEXT};
    border: 1px solid {BORDER};
}}

QLabel#CardStatusCapturing {{
    background-color: {STATUS_PROGRESS_BG};
    color: {STATUS_PROGRESS_TEXT};
    border: 1px solid {ACCENT};
}}

QLabel#CardStatusSending {{
    background-color: {STATUS_PROGRESS_BG};
    color: {STATUS_PROGRESS_TEXT};
    border: 1px solid {ACCENT};
}}

QLabel#CardStatusGenerating {{
    background-color: {STATUS_PROGRESS_BG};
    color: {STATUS_PROGRESS_TEXT};
    border: 1px solid {ACCENT};
}}

QLabel#CardStatusReady {{
    background-color: {STATUS_DONE_BG};
    color: {STATUS_DONE_TEXT};
    border: 1px solid {SUCCESS};
}}

QLabel#CardStatusError {{
    background-color: {STATUS_ERROR_BG};
    color: {STATUS_ERROR_TEXT};
    border: 1px solid {DANGER};
}}

QLabel#CardStatusCancelled {{
    background-color: {STATUS_CANCEL_BG};
    color: {STATUS_CANCEL_TEXT};
    border: 1px solid {BORDER};
}}

/* Кнопка отмены запроса */
QPushButton#CardCancelBtn {{
    background-color: {STATUS_ERROR_BG};
    color: {DANGER};
    border: 1px solid {DANGER};
    border-radius: 6px;
    padding: 3px 10px;
    font-size: 8.5pt;
    font-weight: 600;
}}

QPushButton#CardCancelBtn:hover {{
    background-color: {DANGER};
    color: #FFFFFF;
}}

/* Кнопка подробностей ошибки */
QPushButton#CardDetailsBtn {{
    background-color: transparent;
    color: {TEXT_MUTED};
    border: none;
    font-size: 8pt;
    text-decoration: underline;
    padding: 2px 4px;
}}

QPushButton#CardDetailsBtn:hover {{
    color: {TEXT_PRIMARY};
}}

/* Диагностическая панель подробностей ошибки (Этап 9.6) */
QFrame#CardTechnicalDetails {{
    background-color: {BG_SURFACE_ALT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 8px 12px;
    margin-top: 4px;
}}

QLabel#CardTechnicalDetailsText {{
    color: {TEXT_SECONDARY};
    font-family: "Consolas", "Courier New", monospace;
    font-size: 8.5pt;
}}

/* Кнопка переключения поверх всех окон */
QPushButton#PinTopBtn {{
    background-color: {BTN_BG};
    color: {TEXT_SECONDARY};
    border: 1px solid {BORDER};
    border-radius: 7px;
    padding: 4px 11px;
    min-height: 28px;
    font-size: 9pt;
    font-weight: 600;
}}

QPushButton#PinTopBtn:hover {{
    background-color: {BG_CARD_HOVER};
    color: {TEXT_PRIMARY};
}}

QPushButton#PinTopBtn:checked {{
    background-color: {ACCENT};
    color: #FFFFFF;
    border-color: {ACCENT};
}}

/* Разделение оригинала и результата (Этап 9.2) */
QFrame#SourceContainer {{
    background-color: {SOURCE_BG};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 6px 10px;
    margin-bottom: 4px;
}}

QLabel#SourceHeaderLabel {{
    color: {TEXT_MUTED};
    font-size: 8pt;
    font-weight: 700;
    text-transform: uppercase;
}}

QLabel#CardSourceLabel {{
    color: {SOURCE_TEXT};
    font-size: 9pt;
    line-height: 1.4;
}}

QLabel#CardResultLabel {{
    color: {RESULT_TEXT};
    font-size: 10.5pt;
    font-weight: 500;
    line-height: 1.45;
    padding: 4px 0px;
}}

/* Мастер первоначальной настройки (Этап 9.4) */
QDialog#FirstRunWizard {{
    background-color: {BG_WINDOW};
}}

QFrame#WizardStepCard {{
    background-color: {BG_CARD};
    border: 1px solid {BORDER};
    border-radius: 12px;
    padding: 20px;
}}

QLabel#WizardTitle {{
    color: {TEXT_PRIMARY};
    font-size: 15pt;
    font-weight: 700;
}}

QLabel#WizardSubtitle {{
    color: {TEXT_SECONDARY};
    font-size: 9.5pt;
    line-height: 1.4;
}}

QLabel#WizardStepIndicator {{
    color: {ACCENT};
    font-size: 9pt;
    font-weight: 700;
}}

QFrame#WizardChoiceBox {{
    background-color: {BG_SURFACE_ALT};
    border: 1.5px solid {BORDER};
    border-radius: 10px;
    padding: 12px;
}}

QFrame#WizardChoiceBox:hover {{
    border-color: {ACCENT};
    background-color: {BG_CARD_HOVER};
}}

QFrame#WizardChoiceBoxSelected {{
    background-color: {BG_SURFACE_ALT};
    border: 2px solid {ACCENT};
    border-radius: 10px;
    padding: 12px;
}}
"""


def get_application_stylesheet(theme: str = "dark", font_size: str = "medium") -> str:
    """Генерирует полную таблицу стилей QSS для выбранной темы и размера шрифта."""
    palette = get_theme_palette(theme)
    # Форматируем плейсхолдеры палитры
    qss = _QSS_RAW_TEMPLATE.format(**palette)
    # Масштабируем шрифты
    return scale_font_sizes(qss, font_size)


# Дефолтный стиль (тёмный, средний шрифт) для обратной совместимости
APP_QSS = get_application_stylesheet("dark", "medium")


def apply_theme(app: Optional[QApplication] = None, theme: str = "dark", font_size: str = "medium") -> str:
    """Применяет тему и размер шрифта ко всему приложению.
    Возвращает фактически применённую тему ('dark' или 'light')."""
    palette = get_theme_palette(theme)
    actual_theme = "light" if palette == LIGHT_PALETTE else "dark"
    qss = get_application_stylesheet(actual_theme, font_size)
    target = app or QApplication.instance()
    if target is not None:
        try:
            target.setStyleSheet(qss)
        except Exception:
            pass
    return actual_theme


def repolish(widget: QWidget) -> None:
    """Применяет QSS заново после смены objectName или состояния у виджета."""
    style = widget.style()
    if style:
        style.unpolish(widget)
        style.polish(widget)


def apply_title_bar_theme(window: QWidget, dark: bool = True) -> None:
    """Переключает тему заголовка окна (Windows 10 сборка 19041+ / Windows 11)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        hwnd = int(window.winId())
        val = 1 if dark else 0
        value = ctypes.c_int(val)
        dwm = ctypes.windll.dwmapi
        result = dwm.DwmSetWindowAttribute(
            hwnd, 20, ctypes.byref(value), ctypes.sizeof(value)  # 20 = DWMWA_USE_IMMERSIVE_DARK_MODE
        )
        if result != 0:
            dwm.DwmSetWindowAttribute(
                hwnd, 19, ctypes.byref(value), ctypes.sizeof(value)
            )
    except Exception:
        pass


def apply_dark_title_bar(window: QWidget) -> None:
    """Тёмный заголовок окна (обратная совместимость)."""
    apply_title_bar_theme(window, dark=True)
