"""Гроші: баланс і прогноз · хто скільки намайнив (бухгалтерія) · світло."""
from __future__ import annotations

from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QProgressBar, QTabWidget, QVBoxLayout, QWidget

from ...core.economics import fmt_num, fmt_uah
from .. import theme
from ..widgets import Card, FlowLayout, button, fill_table, help_icon, label, make_table, with_help
from . import Page
from ...i18n import tr


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
        for w, name in ((self.t_bal, tr('Баланс і прогноз')), (self.t_led, tr('Хто скільки намайнив')), (self.t_en, tr('Світло'))):
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
            pool = _rows_card(b.get("title", tr('Пул')), [
                (tr('Баланс'), f"{b['total']}  {b['uah']}", None),
                (tr('Підтверджено + в обробці'), f"{b['confirmed']} + {b['pending']}", "pending"),
                (tr('До виплати'), tr('{0:.0f} % з {1} · {2}').format(p['pct'], p['threshold'], p['text']), "payout"),
                (tr('Можна відключитись?'), ("✓ " if p["switch_ok"] else "▲ " if p["switch_ok"] is False else "") + p["switch_text"], "switch"),
                (tr('Виплачено'), b["paid"], None),
                (tr('Ціна'), b["price"], None),
            ] + ([(tr('Дані пулу оновлено'), b["updated"], None)] if expert else []))
            bar = QProgressBar()
            bar.setRange(0, 1000)
            bar.setValue(int(p["pct"] * 10))
            bar.setFixedHeight(8)
            pool.body.insertWidget(0, bar)
        else:
            pool = Card(b.get("title", tr('Пул')))
            pool.body.addWidget(label(b.get("message") or tr('Пул не надає статистики — баланс дивись на сайті пулу.'), "Secondary", wrap=True))
            pool.body.addWidget(label(tr('Ціна: {0}').format(b['price']), "Secondary"))
        if b.get("page"):
            pool.body.addWidget(button(tr('Відкрити сайт пулу ↗'), "Link", lambda: self.action.emit("open:url:" + b["page"])))
        lay.addWidget(pool)
        f = s["forecast"]
        fc = Card(tr('Прогноз на добу (цей ПК)'), "tariff")
        if not f:
            fc.body.addWidget(label(tr("Прогноз з'явиться, коли будуть ринкові дані (WhatToMine, CoinGecko)."), "Muted"))
        else:
            tb = make_table([tr('Зона тарифу'), tr('Годин'), tr('Тариф, ₴/кВт·год'), tr('Дохід, ₴'), tr('Світло, ₴'), tr('Прибуток, ₴')], stretch=0)
            rows = [[z["name"] + (tr('  ← зараз') if z["now"] else ""), z["hours"], fmt_num(z["price"]), fmt_num(z["income"]),
                     fmt_num(z["cost"]), fmt_uah(z["profit"])] for z in f["zones"] if z["hours"]]
            rows.append([tr('Разом за добу'), 24, "", fmt_num(f["income"]), fmt_num(f["cost"]), fmt_uah(f["profit"])])
            fill_table(tb, rows, bold_rows={len(rows) - 1}, numeric={1, 2, 3, 4, 5})
            fc.body.addWidget(tb)
            fc.body.addWidget(label(tr('Зараз: {0}. Хешрейт і споживання: {1}.').format(f['now_text'], f['src']), "Muted", wrap=True))
        lay.addWidget(fc)
        lay.addStretch(1)

        # ---- Хто скільки намайнив ----
        lay = self._reset(self.t_led)
        L = s["ledger"]
        oc = Card(tr('Власники: скільки монет належить кожному'))
        tb = make_table([tr('Власник'), tr('Монета'), tr('Намайнено'), tr('Видано'), tr('Залишок до видачі')], stretch=0)
        fill_table(tb, L["owners"], numeric={2, 3, 4})
        oc.body.addWidget(tb)
        row = FlowLayout(spacing=8, stretch=False)     # кнопки переносяться, якщо не вміщаються
        row.addWidget(button(tr('Записати видачу…'), "Primary", lambda: self.action.emit("ledger:payout")))
        row.addWidget(button(tr('Призначити власника…'), None, self._owner))
        row.addStretch(1)
        oc.body.addLayout(row)
        lay.addWidget(oc)
        wc = Card(tr('Воркери: нарахування пулу, поділене за виконаною роботою'), "reconcile")
        cols = [tr('Воркер'), tr('Власник'), tr('Монета · пул'), tr('Частка'), tr('Монети')] + ([tr('Пул (6 год)'), tr('Джерело')] if expert else [])
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
        wc.body.addWidget(label(tr('Подвійний клік по воркеру — призначити власника.'), "Muted", wrap=True))
        for line in L["recon"]:
            wc.body.addWidget(label(line, "Secondary", wrap=True))
        for w in L["warn"]:
            wc.body.addWidget(label("▲ " + w, wrap=True))
        lay.addWidget(wc)
        sh = Card(tr('Однакові числа в усіх учасників'), "checkpoint")
        sh.body.addWidget(label(tr('Якщо за твоїм гаманцем майнять інші люди: закрий період (наприклад, коли видаєш монети) і надішли код іншим — після імпорту в усіх будуть однакові числа, без жодного сервера.'), "Secondary", wrap=True))
        row = FlowLayout(spacing=8, stretch=False)     # кнопки переносяться, якщо не вміщаються
        row.addWidget(button(tr('Закрити період і поділитися кодом'), None, lambda: self.action.emit("ledger:close")))
        row.addWidget(button(tr('Вставити код від іншого учасника'), None, lambda: self.action.emit("ledger:import")))
        if expert:
            row.addWidget(button(tr('Показати поточний код'), None, lambda: self.action.emit("ledger:export")))
        row.addStretch(1)
        sh.body.addLayout(row)
        lay.addWidget(sh)
        lay.addStretch(1)

        # ---- Світло ----
        lay = self._reset(self.t_en)
        e = s["energy"]
        lc = Card(tr('Цей ПК'), "idle")
        tb = make_table([tr('Монета'), tr('Час майнінгу'), tr('кВт·год (майнінг / уся карта)'), tr('Світло, ₴'), tr('Чистий прибуток, ₴')], stretch=2)
        fill_table(tb, e["local"], numeric={3, 4})
        lc.body.addWidget(tb)
        lc.body.addWidget(label(tr('Рахується лише відеокарта, поки працює майнер, мінус її простій.'), "Muted", wrap=True))
        lay.addWidget(lc)
        if e["farm"]:
            fcard = Card(tr('Ферма HiveOS'))
            tb = make_table([tr('Риг'), tr('Час (поки панель відкрита)'), tr('кВт·год'), tr('Світло, ₴')], stretch=0)
            fill_table(tb, e["farm"], numeric={2, 3})
            fcard.body.addWidget(tb)
            fcard.body.addWidget(label(tr('За споживанням, яке повідомляє HiveOS, і твоїм тарифом день/ніч.'), "Muted", wrap=True))
            lay.addWidget(fcard)
        lay.addStretch(1)
