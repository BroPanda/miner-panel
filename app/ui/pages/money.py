"""Гроші: баланс і прогноз · хто скільки намайнив (бухгалтерія) · світло."""
from __future__ import annotations

from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QProgressBar, QTabWidget, QVBoxLayout, QWidget

from ...core.economics import fmt_num, fmt_uah
from .. import theme
from ..widgets import Card, FlowLayout, button, fill_table, help_icon, label, make_table, with_help
from . import Page


def _rows_card(title: str, rows: list[tuple[str, str, str | None]], help_key: str | None = None) -> Card:
    c = Card(title, help_key)
    g = QGridLayout()
    g.setHorizontalSpacing(24)
    g.setVerticalSpacing(8)
    for i, (k, v, hk) in enumerate(rows):
        g.addWidget(with_help(k, hk, "Secondary") if hk else label(k, "Secondary"), i, 0)
        g.addWidget(label(v, "CardTitle", wrap=True), i, 1)
    g.setColumnStretch(1, 1)
    c.body.addLayout(g)
    return c


class MoneyPage(Page):
    def __init__(self):
        super().__init__()
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.t_bal, self.t_led, self.t_en = QWidget(), QWidget(), QWidget()
        for w, name in ((self.t_bal, "Баланс і прогноз"), (self.t_led, "Хто скільки намайнив"), (self.t_en, "Світло")):
            QVBoxLayout(w).setContentsMargins(0, 12, 0, 0)
            w.layout().setSpacing(16)
            self.tabs.addTab(w, name)
        self.lay.addWidget(self.tabs)
        self.lay.addStretch(1)

    def _owner(self) -> None:
        tb = getattr(self, "_workers_table", None)
        r = tb.currentRow() if tb else -1
        name = self._worker_names[r] if tb and 0 <= r < len(self._worker_names) else ""
        self.action.emit(f"ledger:owner:{name}")

    @staticmethod
    def _reset(w: QWidget) -> QVBoxLayout:
        lay = w.layout()
        from ..widgets import clear_layout
        clear_layout(lay)
        return lay

    def render(self, s: dict, expert: bool) -> None:
        t = theme.current()
        # ---- Баланс і прогноз ----
        lay = self._reset(self.t_bal)
        b, p = s["balance"], s["payout"]
        if b.get("available", True):
            pool = _rows_card(b.get("title", "Пул"), [
                ("Баланс", f"{b['total']}  {b['uah']}", None),
                ("Підтверджено + в обробці", f"{b['confirmed']} + {b['pending']}", "pending"),
                ("До виплати", f"{p['pct']:.0f} % з {p['threshold']} · {p['text']}", "payout"),
                ("Можна відключитись?", ("✓ " if p["switch_ok"] else "▲ " if p["switch_ok"] is False else "") + p["switch_text"], "switch"),
                ("Виплачено", b["paid"], None),
                ("Ціна", b["price"], None),
            ] + ([("Дані пулу оновлено", b["updated"], None)] if expert else []))
            bar = QProgressBar()
            bar.setRange(0, 1000)
            bar.setValue(int(p["pct"] * 10))
            bar.setFixedHeight(8)
            pool.body.insertWidget(0, bar)
        else:
            pool = Card(b.get("title", "Пул"))
            pool.body.addWidget(label(b.get("message") or "Пул не надає статистики — баланс дивись на сайті пулу.", "Secondary", wrap=True))
            pool.body.addWidget(label(f"Ціна: {b['price']}", "Secondary"))
        if b.get("page"):
            pool.body.addWidget(button("Відкрити сайт пулу ↗", "Link", lambda: self.action.emit("open:url:" + b["page"])))
        lay.addWidget(pool)
        f = s["forecast"]
        fc = Card("Прогноз на добу (цей ПК)", "tariff")
        if not f:
            fc.body.addWidget(label("Прогноз з'явиться, коли будуть ринкові дані (WhatToMine, CoinGecko).", "Muted"))
        else:
            tb = make_table(["Зона тарифу", "Годин", "Тариф, ₴/кВт·год", "Дохід, ₴", "Світло, ₴", "Прибуток, ₴"], stretch=0)
            rows = [[z["name"] + ("  ← зараз" if z["now"] else ""), z["hours"], fmt_num(z["price"]), fmt_num(z["income"]),
                     fmt_num(z["cost"]), fmt_uah(z["profit"])] for z in f["zones"] if z["hours"]]
            rows.append(["Разом за добу", 24, "", fmt_num(f["income"]), fmt_num(f["cost"]), fmt_uah(f["profit"])])
            fill_table(tb, rows, bold_rows={len(rows) - 1}, numeric={1, 2, 3, 4, 5})
            fc.body.addWidget(tb)
            fc.body.addWidget(label(f"Зараз: {f['now_text']}. Хешрейт і споживання: {f['src']}.", "Muted", wrap=True))
        lay.addWidget(fc)
        lay.addStretch(1)

        # ---- Хто скільки намайнив ----
        lay = self._reset(self.t_led)
        L = s["ledger"]
        oc = Card("Власники: скільки монет належить кожному")
        tb = make_table(["Власник", "Монета", "Намайнено", "Видано", "Залишок до видачі"], stretch=0)
        fill_table(tb, L["owners"], numeric={2, 3, 4})
        oc.body.addWidget(tb)
        row = FlowLayout(spacing=8, stretch=False)     # кнопки переносяться, якщо не вміщаються
        row.addWidget(button("Записати видачу…", "Primary", lambda: self.action.emit("ledger:payout")))
        row.addWidget(button("Призначити власника…", None, self._owner))
        row.addStretch(1)
        oc.body.addLayout(row)
        lay.addWidget(oc)
        wc = Card("Воркери: нарахування пулу, поділене за виконаною роботою", "reconcile")
        cols = ["Воркер", "Власник", "Монета · пул", "Частка", "Монети"] + (["Пул (6 год)", "Джерело"] if expert else [])
        tb = make_table(cols, stretch=0)
        names = L.get("worker_names") or [r[0] for r in L["workers"]]
        t = theme.current()
        colors = {}
        for i, off in enumerate(L.get("off") or []):
            if off and expert:
                colors[(i, 5)] = colors[(i, 6)] = t.warning
        fill_table(tb, [r[:len(cols)] for r in L["workers"]], numeric={3, 4}, tags=names, colors=colors,
                   bold_rows=set(L.get("total_rows") or []))
        tb.cellDoubleClicked.connect(lambda r, _c: self.action.emit(f"ledger:owner:{names[r]}") if names[r] else None)
        self._workers_table, self._worker_names = tb, names
        wc.body.addWidget(tb)
        wc.body.addWidget(label("Подвійний клік по воркеру — призначити власника.", "Muted", wrap=True))
        for line in L["recon"]:
            wc.body.addWidget(label(line, "Secondary", wrap=True))
        for w in L["warn"]:
            wc.body.addWidget(label("▲ " + w, wrap=True))
        lay.addWidget(wc)
        sh = Card("Однакові числа в усіх учасників", "checkpoint")
        sh.body.addWidget(label("Якщо за твоїм гаманцем майнять інші люди: закрий період (наприклад, коли видаєш монети) "
                                "і надішли код іншим — після імпорту в усіх будуть однакові числа, без жодного сервера.", "Secondary", wrap=True))
        row = FlowLayout(spacing=8, stretch=False)     # кнопки переносяться, якщо не вміщаються
        row.addWidget(button("Закрити період і поділитися кодом", None, lambda: self.action.emit("ledger:close")))
        row.addWidget(button("Вставити код від іншого учасника", None, lambda: self.action.emit("ledger:import")))
        if expert:
            row.addWidget(button("Показати поточний код", None, lambda: self.action.emit("ledger:export")))
        row.addStretch(1)
        sh.body.addLayout(row)
        lay.addWidget(sh)
        lay.addStretch(1)

        # ---- Світло ----
        lay = self._reset(self.t_en)
        e = s["energy"]
        lc = Card("Цей ПК", "idle")
        tb = make_table(["Монета", "Час майнінгу", "кВт·год (майнінг / уся карта)", "Світло, ₴", "Чистий прибуток, ₴"], stretch=2)
        fill_table(tb, e["local"], numeric={3, 4})
        lc.body.addWidget(tb)
        lc.body.addWidget(label("Рахується лише відеокарта, поки працює майнер, мінус її простій.", "Muted", wrap=True))
        lay.addWidget(lc)
        if e["farm"]:
            fcard = Card("Ферма HiveOS")
            tb = make_table(["Риг", "Час (поки панель відкрита)", "кВт·год", "Світло, ₴"], stretch=0)
            fill_table(tb, e["farm"], numeric={2, 3})
            fcard.body.addWidget(tb)
            fcard.body.addWidget(label("За споживанням, яке повідомляє HiveOS, і твоїм тарифом день/ніч.", "Muted", wrap=True))
            lay.addWidget(fcard)
        lay.addStretch(1)
