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

# --- Палитра (тёмная премиальная тема) ---------------------------------------
BG_WINDOW = "#13151A"       # глубокий фон окна (deep slate)
BG_SURFACE = "#171A21"      # поверхность полотна вкладок и панелей
BG_CARD = "#1D212A"         # фон контейнеров / карточек настроек
BG_CARD_HOVER = "#222732"   # карточка при наведении
BG_SURFACE_ALT = "#111317"  # фон полей ввода (recessed dark box)
BORDER = "#2A303D"          # граница карточек и разделителей
BORDER_LIGHT = "#384152"    # более светлая рамка при наведении
BORDER_INPUT = "#2E3444"    # граница полей ввода
ACCENT = "#5B6CFF"          # основной современный акцент (индиго-электрик)
ACCENT_HOVER = "#7382FF"   # яркий акцент при наведении
ACCENT_PRESSED = "#4B59D9"  # акцент при нажатии
TEXT_PRIMARY = "#F0F2F7"    # четкий высококонтрастный текст
TEXT_SECONDARY = "#8F97A9"  # аккуратный вторичный текст
TEXT_MUTED = "#6B7285"      # приглушённый неактивный текст
DANGER = "#E5484D"          # опасные действия
DANGER_HOVER = "#FF6368"    # опасные действия при наведении
DANGER_PRESSED = "#C23A3F"  # опасные действия в нажатом состоянии
SUCCESS = "#3FB970"         # подтверждение («Скопировано ✓»)
SUCCESS_HOVER = "#49CE7F"   # подтверждение при наведении
WARNING = "#F5A623"         # предупреждения

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

/* --- Кнопки (базовые стили) ------------------------------------------ */
QPushButton {{
    background-color: #242834;
    color: #DDE2ED;
    border: 1px solid #363D4E;
    border-radius: 8px;
    padding: 7px 16px;
    font-weight: 600;
    font-size: 9.5pt;
}}

QPushButton:hover {{
    background-color: #2D3344;
    color: #FFFFFF;
    border-color: {ACCENT};
}}

QPushButton:pressed {{
    background-color: #1F232D;
    border-color: {ACCENT_PRESSED};
}}

QPushButton:disabled {{
    background-color: #1B1E26;
    border-color: #262A34;
    color: {TEXT_MUTED};
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
    background-color: #2D3350;
    border-color: #353B55;
    color: #7B84A0;
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
    padding: 6px 14px;
    font-weight: 600;
}}
QPushButton#ModeButtonAi:hover {{
    background-color: {ACCENT_HOVER};
    border-color: #9AA6FF;
    color: #FFFFFF;
}}

QPushButton#ModeButtonStd {{
    background-color: #202430;
    color: {TEXT_SECONDARY};
    border: 1px solid {BORDER};
    border-radius: 7px;
    padding: 5px 13px;
    font-weight: 600;
}}
QPushButton#ModeButtonStd:hover {{
    background-color: #272C3B;
    color: #FFFFFF;
    border-color: {ACCENT};
}}

/* Кнопка «Очистить историю» */
QPushButton#ClearButton {{
    background-color: #202430;
    color: {TEXT_SECONDARY};
    border: 1px solid {BORDER};
    border-radius: 7px;
    padding: 6px 12px;
}}
QPushButton#ClearButton:hover {{
    background-color: #2D2124;
    color: #FF7075;
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
    background-color: #1F222B;
    color: #BAC2D4;
    border: 1px solid #323847;
    border-radius: 7px;
    padding: 5px 12px;
    font-size: 9pt;
    font-weight: 500;
}}
QPushButton#GhostButton:hover {{
    background-color: #292E3C;
    color: #FFFFFF;
    border-color: {ACCENT};
}}
QPushButton#GhostButton:pressed {{
    background-color: #191B22;
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
    border-color: #3F475A;
}}
QComboBox:focus {{
    border: 1.5px solid {ACCENT};
}}
QComboBox:disabled {{
    background-color: #16181E;
    color: {TEXT_MUTED};
    border-color: #232731;
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

/* Ошибка перевода прямо в карточке (⚠ …) */
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
    background-color: #2D1A1E;
    color: #FFA198;
    border: 1px solid #5A2A32;
    border-radius: 7px;
    padding: 5px 12px;
    font-size: 9pt;
    font-weight: 600;
}}
QPushButton#CancelLoadingBtn:hover {{
    background-color: #402026;
    border-color: #F85149;
    color: #FFFFFF;
}}

