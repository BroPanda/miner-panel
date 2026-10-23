"""Автопідбір частоти ядра (порт lib\\Tuner.ps1).
Від стартової точки: база → вгору кроком 100 МГц, поки оцінка росте; якщо вже перший крок гірший — вниз;
наприкінці уточнення ±50 МГц. Ліміт потужності під час тесту = «Макс. Вт»; пам'ять не змінюється.
  Економний режим: один прохід, оцінка — хешрейт на Вт, результат — і в денний, і в нічний профіль.
  Максимальний дохід: оцінка — ₴ за годину; два проходи (день і ніч), якщо нічний режим увімкнено,
  інакше один за середнім тарифом доби (або за єдиним тарифом).
Точка: 30 с стабілізації + 60 с вимірювання. Перегрів — вище цієї частоти не йдемо."""
from __future__ import annotations

import math
import time
from datetime import datetime
from typing import Callable
from ..i18n import tr

SETTLE, MEASURE, STEP, MIN_CORE = 30, 60, 100, 1100


class Phase:
    def __init__(self, profiles: list[str], price: float | None, title: str):
        self.profiles, self.price, self.title = profiles, price, title
        self.stage = "base"
        self.base = self.best = None
        self.next: int | None = None
        self.refine: list[int] = []
        self.seen: set[int] = set()


