"""Ядро: тарифи, економіка, пули (на справжній відповіді HeroMiners), резерв, HiveOS, події, історія, дані."""
import json
import shutil
import time
from datetime import datetime
from pathlib import Path

import pytest

from app.core import economics as ec
from app.core import events, failover, hiveos, history, ledger, pools, stats, storage

FIX = Path(__file__).with_name("fixtures")
ROOT = Path(__file__).resolve().parents[2]

SETTINGS = {"TwoZone": True, "NightFrom": 23, "NightTo": 7, "TariffDay": 4.32, "TariffNight": 2.16, "PriceSource": {}, "Measured": {}}
COIN = {"id": "pearl-herominers", "ticker": "PRL", "wtm": "Pearl", "coingecko": "pearl", "wallet": "w", "worker": "rtx3060",
        "pool": {"type": "herominers", "coin": "pearl", "fee": 0.0, "hashrateFactor": 4294967296}, "estimate": {"hr": 39.3e12, "watts": 86}}
MARKET = {"coins": {"Pearl": {"nethash": 1e18, "blockTime": 60, "reward": 100, "rateBtc": 0.00002}},
          "btc": {"usd": 100000, "uah": 4150000}, "cg": {"pearl": {"usd": 2.33, "uah": 96.7}}, "tickers": {}}


def test_tariff_zones():
    assert ec.night_hours(SETTINGS) == 8
    assert ec.is_night_hour(SETTINGS, 23) and ec.is_night_hour(SETTINGS, 6) and not ec.is_night_hour(SETTINGS, 7)
    assert ec.tariff_now(SETTINGS, datetime(2026, 1, 1, 2)).get("price") == 2.16
    assert ec.night_hours({**SETTINGS, "TwoZone": False}) == 0


def test_economics_and_forecast():
    e = ec.coin_economics(MARKET, SETTINGS, COIN, 50e12)
    assert e["coins_per_day"] == pytest.approx(50e12 / 1e18 * 86400 / 60 * 100)
    assert e["price_source"] == "CoinGecko"
    f = ec.forecast(MARKET, SETTINGS, COIN, {"hr": 50e12, "watts": 100, "src": "зараз"})
    income = e["coins_per_day"] * 96.7
    cost = 0.1 * (8 * 2.16 + 16 * 4.32)
    assert f["income"] == pytest.approx(income) and f["cost"] == pytest.approx(cost) and f["profit"] == pytest.approx(income - cost)
    assert ec.day_profit(MARKET, SETTINGS, COIN, {"hr": 50e12, "watts": 100}) == pytest.approx(income - cost)
    # Джерело «WhatToMine»: ціна через курс BTC
    p = ec.coin_price(MARKET, {**SETTINGS, "PriceSource": {"PRL": "wtm"}}, COIN)
    assert p["source"] == "WhatToMine" and p["uah"] == pytest.approx(0.00002 * 4150000)


def test_ranking_order_and_payout():
    other = {**COIN, "id": "other", "ticker": "OTH", "wtm": "Other", "coingecko": None, "estimate": {"hr": 1e9, "watts": 100}}
    m = {**MARKET, "coins": {**MARKET["coins"], "Other": {"nethash": 1e15, "blockTime": 60, "reward": 1, "rateBtc": 1e-9}}}
    r = ec.ranking([other, COIN], m, SETTINGS, {"bench": {}}, "RTX 3060")
    assert r[0]["coin"]["id"] == "pearl-herominers"
    d = {"balance": {"total": 0.5, "confirmed": 0.3, "unconfirmed": 0.2, "threshold": 1.0},
         "workers": [{"name": "rtx3060", "online": True, "hr30m": 40e12, "hr3h": 45e12}]}
    eta = ec.payout_eta(MARKET, SETTINGS, COIN, d)
    assert eta["pct"] == 50 and eta["workers"] == 1 and eta["days"] == pytest.approx(0.5 / ec.coin_economics(MARKET, SETTINGS, COIN, 45e12)["coins_per_day"])
    assert ec.can_switch(COIN, d)["ok"] is False
    assert ec.fmt_hr(45.11e12) == "45,11 TH/s"


def test_herominers_real_response(monkeypatch):
    stats_js = json.loads((FIX / "hero_stats.json").read_text(encoding="utf-8"))
    addr_js = json.loads((FIX / "hero_address.json").read_text(encoding="utf-8"))
    monkeypatch.setattr(pools, "get_json", lambda url, *a, **k: addr_js if "stats_address" in url else stats_js)
    d = pools.herominers(COIN["pool"], "w")
    units = float(stats_js["config"]["coinUnits"])
    assert d["workExact"] and d["balance"]["confirmed"] == pytest.approx(float(addr_js["stats"]["balance"]) / units)
    assert d["earned"] == pytest.approx((float(addr_js["stats"]["paid"]) + float(addr_js["stats"]["balance"])) / units)
    w = next(x for x in d["workers"] if x["name"] == "rtx3060")
    assert w["work"] == float(addr_js["workers"][0]["hashes"]) and w["hr24h"] > 1e12   # множник 2^32
    s = {"ledger": {}, "payouts": []}
    assert ledger.add_pool_snapshot(s, COIN, d, "HeroMiners")


