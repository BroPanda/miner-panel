"""Огляд — перший екран. Згори вниз за важливістю: що потребує дії → головні цифри зараз → пристрої з кнопками →
гроші за періоди і прогноз → інші монети → тиждень і порада. Кожне число — в одному місці."""
from __future__ import annotations

from PySide6.QtWidgets import QGridLayout, QVBoxLayout, QWidget

from ...core.economics import fmt_uah
from .. import theme
from ..widgets import Card, ColumnChart, FlowLayout, NoticeCard, StatTile, button, clear_layout, label
from . import Page
from .common import DeviceCard
from ...i18n import tr


class OverviewPage(Page):
    def __init__(self):
        super().__init__()
        self.notices = QWidget()
        self.notices_lay = QGridLayout(self.notices)
        self.notices_lay.setContentsMargins(0, 0, 0, 0)
        self.lay.addWidget(self.notices)

        # Головне зараз: прибуток, коли виплата (з балансом пулу), ціна. Плитки переносяться, коли не вміщаються
        tiles = FlowLayout(min_w=theme.pt(230), uniform=True)
        self.t_profit = StatTile(tr('Прибуток за добу'), hero=True)
        self.t_payout = StatTile(tr('До виплати з пулу'), "payout", meter=True)
        self.t_price = StatTile(tr('Ціна монети'))
        for t in (self.t_profit, self.t_payout, self.t_price):
            tiles.addWidget(t)
        self.lay.addLayout(tiles)

        # Пристрої — одразу під головним: тут стан і кнопки «Старт / Стоп» (без заголовка — картки говорять самі)
        self.devs = QWidget()
        self.devs_lay = FlowLayout(self.devs, min_w=theme.pt(560), uniform=True)
        self.lay.addWidget(self.devs)

        # Гроші за періоди і прогноз — окремі картки поруч; у кожній цей ПК і вся адреса на пулі
        self.c_periods, self.periods, self.pool_box, self.pool_title, self.pool_periods = self._two_box_card(tr('Гроші за періоди'))
        self.c_fc, self.fc_grid, self.fc_pool_box, self.fc_pool_title, self.fc_pool = self._two_box_card(tr('Прогноз'))
        self.pc_mined = label("", "Secondary", wrap=True)          # скільки монет добув цей ПК (коли монета одна)
        pf = FlowLayout(natural=True)
        pf.addWidget(self.c_periods)
        pf.addWidget(self.c_fc)
        self.lay.addLayout(pf)
        self.c_periods.body.addWidget(self.pc_mined)

        # Усі монети — лише коли їх кілька: що добув цей ПК і що лишилось на пулах після перемикання
        self.c_coins = Card(tr('Усі монети'))
        self.coins_g = QGridLayout()
        self.coins_g.setHorizontalSpacing(28)
        self.coins_g.setVerticalSpacing(10)
        self.c_coins.body.addLayout(self.coins_g)
        self.lay.addWidget(self.c_coins)

        bottom = FlowLayout(min_w=theme.pt(330))
        self.c_days = Card(tr('Прибуток за 7 днів (дохід мінус світло)'))
        self.chart = ColumnChart()
        self.chart.setMinimumHeight(190)
        self.c_days.body.addWidget(self.chart)
        bottom.addWidget(self.c_days)
        self.c_best = Card(tr('Що майнити'), "benchmark")
        self.best_text = label("", wrap=True)
        self.best_sub = label("", "Muted", wrap=True)
        self.best_btn = button(tr('Відкрити рейтинг монет'), None, lambda: self.action.emit("open:coins"))
        self.c_best.body.addWidget(self.best_text)
        self.c_best.body.addWidget(self.best_sub)
        self.c_best.body.addStretch(1)
        self.c_best.body.addWidget(self.best_btn)
        bottom.addWidget(self.c_best)
        self.lay.addLayout(bottom)
        self.lay.addStretch(1)

    @staticmethod
    def _two_box_card(title: str):
        """Картка з двома блоками поруч (у вузькому вікні — один під одним): «Цей ПК» і «Уся адреса на пулі»."""
        card = Card(title)
        two = FlowLayout(spacing=28, natural=True)
        out = []
        for sub in (tr('Цей ПК'), ""):
            box = QWidget()
            v = QVBoxLayout(box)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(8)
            t = label(sub, "Secondary", wrap=True)
            v.addWidget(t)
            # Подробиці адреси (воркери, хешрейт) — окремим рядком, щоб заголовок не розпирав картку
            t.sub = label(tr('за хешрейтом, ціною і тарифом') if sub else "", "Muted", wrap=True)
            t.sub.setVisible(bool(sub))
            v.addWidget(t.sub)
            g = QGridLayout()
            g.setHorizontalSpacing(20)
            g.setVerticalSpacing(10)
            v.addLayout(g)
            v.addStretch(1)
            two.addWidget(box)
            out.append((box, t, g))
        card.body.addLayout(two)
        return card, out[0][2], out[1][0], out[1][1], out[1][2]

    @staticmethod
    def _fill_pc(g, rows) -> None:
        clear_layout(g)
        for col, h in enumerate(("", tr('Дохід'), tr('Світло'), tr('Чистими'))):
            g.addWidget(label(h, "KeyHead"), 0, col)
        for r, (name, inc, cst, net) in enumerate(rows, 1):
            g.addWidget(label(name, "CardTitle"), r, 0)
            g.addWidget(label(inc, "KeyAccent"), r, 1)
            g.addWidget(label(cst, "KeyCost"), r, 2)
            g.addWidget(label(net, "KeyBad" if net.startswith(("−", "-")) else "KeyGood"), r, 3)
        g.setColumnStretch(4, 1)

    @staticmethod
    def _fill_pool(box, title_lbl, g, title, rows, sub: str = "") -> None:
        clear_layout(g)
        title_lbl.setText(title)
        title_lbl.sub.setText(sub)
        title_lbl.sub.setVisible(bool(sub))
        box.setVisible(bool(rows))
        for col, h in enumerate(("", tr('Монети'), "≈ ₴")):
            g.addWidget(label(h, "KeyHead"), 0, col)
        for r, (name, coins, uah) in enumerate(rows, 1):
            g.addWidget(label(name, "CardTitle"), r, 0)
            g.addWidget(label(coins, "KeyGood"), r, 1)
            g.addWidget(label(uah, "KeyAccent"), r, 2)
        g.setColumnStretch(3, 1)

    def render(self, s: dict, expert: bool) -> None:
        t = theme.current()
        clear_layout(self.notices_lay)
        for i, n in enumerate(s["notices"]):
            c = NoticeCard(n)
            c.acted.connect(self.action.emit)
            self.notices_lay.addWidget(c, i, 0)
        self.notices.setVisible(bool(s["notices"]))

        sm = s.get("summary") or {}
        parts = [v for v in (s["profit_day"], s.get("farm_profit_day")) if v is not None]
        if parts:
            # Розбивка по пристроях — у картках пристроїв, дохід і світло — у «Прогнозі»; тут — монети на добу і ціна години
            total = sum(parts)
            sub = s["coins_day"] if s["profit_day"] is not None else tr('цей ПК не майнить')
            if sm.get("now_text"):
                sub += tr('\nзараз {0}').format(sm['now_text'])
            self.t_profit.set(fmt_uah(total), sub, value_color=t.good_text if total >= 0 else t.critical)
        else:
            self.t_profit.set("—", tr("Майнер зупинено. Натисни «Старт» угорі — прогноз з'явиться за хвилину."), value_color=t.muted)
        p, b = s["payout"], s["balance"]
        if p["switch_ok"] is None:
            sw = ""
        else:
            sw = tr('✓ можна відключитись') if p["switch_ok"] else "▲ " + p["switch_text"].replace(tr('ні — '), tr('відключатись поки не варто: '))
        # Баланс пулу — тут же, а не окремою плиткою: «0,7377 з 1 PRL ≈ 74,84 ₴»
        have = tr('{0} з {1} {2}').format(b['total'], p['threshold'], b['uah']).strip() if b.get("available", True) and p["threshold"] != "—" else b.get("message", "")
        self.t_payout.set(f"{p['pct']:.0f} %" if p["threshold"] != "—" else "—",
                          "\n".join(x for x in (have, p["text"] if p["text"] != "—" else "", sw) if x), p["pct"])
        self.t_price.set(sm.get("price", "—"), sm.get("price_sub", ""), value_color=t.accent)
        rows, prow = sm.get("periods") or [], sm.get("pool_periods") or []
        self._fill_pc(self.periods, [r[:4] for r in rows if not r[4]])
        self._fill_pool(self.pool_box, self.pool_title, self.pool_periods, sm.get("pool_title", ""), [r[:3] for r in prow if not r[3]],
                        sm.get("pool_sub", ""))
        self.c_periods.setVisible(bool(rows))
        fpc, fpool = [r[:4] for r in rows if r[4]], [r[:3] for r in prow if r[3]]
        self._fill_pc(self.fc_grid, fpc)
        self._fill_pool(self.fc_pool_box, self.fc_pool_title, self.fc_pool, sm.get("pool_title", ""), fpool, sm.get("pool_sub", ""))
        self.c_fc.setVisible(bool(fpc or fpool))

        clear_layout(self.coins_g)
        crow = sm.get("coins") or []
        self.c_coins.setVisible(len(crow) > 1)
        # Одна монета — окрема картка зайва; лише скільки добув цей ПК (з усієї адреси на пулі)
        self.pc_mined.setText(tr('Добув цей ПК: {0}').format(crow[0]['mined']) if len(crow) == 1 and crow[0]["mined"] != "—" else "")
        self.pc_mined.setVisible(len(crow) == 1 and crow[0]["mined"] != "—")
        for col, h in enumerate((tr('Монета'), tr('Добув цей ПК'), tr('На пулі'), "≈ ₴")):
            self.coins_g.addWidget(label(h, "KeyHead"), 0, col)
        for r, x in enumerate(crow, 1):
            self.coins_g.addWidget(label(x["ticker"], "CardTitle"), r, 0)
            self.coins_g.addWidget(label(x["mined"], "KeyGood" if x["mined"] != "—" else "Secondary"), r, 1)
            self.coins_g.addWidget(label(x["pool"], "KeyAccent" if x["pool"] != "—" else "Secondary"), r, 2)
            self.coins_g.addWidget(label(x["uah"], "KeyAccent" if x["uah"] != "—" else "Secondary"), r, 3)
            note = label(("▲ " if x["level"] == "warn" else "") + x["note"], "Secondary", wrap=True)
            if x["level"]:
                note.setStyleSheet(f"color:{t.warning if x['level'] == 'warn' else t.good_text}; font-weight:600")
            self.coins_g.addWidget(note, r, 4)
        self.coins_g.setColumnStretch(4, 1)

        clear_layout(self.devs_lay)
        for d in s["devices"]:
            c = DeviceCard(d)
            c.acted.connect(self.action.emit)
            self.devs_lay.addWidget(c)

        self.chart.set_points(s["days"])
        bst = s["best"]
        if bst["current"]:
            self.best_text.setText(tr('<b>✓ Ти вже майниш найвигіднішу монету:</b> {0}').format(bst['coin']))
            self.best_sub.setText(tr('За еталоном {0} за добу, твій результат {1}. Різниця — через твій розгін і світло.').format(fmt_uah(bst['profit']), fmt_uah(bst['mine'])))
            self.best_btn.setText(tr('Відкрити рейтинг монет'))
        else:
            self.best_text.setText(tr('<b>Вигідніше зараз:</b> {0} — {1} за добу').format(bst['coin'], fmt_uah(bst['profit'])))
            self.best_sub.setText(tr('Перед перемиканням перевір «До виплати» — щоб не лишити монет на пулі.'))
            self.best_btn.setText(tr('Майнити її'))