class Tuner:
    def __init__(self, phases: list[Phase], start_core: int, max_core: int, max_power: int, mem: int, mem_off: int,
                 income_per_hour: Callable[[float], float], apply: Callable[[int, int, int, int], None]):
        self.phases, self.i = phases, 0
        self.max_core, self.max_power, self.mem, self.mem_off = max_core, max_power, mem, mem_off
        self.income = income_per_hour
        self.apply = apply
        self.cache: dict[int, dict] = {}
        self.hot_cap = 99999
        self.n = 0
        self.current = 0
        self.stage_t = "settle"
        self.until = 0.0
        self.hr: list[float] = []
        self.draw: list[float] = []
        self.log: list[str] = []
        self.status = ""
        self.done = False
        self.result: list[tuple[Phase, dict, int]] = []      # (фаза, найкраща точка, ліміт Вт)
        start = int(round(start_core / 50) * 50)
        self.phases[0].next = max(MIN_CORE, min(max_core, start))

    # ---- допоміжне ----
    def add_log(self, s: str) -> None:
        self.log.append(f"[{datetime.now():%H:%M:%S}] {s}")

    def score(self, ph: Phase, r: dict) -> float:
        if ph.price is not None:
            return self.income(r["hr"]) - r["draw"] / 1000 * ph.price
        return r["hr"] / 1e9 / max(1.0, r["draw"])

    def fmt_score(self, ph: Phase, s: float) -> str:
        return tr('{0:.2f} ₴/год').format(s) if ph.price is not None else tr('{0:.1f} GH/s на Вт').format(s)

    def can(self, ph: Phase, c: int) -> bool:
        return MIN_CORE <= c <= self.max_core and c < self.hot_cap and c not in ph.seen

    def better(self, ph: Phase, r: dict) -> bool:
        b = ph.best
        if not b:
            return True
        sb, sr = self.score(ph, b), self.score(ph, r)
        noise = abs(sb) * 0.005
        if sr > sb + noise:
            return True
        return sr >= sb - noise and r["draw"] < b["draw"] - 1

    @property
    def phase(self) -> Phase:
        return self.phases[self.i]

    # ---- хід ----
    def start(self, now: float | None = None) -> None:
        self.next_point(now)

    def next_point(self, now: float | None = None) -> None:
        now = time.time() if now is None else now
        while True:
            ph = self.phase
            if ph.next is None:
                if ph.best:
                    self.add_log(tr('{0}: найкраще — ядро {1} МГц ({2})').format(ph.title, ph.best['core'], self.fmt_score(ph, self.score(ph, ph.best))))
                if self.i + 1 >= len(self.phases):
                    self.complete()
                    return
                prev = ph
                self.i += 1
                ph = self.phase
                ph.next = prev.best["core"] if prev.best else (next(iter(prev.seen)) if prev.seen else None)
                self.add_log(tr('--- Прохід {0}: старт від {1} МГц').format(ph.title, ph.next))
                if ph.next is None:
                    continue
                continue
            c = int(ph.next)
            ph.next = None
            if c in self.cache:
                self.add_result(ph, self.cache[c], True)
                continue
            self.current = c
            self.n += 1
            self.hr.clear()
            self.draw.clear()
            self.stage_t = "settle"
            self.until = now + SETTLE
            self.apply(self.max_power, c, self.mem, self.mem_off)
            d = {"base": tr('база'), "up": tr('вгору'), "down": tr('вниз'), "refine": tr('уточнення')}[ph.stage]
            self.status = tr('Прохід {0}, точка {1}: ядро {2} МГц ({3})… ~{4} с на точку').format(ph.title, self.n, c, d, SETTLE + MEASURE)
            return

    def add_result(self, ph: Phase, r: dict, from_cache: bool) -> None:
        ph.seen.add(int(r["core"]))
        improved = False
        if r["hot"]:
            self.add_log(tr('[{0}] ядро {1} МГц: перегрів, вище не йду.').format(ph.title, r['core']))
        else:
            improved = self.better(ph, r)
            line = (tr('[{0}] ядро {1} МГц: {2:.2f} TH/s, {3:.1f} Вт → {4}').format(ph.title, r['core'], r['hr'] / 1e12, r['draw'], self.fmt_score(ph, self.score(ph, r))))
            if ph.best:
                line += tr('  [КРАЩЕ]') if improved else tr('  [гірше]')
            if from_cache:
                line += tr('  (з попереднього виміру)')
            self.add_log(line)
            if improved:
                ph.best = r
        b = ph.best
        if ph.stage == "base":
            ph.base = r
            if not b:
                ph.stage = "down"
                if self.can(ph, r["core"] - STEP):
                    ph.next = r["core"] - STEP
                return
            ph.stage = "up"
            if self.can(ph, b["core"] + STEP):
                ph.next = b["core"] + STEP
                return
            ph.stage = "down"
            if self.can(ph, b["core"] - STEP):
                ph.next = b["core"] - STEP
                return
        elif ph.stage == "up":
            if improved:
                if self.can(ph, b["core"] + STEP):
                    ph.next = b["core"] + STEP
                    return
            elif b is ph.base:
                ph.stage = "down"
                if self.can(ph, b["core"] - STEP):
                    ph.next = b["core"] - STEP
                    return
        elif ph.stage == "down":
            if improved and self.can(ph, b["core"] - STEP):
                ph.next = b["core"] - STEP
                return
        if not b:
            return
        if ph.stage != "refine":
            ph.stage = "refine"
            ph.refine = [c for c in (b["core"] + STEP // 2, b["core"] - STEP // 2) if self.can(ph, c)]
        while ph.refine:
            c = ph.refine.pop(0)
            if self.can(ph, c):
                ph.next = c
                return

    def step(self, temp: int | None, max_temp: int, hr: float | None, draw: float | None, now: float | None = None) -> None:
        """Викликати щотакту (2 с), поки не done."""
        if self.done:
            return
        now = time.time() if now is None else now
        if temp is not None and temp >= max_temp:
            r = {"core": self.current, "hr": 0.0, "draw": 0.0, "hot": True}
            self.cache[self.current] = r
            self.hot_cap = min(self.hot_cap, self.current)
            self.add_result(self.phase, r, False)
            self.next_point(now)
            return
        if self.stage_t == "settle":
            if now >= self.until:
                self.stage_t, self.until = "measure", now + MEASURE
            return
        if hr is not None:
            self.hr.append(hr)
        if draw is not None:
            self.draw.append(draw)
        if now < self.until:
            return
        r = {"core": self.current, "hot": False,
             "hr": sum(self.hr) / len(self.hr) if self.hr else 0.0, "draw": sum(self.draw) / len(self.draw) if self.draw else 0.0}
        self.cache[self.current] = r
        self.add_result(self.phase, r, False)
        self.next_point(now)

    def complete(self) -> None:
        self.done = True
        for ph in self.phases:
            if ph.best:
                pl = int(math.ceil(ph.best["draw"] * 1.15))
                self.result.append((ph, ph.best, pl))
                self.add_log(tr('НАЙКРАЩЕ [{0}]: ядро {1} МГц, ліміт ≈{2} Вт — {3}').format(ph.title, ph.best['core'], pl, self.fmt_score(ph, self.score(ph, ph.best))))
        if not self.result:
            self.add_log(tr('Не вдалося підібрати — повертаю попередні налаштування.'))
