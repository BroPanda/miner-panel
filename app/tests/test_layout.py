"""Вигляд: на всіх сторінках, ширинах вікна і розмірах шрифту текст не обрізаний, підписи графіків у межах,
немає горизонтальної прокрутки. Дані — зразкові плюс «важкі» (значення на межі поділки, збиток, порожньо, довгі назви)."""
from __future__ import annotations

import copy
import os
import re
from pathlib import Path

import pytest
from PySide6.QtCore import QRectF
from PySide6.QtWidgets import QAbstractButton, QApplication, QComboBox, QLabel, QLineEdit, QTableWidget, QWidget

WIDTHS = (1000, 1240, 1905)
FONTS = ("normal", "large", "huge")
CYR = re.compile("[Ѐ-ӿ]")


def _variants() -> dict[str, dict]:
    from app.i18n import tr
    from app.ui import sample
    base = sample.snapshot(True)
    out = {"sample": base}

    v = copy.deepcopy(base)       # останній стовпчик майже на верхній поділці (39 при шкалі до 40), решта — нулі
    v["days"] = [(f"{d}.10", 0.0, "") for d in range(16, 21)] + [("21.10", 0.6, ""), ("22.10", 39.0, "")]
    out["edge"] = v

    v = copy.deepcopy(base)       # збиток і рівно кругле значення
    v["days"] = [(f"{d}.10", -12.5 + d * 0.1, "") for d in range(16, 22)] + [("22.10", -40.0, "")]
    v["profit_day"], v["devices"][0]["profit_day"] = -5.25, -5.25
    v["summary"]["periods"] = [[n, "0,00 ₴", "12,34 ₴", "-12,34 ₴", False] for n in (tr("Сьогодні"), tr("7 днів"), tr("Весь час"))]
    out["loss"] = v

    v = copy.deepcopy(base)       # великий прибуток поруч зі збитком і дрібницями
    v["days"] = [("16.10", 39.0, ""), ("17.10", -8.2, ""), ("18.10", 0.0, ""), ("19.10", 1234.5, ""),
                 ("20.10", -0.4, ""), ("21.10", 12.0, ""), ("22.10", 0.05, "")]
    out["mixed"] = v

    v = copy.deepcopy(base)       # порожньо: перший запуск
    v["days"] = []
    for d in v["devices"]:
        d["series"] = {"hr": [], "temp": [], "watts": []}
    out["empty"] = v

    v = copy.deepcopy(base)       # довгі назви
    loc = v["devices"][0]
    loc["coin"] = "Quantus Network Token (QUANTUS) · Extra Long Coin Name Example"
    loc["server"] = "stratum+tcp://eu-central-frankfurt-01.very-long-pool-domain.example.com:12345"
    v["summary"]["mined"] = "123 456,7890 QUANTUS"
    v["coins"]["ranking"][0].update(pool_fee="0,85 %", miner_fee="0,85 %")
    out["long"] = v
    return out


def _shots(app, win, snap):
    """Показати кожну сторінку (вкладки «Грошей», кожен пристрій) і віддати назву кадру."""
    from app.main import _settle
    win.render(snap)
    for key in win.pages:
        win.show_section(key)
        if key == "money":
            for i in range(win.pages["money"].tabs.count()):
                win.pages["money"].tabs.setCurrentIndex(i)
                _settle(app)
                yield f"money#{i}"
            continue
        if key == "devices":
            for dev in [d["id"] for d in snap["devices"]]:
                win.pages["devices"].select(dev)
                win.show_section("devices")
                _settle(app)
                yield f"devices:{dev}"
            continue
        _settle(app)
        yield key


def _visible(w: QWidget, top: QWidget) -> bool:
    return w.isVisibleTo(top) and w.width() > 0


def _overlap(a: QRectF, b: QRectF) -> bool:
    """Перетин більший за 1 px з кожного боку (дотик краями — не накладання)."""
    i = a.intersected(b)
    return i.width() > 1 and i.height() > 1


def _table_problems(tb: QTableWidget, where: str) -> list[str]:
    """Текст клітинки чи заголовка ширший за колонку — Qt обрізає його трьома крапками."""
    from app.ui.widgets import cell_need
    out = []
    hh = tb.horizontalHeader()
    for c in range(tb.columnCount()):
        if tb.isColumnHidden(c):
            continue
        cw = tb.columnWidth(c)
        h = tb.horizontalHeaderItem(c)
        if h and h.text():
            need = hh.sectionSizeFromContents(c).width()
            if need > cw + 1:
                out.append(f"{where}: обрізаний заголовок таблиці «{h.text()}» — треба {need} px, є {cw}")
        for r in range(tb.rowCount()):
            it = tb.item(r, c)
            if not it or not it.text():
                continue
            # Переноситься: обрізано, якщо слово ширше за колонку або рядки не влазять у висоту; ні — якщо ширше за колонку
            need = cell_need(tb, it, cw if tb.wordWrap() else None)
            if need.width() > cw + 1 or tb.wordWrap() and need.height() > tb.rowHeight(r) + 1:
                out.append(f"{where}: обрізана клітинка таблиці «{it.text()[:60]}» — треба {need.width()}×{need.height()} px, "
                           f"є {cw}×{tb.rowHeight(r)}")
    return out


