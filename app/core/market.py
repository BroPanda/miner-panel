"""Ринкові дані: WhatToMine (мережа, нагорода, запасна ціна), CoinGecko (курс BTC, ціни монет і бірж),
резерв курсу BTC — Binance + open.er-api.com. Кеш — market-cache.json (той самий формат, що в lib\\Market.ps1)."""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from . import storage, timeutil
from .net import get_json
from ..i18n import tr

CACHE = "market-cache.json"


def fetch(cg_ids: list[str], ticker_ids: list[str]) -> dict:
    r: dict = {"coins": {}, "btc": None, "cg": {}, "tickers": {}, "error": ""}
    try:
        w = get_json("https://whattomine.com/coins.json")
        for name, v in (w.get("coins") or {}).items():
            r["coins"][name] = {"nethash": float(v.get("nethash") or 0), "blockTime": float(v.get("block_time") or 0),
                                "reward": float(v.get("block_reward") or 0), "rateBtc": float(v.get("exchange_rate") or 0),
                                "tag": str(v.get("tag") or "")}
    except Exception as e:  # noqa: BLE001
        r["error"] += f"WhatToMine: {e} "
    cg_ok = False
    try:
        ids = ",".join(["bitcoin"] + [i for i in cg_ids if i])
        p = get_json("https://api.coingecko.com/api/v3/simple/price", params={"ids": ids, "vs_currencies": "usd,uah"})
        r["btc"] = {"usd": float(p["bitcoin"]["usd"]), "uah": float(p["bitcoin"]["uah"])}
        for k, v in p.items():
            r["cg"][k] = {"usd": float(v.get("usd") or 0), "uah": float(v.get("uah") or 0)}
        cg_ok = True
    except Exception as e:  # noqa: BLE001
        r["error"] += f"CoinGecko: {e} "
    if not r["btc"]:
        try:
            usd = float(get_json("https://api.binance.com/api/v3/ticker/price", 15, params={"symbol": "BTCUSDT"})["price"])
            uah = float(get_json("https://open.er-api.com/v6/latest/USD", 15)["rates"]["UAH"])
            if usd > 0 and uah > 0:
                r["btc"] = {"usd": usd, "uah": usd * uah}
        except Exception as e:  # noqa: BLE001
            r["error"] += tr('резервний курс: {0} ').format(e)
    # Ціни бірж — лише якщо CoinGecko відповідає, інакше лише більше 429
    if cg_ok:
        for i in [x for x in ticker_ids if x]:
            try:
                t = get_json(f"https://api.coingecko.com/api/v3/coins/{i}/tickers")
                rows = [{"id": str(x["market"]["identifier"]), "name": str(x["market"]["name"]), "pair": f"{x['base']}/{x['target']}",
                         "usd": float(x["converted_last"]["usd"]), "vol": float((x.get("converted_volume") or {}).get("usd") or 0)}
                        for x in t.get("tickers") or [] if not x.get("is_stale") and (x.get("converted_last") or {}).get("usd")]
                r["tickers"][i] = sorted(rows, key=lambda x: -x["vol"])
            except Exception as e:  # noqa: BLE001
                r["error"] += f"CoinGecko tickers {i}: {e} "
    return r


def merge(prev: dict | None, d: dict) -> dict:
    """Те, що цього разу не завантажилось (напр. 429 від CoinGecko), береться з попередніх даних."""
    if prev:
        if not d.get("coins"):
            d["coins"] = prev.get("coins") or {}
        if not d.get("btc"):
            d["btc"] = prev.get("btc")
        for sec in ("cg", "tickers"):
            for k, v in (prev.get(sec) or {}).items():
                d.setdefault(sec, {}).setdefault(k, v)
    return d


def usable(d: dict | None) -> bool:
    return bool(d and d.get("btc") and d.get("coins"))


def next_delay(d: dict, ok: bool) -> timedelta:
    limited = "429" in (d.get("error") or "")
    if ok:
        return timedelta(minutes=5 if limited else 15)
    return timedelta(minutes=5 if limited else 2)


def load_cache(root: Path) -> tuple[dict | None, object]:
    c = storage.read_json(root / CACHE, None)
    if not isinstance(c, dict):
        return None, None
    t = timeutil.parse(c.get("time"))
    if not t or (timeutil.now() - t).total_seconds() > 86400 or not c.get("btc") or not c.get("coins"):
        return None, None
    return {"coins": c["coins"], "btc": c["btc"], "cg": c.get("cg") or {}, "tickers": c.get("tickers") or {}, "error": ""}, t


def save_cache(root: Path, d: dict, t) -> None:
    storage.write_json(root / CACHE, {"time": timeutil.iso(t), "coins": d["coins"], "btc": d["btc"],
                                      "cg": d.get("cg") or {}, "tickers": d.get("tickers") or {}}, indent=None)
