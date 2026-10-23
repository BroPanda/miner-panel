"""Кольори й стилі інтерфейсу: темна і світла тема (обидві підібрані окремо, не автоматичне інвертування).
Палітра — перевірена базова (поверхні, текст, статуси); статусні кольори зарезервовані лише для станів
і завжди йдуть зі значком і підписом, ніколи не лише кольором."""
from __future__ import annotations

import re

from dataclasses import dataclass

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication


@dataclass(frozen=True)
class Theme:
    name: str
    page: str          # фон вікна
    surface: str       # картки, таблиці, графіки
    raised: str        # кнопки, поля
    hover: str
    border: str
    ink: str           # основний текст
    ink2: str          # другорядний
    muted: str         # підписи осей, підказки
    grid: str
    axis: str
    accent: str        # акцент і серія графіків
    accent_ink: str    # текст на акценті
    good: str
    warning: str
    serious: str
    critical: str
    good_text: str     # «зелений» текст (дельта вгору) з достатнім контрастом


DARK = Theme("dark", page="#121211", surface="#1a1a19", raised="#242422", hover="#2e2e2b", border="#33332f",
             ink="#f0efec", ink2="#d2d1c7", muted="#a3a19a", grid="#2c2c2a", axis="#383835",
             accent="#3987e5", accent_ink="#ffffff", good="#0ca30c", warning="#fab219", serious="#ec835a",
             critical="#d03b3b", good_text="#0ca30c")
LIGHT = Theme("light", page="#f2f1ee", surface="#fcfcfb", raised="#ffffff", hover="#ebeae6", border="#dcdbd4",
              ink="#0b0b0b", ink2="#3f3e3b", muted="#64635e", grid="#e1e0d9", axis="#c3c2b7",
              accent="#2a78d6", accent_ink="#ffffff", good="#0ca30c", warning="#fab219", serious="#ec835a",
              critical="#d03b3b", good_text="#006300")

_current: Theme = DARK
# Розмір шрифту (налаштування UiFont): усі розміри в стилях множаться на коефіцієнт
FONT_SCALE = {"normal": 1.0, "large": 1.2, "huge": 1.4}
_scale = 1.0

STATUS_ICON = {"good": "●", "ok": "●", "info": "ℹ", "warn": "▲", "warning": "▲", "serious": "▲", "error": "■", "critical": "■", "off": "○"}


def current() -> Theme:
    return _current


def status_color(level: str, t: Theme | None = None) -> str:
    t = t or _current
    return {"good": t.good, "ok": t.good, "mining": t.good, "warn": t.warning, "warning": t.warning,
            "serious": t.serious, "error": t.critical, "critical": t.critical, "offline": t.critical,
            "info": t.accent}.get(level, t.muted)


def detect_system_dark() -> bool:
    app = QApplication.instance()
    try:
        from PySide6.QtCore import Qt
        return app.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except Exception:  # noqa: BLE001 — старі Qt без colorScheme
        return True


def pt(size: float) -> int:
    """Розмір шрифту з урахуванням налаштування UiFont — для стилів, заданих прямо у віджетах."""
    return max(1, round(size * _scale))