def _problems(win, page, where: str) -> list[str]:
    from app.ui.widgets import _ChartBase
    out = []
    if page.horizontalScrollBar().maximum() > 0:
        out.append(f"{where}: горизонтальна прокрутка ({page.horizontalScrollBar().maximum()} px)")
    for ch in page.findChildren(_ChartBase) + win.findChildren(_ChartBase):
        if not _visible(ch, win):
            continue
        ch.grab()                                 # примусово намалювати, щоб оновились drawn_text
        box = ch.rect().adjusted(-1, -1, 1, 1)
        name = type(ch).__name__
        for r in ch.drawn_text:
            if not box.contains(r.toAlignedRect()):
                out.append(f"{where}: підпис графіка поза межами {name} {ch.width()}×{ch.height()}: "
                           f"({r.x():.0f},{r.y():.0f} {r.width():.0f}×{r.height():.0f})")
        texts = ch.drawn_text
        for i, a in enumerate(texts):
            for b in texts[i + 1:]:
                if _overlap(a, b):
                    out.append(f"{where}: підписи {name} налазять один на одного ({a.x():.0f},{a.y():.0f}) і ({b.x():.0f},{b.y():.0f})")
            for m in ch.drawn_marks:
                if _overlap(a, m):
                    out.append(f"{where}: підпис {name} налазить на стовпчик ({a.x():.0f},{a.y():.0f})")
    for tb in win.findChildren(QTableWidget):
        if _visible(tb, win):
            out += _table_problems(tb, where)
    for w in win.findChildren(QLabel) + win.findChildren(QAbstractButton):
        if not _visible(w, win) or isinstance(w.parent(), QWidget) and not w.parentWidget().isVisibleTo(win):
            continue
        text = w.text().replace("\n", " ")
        if not text.strip() or (isinstance(w, QLabel) and (w.wordWrap() or w.pixmap() and not w.pixmap().isNull())):
            continue
        need = w.sizeHint().width()
        if need > w.width() + 1:
            out.append(f"{where}: обрізаний текст {type(w).__name__} «{text[:60]}» — треба {need} px, є {w.width()}")
        par = w.parentWidget()
        if par is not None and w.geometry().right() > par.width() + 1:
            out.append(f"{where}: {type(w).__name__} «{text[:60]}» виходить за край батьківського віджета")
    return out


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    yield a
    from app.ui import theme
    theme.apply(a, "dark", "large")


def _untranslated(win, where: str) -> list[str]:
    """Англійською на екрані не має лишитися кирилиці — інакше текст не потрапив у tr() або в словник i18n_en."""
    texts = []
    for w in win.findChildren(QLabel) + win.findChildren(QAbstractButton):
        if w.isVisibleTo(win):
            texts.append(w.text())
    for w in win.findChildren(QLineEdit):
        if w.isVisibleTo(win):
            texts += [w.text(), w.placeholderText()]
    for w in win.findChildren(QComboBox):
        if w.isVisibleTo(win):
            texts += [w.itemText(i) for i in range(w.count())]
    for tb in win.findChildren(QTableWidget):
        if tb.isVisibleTo(win):
            texts += [h.text() for c in range(tb.columnCount()) if (h := tb.horizontalHeaderItem(c))]
            texts += [it.text() for r in range(tb.rowCount()) for c in range(tb.columnCount()) if (it := tb.item(r, c))]
    from app.i18n import LANGS
    keep = set(LANGS.values()) | {"Мова / Language"}       # вибір мови — свідомо двома мовами
    return [f"{where}: не перекладено «{s[:70]}»" for s in texts if s and CYR.search(s) and s not in keep]


@pytest.mark.parametrize("lang,font", [("uk", f) for f in FONTS] + [("en", f) for f in FONTS])
def test_layout(app, lang, font):
    from app import i18n
    from app.ui import theme
    from app.ui.main_window import MainWindow
    snap_dir = os.environ.get("PANEL_TEST_SNAP")
    problems = []
    i18n.set_lang(lang)
    themes = ("dark", "light") if font == "large" and lang == "uk" else ("dark",)   # тема не змінює розмірів — світлу досить раз
    for tname in themes:
        theme.apply(app, tname, font)
        for vname, snap in _variants().items():
            for width in WIDTHS:
                win = MainWindow()
                win.resize(width, 860)
                win.show()
                problems += [f"{tname}/{font}: немає значка в меню «{b.text().strip()}»"
                             for b in win.nav_buttons.values() if b.icon().isNull()]
                if win.width() > width:
                    problems.append(f"{tname}/{vname}/{width}: вікно не стискається до {width} px (мінімум {win.width()})")
                for shot in _shots(app, win, snap):
                    where = f"{lang}/{tname}/{font}/{vname}/{width}/{shot}"
                    found = _problems(win, win.stack.currentWidget(), where)
                    if lang == "en":
                        found += _untranslated(win, where)
                    if found and snap_dir:
                        Path(snap_dir).mkdir(parents=True, exist_ok=True)
                        win.grab().save(str(Path(snap_dir) / (where.replace("/", "_").replace(":", "-") + ".png")))
                    problems += found
                win.close()
                win.deleteLater()
    i18n.set_lang("uk")
    uniq = list(dict.fromkeys(problems))
    assert not uniq, f"{len(uniq)} проблем вигляду:\n" + "\n".join(uniq[:40])
