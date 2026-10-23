"""Історія для графіків: history.db (SQLite).
samples — щохвилини для кожного пристрою: хешрейт, °C, Вт, монета; старші 7 днів стискаються до годинних.
daily   — за кожну добу для кожного пристрою й монети: дохід (₴, розрахунково), світло (₴), кВт·год, монети."""
from __future__ import annotations

import sqlite3
import time
from datetime import date
from pathlib import Path

KEEP_MINUTE_S = 7 * 86400


class History:
    def __init__(self, path: Path | str):
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS samples (device TEXT, ts INTEGER, hr REAL, temp REAL, watts REAL, hourly INTEGER DEFAULT 0);
            CREATE INDEX IF NOT EXISTS samples_dev_ts ON samples(device, ts);
            CREATE TABLE IF NOT EXISTS daily (device TEXT, day TEXT, income REAL, cost REAL, kwh REAL, coins REAL, ticker TEXT,
                                              PRIMARY KEY (device, day, ticker));
        """)
        self._migrate()
        self._last_compact = time.time()

    def _migrate(self) -> None:
        """Старі бази: у заміри — колонка монети; доба — окремо для кожної монети (раніше монети різних тикерів
        за день складались в одне число)."""
        cols = [r[1] for r in self.db.execute("PRAGMA table_info(samples)")]
        if "ticker" not in cols:
            self.db.execute("ALTER TABLE samples ADD COLUMN ticker TEXT DEFAULT ''")
        sql = self.db.execute("SELECT sql FROM sqlite_master WHERE name = 'daily'").fetchone()[0]
        if "PRIMARY KEY (device, day)" in sql:
            self.db.executescript("""
                CREATE TABLE daily_new (device TEXT, day TEXT, income REAL, cost REAL, kwh REAL, coins REAL, ticker TEXT,
                                        PRIMARY KEY (device, day, ticker));
                INSERT INTO daily_new SELECT device, day, income, cost, kwh, coins, COALESCE(ticker, '') FROM daily;
                DROP TABLE daily;
                ALTER TABLE daily_new RENAME TO daily;
            """)
        self.db.commit()

    def add_sample(self, device: str, hr: float, temp: float, watts: float, ts: float | None = None, ticker: str = "") -> None:
        self.db.execute("INSERT INTO samples(device, ts, hr, temp, watts, ticker) VALUES (?,?,?,?,?,?)",
                        (device, int(ts or time.time()), hr, temp, watts, ticker))
        self.db.commit()
        if time.time() - self._last_compact > 3600:
            self.compact()

    def add_daily(self, device: str, income: float, cost: float, kwh: float, coins: float, ticker: str,
                  day: date | None = None) -> None:
        """Додає до підсумку доби (накопичувально)."""
        d = (day or date.today()).isoformat()
        self.db.execute("""INSERT INTO daily(device, day, income, cost, kwh, coins, ticker) VALUES (?,?,?,?,?,?,?)
                           ON CONFLICT(device, day, ticker) DO UPDATE SET income = income + excluded.income,
                           cost = cost + excluded.cost, kwh = kwh + excluded.kwh, coins = coins + excluded.coins""",
                        (device, d, income, cost, kwh, coins, ticker or ""))
        self.db.commit()

    def compact(self, now: float | None = None) -> None:
        """Хвилинні заміри старші 7 днів → середні за годину. Межа вирівняна по годині, тож кожна
        година стискається один раз, цілком."""
        now = time.time() if now is None else now
        self._last_compact = now
        cut = int(now - KEEP_MINUTE_S) // 3600 * 3600
        self.db.execute("""INSERT INTO samples(device, ts, hr, temp, watts, hourly, ticker)
                           SELECT device, (ts / 3600) * 3600, AVG(hr), AVG(temp), AVG(watts), 1, ticker FROM samples
                           WHERE hourly = 0 AND ts < ? GROUP BY device, ts / 3600, ticker""", (cut,))
        self.db.execute("DELETE FROM samples WHERE hourly = 0 AND ts < ?", (cut,))
        self.db.commit()

    def series(self, device: str, since_s: float, bucket_s: int = 60, ticker: str | None = None) -> list[tuple[int, float, float, float]]:
        """[(ts, hr, temp, watts)] за останні since_s секунд, усереднені по bucket_s; ticker — лише заміри цієї монети
        (хешрейт різних алгоритмів не можна змішувати на одному графіку)."""
        flt, args = ("AND ticker = ?", [ticker]) if ticker is not None else ("", [])
        rows = self.db.execute(f"""SELECT (ts / ?) * ?, AVG(hr), AVG(temp), AVG(watts) FROM samples
                                   WHERE device = ? AND ts >= ? {flt} GROUP BY ts / ? ORDER BY 1""",
                               [bucket_s, bucket_s, device, int(time.time() - since_s)] + args + [bucket_s]).fetchall()
        return [(int(a), float(b or 0), float(c or 0), float(d or 0)) for a, b, c, d in rows]

    def days(self, n: int, device: str | None = None) -> list[tuple[str, float, float]]:
        """[(день, дохід, світло)] за останні n днів — для одного пристрою або всіх разом."""
        q = "SELECT day, SUM(income), SUM(cost) FROM daily WHERE day >= date('now', ?)"
        args: list = [f"-{n - 1} day"]
        if device:
            q += " AND device = ?"
            args.append(device)
        q += " GROUP BY day ORDER BY day"
        return [(d, float(i or 0), float(c or 0)) for d, i, c in self.db.execute(q, args).fetchall()]

    def close(self) -> None:
        self.db.close()
