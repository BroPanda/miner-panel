"""Спільні елементи інтерфейсу: картки, плитки-підсумки, статус, повідомлення, графіки, таблиці."""
from __future__ import annotations

import math
from datetime import datetime
from typing import Callable

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QCheckBox, QFrame, QHBoxLayout, QHeaderView, QLabel, QLayout, QProgressBar, QPushButton, QSizePolicy,
                               QStyle, QStyledItemDelegate, QTableWidget, QTableWidgetItem, QToolTip, QVBoxLayout, QWidget,
                               QAbstractItemView)

from . import glossary, theme


# ---- Прості будівельні блоки -------------------------------------------------
class FlowLayout(QLayout):
    """Ряд, що переноситься: елементи стоять поруч, поки вміщаються (не вужче за свій мінімум і min_w),
    решта — у наступний рядок. stretch=True — елементи рядка ділять ширину порівну й мають однакову висоту
    (картки, плитки); stretch=False — природна ширина, притиснуті ліворуч (кнопки).
    natural=True — елемент переноситься, щойно не вміщається його бажана ширина (а не мінімальна): картка
    з кількома колонками всередині спершу переходить у новий рядок цілою і лише потім складається сама."""

    def __init__(self, parent=None, spacing: int = 16, min_w: int = 0, stretch: bool = True, natural: bool = False,
                 uniform: bool = False):
        """uniform=True — сітка: однакова ширина в усіх рядках (останній неповний рядок не розтягується)."""
        super().__init__(parent)
        self.uniform = uniform
        self._items = []
        self._sp = spacing
        self.min_w = min_w
        self.stretch = stretch
        self.natural = natural
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)

    def addLayout(self, lay, *_):
        self.addChildLayout(lay)
        self.addItem(lay)

    def addStretch(self, *_):       # сумісність із QHBoxLayout: у потоці вирівнювання ліворуч і так є
        pass

    def setSpacing(self, s: int) -> None:
        self._sp = s

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return self._place(QRect(0, 0, w, 0), False)

    def setGeometry(self, r):
        super().setGeometry(r)
        self._place(r, True)

    def _vis(self):
        return [it for it in self._items if not it.isEmpty()]

    def _w(self, it) -> int:
        return max(it.minimumSize().width(), self.min_w if self.stretch else 0,
                   it.sizeHint().width() if self.natural or not self.stretch else 0)

    def minimumSize(self):
        s = QSize(0, 0)
        for it in self._vis():      # мінімум — справжній мінімум елемента; min_w і бажана ширина лише вирішують, коли переносити
            s = s.expandedTo(QSize(it.minimumSize().width(), it.minimumSize().height()))
        m = self.contentsMargins()
        return s + QSize(m.left() + m.right(), m.top() + m.bottom())

    def sizeHint(self):
        vis = self._vis()
        w = sum(max(self._w(it), it.sizeHint().width()) for it in vis) + self._sp * max(0, len(vis) - 1)
        h = max([it.sizeHint().height() for it in vis] or [0])
        m = self.contentsMargins()
        return QSize(w + m.left() + m.right(), h + m.top() + m.bottom())

    def _place(self, rect: QRect, apply: bool) -> int:
        m = self.contentsMargins()
        r = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        rows, row, used = [], [], 0
        for it in self._vis():
            w = self._w(it)
            if row and used + self._sp + w > r.width():
                rows.append(row)
                row, used = [], 0
            used += (self._sp if row else 0) + w
            row.append((it, w))
        if row:
            rows.append(row)
        y = r.y()
        cols = max((len(rw) for rw in rows), default=1)
        for row in rows:
            extra = r.width() - sum(w for _, w in row) - self._sp * (len(row) - 1)
            widths = [w + (extra // len(row) if self.stretch and extra > 0 else 0) for _, w in row]
            if self.stretch and extra > 0:
                widths[-1] += extra - (extra // len(row)) * len(row)
            if self.uniform and self.stretch:
                widths = [max(w, (r.width() - self._sp * (cols - 1)) // cols) for _, w in row]
            widths = [min(w, r.width()) for w in widths]     # ширший за рядок (natural) — стискається до рядка
            x = r.x()
            hs = [max(it.minimumSize().height(), it.heightForWidth(w) if it.hasHeightForWidth() else it.sizeHint().height())
                  for (it, _), w in zip(row, widths)]
            h = max(hs)
            for (it, _), w, ih in zip(row, widths, hs):
                if apply:
                    it.setGeometry(QRect(x, y, w, h if self.stretch else ih))
                x += w + self._sp
            y += h + self._sp
        return y - self._sp - r.y() + m.top() + m.bottom() if rows else 0


class CheckLine(QWidget):
    """Галочка з довгим підписом, що переноситься (у QCheckBox текст лише в один рядок і розпирає вікно)."""

    def __init__(self, text: str, checked: bool = False):
        super().__init__()
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        self.box = QCheckBox()
        self.box.setChecked(checked)
        self.text_label = label(text, wrap=True)
        self.text_label.setTextInteractionFlags(Qt.NoTextInteraction)
        self.text_label.ensurePolished()
        self.box.ensurePolished()
        # Квадратик і перший рядок підпису — на одній висоті (обидва притиснуті догори, нижчий зсунутий)
        diff = self.text_label.fontMetrics().height() - self.box.sizeHint().height()
        self.text_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.text_label.setContentsMargins(0, max(0, -diff) // 2, 0, 0)
        box_col = QVBoxLayout()
        box_col.setContentsMargins(0, max(0, diff) // 2, 0, 0)
        box_col.addWidget(self.box)
        box_col.addStretch(1)
        h.addLayout(box_col)
        h.addWidget(self.text_label, 1)
        self.toggled = self.box.toggled

    def setChecked(self, v: bool) -> None:
        self.box.setChecked(v)

    def isChecked(self) -> bool:
        return self.box.isChecked()

    def blockSignals(self, b: bool) -> bool:     # сигнал toggled — у самої галочки
        return self.box.blockSignals(b)

    def mouseReleaseEvent(self, e):      # клік по підпису теж перемикає
        if e.button() == Qt.LeftButton and self.isEnabled():
            self.box.toggle()


def label(text: str = "", obj: str | None = None, wrap: bool = False) -> QLabel:
    l = QLabel(text)
    if obj:
        l.setObjectName(obj)
    l.setWordWrap(wrap)
    l.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return l


def button(text: str, obj: str | None = None, cb: Callable | None = None, tip: str = "") -> QPushButton:
    b = QPushButton(text)
    if obj:
        b.setObjectName(obj)
    if cb:
        b.clicked.connect(cb)
    if tip:
        b.setToolTip(tip)
    b.setCursor(Qt.PointingHandCursor)
    return b


def help_icon(key: str) -> QPushButton:
    """Значок «?» з поясненням терміну — підказка при наведенні і при натисканні."""
    b = QPushButton("?")
    b.setObjectName("Help")
    text = glossary.term(key)
    b.setToolTip(text)
    b.clicked.connect(lambda: QToolTip.showText(b.mapToGlobal(b.rect().bottomLeft()), text, b))
    b.setCursor(Qt.WhatsThisCursor)
    b.setFocusPolicy(Qt.NoFocus)
    return b


def with_help(text: str, key: str, obj: str | None = None) -> QWidget:
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(6)
    h.addWidget(label(text, obj))
    h.addWidget(help_icon(key))
    h.addStretch(1)
    return w


class Card(QFrame):
    """Картка з необов'язковим заголовком; вміст — у self.body (QVBoxLayout)."""

    def __init__(self, title: str = "", help_key: str | None = None, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 14, 16, 14)
        v.setSpacing(10)
        self.head = QHBoxLayout()
        self.head.setSpacing(6)
        self.title = label(title, "CardTitle", wrap=True)
        if title:
            # Заголовок забирає всю вільну ширину: переноситься лише тоді, коли справді не вміщається
            self.head.addWidget(self.title, 1)
            if help_key:
                self.head.addWidget(help_icon(help_key))
            v.addLayout(self.head)
        self.body = QVBoxLayout()
        self.body.setSpacing(8)
        v.addLayout(self.body)


class StatusDot(QLabel):
    """Стан: значок + підпис (колір ніколи не несе зміст сам)."""

    def set(self, level: str, text: str):
        t = theme.current()
        icon = theme.STATUS_ICON.get(level, "●")
        self.setText(f"<span style='color:{theme.status_color(level)}'>{icon}</span>&nbsp;{text}")
        self.setTextFormat(Qt.RichText)


class StatTile(Card):
    """Плитка-підсумок: підпис · значення · підрядок · (необов'язково) шкала."""

    def __init__(self, caption: str, help_key: str | None = None, hero: bool = False, meter: bool = False):
        super().__init__()
        top = QHBoxLayout()
        top.setSpacing(6)
        top.addWidget(label(caption, "TileLabel"))
        if help_key:
            top.addWidget(help_icon(help_key))
        top.addStretch(1)
        self.body.addLayout(top)
        self.value = label("—", "TileHero" if hero else "TileValue")
        self.body.addWidget(self.value)
        self.bar = None
        if meter:
            self.bar = QProgressBar()
            self.bar.setRange(0, 1000)
            self.bar.setFixedHeight(8)
            self.body.addWidget(self.bar)
        self.sub = label("", "TileSub", wrap=True)
        self.body.addWidget(self.sub)
        self.body.addStretch(1)

    def set(self, value: str, sub: str = "", pct: float | None = None, value_color: str | None = None):
        self.value.setText(value)
        self.value.setStyleSheet(f"color:{value_color}" if value_color else "")
        self.sub.setText(sub)
        if self.bar is not None and pct is not None:
            self.bar.setValue(int(max(0, min(100, pct)) * 10))


class NoticeCard(QFrame):
    """Повідомлення: значок рівня, заголовок, пояснення (що сталося / що зроблено / що робити), кнопка дії."""
    acted = Signal(str)

    def __init__(self, n):
        super().__init__()
        t = theme.current()
        self.setObjectName("Card")
        col = theme.status_color(n.level)
        self.setStyleSheet(f"#Card {{ border-left: 4px solid {col}; }}")
        h = QHBoxLayout(self)
        h.setContentsMargins(14, 10, 14, 10)
        icon = QLabel(theme.STATUS_ICON.get(n.level, "●"))
        icon.setStyleSheet(f"color:{col}; font-size:{theme.pt(14)}pt")
        icon.setFixedWidth(22)
        h.addWidget(icon, 0, Qt.AlignTop)
        v = QVBoxLayout()
        v.setSpacing(2)
        v.addWidget(label(n.title, "CardTitle"))
        v.addWidget(label(n.text, "Secondary", wrap=True))
        h.addLayout(v, 1)
        if n.action:
            b = button(n.action, "Primary" if n.level in ("warn", "error") else None, lambda: self.acted.emit(n.action_id or ""))
            h.addWidget(b, 0, Qt.AlignVCenter)


class _BgDelegate(QStyledItemDelegate):
    """Фон рядка з BackgroundRole: стиль таблиці (QSS ::item) його ігнорує, тож малюємо самі під текстом."""

    def paint(self, p, option, index):
        b = index.data(Qt.BackgroundRole)
        if b is not None:
            p.fillRect(option.rect, b)
        super().paint(p, option, index)


class _Table(QTableWidget):
    """Ширини колонок рахуємо самі: усі за вмістом, а якщо не влазять — звужуються найширші (текст переноситься,
    числа — ні); заголовок теж переноситься. Залишок ширини — розтягнутій колонці."""

    def resizeEvent(self, e):
        super().resizeEvent(e)
        _fit_columns(self)


def cell_need(tb: QTableWidget, it: QTableWidgetItem, width: int | None = None) -> QSize:
    """Розмір клітинки разом із padding зі стилю: в один рядок (width=None) або з переносом у колонці ширини width.
    Qt сам рахує висоту перенесеного тексту без padding із QSS — рядок виходить нижчим і текст обрізається."""
    hint = tb.sizeHintForIndex(tb.indexFromItem(it))
    f = it.data(Qt.FontRole)
    fm = QFontMetrics(f) if f else QFontMetrics(tb.font())
    one = fm.boundingRect(QRect(0, 0, 10 ** 6, 10 ** 6), 0, it.text())
    pad, vpad = hint.width() - one.width(), hint.height() - one.height()
    if width is None:
        return hint
    br = fm.boundingRect(QRect(0, 0, max(1, width - pad), 10 ** 6), Qt.TextWordWrap, it.text())
    return QSize(br.width() + pad, br.height() + vpad)


def _words(s: str) -> list[str]:
    return s.replace("\n", " ").split() or [""]


def _wrap_header(fm, text: str, width: int) -> str:
    """Розбити заголовок на рядки не ширші за width (по словах)."""
    lines: list[str] = []
    for w in _words(text):
        if lines and fm.horizontalAdvance(lines[-1] + " " + w) <= width:
            lines[-1] += " " + w
        else:
            lines.append(w)
    return "\n".join(lines)


def _fit_columns(tb: QTableWidget) -> None:
    n = tb.columnCount()
    if not n or tb.property("fitting"):
        return
    tb.setProperty("fitting", True)
    hh = tb.horizontalHeader()
    tb.ensurePolished()
    hh.ensurePolished()
    numeric = set(tb.property("numeric_cols") or [])
    cfm, hfm = QFontMetrics(tb.font()), QFontMetrics(hh.font())
    nat, low, heads, hpads = [], [], [], []
    for c in range(n):
        h = tb.horizontalHeaderItem(c)
        head = (h.data(Qt.UserRole) or h.text()) if h else ""
        if h and h.text() != head:
            h.setText(head)
        heads.append(head)
        # Відступи заголовка (стиль, жирність) — з реального розміру секції, а не з метрик шрифту
        a = hh.sectionSizeFromContents(c).width()
        hpad = a - max(hfm.horizontalAdvance(x) for x in head.split("\n"))
        hpads.append((hpad, a))
        b = max(hfm.horizontalAdvance(w) for w in _words(head)) + hpad
        for r in range(tb.rowCount()):
            it = tb.item(r, c)
            if it and it.text():
                f = it.data(Qt.FontRole)
                fm = QFontMetrics(f) if f else cfm
                full = cell_need(tb, it).width()                  # разом із padding зі стилю
                pad = full - fm.horizontalAdvance(it.text())
                a = max(a, full)
                b = max(b, full if c in numeric else max(fm.horizontalAdvance(w) for w in _words(it.text())) + pad)
        nat.append(a)
        low.append(min(a, b))
    avail = tb.viewport().width()
    widths = list(nat)
    if sum(nat) > avail:
        # Стеля cap: колонки ширші за неї звужуються до неї (але не вужче за найдовше слово)
        lo_c, hi_c = 0, max(nat)
        while hi_c - lo_c > 1:
            mid = (lo_c + hi_c) // 2
            if sum(max(lw, min(nw, mid)) for nw, lw in zip(nat, low)) > avail:
                hi_c = mid
            else:
                lo_c = mid
        widths = [max(lw, min(nw, lo_c)) for nw, lw in zip(nat, low)]
    st = tb.property("stretch_col")
    if isinstance(st, int) and 0 <= st < n and sum(widths) < avail:
        widths[st] += avail - sum(widths)
    for c, w in enumerate(widths):
        hh.setSectionResizeMode(c, QHeaderView.Fixed)
        tb.setColumnWidth(c, w)
        h = tb.horizontalHeaderItem(c)
        if h:
            h.setData(Qt.UserRole, heads[c])
            hpad, hw = hpads[c]
            h.setText(_wrap_header(hfm, heads[c], w - hpad) if hw > w else heads[c])
    for r in range(tb.rowCount()):
        need = [cell_need(tb, it, widths[c]).height() for c in range(n) if (it := tb.item(r, c)) and it.text()]
        tb.setRowHeight(r, max([34] + need))
    _fit_height(tb)
    tb.setProperty("fitting", False)


def make_table(columns: list[str], stretch: int = 0) -> QTableWidget:
    tb = _Table(0, len(columns))
    tb.setItemDelegate(_BgDelegate(tb))
    tb.setHorizontalHeaderLabels(columns)
    tb.verticalHeader().setVisible(False)
    tb.setShowGrid(False)
    tb.setSelectionBehavior(QAbstractItemView.SelectRows)
    tb.setSelectionMode(QAbstractItemView.SingleSelection)
    tb.setEditTriggers(QAbstractItemView.NoEditTriggers)
    tb.setFocusPolicy(Qt.NoFocus)
    hh = tb.horizontalHeader()
    hh.setHighlightSections(False)
    hh.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    tb.setProperty("stretch_col", stretch)
    # Довгий текст у розтягнутій колонці переноситься (а не обрізається «…»), рядок росте по висоті
    tb.setWordWrap(True)
    tb.verticalHeader().setDefaultSectionSize(34)    # висоти рядків під перенесений текст ставить _fit_columns
    return tb


def _fit_height(tb: QTableWidget) -> None:
    """Висота таблиці — під усі рядки (до 12), без внутрішньої прокрутки."""
    shown = min(tb.rowCount(), 12)
    rows = sum(tb.rowHeight(i) for i in range(shown)) if shown else 34
    tb.setFixedHeight(tb.horizontalHeader().sizeHint().height() + rows + 2 * tb.frameWidth() + 2)


def highlight_bg() -> QColor:
    """Легкий фон виділеного рядка: акцент ~15 % поверх поверхні (непрозорий — щоб не залежати від стилю таблиці)."""
    t = theme.current()
    a, s = QColor(t.accent), QColor(t.surface)
    k = 0.15
    return QColor(int(s.red() + (a.red() - s.red()) * k), int(s.green() + (a.green() - s.green()) * k), int(s.blue() + (a.blue() - s.blue()) * k))


def fill_table(tb: QTableWidget, rows: list[list], bold_rows: set[int] | None = None, colors: dict | None = None,
               numeric: set[int] | None = None, tags: list | None = None, bg_rows: set[int] | None = None) -> None:
    """rows — список рядків (текст клітинок); colors — {(рядок, колонка): колір} лише для значків стану;
    bg_rows — рядки з легким фоном (напр. поточний сервер)."""
    tb.setRowCount(len(rows))
    numeric = numeric or set()
    tb.setProperty("numeric_cols", sorted(numeric))
    for r, row in enumerate(rows):
        for c, val in enumerate(row):
            it = QTableWidgetItem(str(val))
            if c in numeric:
                it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                f = it.font()
                f.setStyleHint(QFont.Monospace)
                it.setFont(f)
            if bold_rows and r in bold_rows:
                f = it.font()
                f.setBold(True)
                it.setFont(f)
            if colors and (r, c) in colors:
                it.setForeground(QColor(colors[(r, c)]))
            if bg_rows and r in bg_rows:
                it.setBackground(highlight_bg())
            if tags and c == 0:
                it.setData(Qt.UserRole, tags[r])
            tb.setItem(r, c, it)
    _fit_columns(tb)


def clear_layout(lay) -> None:
    while lay.count():
        it = lay.takeAt(0)
        w = it.widget()
        if w:
            # Прибрати одразу: deleteLater спрацює пізніше, і старий віджет устиг би намалюватись під новим
            w.hide()
            w.setParent(None)
            w.deleteLater()
        elif it.layout():
            clear_layout(it.layout())


# ---- Графіки ----------------------------------------------------------------
def nice_ticks(vmax: float, n: int = 4) -> list[float]:
    """Круглі поділки осі від 0 до ≥ vmax."""
    if vmax <= 0:
        return [0, 1]
    raw = vmax / n
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    return [i * step for i in range(int(math.ceil(vmax / step)) + 1)]


def compact(v: float) -> str:
    a = abs(v)
    if a >= 1e6:
        return f"{v / 1e6:.1f}M".replace(".0M", "M")
    if a >= 1e3:
        return f"{v / 1e3:.1f}K".replace(".0K", "K")
    if a >= 10 or v == 0:
        return f"{v:.0f}"
    s = f"{v:.1f}" if a >= 1 else f"{v:.2f}"
    return s.replace(".", ",")


class _ChartBase(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setMinimumHeight(150)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.hover: int | None = None
        self.empty_text = "ще немає даних — з'являться під час майнінгу"
        self.drawn_text: list[QRectF] = []    # де реально лягли підписи — тест вигляду перевіряє, що вони в межах віджета
        self.drawn_marks: list[QRectF] = []   # стовпчики — тест перевіряє, що підписи на них не налазять

    def _text(self, p: QPainter, rect: QRectF, flags, s: str) -> None:
        self.drawn_text.append(p.boundingRect(rect, flags, s))
        p.drawText(rect, flags, s)

    def leaveEvent(self, e):
        self.hover = None
        QToolTip.hideText()
        self.update()

    def _frame(self, p: QPainter, vmax: float, vmin: float = 0.0, fmt=compact, top: float = 8):
        """Сітка і вісь Y; повертає (rect графіка, функція y→пікселі). top — місце над графіком для підпису значення."""
        t = theme.current()
        ticks = nice_ticks(vmax) if vmax > 0 or vmin >= 0 else [0.0]   # лише збиток — шкала від 0 донизу
        lo = 0.0 if vmin >= 0 else -nice_ticks(-vmin)[-1]
        hi = ticks[-1]
        step = ticks[1] - ticks[0] if len(ticks) > 1 else 1
        if fmt is compact and step < 1:
            # Дрібні значення (копійки за перші хвилини) — стільки знаків, скільки потребує крок поділок
            dec = max(1, -math.floor(math.log10(step)))
            fmt = lambda v, d=dec: f"{v:.{d}f}".replace(".", ",")  # noqa: E731
        self._axis_fmt = fmt
        fm = p.fontMetrics()
        left = max(fm.horizontalAdvance(fmt(x)) for x in ticks + [lo]) + 10
        r = QRectF(left, top, self.width() - left - 12, self.height() - top - fm.height() - 8)

        def y(v):
            return r.bottom() - (v - lo) / (hi - lo or 1) * r.height()

        # Нуль і поділки вгору першими; від'ємні — лише ті, що не налазять на вже підписані
        neg = [-x for x in nice_ticks(-vmin)[1:]] if vmin < 0 else []
        placed: list[float] = []
        for v in ticks + neg:
            yy = round(y(v)) + 0.5
            if any(abs(yy - q) < fm.height() for q in placed):
                continue
            placed.append(yy)
            p.setPen(QPen(QColor(t.axis if v == 0 else t.grid), 1))
            p.drawLine(QPointF(r.left(), yy), QPointF(r.right(), yy))
            p.setPen(QColor(t.muted))
            self._text(p, QRectF(0, yy - fm.height() / 2, left - 6, fm.height()), Qt.AlignRight | Qt.AlignVCenter, fmt(v))
        return r, y


class ColumnChart(_ChartBase):
    """Стовпчики (одна серія): ≤ 24 px, заокруглений верх 4 px, квадратні біля основи; підказка при наведенні.
    points: [(підпис, значення, текст підказки)]."""

    def __init__(self, parent=None, fmt=compact):
        super().__init__(parent)
        self.points: list[tuple[str, float, str]] = []
        self.fmt = fmt
        self._bars: list[QRectF] = []

    def set_points(self, pts):
        self.points = list(pts)
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        t = theme.current()
        self.drawn_text, self.drawn_marks = [], []
        if not self.points:
            p.setPen(QColor(t.muted))
            p.drawText(self.rect().adjusted(8, 0, -8, 0), Qt.AlignCenter | Qt.TextWordWrap, self.empty_text)
            return
        vals = [v for _, v, _ in self.points]
        r, y = self._frame(p, max(max(vals), 0), min(min(vals), 0), self.fmt, top=p.fontMetrics().height() + 6)
        n = len(self.points)
        slot = r.width() / n
        w = min(24.0, slot * 0.6)
        fm = p.fontMetrics()
        self._bars = []
        for i, (lab, v, _) in enumerate(self.points):
            cx = r.left() + slot * (i + 0.5)
            y0, y1 = y(0), y(v)
            top, bot = min(y0, y1), max(y0, y1)
            rect = QRectF(cx - w / 2, top, w, max(1.0, bot - top))
            self._bars.append(QRectF(r.left() + slot * i, r.top(), slot, r.height()))
            col = QColor(t.accent)
            if self.hover is not None and self.hover != i:
                col.setAlphaF(0.55)
            path = QPainterPath()
            rad = min(4.0, rect.height() / 2, w / 2)
            if v >= 0:   # заокруглений кінець даних угорі, квадратний біля основи
                path.moveTo(rect.left(), rect.bottom())
                path.lineTo(rect.left(), rect.top() + rad)
                path.quadTo(rect.left(), rect.top(), rect.left() + rad, rect.top())
                path.lineTo(rect.right() - rad, rect.top())
                path.quadTo(rect.right(), rect.top(), rect.right(), rect.top() + rad)
                path.lineTo(rect.right(), rect.bottom())
            else:
                path.moveTo(rect.left(), rect.top())
                path.lineTo(rect.left(), rect.bottom() - rad)
                path.quadTo(rect.left(), rect.bottom(), rect.left() + rad, rect.bottom())
                path.lineTo(rect.right() - rad, rect.bottom())
                path.quadTo(rect.right(), rect.bottom(), rect.right(), rect.bottom() - rad)
                path.lineTo(rect.right(), rect.top())
            path.closeSubpath()
            p.fillPath(path, col)
            self.drawn_marks.append(rect)
            p.setPen(QColor(t.muted))
            self._text(p, QRectF(cx - slot / 2, r.bottom() + 4, slot, fm.height()), Qt.AlignCenter, lab)
        # Значення на кожному стовпчику: над ним; від'ємне — над нульовою лінією (стовпчик іде вниз, під ним місця нема)
        p.setPen(QColor(t.ink))
        for i, (_, v, _) in enumerate(self.points):
            cx = r.left() + slot * (i + 0.5)
            ly = y(max(v, 0)) - fm.height() - 2
            self._text(p, QRectF(cx - slot / 2, ly, slot, fm.height()), Qt.AlignCenter, self._axis_fmt(v))

    def mouseMoveEvent(self, e):
        for i, b in enumerate(self._bars):
            if b.contains(e.position()):
                if self.hover != i:
                    self.hover = i
                    self.update()
                QToolTip.showText(e.globalPosition().toPoint(), self.points[i][2], self)
                return
        self.leaveEvent(e)


class LineChart(_ChartBase):
    """Лінія (одна серія): 2 px, заливка ~10 %, кінцева точка 8 px з кільцем 2 px кольору поверхні,
    підпис значення в кінці, пунктир середнього з підписом, перехрестя з підказкою при наведенні. points: [(unix-час, значення)]."""

    def __init__(self, parent=None, fmt=compact, value_text: Callable[[float], str] | None = None):
        super().__init__(parent)
        self.points: list[tuple[float, float]] = []
        self.fmt = fmt
        self.value_text = value_text or fmt
        self._xs: list[float] = []
        self._map = None

    def set_points(self, pts):
        self.points = list(pts)
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        t = theme.current()
        self.drawn_text = []
        if len(self.points) < 2:
            p.setPen(QColor(t.muted))
            p.drawText(self.rect().adjusted(8, 0, -8, 0), Qt.AlignCenter | Qt.TextWordWrap, self.empty_text)
            return
        vals = [v for _, v in self.points]
        r, y = self._frame(p, max(vals) * 1.05, 0, self.fmt, top=p.fontMetrics().height() + 10)
        t0, t1 = self.points[0][0], self.points[-1][0]

        def x(ts):
            return r.left() + (ts - t0) / ((t1 - t0) or 1) * r.width()

        self._xs = [x(ts) for ts, _ in self.points]
        self._map = (r, y)
        # Розрив лінії там, де замірів не було (майнер стояв або майнилась інша монета): проміжок > 3 звичайних кроків
        tss = [ts for ts, _ in self.points]
        steps = sorted(b - a for a, b in zip(tss, tss[1:]))
        gap = steps[len(steps) // 2] * 3 if steps else 0
        segs, cur = [], [0]
        for i in range(1, len(tss)):
            if gap and tss[i] - tss[i - 1] > gap:
                segs.append(cur)
                cur = []
            cur.append(i)
        segs.append(cur)
        line = QPainterPath()
        wash = QColor(t.accent)
        wash.setAlphaF(0.10)
        for sg in segs:
            part = QPainterPath(QPointF(self._xs[sg[0]], y(vals[sg[0]])))
            for i in sg[1:]:
                part.lineTo(self._xs[i], y(vals[i]))
            area = QPainterPath(part)
            area.lineTo(self._xs[sg[-1]], r.bottom())
            area.lineTo(self._xs[sg[0]], r.bottom())
            area.closeSubpath()
            p.fillPath(area, wash)
            line.addPath(part)
        pen = QPen(QColor(t.accent), 2)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.drawPath(line)
        fm = p.fontMetrics()
        # Середнє за період — пунктирна жовто-гаряча лінія з підписом зліва (справа підпис поточного значення)
        avg = sum(vals) / len(vals)
        ay = round(y(avg)) + 0.5
        p.setPen(QPen(QColor(t.warning), 2, Qt.DashLine))
        p.drawLine(QPointF(r.left(), ay), QPointF(r.right(), ay))
        atxt = "сер. " + self.value_text(avg)
        f = p.font()
        f.setBold(True)
        p.setFont(f)
        afm = p.fontMetrics()
        aw = afm.horizontalAdvance(atxt)
        # Над лінією, якщо є місце і не налазить на підпис поточного значення (він справа вгорі від точки); інакше — під
        vtw = fm.horizontalAdvance(self.value_text(vals[-1]))
        vrect = QRectF(self._xs[-1] - vtw - 8, y(vals[-1]) - fm.height() - 6, vtw, fm.height())
        aty = ay - afm.height() - 3
        if aty < r.top() or QRectF(r.left() + 4, aty, aw + 8, afm.height()).intersects(vrect):
            aty = ay + 3
        bg = QColor(t.surface)
        bg.setAlphaF(0.85)
        p.fillRect(QRectF(r.left() + 4, aty, aw + 8, afm.height()), bg)
        # На світлому фоні жовтий текст не читається — темніший відтінок
        p.setPen(QColor(t.warning if t.name == "dark" else "#a86400"))
        self._text(p, QRectF(r.left() + 8, aty, aw, afm.height()), Qt.AlignLeft, atxt)
        f.setBold(False)
        p.setFont(f)
        # Підписи часу: початок, середина, кінець
        p.setPen(QColor(t.muted))
        for ts in (t0, (t0 + t1) / 2, t1):
            s = datetime.fromtimestamp(ts).strftime("%H:%M" if t1 - t0 <= 2 * 86400 else "%d.%m")
            xx = x(ts)
            al = Qt.AlignLeft if ts == t0 else Qt.AlignRight if ts == t1 else Qt.AlignHCenter
            self._text(p, QRectF(xx - (0 if ts == t0 else 60 if ts == t1 else 30), r.bottom() + 4, 60, fm.height()), al, s)
        # Кінцева точка з кільцем і підписом
        self._dot(p, QPointF(self._xs[-1], y(vals[-1])))
        p.setPen(QColor(t.ink))
        txt = self.value_text(vals[-1])
        tw = fm.horizontalAdvance(txt)
        self._text(p, QRectF(self._xs[-1] - tw - 8, y(vals[-1]) - fm.height() - 6, tw, fm.height()), Qt.AlignRight, txt)
        if self.hover is not None:
            i = self.hover
            hx = self._xs[i]
            p.setPen(QPen(QColor(t.axis), 1))
            p.drawLine(QPointF(hx, r.top()), QPointF(hx, r.bottom()))
            self._dot(p, QPointF(hx, y(vals[i])))

    def _dot(self, p: QPainter, c: QPointF):
        t = theme.current()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(t.surface))
        p.drawEllipse(c, 6, 6)
        p.setBrush(QColor(t.accent))
        p.drawEllipse(c, 4, 4)

    def mouseMoveEvent(self, e):
        if not self._xs:
            return
        px = e.position().x()
        i = min(range(len(self._xs)), key=lambda k: abs(self._xs[k] - px))
        if self.hover != i:
            self.hover = i
            self.update()
        ts, v = self.points[i]
        QToolTip.showText(e.globalPosition().toPoint(), f"{datetime.fromtimestamp(ts):%d.%m %H:%M}\n{self.value_text(v)}", self)


class ChoiceCard(QFrame):
    """Велика картка вибору (режим роботи): назва + опис, що переноситься; вибрана — з рамкою акценту."""
    clicked = Signal()

    def __init__(self, title: str, desc: str, checked: bool, tip: str = ""):
        super().__init__()
        t = theme.current()
        self.setObjectName("Card")
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(tip)
        border = f"2px solid {t.accent}" if checked else f"1px solid {t.border}"
        self.setStyleSheet(f"#Card {{ border: {border}; background: {t.raised if checked else t.surface}; }}")
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 12, 14, 12)
        v.setSpacing(4)
        v.addWidget(label(("● " if checked else "○ ") + title, "CardTitle", wrap=True))
        v.addWidget(label(desc, "Secondary", wrap=True))
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit()


def hr_scale(values) -> tuple[float, str]:
    """Одиниця хешрейту за найбільшим значенням ряду: (дільник, 'TH/s')."""
    m = max(values) if values else 0
    for scale, unit in ((1e15, "PH/s"), (1e12, "TH/s"), (1e9, "GH/s"), (1e6, "MH/s"), (1e3, "kH/s")):
        if m >= scale:
            return scale, unit
    return 1.0, "H/s"


class Segmented(QWidget):
    """Перемикач із кількох кнопок (простий/експертний, доба/тиждень/місяць)."""
    changed = Signal(str)

    def __init__(self, options: list[tuple[str, str]], value: str):
        super().__init__()
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        self.buttons: dict[str, QPushButton] = {}
        for i, (key, text) in enumerate(options):
            b = QPushButton(text)
            b.setObjectName("SegL" if i == 0 else "SegR" if i == len(options) - 1 else "Seg")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self.set(k, emit=True))
            h.addWidget(b)
            self.buttons[key] = b
        self.value = value
        self.set(value)

    def set(self, key: str, emit: bool = False):
        self.value = key
        for k, b in self.buttons.items():
            b.setChecked(k == key)
        if emit:
            self.changed.emit(key)
