"""Налаштування: тариф, запобіжники, інтерфейс, підключення (HiveOS, hashrate.no), майнери.
Кожна зміна одразу надсилається контролеру (set:<ключ>:<значення>) і зберігається."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDoubleSpinBox, QGridLayout, QHBoxLayout, QLineEdit, QSpinBox

from .. import theme
from ..widgets import Card, CheckLine, FlowLayout, Segmented, button, clear_layout, fill_table, label, make_table, with_help
from . import Page
from ...i18n import LANGS, tr


class SettingsPage(Page):
    def _spin(self, key: str, lo, hi, val, step=1, dec=None):
        s = QDoubleSpinBox() if dec is not None else QSpinBox()
        if dec is not None:
            s.setDecimals(dec)
        s.setRange(lo, hi)
        s.setSingleStep(step)
        s.setValue(val)
        s.setFixedWidth(120)
        s.setMinimumHeight(34)
        s.editingFinished.connect(lambda: self.action.emit(f"set:{key}:{s.value()}"))
        return s

    @staticmethod
    def _grid() -> QGridLayout:
        """Підпис — поле фіксованої ширини — порожня колонка, що забирає решту місця."""
        g = QGridLayout()
        g.setHorizontalSpacing(14)
        g.setVerticalSpacing(10)
        g.setColumnStretch(2, 1)
        return g

    def _check(self, key: str, text: str, val: bool) -> CheckLine:
        c = CheckLine(text, bool(val))
        c.toggled.connect(lambda on: self.action.emit(f"set:{key}:{int(on)}"))
        return c

    def render(self, s: dict, expert: bool) -> None:
        if self.inner.focusWidget() and self.inner.isAncestorOf(self.inner.focusWidget()) and isinstance(self.inner.focusWidget(), QLineEdit):
            return      # не перебудовувати, поки вписують токен
        clear_layout(self.lay)
        st = s["settings"]
        # Картки по дві в ряд, а коли не вміщаються (вузьке вікно, великий шрифт) — одна під одною
        row = FlowLayout(min_w=theme.pt(380))
        c = Card(tr('Тариф на світло'), "tariff")
        g = self._grid()
        g.addWidget(self._check("TwoZone", tr('Двозонний лічильник (вночі дешевше)'), st["TwoZone"]), 0, 0, 1, 3)
        g.addWidget(label(tr('День, ₴/кВт·год'), "Secondary"), 1, 0)
        g.addWidget(self._spin("TariffDay", 0, 50, st["TariffDay"], 0.01, 2), 1, 1)
        g.addWidget(label(tr('Ніч, ₴/кВт·год'), "Secondary"), 2, 0)
        g.addWidget(self._spin("TariffNight", 0, 50, st["TariffNight"], 0.01, 2), 2, 1)
        g.addWidget(label(tr('Ніч з / до (година)'), "Secondary"), 3, 0)
        hh = QHBoxLayout()
        hh.setSpacing(8)
        hh.addWidget(self._spin("NightFrom", 0, 23, st["NightFrom"]))
        hh.addWidget(self._spin("NightTo", 0, 23, st["NightTo"]))
        hh.addStretch(1)
        g.addLayout(hh, 3, 1, 1, 2)
        c.body.addLayout(g)
        row.addWidget(c)
        c = Card(tr('Запобіжники відеокарти'))
        g = self._grid()
        g.addWidget(label(tr('Макс. температура, °C'), "Secondary"), 0, 0)
        g.addWidget(self._spin("MaxTemp", 50, st.get("TempMaxDriver", 90), st["MaxTemp"]), 0, 1)
        g.addWidget(with_help(tr('Макс. ліміт потужності, Вт'), "power_limit", "Secondary"), 1, 0)
        g.addWidget(self._spin("MaxPower", st.get("PlMin", 80), st.get("PlMax", 170), st["MaxPower"], 5), 1, 1)
        if expert:
            g.addWidget(with_help(tr('Автопідбір шукає ядро до, МГц'), "autotune", "Secondary"), 2, 0)
            g.addWidget(self._spin("TuneCoreMax", 1100, st.get("CoreMaxDriver", 2130), st["TuneCoreMax"], 50), 2, 1)
        c.body.addLayout(g)
        c.body.addWidget(label(tr('На межі температури панель знижує ядро на 100 МГц; на 8 °C вище — зупиняє майнінг і скидає розгін.'), "Muted", wrap=True))
        row.addWidget(c)
        self.lay.addLayout(row)

        row = FlowLayout(min_w=theme.pt(380))
        row.setSpacing(16)
        c = Card(tr('Інтерфейс'))
        g = self._grid()
        g.addWidget(label(tr('Тема'), "Secondary"), 0, 0)
        th = Segmented([("dark", tr('Темна')), ("light", tr('Світла')), ("system", tr('Як у системі'))], st["UiTheme"])
        th.changed.connect(lambda v: self.action.emit(f"theme:{v}"))
        g.addWidget(th, 0, 1)
        g.addWidget(label(tr('Шрифт'), "Secondary"), 1, 0)
        fs = Segmented([("normal", tr('Звичайний')), ("large", tr('Великий')), ("huge", tr('Дуже великий'))], st.get("UiFont") or "large")
        fs.changed.connect(lambda v: self.action.emit(f"font:{v}"))
        g.addWidget(fs, 1, 1)
        g.addWidget(label("Мова / Language", "Secondary"), 2, 0)
        lg = Segmented(list(LANGS.items()), st.get("UiLang") or "uk")
        lg.changed.connect(lambda v: self.action.emit(f"lang:{v}"))
        g.addWidget(lg, 2, 1)
        g.addWidget(self._check("Autostart", tr('Запускати панель разом із системою'), st["Autostart"]), 3, 0, 1, 3)
        g.addWidget(self._check("MinimizeToTray", tr('Хрестик згортає панель біля годинника (майнінг триває)'), st["MinimizeToTray"]), 4, 0, 1, 3)
        c.body.addLayout(g)
        c.body.addWidget(button(tr('Запустити майстер налаштування ще раз'), None, lambda: self.action.emit("wizard")))
        row.addWidget(c)
        c = Card(tr('Підключення'))
        g = QGridLayout()
        g.addWidget(label(tr('Токен HiveOS'), "Secondary"), 0, 0)
        tok = QLineEdit()
        tok.setEchoMode(QLineEdit.Password)
        tok.setPlaceholderText(tr('збережено — впиши новий, щоб замінити') if st["HiveOsToken"] else "HiveOS → Account → API tokens")
        g.addWidget(tok, 0, 1)
        g.addWidget(button(tr('Зберегти'), "Primary", lambda: self.action.emit(f"hive:token:{tok.text().strip()}")), 0, 2)
        g.addWidget(label(tr('Ключ hashrate.no'), "Secondary"), 1, 0)
        key = QLineEdit()
        key.setEchoMode(QLineEdit.Password)
        key.setPlaceholderText(tr('збережено') if st["HashrateNoKey"] else "hashrate.no → account → API Access")
        g.addWidget(key, 1, 1)
        g.addWidget(button(tr('Зберегти'), None, lambda: self.action.emit(f"hrn:key:{key.text().strip()}")), 1, 2)
        g.setColumnStretch(1, 1)
        c.body.addLayout(g)
        if st.get("HiveStatus"):
            c.body.addWidget(label(st["HiveStatus"], "Secondary", wrap=True))
        c.body.addWidget(label(tr('Токен HiveOS дає повний доступ до акаунта — він зберігається лише на цьому ПК.'), "Muted", wrap=True))
        row.addWidget(c)
        self.lay.addLayout(row)

        c = Card(tr('Майнери'))
        tb = make_table([tr('Майнер'), tr('Встановлено'), tr('Найновіша'), tr('Стан')], stretch=0)
        t = theme.current()
        mins = s["miners"]
        colors = {(i, 3): (t.warning if r["state"] == tr('є оновлення') else t.muted if r["state"] in (tr('не встановлено'), tr('перевіряю…')) else t.good_text)
                  for i, r in enumerate(mins)}
        fill_table(tb, [[r["name"], r["installed"], r["latest"], r["state"]] for r in mins], colors=colors, tags=[r["id"] for r in mins])
        c.body.addWidget(tb)

        def sel() -> str:
            it = tb.item(tb.currentRow(), 0) if tb.currentRow() >= 0 else None
            return str(it.data(Qt.UserRole)) if it else ""
        r2 = FlowLayout(spacing=8, stretch=False)
        r2.addWidget(button(tr('Встановити / оновити вибраний'), "Primary", lambda: self.action.emit(f"miner:update:{sel()}")))
        if expert:
            r2.addWidget(button(tr('Повернути попередню версію'), None, lambda: self.action.emit(f"miner:rollback:{sel()}")))
        r2.addWidget(button(tr('Перевірити оновлення'), None, lambda: self.action.emit("miner:check")))
        if st.get("DefenderAction"):
            r2.addWidget(button(tr('Дозволити теку майнерів у Defender'), "Primary", lambda a=st["DefenderAction"]: self.action.emit(a)))
        r2.addStretch(1)
        c.body.addLayout(r2)
        c.body.addWidget(label(s.get("miners_note") or tr('Майнери завантажуються лише з офіційних сторінок GitHub і перевіряються за SHA256.'), "Muted", wrap=True))
        self.lay.addWidget(c)
        self.lay.addStretch(1)
