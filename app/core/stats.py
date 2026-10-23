"""Облік енергії і світла (порт lib\\Stats.ps1 і Add-HiveStats з lib\\HiveOs.ps1).
Цей ПК: монети розрахунково за живим хешрейтом, енергія — лише відеокарта під час майнінгу,
KWhMine — без простою карти (IdleWatts вимірюється через 30 с після зупинки майнера).
Ферма: енергія ригів HiveOS за їхнім споживанням, лише поки панель відкрита."""
from __future__ import annotations

import time

from . import economics, timeutil


class IdleMeter:
    """Простій відеокарти: високі значення (гра, відео) відкидаються — оцінка тягнеться до найнижчого стабільного."""

    def __init__(self):
        self.since: float | None = None

    def update(self, settings: dict, draw: float, running: bool, now: float | None = None) -> None:
        now = time.time() if now is None else now
        if running:
            self.since = None
            return
        if self.since is None:
            self.since = now
            return
        if now - self.since < 30 or draw <= 0:
            return
        idle = float(settings.get("IdleWatts") or 0)
        if idle <= 0:
            idle = draw
        elif draw < idle:
            idle = 0.8 * idle + 0.2 * draw
        elif draw < idle * 1.25:
            idle = 0.98 * idle + 0.02 * draw
        settings["IdleWatts"] = round(idle, 2)


def add_local(stats: dict, settings: dict, market: dict | None, coin: dict, hr: float, draw: float, dt: float) -> dict:
    """Облік цього ПК за dt секунд майнінгу; повертає приріст {coins, kwh, cost, income}."""
    if dt <= 0 or not coin.get("ticker"):
        return {"coins": 0.0, "kwh": 0.0, "cost": 0.0, "income": 0.0}
    tk = str(coin["ticker"])
    s = stats.setdefault("local", {}).setdefault(tk, {"Coins": 0.0, "KWhGpu": 0.0, "KWhMine": 0.0, "Cost": 0.0,
                                                       "Seconds": 0.0, "Since": timeutil.iso()})
    coins = economics.coins_per_second(market, settings, coin, hr) * dt
    kwh_mine = max(0.0, draw - float(settings.get("IdleWatts") or 0)) * dt / 3600000
    cost = kwh_mine * economics.tariff_now(settings)["price"]
    s["Coins"] = float(s.get("Coins") or 0) + coins
    s["KWhGpu"] = float(s.get("KWhGpu") or 0) + draw * dt / 3600000
    s["KWhMine"] = float(s.get("KWhMine") or 0) + kwh_mine
    s["Cost"] = float(s.get("Cost") or 0) + cost
    s["Seconds"] = float(s.get("Seconds") or 0) + dt
    e = economics.coin_economics(market, settings, coin, hr)
    income = coins * e["price_uah"] if e else 0.0
    if e:
        # Дохід у ₴ за ціною на момент майнінгу; IncomeCoins — скільки монет уже оцінено так (старіший облік — без ціни)
        s["Income"] = float(s.get("Income") or 0) + income
        s["IncomeCoins"] = float(s.get("IncomeCoins") or 0) + coins
    return {"coins": coins, "kwh": kwh_mine, "cost": cost, "income": income}


def add_farm(stats: dict, settings: dict, workers: list[dict], now=None) -> dict[str, dict]:
    """Енергія онлайн-ригів між оновленнями (не більше 2 хв проміжку). → {ферма/воркер: {kwh, cost}}."""
    farm = stats.setdefault("farm", {})
    now = now or timeutil.now()
    out = {}
    for w in workers:
        if not w["online"] or w["power"] <= 0:
            continue
        k = f"{w['farm']}/{w['name']}"
        s = farm.get(k)
        if not s:
            farm[k] = {"Seconds": 0.0, "KWh": 0.0, "Cost": 0.0, "Since": timeutil.iso(now), "Last": timeutil.iso(now)}
            continue
        last = timeutil.parse(s.get("Last")) or now
        dt = min(120.0, (now - last).total_seconds())
        s["Last"] = timeutil.iso(now)
        if dt <= 0:
            continue
        kwh = w["power"] * dt / 3600000
        cost = kwh * economics.tariff_now(settings, now)["price"]
        s["Seconds"] = float(s["Seconds"]) + dt
        s["KWh"] = float(s["KWh"]) + kwh
        s["Cost"] = float(s["Cost"]) + cost
        out[k] = {"kwh": kwh, "cost": cost, "dt": dt}
    return out
