"""Журнал: події простою мовою; в експертному режимі ще й лог майнера."""
from __future__ import annotations

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QPlainTextEdit

from .. import theme
from ..widgets import Card, fill_table, make_table
from . import Page

LEVEL_TEXT = {"info": "ℹ подія", "ok": "● добре", "warn": "▲ увага", "error": "■ проблема"}


class JournalPage(Page):
    def __init__(self):
        super().__init__()
        self.c_events = Card("Що відбувалося")
        self.table = make_table(["Час", "Що", "Подія"], stretch=2)
        self.c_events.body.addWidget(self.table)
        self.lay.addWidget(self.c_events)
        self.c_log = Card("Лог майнера")
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(QFont("Consolas", 9))
        self.log.setMinimumHeight(260)
        self.c_log.body.addWidget(self.log)
        self.lay.addWidget(self.c_log)
        self.lay.addStretch(1)

    def render(self, s: dict, expert: bool) -> None:
        t = theme.current()
        rows = [[tm, LEVEL_TEXT.get(lv, lv), text] for tm, lv, text in s["journal"]]
        colors = {(i, 1): theme.status_color(lv) for i, (_, lv, _) in enumerate(s["journal"])}
        fill_table(self.table, rows, colors=colors)
        self.c_log.setVisible(expert)
        if self.log.toPlainText() != s["miner_log"]:
            self.log.setPlainText(s["miner_log"])
