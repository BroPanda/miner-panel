"""Розумний вибір сервера пулу за затримкою.

Раз на 5 хв міряємо час TCP-з'єднання з портом кожного сервера (те саме з'єднання, яким користується
майнер; ICMP-ping часто блокують). Рішення з запасом, щоб не перемикатися через разові коливання:
  • поточний сервер недоступний (його повідомляє резерв: немає хешрейту / шар) → одразу на найшвидший живий;
  • інший сервер стабільно швидший: у вікні останніх 6 перевірок (30 хв) має щонайменше 4 вдалі виміри,
    ≥ 80 % успішних, і його медіана краща за поточну на ≥ 15 % і на ≥ 8 мс → перемкнутись;
  • добровільне перемикання — не частіше ніж раз на 2 год і не раніше ніж через 10 хв після старту майнера.
Кожне перемикання — перезапуск майнера (~20–30 с без роботи), тож навіть у найгіршому разі це ≤ 0,4 % часу."""
from __future__ import annotations

import socket
import statistics
import time
from collections import deque

PING_EVERY_S = 300
WINDOW = 6
MIN_OK = 4
MIN_SUCCESS = 0.8
BETTER_REL = 0.15
BETTER_ABS_MS = 8.0
MIN_SWITCH_S = 2 * 3600
GRACE_S = 600


def split(url: str) -> tuple[str, int]:
    u = url.split("://", 1)[-1]
    host, _, port = u.rpartition(":")
    return host, int(port or 0)


def same_server(a: str, b: str) -> bool:
    """Сервер майнера (може бути з префіксом stratum+tcp://) — той самий, що в списку."""
    return bool(a and b) and split(a)[0].lower() == split(b)[0].lower()


def probe_one(url: str, tries: int = 3, timeout: float = 2.0) -> float | None:
    """Медіана часу TCP-з'єднання, мс; None — сервер не відповів жодного разу."""
    host, port = split(url)
    res = []
    for _ in range(tries):
        t0 = time.perf_counter()
        try:
            with socket.create_connection((host, port), timeout=timeout):
                res.append((time.perf_counter() - t0) * 1000)
        except OSError:
            pass
    return statistics.median(res) if res else None


def probe(urls: list[str]) -> dict[str, float | None]:
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=max(1, len(urls))) as ex:
        return dict(zip(urls, ex.map(probe_one, urls)))


class Selector:
    def __init__(self):
        self.hist: dict[str, deque] = {}
        self.last_switch = 0.0
        self.bad: dict[str, float] = {}     # сервер → коли резерв визнав його недоступним

    def add(self, results: dict[str, float | None]) -> None:
        for url, ms in results.items():
            self.hist.setdefault(url, deque(maxlen=WINDOW)).append(ms)

    def stats(self, url: str) -> dict:
        h = list(self.hist.get(url) or [])
        ok = [x for x in h if x is not None]
        return {"n": len(h), "ok": len(ok), "success": len(ok) / len(h) if h else 0.0,
                "median": statistics.median(ok) if ok else None, "last": h[-1] if h else None}

    def stable(self, url: str) -> bool:
        s = self.stats(url)
        return s["ok"] >= MIN_OK and s["success"] >= MIN_SUCCESS

    def alive(self, url: str, now: float) -> bool:
        """Живий — останній вимір вдалий. Щойно визнаний недоступним (за 30 хв) — лише після двох вдалих поспіль."""
        h = list(self.hist.get(url) or [])
        recently_bad = now - self.bad.get(url, -1e18) < 1800
        if not h:
            return not recently_bad
        if h[-1] is None:
            return False
        return not recently_bad or (len(h) >= 2 and h[-2] is not None)

    def order(self, urls: list[str], now: float | None = None, first: str | None = None) -> list[str]:
        """Порядок для майнера: вибраний (або найшвидший живий) першим, далі живі за затримкою, решта — у кінці."""
        now = time.time() if now is None else now

        def key(u):
            s = self.stats(u)
            med = s["median"] if s["median"] is not None else 1e9
            return (0 if u == first else 1, 0 if self.alive(u, now) else 1, med, urls.index(u))
        return sorted(urls, key=key)

    def mark_bad(self, url: str, now: float | None = None) -> None:
        self.bad[url] = time.time() if now is None else now

    def decide(self, urls: list[str], current: str | None, started_at: float, now: float | None = None) -> dict | None:
        """Чи варто добровільно перейти на швидший сервер. → None або {url, reason}."""
        now = time.time() if now is None else now
        cur = next((u for u in urls if current and same_server(current, u)), None)
        if not cur or now - started_at < GRACE_S or now - self.last_switch < MIN_SWITCH_S:
            return None
        cs = self.stats(cur)
        if cs["median"] is None:
            return None              # поточний не міряється (блок?) — майнер працює, рішення лишаємо резерву
        best, best_ms = None, None
        for u in urls:
            if u == cur or not self.stable(u):
                continue
            m = self.stats(u)["median"]
            if best_ms is None or m < best_ms:
                best, best_ms = u, m
        if best is None:
            return None
        gain = cs["median"] - best_ms
        if gain >= BETTER_ABS_MS and gain >= cs["median"] * BETTER_REL:
            return {"url": best, "reason": f"{split(best)[0]} стабільно швидший: {best_ms:.0f} мс проти {cs['median']:.0f} мс "
                                           f"у {split(cur)[0]} (медіана за 30 хв)"}
        return None

    def switched(self, now: float | None = None) -> None:
        self.last_switch = time.time() if now is None else now
