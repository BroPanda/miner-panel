"""Картка пристрою — однакова для цього ПК і ригів HiveOS."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QVBoxLayout, QWidget

from ...core.economics import fmt_hr, fmt_uah
from .. import theme
from ..widgets import Card, FlowLayout, StatusDot, button, label

ACTION_TEXT = {"start": "Старт", "stop": "Стоп", "restart": "Перезапуск"}
ACTION_OBJ = {"start": "Start", "stop": None, "restart": None}


def device_level(d: dict) -> str:
    return {"mining": "good", "warn": "warn", "offline": "critical", "stopped": "off", "starting": "info"}.get(d["state"], "off")


class DeviceCard(Card):
    """Компактно: назва · модель · стан в одному рядку; показники — в ряд (переносяться), кнопки — праворуч."""
    acted = Signal(str)

    def __init__(self, d: dict, compact: bool = True):
        super().__init__()
        top = QHBoxLayout()
        nm = d["name"] if d["kind"] == "local" else f"{d['name']}  ·  {d.get('farm', '')}"
        top.addWidget(label(nm, "CardTitle"))
        top.addWidget(label(f"{d['model']}  ·  {'HiveOS' if d['kind'] == 'hive' else 'керує ця панель'}", "Muted", wrap=True), 1)
        dot = StatusDot()
        dot.set(device_level(d), d["state_text"])
        top.addWidget(dot)
        self.body.addLayout(top)

        # Показники і кнопки — в один ряд; не вміщаються — кнопки переходять нижче, показники переносяться
        row = FlowLayout(spacing=16, natural=True, stretch=False)
        cells = [("Монета", d.get("coin") or "—"), ("Хешрейт", fmt_hr(d["hr"]) if d.get("hr") else "—"),
                 ("Температура", f"{d['temp']} °C" if d.get("temp") is not None else "—"),
                 ("Споживання", f"{d['watts']:.0f} Вт" if d.get("watts") else "—"),
                 ("Прибуток за добу", fmt_uah(d.get("profit_day")) if d.get("profit_day") is not None else "—")]
        box = QWidget()
        flow = FlowLayout(box, spacing=28, stretch=False)
        for k, v in cells:
            cell = QWidget()
            cv = QVBoxLayout(cell)
            cv.setContentsMargins(0, 0, 0, 0)
            cv.setSpacing(2)
            cv.addWidget(label(k, "Muted"))
            cv.addWidget(label(v, "CardTitle", wrap=True))
            flow.addWidget(cell)
        row.addWidget(box)
        acts_w = QWidget()
        acts = QHBoxLayout(acts_w)
        acts.setContentsMargins(0, 0, 0, 0)
        acts.setSpacing(8)
        for a in d.get("actions") or []:
            b = button(ACTION_TEXT[a], ACTION_OBJ.get(a), lambda _=False, a=a: self.acted.emit(f"device:{a}:{d['id']}"))
            if a == "start":
                b.setObjectName("Primary")
            acts.addWidget(b)
        if compact:
            acts.addWidget(button("Детальніше →", "Link", lambda: self.acted.emit(f"open:device:{d['id']}")))
        row.addWidget(acts_w)
        self.body.addLayout(row)