def test_failover_rules():
    f = failover.Failover()
    f.started(manual=True, now=0)
    assert f.tick(True, {"hr": 4e13, "accepted": 3}, now=1) is None
    assert f.tick(False, None, now=10) is None
    assert f.tick(False, None, now=26)["reason"] == "майнер несподівано завершився"
    f.started(manual=False, now=30)
    f.tick(True, {"hr": 0, "accepted": 0}, now=31)
    r = f.tick(True, {"hr": 0, "accepted": 0}, now=212)
    assert r["shift"] and f.pool_shift == 1
    f.started(manual=False, now=220)
    f.tick(True, {"hr": 1, "accepted": 7}, now=221)
    assert f.tick(True, {"hr": 1, "accepted": 7}, now=221 + 901) is None          # 15 хв без шар — ще норма
    assert f.tick(True, {"hr": 1, "accepted": 7}, now=221 + 1801)["reason"].startswith("немає прийнятих шар")
    # Рідкі шари (раз на 5 хв) — поріг росте до 10 інтервалів = 50 хв
    h = failover.Failover()
    h.started(manual=True, now=0)
    for i in range(6):
        h.tick(True, {"hr": 1, "accepted": i}, now=i * 300)
    assert h.share_gap_limit() == 3000
    assert h.tick(True, {"hr": 1, "accepted": 5}, now=1500 + 2000) is None
    # 5 перезапусків за 30 хв → наступний не раніше ніж через 10 хв після останнього
    g = failover.Failover()
    g.started(manual=True, now=0)
    for t in (0, 400, 800, 1200, 1600):
        g.started(manual=False, now=t)
        g.tick(True, {"hr": 0}, now=t + 1)
        assert g.tick(True, {"hr": 0}, now=t + 182)
    g.started(manual=False, now=1790)
    g.tick(True, {"hr": 0}, now=1791)
    assert g.tick(True, {"hr": 0}, now=1975) is None
    assert g.tick(True, {"hr": 0}, now=2400)                   # найстаріші випали з вікна — знову можна
    f.stopped()
    assert f.tick(False, None, now=5000) is None
    assert failover.rotate(["de", "fi", "tr"], 4) == ["fi", "tr", "de"]


def test_hive_normalize_and_watch():
    raw = {"id": 101, "name": "rig1", "stats": {"online": True, "power_draw": 690, "miner_start_time": 0},
           "miners_summary": {"hashrates": [{"miner": "srbminer", "coin": "PRL", "algo": "pearlhash", "hash": 312e9, "shares": {"accepted": 812, "rejected": 3}}]},
           "miners_stats": {"hashrates": [{"hashes": [52e9] * 6}]},
           "gpu_info": [{"bus_number": i, "index": i, "model": "RTX 3070"} for i in range(6)],
           "gpu_stats": [{"bus_number": i, "temp": 60 + i, "fan": 55, "power": 115} for i in range(6)],
           "gpu_summary": {"max_temp": 65}, "flight_sheet": {"id": 11, "name": "PRL HeroMiners", "items": [{"pool": "HeroMiners"}]}}
    w = hiveos.normalize_worker(raw, {"id": 1, "name": "Дім"})
    assert w["hr"] == 312e12 and len(w["gpus"]) == 6 and w["gpus"][5]["temp"] == 65 and w["gpus"][0]["hr"] == 52e12
    assert hiveos.coin_for([COIN], w)["id"] == "pearl-herominers"
    stopped = {**w, "id": 102, "minerOn": False, "hr": 0}
    zero = {**w, "id": 103, "hr": 0}
    watch = hiveos.Watch()
    a, r = watch.check([w, stopped, zero], auto=True, now=0)
    assert [x["kind"] for x in a] == ["stopped"] and not r
    a, r = watch.check([w, stopped, zero], auto=True, now=11 * 60)
    assert {x["kind"] for x in a} == {"stopped", "nohash"} and [x["id"] for x in r] == [103]
    assert watch.check([zero], auto=True, now=20 * 60)[1] == []          # не частіше ніж раз на 30 хв


def test_events_dedupe(tmp_path):
    got = []
    ev = events.Events(tmp_path / "panel.log", got.append)
    n = events.Notice("pool:de", events.WARN, "Пул не відповідає", "Панель перейшла на fi. Нічого робити не треба.")
    ev.raise_(n)
    ev.raise_(n)
    assert len(got) == 1 and len(ev.sorted_active()) == 1
    ev.clear("pool:de")
    assert not ev.active and "Пул не відповідає" in (tmp_path / "panel.log").read_text(encoding="utf-8")


