"""Монети: рейтинг за еталоном і вибір «що майнити»."""
from __future__ import annotations

import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QGridLayout, QHBoxLayout, QLineEdit

from ...core.economics import fmt_uah
from .. import theme
from ..widgets import Card, CheckLine, button, fill_table, label, make_table, with_help
from . import Page
from ...i18n import tr


class CoinsPage(Page):
    def __init__(self):
        super().__init__()
        self.rank = Card(tr('Рейтинг монет: прибуток за добу на твоїй карті з твоїм тарифом'), "benchmark")
        self.table = make_table([tr('Монета · пул'), tr('Прибуток за добу'), tr('Твій результат')], stretch=0)
        self.table.cellDoubleClicked.connect(self._pick_row)
        self.rank.body.addWidget(self.table)
        self.rank.body.addWidget(label(tr('Порівняння в однакових умовах — за еталоном такої самої карти (hashrate.no) або оцінкою. «Пул» і «Майнер» — комісії: пулу (вже врахована в прибутку) і майнера (частка часу, що він майнить розробнику; «?» — невідома). Сірим — монети без гаманця. Подвійний клік — вибрати монету нижче.'), "Muted", wrap=True))
        self.lay.addWidget(self.rank)

        self.pick = Card(tr('Що майнити'))
        g = QGridLayout()
        g.setHorizontalSpacing(12)
        g.setVerticalSpacing(10)
        self.coin, self.pool, self.miner, self.wallet, self.price = (QComboBox() for _ in range(5))
        self.worker = QLineEdit()
        self.worker.setMaxLength(32)
        self._coin_default: dict[str, str] = {}
        # Інша монета — її пул за замовчуванням; пул — це і є запис coins.json (монета+пул)
        self.coin.activated.connect(lambda i: self.action.emit(f"coins:preview:{self._coin_default.get(self.coin.itemData(i), '')}"))
        self.pool.activated.connect(lambda i: self.action.emit(f"coins:preview:{self.pool.itemData(i)}"))
        rows = [(tr('Монета'), self.coin, None), (tr('Пул'), self.pool, "pool"), (tr('Майнер'), self.miner, None), (tr('Гаманець'), self.wallet, None),
                (tr("Ім'я воркера"), self.worker, "worker"), (tr('Ціна монети'), self.price, None)]
        for i, (k, w, hk) in enumerate(rows):
            g.addWidget(with_help(k, hk, "Secondary") if hk else label(k, "Secondary"), i, 0)
            g.addWidget(w, i, 1)
        wrow = QHBoxLayout()
        wrow.addWidget(button(tr('+ Додати'), None, lambda: self.action.emit(f"wallet:add:{self._coin_id()}"), tr('Додати адресу гаманця')))
        wrow.addWidget(button("✎", None, lambda: self.action.emit(f"wallet:edit:{self._coin_id()}:{self.wallet.currentData() or ''}"), tr('Змінити назву чи адресу')))
        wrow.addWidget(button("−", None, lambda: self.action.emit(f"wallet:remove:{self._coin_id()}:{self.wallet.currentData() or ''}"), tr('Видалити адресу зі списку')))
        g.addLayout(wrow, 3, 2)
        g.setColumnStretch(1, 1)
        self.pick.body.addLayout(g)
        self.note = label("", "Muted", wrap=True)
        self.pick.body.addWidget(self.note)
        brow = QHBoxLayout()
        brow.addStretch(1)
        self.apply_btn = button(tr('Майнити це'), "Primary", self._apply)
        brow.addWidget(self.apply_btn)
        self.pick.body.addLayout(brow)
        self.lay.addWidget(self.pick)

        self.servers = Card(tr('Сервери пулу'), "backup_servers")
        self.srv_table = make_table([tr('Сервер'), tr('Затримка зараз'), tr('Медіана за 30 хв'), tr('Стан')], stretch=0)
        self.servers.body.addWidget(self.srv_table)
        self.srv_auto = CheckLine(tr('Автоматично переходити на стабільно швидший сервер'))
        self.srv_auto.toggled.connect(lambda on: self.action.emit(f"set:ServerAuto:{int(on)}"))
        self.servers.body.addWidget(self.srv_auto)
        self.srv_note = label(tr('Затримка міряється раз на 5 хв. Сервер ліг — майнер одразу переходить на найшвидший робочий. На інший робочий — лише якщо він швидший щонайменше 30 хв поспіль (на 15 % і 8 мс), не частіше ніж раз на 2 год: кожне перемикання — кілька секунд без майнінгу.'), "Muted", wrap=True)
        self.servers.body.addWidget(self.srv_note)
        self.lay.addWidget(self.servers)
        self.lay.addStretch(1)
        self._ids: list[str] = []

    def _coin_id(self) -> str:
        return str(self.pool.currentData() or "")

    def _pick_row(self, r: int, _c: int) -> None:
        if 0 <= r < len(self._ids):
            self.action.emit(f"coins:preview:{self._ids[r]}")

    def _apply(self) -> None:
        d = {"coin": self._coin_id(), "miner": self.miner.currentData(), "wallet": self.wallet.currentData(),
             "worker": self.worker.text().strip(), "price": self.price.currentData()}
        self.action.emit("coin:apply:" + json.dumps(d, ensure_ascii=False))

    @staticmethod
    def _fill(cb: QComboBox, items: list[tuple[str, str]], value) -> None:
        cb.blockSignals(True)
        cb.clear()
        for key, text in items:
            cb.addItem(text, key)
        i = cb.findData(value)
        cb.setCurrentIndex(i if i >= 0 else (0 if items else -1))
        cb.blockSignals(False)

    def render(self, s: dict, expert: bool) -> None:
        t = theme.current()
        c = s["coins"]
        cols = [tr('Монета · пул'), tr('Прибуток за добу'), tr('Твій результат'), tr('Пул'), tr('Майнер')] + \
            ([tr('Еталон: хешрейт · Вт'), tr('Джерело')] if expert else [])
        self.table.setColumnCount(len(cols))
        self.table.setHorizontalHeaderLabels(cols)
        self.table.horizontalHeaderItem(3).setToolTip(tr('Комісія пулу'))
        self.table.horizontalHeaderItem(4).setToolTip(tr('Комісія майнера (dev fee): частка часу, що він майнить розробнику'))
        rows, colors, bold = [], {}, set()
        self._ids = [r["id"] for r in c["ranking"]]
        for i, r in enumerate(c["ranking"]):
            rows.append([("★ " if i == 0 and r["profit"] is not None else "") + r["name"],
                         fmt_uah(r["profit"]) if r["profit"] is not None else tr('н/д'), r["mine"] or "",
                         r["pool_fee"], r["miner_fee"]] +
                        ([r["bench"], r["src"]] if expert else []))
            if not r["has_wallet"]:
                for k in range(len(cols)):
                    colors[(i, k)] = t.muted
            else:
                colors[(i, 3)] = colors[(i, 4)] = t.serious
            if r["current"]:
                bold.add(i)
        fill_table(self.table, rows, bold_rows=bold, colors=colors, numeric={1, 2, 3, 4})
        for i, r in enumerate(c["ranking"]):
            self.table.item(i, 4).setToolTip(tr('Комісія {0}').format(r['miner_name']) + (tr(' невідома') if r["miner_fee"] == "?" else ""))
        f = c["form"]
        self._coin_default = f["coin_default"]
        self._fill(self.coin, f["coins"], f["ticker"])
        self._fill(self.pool, f["pools"], f["coin"])
        self._fill(self.miner, f["miners"], f["miner"])
        self._fill(self.wallet, f["wallets"], f["wallet"])
        tk = f.get("ticker", "")
        self.wallet.setPlaceholderText(tr('немає гаманця {0} — натисни «+ Додати»').format(tk))
        self.apply_btn.setEnabled(bool(f["wallets"]))
        self.apply_btn.setToolTip("" if f["wallets"] else tr('Спершу додай гаманець {0}').format(tk))
        self._fill(self.price, f["prices"], f["price"])
        if not self.worker.hasFocus():
            self.worker.setText(f["worker"])
        self.note.setText(f["note"])
        self.apply_btn.setText(tr('Зберегти') if f["is_current"] else tr('Майнити це'))
        rows, colors = [], {}
        for i, x in enumerate(f["servers"]):
            rows.append([("▶ " if x["current"] else "   ") + x["url"], x["now"], x["median"], x["state"]])
            colors[(i, 3)] = {"good": t.good_text, "warn": t.warning, "bad": t.critical}.get(x["level"], t.muted)
        cur = {i for i, x in enumerate(f["servers"]) if x["current"]}
        fill_table(self.srv_table, rows, colors=colors, numeric={1, 2}, bold_rows=cur, bg_rows=cur)
        self.srv_auto.blockSignals(True)
        self.srv_auto.setChecked(bool(f.get("server_auto", True)))
        self.srv_auto.blockSignals(False)
        self.servers.title.setText(tr('Сервери пулу') + (tr(' · перевірено {0}').format(f['ping_time']) if f.get("ping_time") else ""))