/* Кнопка «Сравнить» / Diff (Этап 6.3) */
QPushButton#DiffToggleBtn {{
    background-color: #1A1D24;
    color: #BAC2D4;
    border: 1px solid #2F3647;
    border-radius: 7px;
    padding: 5px 10px;
    font-size: 8.5pt;
    font-weight: 600;
}}
QPushButton#DiffToggleBtn:hover {{
    background-color: #242938;
    color: #FFFFFF;
    border-color: {ACCENT};
}}
QPushButton#DiffToggleBtn[active="true"] {{
    background-color: #22294A;
    color: #9AA6FF;
    border-color: {ACCENT};
}}

/* Кнопки в карточке: удалить, редактировать исходник, меню «⋯» (Этап 6.4) */
QPushButton#CardSmallIconBtn, QPushButton#MoreMenuBtn {{
    background-color: transparent;
    color: #8B949E;
    border: 1px solid transparent;
    border-radius: 5px;
    padding: 2px 7px;
    font-size: 9pt;
    font-weight: 600;
}}
QPushButton#CardSmallIconBtn:hover, QPushButton#MoreMenuBtn:hover {{
    background-color: #242938;
    color: #FFFFFF;
    border-color: #384152;
}}

QPushButton#DeleteCardBtn {{
    background-color: transparent;
    color: #8B949E;
    border: 1px solid transparent;
    border-radius: 5px;
    padding: 2px 6px;
    font-size: 9pt;
    font-weight: 700;
}}
QPushButton#DeleteCardBtn:hover {{
    background-color: #3A1F23;
    color: #FFA198;
    border-color: #F85149;
}}

/* Блок сравнения оригинала и результата (Этап 6.3) */
QFrame#ComparisonPanel {{
    background-color: #12141A;
    border: 1px solid #2A303F;
    border-radius: 9px;
}}
QLabel#DiffColHeader {{
    color: #9AA6FF;
    font-size: 8.5pt;
    font-weight: 700;
}}
QLabel#DiffTextBox {{
    background-color: #181B23;
    color: #C9D1D9;
    border: 1px solid #262B38;
    border-radius: 6px;
    padding: 8px;
    font-size: 9.5pt;
}}
QLabel#DiffSectionHeader {{
    color: #BAC2D4;
    font-size: 8.5pt;
    font-weight: 700;
}}
QLabel#DiffStatsBadge {{
    background-color: rgba(94, 106, 210, 0.15);
    color: #9AA6FF;
    border-radius: 4px;
    padding: 1px 6px;
    font-size: 8pt;
    font-weight: 600;
}}
QLabel#DiffHtmlView {{
    background-color: #181B23;
    border: 1px solid #262B38;
    border-radius: 6px;
    padding: 10px;
    font-size: 10pt;
    line-height: 1.4;
}}

/* Блоки отдельных вариантов (Этап 6.2) */
QFrame#VariantBlock {{
    background-color: #141720;
    border: 1px solid #282E3E;
    border-radius: 8px;
}}
QFrame#VariantBlock:hover {{
    border-color: #3B445A;
}}
QLabel#VariantTitle {{
    color: #9AA6FF;
    font-size: 9pt;
    font-weight: 700;
}}
QLabel#VariantText {{
    color: {TEXT_PRIMARY};
    font-size: 10pt;
    line-height: 1.35;
}}
QPushButton#VariantActionBtn {{
    background-color: #1E232E;
    color: #BAC2D4;
    border: 1px solid #2E3646;
    border-radius: 5px;
    padding: 3px 9px;
    font-size: 8pt;
    font-weight: 600;
}}
QPushButton#VariantActionBtn:hover {{
    background-color: #293040;
    color: #FFFFFF;
    border-color: {ACCENT};
}}