def apply(app: QApplication, mode: str, font: str = "large") -> Theme:
    """mode: 'dark' | 'light' | 'system'; font: 'normal' | 'large' | 'huge'."""
    global _current, _scale
    _scale = FONT_SCALE.get(font, 1.2)
    _current = (DARK if detect_system_dark() else LIGHT) if mode == "system" else (LIGHT if mode == "light" else DARK)
    t = _current
    app.setStyle("Fusion")
    pal = QPalette()
    for role, c in ((QPalette.Window, t.page), (QPalette.Base, t.surface), (QPalette.AlternateBase, t.raised),
                    (QPalette.Text, t.ink), (QPalette.WindowText, t.ink), (QPalette.Button, t.raised),
                    (QPalette.ButtonText, t.ink), (QPalette.Highlight, t.accent), (QPalette.HighlightedText, t.accent_ink),
                    (QPalette.ToolTipBase, t.raised), (QPalette.ToolTipText, t.ink), (QPalette.PlaceholderText, t.muted)):
        pal.setColor(role, QColor(c))
    pal.setColor(QPalette.Disabled, QPalette.Text, QColor(t.muted))
    pal.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(t.muted))
    pal.setColor(QPalette.Disabled, QPalette.WindowText, QColor(t.muted))
    app.setPalette(pal)
    # Дробові числа в полях — як в усьому інтерфейсі: українською 4,32, англійською 4.32
    from .. import i18n
    i18n.set_lang(i18n.LANG)
    f = QFont("Segoe UI" if _is_windows() else "Sans Serif", pt(10))
    app.setFont(f)
    app.setStyleSheet(re.sub(r"font-size: ?(\d+)pt", lambda m: f"font-size: {pt(int(m.group(1)))}pt", stylesheet(t)))
    return t


def _is_windows() -> bool:
    import sys
    return sys.platform == "win32"


