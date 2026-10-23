"""Головне вікно: верхній рядок стану, бічне меню з розділами, сторінки."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (QButtonGroup, QFrame, QHBoxLayout, QLabel, QMainWindow, QPushButton, QStackedWidget,
                               QVBoxLayout, QWidget)

from ..core.economics import fmt_uah
from . import icons, theme
from .pages.coins import CoinsPage
from .pages.devices import DevicesPage
from .pages.journal import JournalPage
from .pages.money import MoneyPage
from .pages.overview import OverviewPage
from .pages.settings import SettingsPage
from .widgets import StatusDot, button, label

# Значки малюються лініями (icons.py): символи шрифту на кшталт ▦ ◈ у Segoe UI виходили крихітними
SECTIONS = [("overview", "Огляд"), ("devices", "Пристрої"), ("money", "Гроші"),
            ("coins", "Монети"), ("settings", "Налаштування"), ("journal", "Журнал")]


class MainWindow(QMainWindow):
    action = Signal(str)          # дія користувача → контролер
    closing = Signal(object)      # подія закриття (контролер вирішує: трей чи вихід)

    def __init__(self, expert: bool = True):
        super().__init__()
        self.setWindowTitle("Miner Panel")
        self.setMinimumSize(1000, 680)
        self.resize(1240, 820)
        self.expert = expert
        self.snap: dict | None = None
        root = QWidget()
        h = QHBoxLayout(root)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)

        # ---- бічне меню ----
        side = QFrame()
        side.setObjectName("Sidebar")
        side.setFixedWidth(theme.pt(208))         # ширше з більшим шрифтом
        sv = QVBoxLayout(side)
        sv.setContentsMargins(10, 16, 10, 12)
        sv.setSpacing(4)
        sv.addWidget(label("⛏  Miner Panel", "Brand"))
        self.nav = QButtonGroup(self)
        self.nav.setExclusive(True)
        self.nav_buttons: dict[str, QPushButton] = {}
        for key, text in SECTIONS:
            if key == "journal":
                sv.addStretch(1)
            b = QPushButton(f"  {text}")
            b.setIcon(icons.nav_icon(key, theme.pt(20)))
            b.setIconSize(QSize(theme.pt(20), theme.pt(20)))
            b.setObjectName("NavButton")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self.show_section(k))
            self.nav.addButton(b)
            self.nav_buttons[key] = b
            sv.addWidget(b)
        # Жовта позначка на «Налаштуваннях»: є оновлення майнерів
        self.upd_badge = QLabel(self.nav_buttons["settings"])
        self.upd_badge.setAlignment(Qt.AlignCenter)
        self.upd_badge.setFixedSize(22, 18)
        self.upd_badge.hide()
        self.version = label("версія 2.0 · Windows і Linux", "Muted")
        self.version.setContentsMargins(16, 8, 0, 0)
        sv.addWidget(self.version)
        h.addWidget(side)

        # ---- верхній рядок + сторінки ----
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(0)
        head = QFrame()
        head.setObjectName("Header")
        hh = QHBoxLayout(head)
        hh.setContentsMargins(24, 12, 24, 12)
        hh.setSpacing(18)
        st = QVBoxLayout()
        st.setSpacing(0)
        self.h_state = StatusDot()
        self.h_state.setObjectName("HeaderState")
        self.h_sub = label("", "HeaderSub")
        st.addWidget(self.h_state)
        st.addWidget(self.h_sub)
        hh.addLayout(st, 1)
        pr = QVBoxLayout()
        pr.setSpacing(0)
        self.h_profit_lbl = label("ПРИБУТОК ЗА ДОБУ", "HeaderProfitLabel")
        pr.addWidget(self.h_profit_lbl, 0, Qt.AlignRight)
        self.h_profit = label("—", "HeaderProfit")
        pr.addWidget(self.h_profit, 0, Qt.AlignRight)
        hh.addLayout(pr)
        self.run_btn = button("▶  Старт", "Start", lambda: self.action.emit("run:toggle"))
        self.run_btn.setMinimumWidth(130)
        hh.addWidget(self.run_btn)
        rv.addWidget(head)

        self.stack = QStackedWidget()
        self.pages = {"overview": OverviewPage(), "devices": DevicesPage(), "money": MoneyPage(),
                      "coins": CoinsPage(), "settings": SettingsPage(), "journal": JournalPage()}
        for k, p in self.pages.items():
            self.stack.addWidget(p)
            p.action.connect(self._on_page_action)
        rv.addWidget(self.stack, 1)
        h.addWidget(right, 1)
        self.setCentralWidget(root)
        self.show_section("overview")

    # ---- навігація і показ ----
    def show_section(self, key: str) -> None:
        self.nav_buttons[key].setChecked(True)
        # На «Огляді» прибуток — велика плитка, у шапці його не дублюємо
        self.h_profit_lbl.setVisible(key != "overview")
        self.h_profit.setVisible(key != "overview")
        self.stack.setCurrentWidget(self.pages[key])
        if self.snap:
            self.pages[key].render(self.snap, self.expert)

    def current_section(self) -> str:
        return next(k for k, p in self.pages.items() if p is self.stack.currentWidget())

    def _on_page_action(self, a: str) -> None:
        if a.startswith("open:device:"):
            self.pages["devices"].select(a.split(":", 2)[2])
            self.show_section("devices")
            return
        if a.startswith("open:") and a[5:] in self.pages:
            self.show_section(a[5:])
            return
        self.action.emit(a)

    def update_header(self, snap: dict) -> None:
        """Верхній рядок і позначки меню — щотакту, без перебудови сторінки."""
        t = theme.current()
        s = snap["status"]
        self.h_state.set(s["level"], s["text"])
        self.h_sub.setText(s["detail"])
        parts = [v for v in (snap.get("profit_day"), snap.get("farm_profit_day")) if v is not None]
        if parts:
            total = sum(parts)
            self.h_profit.setText(fmt_uah(total))
            self.h_profit.setStyleSheet(f"color:{t.good_text if total >= 0 else t.critical}")
        else:
            self.h_profit.setText("—")
            self.h_profit.setStyleSheet(f"color:{t.muted}")
        running = s["running"]
        if self.run_btn.objectName() != ("Stop" if running else "Start"):
            self.run_btn.setText("■  Стоп" if running else "▶  Старт")
            self.run_btn.setObjectName("Stop" if running else "Start")
            self.run_btn.style().unpolish(self.run_btn)
            self.run_btn.style().polish(self.run_btn)
        n = len(snap["notices"])
        self.nav_buttons["overview"].setText(f"  Огляд{'   ▲ ' + str(n) if n else ''}")
        upd = [m["name"] for m in snap.get("miners") or [] if m.get("state") == "є оновлення"]
        if upd:
            b = self.nav_buttons["settings"]
            self.upd_badge.setText(str(len(upd)))
            self.upd_badge.setStyleSheet(f"background:{t.warning}; color:#1a1a19; border-radius:9px; font-weight:700; font-size:{theme.pt(8)}pt;")
            self.upd_badge.move(b.width() - self.upd_badge.width() - 10, (b.height() - self.upd_badge.height()) // 2)
            self.upd_badge.setToolTip("Є оновлення: " + ", ".join(upd))
            b.setToolTip("Є оновлення майнерів: " + ", ".join(upd))
            self.upd_badge.show()
        else:
            self.upd_badge.hide()
            self.nav_buttons["settings"].setToolTip("")

    def render(self, snap: dict) -> None:
        """Верхній рядок + перебудова поточної сторінки (без блимання, зі збереженням прокрутки)."""
        self.snap = snap
        self.update_header(snap)
        page = self.stack.currentWidget()
        sb = page.verticalScrollBar().value()
        self.setUpdatesEnabled(False)
        try:
            page.render(snap, self.expert)
        finally:
            self.setUpdatesEnabled(True)
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, lambda: page.verticalScrollBar().setValue(sb))

    def resizeEvent(self, e):
        # Сторінки підлаштовують розкладку під ширину (картки в ряд чи одна під одною) — перебудувати після зміни розміру
        super().resizeEvent(e)
        if self.snap:
            from PySide6.QtCore import QTimer
            if not hasattr(self, "_resize_timer"):
                self._resize_timer = QTimer(self)
                self._resize_timer.setSingleShot(True)
                self._resize_timer.timeout.connect(lambda: self.snap and self.render(self.snap))
            self._resize_timer.start(200)

    def closeEvent(self, e):
        self.closing.emit(e)
