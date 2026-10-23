"""Пристрої: список угорі, під ним сторінка вибраного — однаково для цього ПК і ригів HiveOS."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QGridLayout, QHBoxLayout, QPlainTextEdit, QPushButton,
                               QSpinBox, QVBoxLayout, QWidget)

from ...core.economics import MODE_NAMES, fmt_hr, fmt_uah
from .. import glossary, theme
from ..widgets import (Card, CheckLine, ChoiceCard, FlowLayout, LineChart, Segmented, StatusDot, button, clear_layout,
                       fill_table, help_icon, hr_scale, label, make_table, with_help)
from . import Page
from .common import ACTION_TEXT, device_level

MODE_DESC = {
    "eff": ("Економний", "Найбільше монет на кожен ват. Холодніше й тихіше."),
    "profit": ("Максимальний дохід", "Швидше, але світла йде більше. Вигідно вночі."),
    "custom": ("Свій", "Ліміт і частоти задаєш сам у «Розширено»."),
}


class DevicesPage(Page):
    def __init__(self):
        super().__init__()
        self.selected: str | None = None
        self.period = "day"
        # Список пристроїв — рядок кнопок угорі (переноситься), щоб сторінці пристрою лишалась уся ширина
        self.list_box = QWidget()
        self.list_lay = FlowLayout(self.list_box, spacing=8, stretch=False)
        self.lay.addWidget(self.list_box)
        self.detail = QWidget()
        self.detail_lay = QVBoxLayout(self.detail)
        self.detail_lay.setContentsMargins(0, 0, 0, 0)
        self.detail_lay.setSpacing(16)
        self.lay.addWidget(self.detail)
        self.lay.addStretch(1)

    def select(self, dev_id: str) -> None:
        self.selected = dev_id

    def render(self, s: dict, expert: bool) -> None:
        devs = s["devices"]
        if not self.selected or not any(d["id"] == self.selected for d in devs):
            self.selected = devs[0]["id"] if devs else None
        clear_layout(self.list_lay)
        for d in devs:
            b = QPushButton()
            b.setObjectName("NavButton")
            b.setCheckable(True)
            b.setChecked(d["id"] == self.selected)
            col = theme.status_color(device_level(d))
            icon = theme.STATUS_ICON.get(device_level(d), "●")
            b.setText(f"{icon}  {d['name']}\n     {d['state_text']}")
            b.setStyleSheet(f"QPushButton {{ color: {theme.current().ink}; }}")
            b.setToolTip(d["model"])
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, i=d["id"]: (self.select(i), self.render(s, expert)))
            self.list_lay.addWidget(b)
        clear_layout(self.detail_lay)
        d = next((x for x in devs if x["id"] == self.selected), None)
        if not d:
            self.detail_lay.addWidget(label("Пристроїв ще немає. Додай токен HiveOS у «Налаштуваннях», щоб побачити ферму.", "Muted"))
            return
        self._header(d, expert)
        self._charts(d)
        if d["kind"] == "local":
            self._mode(d)
            self._advanced(d)
        else:
            self._hive(d, expert)
        self.detail_lay.addStretch(1)

    # ---- частини сторінки ----
    def _header(self, d: dict, expert: bool) -> None:
        c = Card()
        top = FlowLayout(spacing=10, stretch=False)
        title = d["name"] if d["kind"] == "local" else f"{d['name']} · {d.get('farm', '')}"
        top.addWidget(label(title, "Big"))
        dot = StatusDot()
        dot.set(device_level(d), d["state_text"])
        top.addWidget(dot)
        top.addStretch(1)
        for a in d.get("actions") or []:
            b = button(ACTION_TEXT[a], "Primary" if a == "start" else ("Danger" if a == "stop" else None),
                       lambda _=False, a=a: self.action.emit(f"device:{a}:{d['id']}"))
            top.addWidget(b)
        c.body.addLayout(top)
        sub = f"{d['model']} · {d.get('coin') or '—'} · {d.get('pool', '')}"
        if expert and d.get("server"):
            sub += f" · {d['server']} · {d.get('miner', '')}"
        c.body.addWidget(label(sub, "Muted", wrap=True))
        cells = [("Хешрейт", fmt_hr(d["hr"]) if d.get("hr") else "—", "hashrate"),
                 ("Температура", f"{d['temp']} °C" if d.get("temp") is not None else "—", None),
                 ("Споживання", f"{d['watts']:.0f} Вт" if d.get("watts") else "—", None),
                 ("Прибуток за добу", fmt_uah(d.get("profit_day")) if d.get("profit_day") is not None else "—", None)]
        if expert:
            cells += [("Прийнята робота", f"{d.get('accepted', 0)} / відх. {d.get('rejected', 0)}", "shares"),
                      ("Час роботи", d.get("uptime", "—"), None)]
            if d["kind"] == "local":
                cells += [("Ядро / пам'ять", f"{d.get('core')} / {d.get('mem')} МГц", None), ("Ефективність", d.get("eff", "—"), None)]
        # Показники — по 4 в ряд, а коли не вміщаються — переносяться
        g = FlowLayout(spacing=20, min_w=theme.pt(150))
        for k, v, hk in cells:
            cell = QWidget()
            cv = QVBoxLayout(cell)
            cv.setContentsMargins(0, 0, 0, 0)
            cv.setSpacing(2)
            cv.addWidget(with_help(k, hk, "Muted") if hk else label(k, "Muted"))
            cv.addWidget(label(v, "CardTitle", wrap=True))
            g.addWidget(cell)
        c.body.addLayout(g)
        self.detail_lay.addWidget(c)

    def _charts(self, d: dict) -> None:
        c = Card("Історія")
        seg = Segmented([("day", "Доба"), ("week", "Тиждень"), ("month", "Місяць")], self.period)
        seg.changed.connect(lambda p: (setattr(self, "period", p), self.action.emit(f"history:{p}:{d['id']}")))
        c.head.addWidget(seg)
        row = FlowLayout(min_w=theme.pt(220))
        series = d.get("series") or {}
        # Хешрейт: одиниця в заголовку, на осі — круглі числа в цій одиниці
        scale, unit = hr_scale([v for _, v in series.get("hr") or []])
        for key, title, pts, vt in (
                ("hr", f"Хешрейт{' · ' + d['hr_coin'] if d.get('hr_coin') else ''}, {unit}", [(ts, v / scale) for ts, v in series.get("hr") or []], lambda v: f"{v:.2f} {unit}".replace(".", ",")),
                ("temp", "Температура, °C", series.get("temp") or [], lambda v: f"{v:.0f} °C"),
                ("watts", "Споживання, Вт", series.get("watts") or [], lambda v: f"{v:.0f} Вт")):
            col = QVBoxLayout()
            col.addWidget(label(title, "Secondary"))
            ch = LineChart(value_text=vt)
            ch.setMinimumHeight(160)
            ch.set_points(pts)
            col.addWidget(ch)
            row.addLayout(col)
        c.body.addLayout(row)
        self.detail_lay.addWidget(c)

    def _mode(self, d: dict) -> None:
        c = Card("Режим роботи")
        row = FlowLayout(spacing=12, min_w=theme.pt(170))
        for key, (title, desc) in MODE_DESC.items():
            b = ChoiceCard(title, desc, d["mode"] == key, glossary.term(f"mode_{key}"))
            b.clicked.connect(lambda k=key: self.action.emit(f"mode:{k}"))
            row.addWidget(b)
        c.body.addLayout(row)
        c.body.addWidget(label(f"Зараз діє: {MODE_DESC[d['mode']][0]} · {d['zone_text']}", "Secondary", wrap=True))
        self.detail_lay.addWidget(c)

    def _advanced(self, d: dict) -> None:
        c = Card("Розширено: ліміт і частоти")
        g = QGridLayout()
        g.setHorizontalSpacing(10)
        g.setColumnStretch(5, 1)
        # Короткі заголовки і фіксована ширина полів — щоб сітка вміщалась і у вузькому вікні
        heads = [("", None), ("Ліміт, Вт", "power_limit"), ("Ядро, МГц", "core"), ("Пам'ять", "memory"), ("Зсув, МГц", "mem_offset")]
        for i, (h, k) in enumerate(heads):
            g.addWidget(with_help(h, k, "Muted") if k else label(h), 0, i)
        for r, (zone, name) in enumerate((("day", "День"), ("night", "Ніч"))):
            tv = d["tuning"][zone]
            active = d["zone"] == zone
            on = zone == "day" or d["night_split"]
            text = ("▶ " if active else "") + name
            if zone == "day":
                lab = label(text, "CardTitle" if active else "Secondary")
                lab.setToolTip("діє зараз" if active else "")
            else:
                # Ніч вмикається/вимикається прямо тут — той самий NightProfile, що й у «Режим роботи»
                lab = QCheckBox(text)
                lab.setObjectName("CardTitle" if active else "Secondary")
                lab.setChecked(d["night_split"])
                if d.get("two_zone", True):
                    lab.setToolTip(("діє зараз · " if active else "") + "вимкни, щоб уночі діяли денні значення")
                else:
                    lab.setEnabled(False)
                    lab.setToolTip("тариф однозонний — увімкни двозонний у Налаштуваннях")
                lab.toggled.connect(lambda v: self.action.emit(f"night:{int(v)}"))
            if zone == "night":
                cell = QHBoxLayout()
                cell.addWidget(lab)
                cell.addWidget(help_icon("night"))
                g.addLayout(cell, r + 1, 0)
            else:
                g.addWidget(lab, r + 1, 0)
            if not on:
                g.addWidget(label("вимкнено — уночі діють денні значення", "Muted"), r + 1, 1, 1, 5)
                continue
            (plo, phi), (clo, chi), (mlo, mhi) = d["pl_range"], d["core_range"], d["mem_off_range"]
            for col, (key, lo, hi, step) in enumerate((("PL", plo, phi, 5), ("Core", clo, chi, 50), ("MemOff", mlo, mhi, 50))):
                sp = QSpinBox()
                sp.setRange(lo, hi)
                sp.setSingleStep(step)
                sp.setValue(max(lo, min(hi, int(tv[key]))))
                sp.setEnabled(on and (key != "MemOff" or mhi > mlo))
                sp.setFixedWidth(100)
                if key == "Core":
                    sp.setSpecialValueText("без меж")             # 0 — ядро не обмежене
                sp.editingFinished.connect(lambda z=zone, k=key, w=sp: self.action.emit(f"tune:set:{z}:{k}:{w.value()}"))
                g.addWidget(sp, r + 1, {0: 1, 1: 2, 2: 4}[col])
            mem = QComboBox()
            mem.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            mem.setMinimumContentsLength(11)
            mem.addItem("Заводська", 0)
            for m in d["mem_clocks"]:
                mem.addItem(f"до {m} МГц", m)
                if m < 1000:
                    mem.setItemData(mem.count() - 1, "економно: для монет, яким пам'ять майже не потрібна (напр. Pearl)", Qt.ToolTipRole)
            i = mem.findData(int(tv["Mem"]))
            mem.setCurrentIndex(i if i >= 0 else 0)
            mem.setEnabled(on)
            mem.activated.connect(lambda _i, z=zone, w=mem: self.action.emit(f"tune:set:{z}:Mem:{w.currentData()}"))
            g.addWidget(mem, r + 1, 3)
        c.body.addLayout(g)
        c.body.addWidget(label(f"Межі цієї карти: {d['limits']}. Панель лише знижує частоти й потужність, напругу не чіпає.", "Muted", wrap=True))
        if d.get("tune_note"):
            c.body.addWidget(label(d["tune_note"], "Secondary", wrap=True))
        row = QHBoxLayout()
        row.addWidget(button("Рекомендовані", None, lambda: self.action.emit("tune:recommended")))
        if d.get("tuning_active"):
            row.addWidget(button("Скасувати автопідбір", "Danger", lambda: self.action.emit("tune:cancel")))
        else:
            row.addWidget(button("Автопідбір ядра", "Primary", lambda: self.action.emit("tune:auto")))
        row.addWidget(help_icon("autotune"))
        row.addStretch(1)
        c.body.addLayout(row)
        if d.get("tune_log"):
            log = QPlainTextEdit("\n".join(d["tune_log"]))
            log.setReadOnly(True)
            log.setMaximumHeight(90)
            c.body.addWidget(log)
        self.detail_lay.addWidget(c)

    def _hive(self, d: dict, expert: bool) -> None:
        if d.get("gpus"):
            c = Card("Відеокарти рига")
            tb = make_table(["№", "Карта", "°C", "Вентилятор", "Вт", "Хешрейт"] + (["Ядро / пам'ять, МГц"] if expert else []), stretch=1)
            rows = [[g["idx"], g["name"], g["temp"], f"{g['fan']} %", f"{g['watts']:.0f}", fmt_hr(g["hr"])] +
                    ([f"{g['core']} / {g['mem']}"] if expert else []) for g in d["gpus"]]
            hot = {(i, 2): theme.current().warning for i, g in enumerate(d["gpus"]) if g["temp"] >= 75}
            fill_table(tb, rows, colors=hot, numeric={2, 4})
            c.body.addWidget(tb)
            self.detail_lay.addWidget(c)
        c = Card("Що майнить риг")
        g = QGridLayout()
        g.setHorizontalSpacing(10)
        g.addWidget(with_help("Польотний лист", "flight_sheet", "Secondary"), 0, 0)
        fs = QComboBox()
        fs.addItems(d.get("fs_list") or [])
        fs.setCurrentIndex(d.get("fs_index", -1))
        g.addWidget(fs, 0, 1)
        g.addWidget(button("Застосувати", None, lambda: self.action.emit(f"hive:fs:{d['id']}:{fs.currentIndex()}")), 0, 2)
        g.addWidget(with_help("Профіль розгону", "oc_profile", "Secondary"), 1, 0)
        oc = QComboBox()
        oc.addItems(d.get("oc_list") or [])
        oc.setCurrentIndex(d.get("oc_index", -1))
        g.addWidget(oc, 1, 1)
        g.addWidget(button("Застосувати", None, lambda: self.action.emit(f"hive:oc:{d['id']}:{oc.currentIndex()}")), 1, 2)
        g.setColumnStretch(1, 1)
        c.body.addLayout(g)
        ar = CheckLine("Перезапускати майнер, якщо 10 хв немає хешрейту (у HiveOS є і свій watchdog)", bool(d.get("auto_restart")))
        for w in (fs, oc):
            w.setEnabled(d["state"] != "offline")
        ar.toggled.connect(lambda on: self.action.emit(f"hive:auto:{int(on)}"))
        c.body.addWidget(ar)
        self.detail_lay.addWidget(c)