def test_history_compact(tmp_path):
    h = history.History(tmp_path / "h.db")
    now = time.time()
    for i in range(120):
        h.add_sample("pc", 40e12 + i, 60, 100, ts=now - 8 * 86400 + i * 60)
    h.add_sample("pc", 45e12, 61, 101, ts=now - 60)
    h.compact(now)
    cut = int(now - history.KEEP_MINUTE_S) // 3600 * 3600
    old = [int(now - 8 * 86400 + i * 60) for i in range(120)]
    left = sum(1 for t in old if t >= cut) + 1
    assert h.db.execute("SELECT COUNT(*) FROM samples WHERE hourly = 0").fetchone()[0] == left
    assert h.db.execute("SELECT COUNT(*) FROM samples WHERE hourly = 1").fetchone()[0] == len({t // 3600 for t in old if t < cut})
    h.compact(now)                                   # повторне стискання нічого не дублює
    assert h.db.execute("SELECT COUNT(*) FROM samples WHERE hourly = 1").fetchone()[0] == len({t // 3600 for t in old if t < cut})
    h.add_daily("pc", 50, 8, 2, 0.6, "PRL")
    h.add_daily("pc", 10, 1, 0.5, 0.1, "PRL")
    assert h.days(7) == [(datetime.now().date().isoformat(), 60.0, 9.0)]


def test_history_per_coin_and_migration(tmp_path):
    import sqlite3
    p = tmp_path / "old.db"
    db = sqlite3.connect(p)                          # база старої версії: доба без монети в ключі, заміри без монети
    db.executescript("""CREATE TABLE samples (device TEXT, ts INTEGER, hr REAL, temp REAL, watts REAL, hourly INTEGER DEFAULT 0);
                        CREATE TABLE daily (device TEXT, day TEXT, income REAL, cost REAL, kwh REAL, coins REAL, ticker TEXT,
                                            PRIMARY KEY (device, day));""")
    db.execute("INSERT INTO daily VALUES ('pc', date('now', 'localtime'), 5, 1, 0.2, 0.1, 'PRL')")   # доба — за місцевим часом
    db.execute("INSERT INTO samples(device, ts, hr, temp, watts) VALUES ('pc', ?, 1, 60, 100)", (int(time.time()) - 120,))
    db.commit()
    db.close()
    h = history.History(p)
    h.add_daily("pc", 50, 8, 2, 0.6, "PRL")
    h.add_daily("pc", 30, 4, 1, 2.0, "XEL")          # інша монета того ж дня — окремий рядок, монети не складаються
    rows = dict(h.db.execute("SELECT ticker, coins FROM daily").fetchall())
    assert rows == {"PRL": pytest.approx(0.7), "XEL": pytest.approx(2.0)}
    assert h.days(7) == [(datetime.now().date().isoformat(), 85.0, 13.0)]
    now = time.time()
    h.add_sample("pc", 45e12, 60, 100, ts=now - 60, ticker="PRL")
    h.add_sample("pc", 9e6, 61, 110, ts=now - 30, ticker="XEL")
    assert [round(x[1]) for x in h.series("pc", 600, 1, ticker="PRL")] == [45e12]   # хешрейт лише цієї монети
    assert len(h.series("pc", 600, 1)) == 3                                           # температура й Вт — усі


def test_income_kept_at_mining_price():
    s, st = dict(SETTINGS), {"local": {}}
    inc = stats.add_local(st, s, MARKET, COIN, 45e12, 100.0, 3600)
    x = st["local"]["PRL"]
    assert x["Income"] == pytest.approx(inc["income"]) and x["IncomeCoins"] == pytest.approx(x["Coins"])


def test_local_energy_and_idle():
    s, st = dict(SETTINGS, IdleWatts=19), {"local": {}}
    inc = stats.add_local(st, s, MARKET, COIN, 45e12, 100.0, 3600)
    assert st["local"]["PRL"]["KWhMine"] == pytest.approx(0.081) and inc["income"] > 0
    m = stats.IdleMeter()
    s2 = {"IdleWatts": 0}
    m.update(s2, 18, False, now=0)
    m.update(s2, 18, False, now=31)
    assert s2["IdleWatts"] == 18


def test_store_reads_real_data(tmp_path):
    for f in ("settings.json", "coins.json", "wallets.json", "stats.json"):
        if (ROOT / f).exists():
            shutil.copy(ROOT / f, tmp_path / f)
    st = storage.Store(tmp_path, test=True).load()
    assert st.coins and st.coin() is not None
    for L in st.stats["ledger"].values():
        r = ledger.account_coins(L)
        assert isinstance(L["Cp"]["EarnedQ"], int) and r["Distributed"] >= 0