def stylesheet(t: Theme) -> str:
    return f"""
    QWidget {{ color: {t.ink}; }}
    QMainWindow, #Page, QScrollArea, QScrollArea > QWidget > QWidget {{ background: {t.page}; }}
    QToolTip {{ background: {t.raised}; color: {t.ink}; border: 1px solid {t.border}; padding: 6px 8px; border-radius: 6px; }}

    #Sidebar {{ background: {t.surface}; border-right: 1px solid {t.border}; }}
    #NavButton {{ text-align: left; padding: 10px 16px; border: none; border-radius: 8px; color: {t.ink2};
                  background: transparent; font-size: 11pt; }}
    #NavButton:hover {{ background: {t.hover}; color: {t.ink}; }}
    #NavButton:checked {{ background: {t.raised}; color: {t.ink}; font-weight: 600; border-left: 3px solid {t.accent}; }}
    #Brand {{ font-size: 12pt; font-weight: 700; padding: 4px 16px 12px 16px; }}

    #Header {{ background: {t.surface}; border-bottom: 1px solid {t.border}; }}
    #HeaderState {{ font-size: 14pt; font-weight: 700; }}
    #HeaderSub {{ color: {t.ink2}; }}
    #HeaderProfitLabel {{ color: {t.muted}; font-size: 9pt; }}
    #HeaderProfit {{ font-size: 18pt; font-weight: 700; }}

    #Card {{ background: {t.surface}; border: 1px solid {t.border}; border-radius: 12px; }}
    #CardTitle {{ font-size: 11pt; font-weight: 600; }}
    #SectionTitle {{ font-size: 13pt; font-weight: 700; padding: 4px 0; }}
    #TileLabel {{ color: {t.ink2}; font-size: 10pt; }}
    #TileValue {{ font-size: 22pt; font-weight: 700; }}
    #TileHero {{ font-size: 30pt; font-weight: 700; }}
    #TileSub {{ color: {t.ink2}; }}
    #KeyGood {{ color: {t.good_text}; font-weight: 700; font-size: 12pt; }}
    #KeyBad {{ color: {t.critical}; font-weight: 700; font-size: 12pt; }}
    #KeyCost {{ color: {t.serious}; font-weight: 700; font-size: 12pt; }}
    #KeyAccent {{ color: {t.accent}; font-weight: 700; font-size: 12pt; }}
    #KeyHead {{ color: {t.ink2}; font-size: 10pt; }}
    #Muted {{ color: {t.muted}; }}
    #Secondary {{ color: {t.ink2}; }}
    #Big {{ font-size: 16pt; font-weight: 700; }}

    QPushButton {{ background: {t.raised}; border: 1px solid {t.border}; border-radius: 8px; padding: 7px 14px; }}
    QPushButton:hover {{ background: {t.hover}; }}
    QPushButton:disabled {{ color: {t.muted}; }}
    QPushButton#Primary {{ background: {t.accent}; color: {t.accent_ink}; border: none; font-weight: 600; }}
    QPushButton#Primary:hover {{ background: {QColor(t.accent).lighter(112).name()}; }}
    QPushButton#Danger {{ background: {t.critical}; color: #ffffff; border: none; font-weight: 600; }}
    QPushButton#Danger:hover {{ background: {QColor(t.critical).lighter(112).name()}; }}
    QPushButton#Start {{ background: {t.good}; color: #ffffff; border: none; font-weight: 700; font-size: 12pt; padding: 10px 22px; }}
    QPushButton#Stop {{ background: {t.critical}; color: #ffffff; border: none; font-weight: 700; font-size: 12pt; padding: 10px 22px; }}
    QPushButton#Link {{ background: transparent; border: none; color: {t.accent}; padding: 2px 4px; }}
    QPushButton#Seg {{ border-radius: 0; padding: 6px 12px; }}
    QPushButton#Seg:checked {{ background: {t.accent}; color: {t.accent_ink}; border-color: {t.accent}; }}
    QPushButton#SegL {{ border-top-right-radius: 0; border-bottom-right-radius: 0; padding: 6px 12px; }}
    QPushButton#SegR {{ border-top-left-radius: 0; border-bottom-left-radius: 0; padding: 6px 12px; }}
    QPushButton#SegL:checked, QPushButton#SegR:checked {{ background: {t.accent}; color: {t.accent_ink}; border-color: {t.accent}; }}
    QPushButton#ModeCard {{ text-align: left; padding: 14px; border-radius: 12px; background: {t.surface}; }}
    QPushButton#ModeCard:checked {{ border: 2px solid {t.accent}; background: {t.raised}; }}
    QPushButton#Help {{ border-radius: 9px; padding: 0; min-width: 18px; max-width: 18px; min-height: 18px; max-height: 18px;
                        font-size: 8pt; font-weight: 700; color: {t.ink2}; }}

    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextEdit {{
        background: {t.raised}; border: 1px solid {t.border}; border-radius: 8px; padding: 6px 8px;
        selection-background-color: {t.accent}; }}
    QSpinBox, QDoubleSpinBox {{ padding: 4px 6px; min-height: 24px; }}
    QSpinBox::up-button, QDoubleSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::down-button {{ width: 18px; }}
    QComboBox QAbstractItemView {{ background: {t.raised}; border: 1px solid {t.border}; selection-background-color: {t.accent}; }}
    QCheckBox {{ spacing: 8px; }}

    QTableWidget, QTreeWidget {{ background: {t.surface}; border: none; gridline-color: {t.grid};
                                 alternate-background-color: {t.surface}; }}
    QHeaderView::section {{ background: {t.surface}; color: {t.muted}; border: none; border-bottom: 1px solid {t.border};
                            padding: 6px 8px; font-weight: 600; }}
    QTableWidget::item {{ padding: 4px 8px; border-bottom: 1px solid {t.grid}; }}
    QTableWidget::item:selected {{ background: {t.hover}; color: {t.ink}; }}

    QTabWidget::pane {{ border: none; }}
    QTabBar::tab {{ background: transparent; color: {t.ink2}; padding: 8px 16px; border: none; border-bottom: 2px solid transparent; }}
    QTabBar::tab:selected {{ color: {t.ink}; border-bottom: 2px solid {t.accent}; font-weight: 600; }}

    QProgressBar {{ background: {QColor(t.accent).darker(250).name() if t.name == 'dark' else '#cde2fb'}; border: none;
                    border-radius: 4px; height: 8px; text-align: center; color: transparent; }}
    QProgressBar::chunk {{ background: {t.accent}; border-radius: 4px; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; }}
    QScrollBar::handle:vertical {{ background: {t.border}; border-radius: 5px; min-height: 30px; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
    """
