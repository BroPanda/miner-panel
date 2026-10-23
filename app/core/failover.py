"""Резерв майнера цього ПК (порт Invoke-Failover з MinerPanel.ps1):
  майнер завершився сам — перезапуск через 15 с;
  працює, але без хешрейту 3 хв або довго без прийнятих шар (пул недоступний, завис) —
  перезапуск з іншого сервера пулу. «Довго» підлаштовується під частоту шар: щонайменше 30 хв
  і не менше 10 середніх інтервалів між шарами (шари приходять випадково: на Pearl ~1 за 3 хв, і
  15-хвилинна пауза трапляється сама кілька разів на добу — фіксований поріг давав хибні перезапуски);
  після 5 перезапусків за 30 хв наступні спроби не частіше ніж раз на 10 хв.
Лише логіка: tick() повертає рішення, а запускає майнер той, хто викликає."""
from __future__ import annotations

import time
from collections import deque

SHARE_GAP_MIN_S = 1800
SHARE_GAP_FACTOR = 10


def rotate(urls: list[str], shift: int) -> list[str]:
    """Сервери пулу, починаючи з shift-го (після простою — з наступного у списку)."""
    if not urls:
        return []
    k = shift % len(urls)
    return urls[k:] + urls[:k]


class Failover:
    def __init__(self):
        self.want_running = False
        self.pool_shift = 0
        self.dead_since: float | None = None
        self.hr_zero_since: float | None = None
        self.last_accepted = -1
        self.accepted_at = time.time()
        self.restarts: list[float] = []
        self.share_times: deque = deque(maxlen=50)     # коли приходили нові прийняті шари (переживає перезапуски)

    def share_gap_limit(self) -> float:
        """Скільки можна чекати нової шари: max(30 хв, 10 × середній інтервал за останніми шарами)."""
        t = self.share_times
        if len(t) >= 3:
            mean = (t[-1] - t[0]) / (len(t) - 1)
            return max(SHARE_GAP_MIN_S, SHARE_GAP_FACTOR * mean)
        return SHARE_GAP_MIN_S

    def started(self, manual: bool, now: float | None = None) -> None:
        now = time.time() if now is None else now
        if manual:
            self.pool_shift = 0
            self.restarts.clear()
        self.want_running = True
        self.dead_since = self.hr_zero_since = None
        self.last_accepted = -1
        self.accepted_at = now

    def stopped(self) -> None:
        self.want_running = False

    def tick(self, alive: bool, stats: dict | None, paused: bool = False, now: float | None = None) -> dict | None:
        """→ None або {reason, shift} — треба перезапустити майнер (shift: з наступного сервера)."""
        now = time.time() if now is None else now
        if not self.want_running or paused:
            self.dead_since = self.hr_zero_since = None
            return None
        reason, shift = None, False
        if not alive:
            self.hr_zero_since = None
            if self.dead_since is None:
                self.dead_since = now
            if now - self.dead_since >= 15:
                reason = "майнер несподівано завершився"
        else:
            self.dead_since = None
            if not stats or float(stats.get("hr") or 0) <= 0:
                if self.hr_zero_since is None:
                    self.hr_zero_since = now
                if now - self.hr_zero_since >= 180:
                    reason, shift = "немає хешрейту 3 хв", True
            else:
                self.hr_zero_since = None
            if stats:
                acc = int(stats.get("accepted") or 0)
                if acc != self.last_accepted:
                    if self.last_accepted >= 0 and acc > self.last_accepted:
                        self.share_times.append(now)
                    self.last_accepted, self.accepted_at = acc, now
                elif now - self.accepted_at >= self.share_gap_limit():
                    reason, shift = f"немає прийнятих шар {(now - self.accepted_at) / 60:.0f} хв", True
        if not reason:
            return None
        self.restarts = [t for t in self.restarts if now - t <= 1800]
        if len(self.restarts) >= 5 and now - self.restarts[-1] < 600:
            return None
        self.restarts.append(now)
        if shift:
            self.pool_shift += 1
        return {"reason": reason, "shift": shift, "attempt": len(self.restarts)}