/* Встроенные панели редактирования (Этап 6.1 и 6.4) */
QFrame#InlineEditorBar {{
    background-color: #13161D;
    border: 1px solid #2C3342;
    border-radius: 8px;
}}
QTextEdit#InlineTextEdit, QLineEdit#InlineLineEdit {{
    background-color: #1A1D26;
    color: {TEXT_PRIMARY};
    border: 1px solid #333C4E;
    border-radius: 6px;
    padding: 6px 8px;
    font-size: 9.5pt;
}}
QTextEdit#InlineTextEdit:focus, QLineEdit#InlineLineEdit:focus {{
    border: 1.5px solid {ACCENT};
}}

/* Кнопка «Скопировать» и её состояние «Скопировано ✓» */
QPushButton#CopyButton {{
    background-color: #202430;
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 7px;
    padding: 5px 14px;
    font-size: 9pt;
    font-weight: 600;
}}
QPushButton#CopyButton:hover {{
    background-color: #272C3B;
    border-color: {ACCENT};
    color: #FFFFFF;
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
    background-color: #202430;
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 7px;
    padding: 5px 12px;
    font-size: 9pt;
    font-weight: 600;
}}
QPushButton#RegenerateButton:hover {{
    background-color: #272C3B;
    border-color: {ACCENT};
    color: #FFFFFF;
}}
QPushButton#RegenerateButton:disabled {{
    background-color: #16181E;
    color: {TEXT_MUTED};
    border-color: #232731;
}}

/* Бейдж направления перевода на карточке (EN → RU) (Этап 4) */
QPushButton#DirectionBadge {{
    background-color: #1A1D24;
    color: #7987FF;
    border: 1px solid #2F3647;
    border-radius: 6px;
    padding: 4px 9px;
    font-size: 8.5pt;
    font-weight: 700;
    letter-spacing: 0.5px;
}}
QPushButton#DirectionBadge:hover {{
    background-color: #242938;
    color: #9AA6FF;
    border-color: {ACCENT};
}}

/* Бейдж применённого действия на карточке (Этап 5) */
QLabel#CardActionBadge {{
    background-color: rgba(94, 106, 210, 0.15);
    color: #9AA6FF;
    border: 1px solid rgba(94, 106, 210, 0.35);
    border-radius: 5px;
    padding: 2px 7px;
    font-size: 7.5pt;
    font-weight: 700;
    letter-spacing: 0.3px;
}}

/* Кнопка выбора действия на карточке (Этап 5) */
QPushButton#CardActionBtn {{
    background-color: #1A1D24;
    color: #BAC2D4;
    border: 1px solid #2F3647;
    border-radius: 6px;
    padding: 4px 10px;
    font-size: 8.5pt;
    font-weight: 600;
}}
QPushButton#CardActionBtn:hover {{
    background-color: #242938;
    color: #FFFFFF;
    border-color: {ACCENT};
}}

/* Кнопка меню действий в заголовке мини-окна (Этап 5) */
QPushButton#QuickActionsMenuBtn {{
    background-color: #202430;
    color: #BAC2D4;
    border: 1px solid #333948;
    border-radius: 7px;
    padding: 6px 12px;
    font-size: 9pt;
    font-weight: 600;
}}
QPushButton#QuickActionsMenuBtn:hover {{
    background-color: #292E3C;
    color: #FFFFFF;
    border-color: {ACCENT};
}}

/* Кнопка добавления своего запроса */
QPushButton#CustomPromptToggleBtn {{
    background-color: #202430;
    color: #BAC2D4;
    border: 1px solid #333948;
    border-radius: 7px;
    padding: 6px 11px;
    font-size: 8.5pt;
    font-weight: 600;
}}
QPushButton#CustomPromptToggleBtn:hover {{
    background-color: #292E3C;
    color: #FFFFFF;
    border-color: {ACCENT};
}}

/* Подпанель ввода произвольного промпта */
QFrame#CustomPromptBar {{
    background-color: #171920;
    border-bottom: 1px solid #2B303E;
}}

QLineEdit#CustomPromptEdit {{
    background-color: #1F232D;
    color: {TEXT_PRIMARY};
    border: 1px solid #363D4E;
    border-radius: 6px;
    padding: 5px 9px;
    font-size: 9pt;
}}
QLineEdit#CustomPromptEdit:focus {{
    border: 1.5px solid {ACCENT};
}}

