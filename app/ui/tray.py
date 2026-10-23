"""Значок біля годинника: стан кольоровою крапкою + меню; сповіщення про проблеми."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from . import theme
from ..i18n import tr


def dot_icon(color: str) -> QIcon:
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor("#1a1a19"))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(2, 2, 60, 60, 14, 14)
    p.setBrush(QColor(color))
    p.drawEllipse(16, 16, 32, 32)
    p.end()
    return QIcon(pm)


class Tray(QSystemTrayIcon):
    requested = Signal(str)      # 'open' | 'run:toggle' | 'quit'

    def __init__(self, parent=None):
        super().__init__(parent)
        m = QMenu()
        self.a_open = QAction(tr('Відкрити панель'))
        self.a_run = QAction(tr('Старт'))
        self.a_quit = QAction(tr('Вийти (майнінг зупиниться)'))
        for a, key in ((self.a_open, "open"), (self.a_run, "run:toggle"), (self.a_quit, "quit")):
            a.triggered.connect(lambda _=False, k=key: self.requested.emit(k))
            m.addAction(a)
        m.insertSeparator(self.a_quit)
        self.setContextMenu(m)
        self._menu = m
        self.activated.connect(lambda r: self.requested.emit("open") if r == QSystemTrayIcon.Trigger else None)
        self.update_state("off", tr('Зупинено'), False)

    def retranslate(self) -> None:
        self.a_open.setText(tr('Відкрити панель'))
        self.a_quit.setText(tr('Вийти (майнінг зупиниться)'))

    def update_state(self, level: str, text: str, running: bool) -> None:
        self.setIcon(dot_icon(theme.status_color(level, theme.DARK) if level != "off" else "#898781"))
        self.setToolTip(f"Miner Panel — {text}")
        self.a_run.setText(tr('Зупинити майнінг') if running else tr('Почати майнінг'))

    def notify(self, n) -> None:
        icon = {"error": QSystemTrayIcon.Critical, "warn": QSystemTrayIcon.Warning}.get(n.level, QSystemTrayIcon.Information)
        self.showMessage(n.title, n.text, icon, 10000)
