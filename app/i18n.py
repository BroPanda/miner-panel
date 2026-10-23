"""Мова інтерфейсу. tr("український текст") — переклад для вибраної мови; ключ — сам український текст
(шаблони з {0}, {1}… — як у str.format). Словник англійської — i18n_en.EN; чого в ньому немає, лишається українською.
Мова — налаштування UiLang ("uk" / "en"; порожньо — за мовою системи). Числа: uk «1 234,56», en «1,234.56»."""
from __future__ import annotations

LANGS = {"uk": "Українська", "en": "English"}
LANG = "uk"
_EN: dict[str, str] | None = None


def set_lang(code: str) -> None:
    global LANG
    LANG = code if code in LANGS else "uk"
    try:        # числові поля Qt (кома чи крапка) — за мовою панелі, а не системи
        from PySide6.QtCore import QLocale
        QLocale.setDefault(QLocale(QLocale.English, QLocale.UnitedStates) if LANG == "en" else QLocale(QLocale.Ukrainian, QLocale.Ukraine))
    except ImportError:
        pass


def tr(s: str) -> str:
    global _EN
    if LANG == "uk":
        return s
    if _EN is None:
        from .i18n_en import EN
        _EN = EN
    return _EN.get(s, s)


def num(s: str) -> str:
    """Число, відформатоване Python ("1,234.56" або "0.5"), — у формат вибраної мови."""
    return s if LANG == "en" else s.replace(",", " ").replace(".", ",")


def system_lang() -> str:
    """Мова системи: українська (або російська — люди з України) → "uk", інакше "en"."""
    try:
        from PySide6.QtCore import QLocale
        return "uk" if QLocale.system().language() in (QLocale.Ukrainian, QLocale.Russian) else "en"
    except Exception:  # noqa: BLE001
        return "uk"
