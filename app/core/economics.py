"""Тарифи, ціни, прогноз і рейтинг — як у MinerPanel.ps1 / lib\\Market.ps1.

Ринкові дані (`market`): {coins: {wtm-назва: {nethash, blockTime, reward, rateBtc, tag}},
btc: {usd, uah}, cg: {coingecko-id: {usd, uah}}, tickers: {coingecko-id: [{id, name, pair, usd, vol}]}}.
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from . import timeutil

MODE_NAMES = {"eff": "Економний", "profit": "Максимальний дохід", "custom": "Свій"}


# ---- Тариф ------------------------------------------------------------------
def is_night_hour(settings: dict, h: int) -> bool:
    """Двозонний тариф: нічна зона з NightFrom до NightTo (години); однозонний — завжди день."""
    if not settings.get("TwoZone", True):
        return False
    f, t = int(settings.get("NightFrom", 23)), int(settings.get("NightTo", 7))
    if f == t:
        return False
    return f <= h < t if f < t else (h >= f or h < t)


def night_hours(settings: dict) -> int:
    return sum(1 for h in range(24) if is_night_hour(settings, h))


def tariff_now(settings: dict, now: datetime | None = None) -> dict:
    h = (now or timeutil.now()).hour
    if is_night_hour(settings, h):
        return {"night": True, "price": float(settings.get("TariffNight", 0)), "name": "нічний"}
    return {"night": False, "price": float(settings.get("TariffDay", 0)), "name": "денний"}


def day_kwh_price(settings: dict) -> float:
    """Ціна 1 кВт·год, помножена на 24 год доби з урахуванням зон (для прибутку за добу)."""
    nh = night_hours(settings)
    return nh * float(settings.get("TariffNight", 0)) + (24 - nh) * float(settings.get("TariffDay", 0))


# ---- Ціна і монети на добу ----------------------------------------------------
def price_source(settings: dict, coin: dict) -> str:
    s = (settings.get("PriceSource") or {}).get(str(coin.get("ticker")))
    if s:
        return str(s)
    return "coingecko" if coin.get("coingecko") else "wtm"


def coin_tickers(market: dict | None, coin: dict) -> list[dict]:
    if not market or not coin.get("coingecko"):
        return []
    return [t for t in (market.get("tickers") or {}).get(str(coin["coingecko"]), []) or [] if t]


def coin_price(market: dict | None, settings: dict, coin: dict) -> dict | None:
    """Ціна за вибраним джерелом, з резервом: біржа → CoinGecko → WhatToMine."""
    if not market or not market.get("btc"):
        return None
    btc = market["btc"]
    usd_uah = btc["uah"] / btc["usd"] if btc.get("usd", 0) > 0 else 0
    src = price_source(settings, coin)
    if src not in ("coingecko", "wtm"):
        t = next((t for t in coin_tickers(market, coin) if t.get("id") == src), None)
        if t:
            return {"usd": t["usd"], "uah": t["usd"] * usd_uah, "source": t["name"]}
    if src != "wtm" and coin.get("coingecko") and market.get("cg"):
        g = market["cg"].get(str(coin["coingecko"]))
        if g and g.get("usd", 0) > 0:
            return {"usd": g["usd"], "uah": g["uah"], "source": "CoinGecko"}
    m = (market.get("coins") or {}).get(str(coin.get("wtm")))
    if m and m.get("rateBtc", 0) > 0:
        return {"usd": m["rateBtc"] * btc["usd"], "uah": m["rateBtc"] * btc["uah"], "source": "WhatToMine"}
    return None


def coin_economics(market: dict | None, settings: dict, coin: dict, hr: float) -> dict | None:
    """Скільки монет на добу дає хешрейт hr (з комісією пулу) і ціна."""
    if not market or not coin.get("wtm"):
        return None
    m = (market.get("coins") or {}).get(str(coin["wtm"]))
    if not m or m.get("nethash", 0) <= 0 or m.get("blockTime", 0) <= 0:
        return None
    price = coin_price(market, settings, coin)
    if not price:
        return None
    fee = float((coin.get("pool") or {}).get("fee") or 0)
    per_day = hr / m["nethash"] * 86400 / m["blockTime"] * m["reward"] * (1 - fee)
    return {"coins_per_day": per_day, "price_uah": price["uah"], "price_usd": price["usd"], "price_source": price["source"]}


def income_per_hour(market, settings, coin, hr) -> float:
    e = coin_economics(market, settings, coin, hr)
    return e["coins_per_day"] * e["price_uah"] / 24 if e else 0.0


def coins_per_second(market, settings, coin, hr) -> float:
    e = coin_economics(market, settings, coin, hr)
    return e["coins_per_day"] / 86400 if e else 0.0


# ---- Хешрейт і споживання монети ---------------------------------------------
def profile_key(coin: dict) -> str:
    return str(coin.get("ticker") or coin.get("id"))


def hrn_bench(hrn: dict, gpu_name: str | None, coin: dict) -> dict | None:
    """Еталон hashrate.no для монети на цій карті; відкидається, якщо явно інші одиниці (×5)."""
    b = (hrn.get("bench") or {}).get(str(coin.get("ticker")))
    if not gpu_name or not b or not b.get("devices"):
        return None
    d = b["devices"].get(gpu_name)
    if not d or float(d.get("hr") or 0) <= 0:
        return None
    est = float((coin.get("estimate") or {}).get("hr") or 0)
    hr = float(d["hr"])
    if est > 0 and (hr / est > 5 or est / hr > 5):
        return None
    return {"hr": hr, "watts": float(d.get("watts") or 0)}


def coin_perf(coin: dict, settings: dict, hrn: dict, gpu_name: str | None,
              live: dict | None = None) -> dict:
    """Живі (live = {coin_id, hr, watts}), виміряні раніше, еталон hashrate.no або оцінка з coins.json."""
    if live and live.get("coin_id") == coin.get("id") and live.get("hr", 0) > 0:
        return {"hr": live["hr"], "watts": live["watts"], "src": "зараз"}
    m = (settings.get("Measured") or {}).get(profile_key(coin))
    if m and float(m.get("hr") or 0) > 0:
        return {"hr": float(m["hr"]), "watts": float(m.get("watts") or 0), "src": "виміряно"}
    return bench_perf(coin, hrn, gpu_name)


def bench_perf(coin: dict, hrn: dict, gpu_name: str | None) -> dict:
    b = hrn_bench(hrn, gpu_name, coin)
    if b:
        return {**b, "src": "hashrate.no"}
    e = coin.get("estimate") or {}
    return {"hr": float(e.get("hr") or 0), "watts": float(e.get("watts") or 0), "src": "оцінка"}


def day_profit(market, settings, coin, perf) -> float | None:
    """Прибуток за добу (₴) з урахуванням нічної і денної зон."""
    if not perf or perf["hr"] <= 0:
        return None
    e = coin_economics(market, settings, coin, perf["hr"])
    if not e:
        return None
    return e["coins_per_day"] * e["price_uah"] - perf["watts"] / 1000 * day_kwh_price(settings)


# ---- Прогноз ----------------------------------------------------------------
def forecast(market, settings, coin, perf) -> dict | None:
    """Прогноз за зонами тарифу: {zones: [{name, hours, price, income, cost, profit_hour, profit}], total…}."""
    econ = coin_economics(market, settings, coin, perf["hr"]) if perf else None
    if not econ or perf["hr"] <= 0:
        return None
    income_hour = econ["coins_per_day"] * econ["price_uah"] / 24
    kwh_hour = perf["watts"] / 1000
    nh = night_hours(settings)
    f, t = int(settings.get("NightFrom", 23)), int(settings.get("NightTo", 7))
    two = bool(settings.get("TwoZone", True))
    zones = []
    for name, hours, price, night in (
            (f"Ніч ({f:02d}:00–{t:02d}:00)" if two else "Нічна зона вимкнена", nh, float(settings.get("TariffNight", 0)), True),
            (f"День ({t:02d}:00–{f:02d}:00)" if two else "Цілодобово", 24 - nh, float(settings.get("TariffDay", 0)), False)):
        cost = kwh_hour * price
        zones.append({"name": name, "hours": hours, "price": price, "night": night,
                      "income": income_hour * hours, "cost": cost * hours,
                      "profit_hour": income_hour - cost, "profit": (income_hour - cost) * hours})
    income = sum(z["income"] for z in zones)
    cost = sum(z["cost"] for z in zones)
    now_t = tariff_now(settings)
    return {"zones": zones, "income": income, "cost": cost, "profit": income - cost,
            "coins_per_day": econ["coins_per_day"], "price_uah": econ["price_uah"], "price_usd": econ["price_usd"],
            "price_source": econ["price_source"], "src": perf["src"],
            "now_profit_hour": income_hour - kwh_hour * now_t["price"], "now_tariff": now_t}


def ranking(coins, market, settings, hrn, gpu_name, live=None) -> list[dict]:
    """Монети за прибутком за еталоном (однакові умови); поруч твій живий/виміряний результат."""
    rows = []
    for c in coins:
        bp = bench_perf(c, hrn, gpu_name)
        p = coin_perf(c, settings, hrn, gpu_name, live)
        mp = p if p["src"] in ("зараз", "виміряно") else None
        rows.append({"coin": c, "bench": bp, "profit": day_profit(market, settings, c, bp),
                     "my": mp, "my_profit": day_profit(market, settings, c, mp)})
    rows.sort(key=lambda r: -math.inf if r["profit"] is None else r["profit"], reverse=True)
    return rows


# ---- Виплата пулу -------------------------------------------------------------
def payout_eta(market, settings, coin, d: dict, local_hr: float = 0.0, running_here: bool = False,
               now: datetime | None = None) -> dict:
    """Орієнтовний час до мінімальної виплати за хешрейтом усіх online-воркерів адреси на пулі."""
    b = d.get("balance") or {}
    total, th = float(b.get("total") or 0), float(b.get("threshold") or 0) or 1.0
    pct = min(100.0, total / th * 100)
    res = {"pct": pct, "threshold": th, "total": total, "days": None, "workers": 0, "hr": 0.0, "text": ""}
    if total >= th:
        c = float(b.get("confirmed") or 0)
        res["text"] = "поріг досягнуто — виплата найближчим часом" if c >= th else \
            f"на виплату вистачає — прийде, коли дозріє ще {fmt_num(th - c, 4)} {coin.get('ticker')}"
        res["days"] = 0
        return res
    s, n = 0.0, 0
    for w in d.get("workers") or []:
        if not w or not w.get("online"):
            continue
        h = max(float(w.get("hr30m") or 0), float(w.get("hr3h") or 0))
        if w.get("name") == coin.get("worker") and running_here and local_hr > 0:
            h = local_hr
        s += h
        n += 1
    if s <= 0 and running_here and local_hr > 0:
        s, n = local_hr, 1
    res.update(workers=n, hr=s)
    if s <= 0:
        res["text"] = "немає активних воркерів"
        return res
    e = coin_economics(market, settings, coin, s)
    if not e or e["coins_per_day"] <= 0:
        res["text"] = "час — коли будуть ринкові дані"
        return res
    res["days"] = (th - total) / e["coins_per_day"]
    return res


def can_switch(coin: dict, d: dict) -> dict:
    """Чи можна відключитись, не лишивши монет на пулі: {ok, text}."""
    b = d.get("balance") or {}
    c = float(b.get("confirmed") or 0)
    total = c + float(b.get("unconfirmed") or 0)
    th = float(b.get("threshold") or 0)
    tk = coin.get("ticker")
    if th <= 0:
        return {"ok": None, "text": "—"}
    if total < th:
        return {"ok": False, "text": f"ні — до виплати бракує {fmt_num(th - total, 4)} {tk}"}
    if c >= th:
        return {"ok": True, "text": "так — виплата найближчим часом"}
    return {"ok": True, "text": f"так — на виплату вже вистачає, прийде сама ({fmt_num(th - c, 4)} {tk} ще дозріває)"}


# ---- Форматування ---------------------------------------------------------------
def fmt_hr(h: float) -> str:
    for scale, unit in ((1e15, "PH/s"), (1e12, "TH/s"), (1e9, "GH/s"), (1e6, "MH/s"), (1e3, "kH/s")):
        if h >= scale:
            return f"{h / scale:,.2f} {unit}".replace(",", " ").replace(".", ",")
    return f"{h:.0f} H/s" if h > 0 else "0"


def fmt_uah(v: float | None, sign: bool = True) -> str:
    if v is None:
        return "—"
    s = f"{v:+,.2f}" if sign else f"{v:,.2f}"
    return s.replace(",", " ").replace(".", ",") + " ₴"


def fmt_num(v: float, digits: int = 2) -> str:
    return f"{v:,.{digits}f}".replace(",", " ").replace(".", ",")


def fmt_duration_days(days: float) -> str:
    if days > 365:
        return "понад рік"
    total_min = int(days * 24 * 60)
    d, rem = divmod(total_min, 24 * 60)
    h, m = divmod(rem, 60)
    return f"{d} д {h} год" if d else f"{h} год {m} хв"


def worker_word(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return "воркер"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return "воркери"
    return "воркерів"


def recommended(coin: dict, pl_min: int, max_power: int) -> dict[str, Any]:
    """Рекомендована ефективна точка монети (з coins.json або оцінка)."""
    r = coin.get("recommended")
    if r:
        return {"PL": int(r.get("pl", 100)), "Core": int(r.get("core", 1500))}
    pl = 100
    w = (coin.get("estimate") or {}).get("watts")
    if w:
        pl = int(math.ceil(float(w) * 1.15))
    return {"PL": max(pl_min, min(int(max_power), pl)), "Core": 1500}
