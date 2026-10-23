"""Усі тести — без вікон на екрані (offscreen), але зі шрифтами Windows: тоді розміри тексту такі самі, як у справжньому
вікні, а користувачу нічого не вискакує на панелі задач і не перехоплює фокус."""
import os

from app.core import platform

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if platform.IS_WIN:
    os.environ.setdefault("QT_QPA_FONTDIR", os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"))