QPushButton#CloseSubBarBtn {{
    background-color: transparent;
    color: #7B84A0;
    border: none;
    font-size: 11pt;
    padding: 2px 8px;
}}
QPushButton#CloseSubBarBtn:hover {{
    color: #FF7075;
}}

/* Панель быстрых действий (Pills) */
QFrame#PinnedActionsBar {{
    background-color: #15171D;
    border-bottom: 1px solid #262A36;
}}

QLabel#PinnedBarLabel {{
    color: #70788D;
    font-size: 8pt;
    font-weight: 600;
    padding-right: 4px;
}}

QPushButton#QuickActionPill {{
    background-color: #1E222C;
    color: #BAC2D4;
    border: 1px solid #2D3342;
    border-radius: 12px;
    padding: 3px 10px;
    font-size: 8pt;
    font-weight: 600;
}}
QPushButton#QuickActionPill:hover {{
    background-color: #272C39;
    color: #FFFFFF;
    border-color: {ACCENT};
}}
QPushButton#QuickActionPill:pressed {{
    background-color: #191B22;
}}

/* Кнопка смены направления ⇄ (Этап 4) */
QPushButton#DirectionSwapBtn {{
    background-color: #1A1D24;
    color: #8F97A9;
    border: 1px solid #2F3647;
    border-radius: 6px;
    padding: 4px 8px;
    font-size: 9.5pt;
    font-weight: 700;
}}
QPushButton#DirectionSwapBtn:hover {{
    background-color: #242938;
    color: #FFFFFF;
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
    background-color: #2D3350;
    border-color: #353B55;
    color: #7B84A0;
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
    background-color: {BG_SURFACE};
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
    padding: 9px 20px;
    margin-right: 4px;
    font-weight: 600;
    border: 1px solid transparent;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
}}

QTabBar::tab:selected {{
    background-color: {BG_SURFACE};
    color: #FFFFFF;
    border: 1px solid {BORDER};
    border-bottom: 1px solid {BG_SURFACE};
}}

QTabBar::tab:hover:!selected {{
    color: #FFFFFF;
    background-color: rgba(255, 255, 255, 0.04);
}}

/* Карточки-контейнеры для группировки настроек */
QFrame#SettingsCard {{
    background-color: {BG_CARD};
    border: 1px solid {BORDER};
    border-radius: 12px;
}}

QFrame#SettingsCard:hover {{
    border-color: {BORDER_LIGHT};
}}

QLabel#CardTitle {{
    font-size: 11pt;
    font-weight: 700;
    color: #FFFFFF;
}}

QLabel#CardSubtitle {{
    font-size: 8.5pt;
    color: {TEXT_SECONDARY};
}}

QLabel#FieldLabel {{
    font-size: 9.5pt;
    font-weight: 600;
    color: #DDE2EC;
}}

/* Поля ввода (выделенные контрастные боксы) */
QLineEdit, QTextEdit, QSpinBox {{
    background-color: {BG_SURFACE_ALT};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER_INPUT};
    border-radius: 8px;
    padding: 8px 12px;
    selection-background-color: {ACCENT};
    selection-color: #FFFFFF;
}}

QLineEdit:hover, QTextEdit:hover, QSpinBox:hover {{
    border-color: #3F475A;
}}

QLineEdit:focus, QTextEdit:focus, QSpinBox:focus {{
    border: 1.5px solid {ACCENT};
    background-color: #151820;
    color: #FFFFFF;
}}

QLineEdit:disabled, QSpinBox:disabled {{
    background-color: #16181E;
    color: {TEXT_MUTED};
    border-color: #232731;
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
    background-color: #232734;
    color: {ACCENT};
    border: 1px solid #353C4D;
    border-radius: 6px;
    padding: 1px 7px;
    font-weight: 700;
    font-size: 8.5pt;
}}

QLabel#HintLabel:hover {{
    background-color: #31374A;
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
    background-color: #171A22;
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
    background-color: #1A1E28;
    color: #FFFFFF;
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
