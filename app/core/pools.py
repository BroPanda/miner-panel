"""Адаптери пулів (порт pools\\*.ps1). fetch(pool, wallet) повертає уніфіковані дані:
balance {total, confirmed, unconfirmed, threshold}, paid {total, last {amount, time(ms)}},
earned (виплачено + підтверджений баланс — для бухгалтерії), workExact,
workers [{name, online, hr30m, hr3h, hr24h, valid, stale, invalid, lastShare(ms), work}]."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from .net import get_json


def _num(x: Any) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def _sum(v: Any) -> float:
    """Число або список нарахувань (amount/reward/value/balance) → сума; записи блоків «висота:хеш:…» пропускаємо."""
    if v is None:
        return 0.0
    s = 0.0
    for x in v if isinstance(v, list) else [v]:
        if isinstance(x, (int, float)):
            s += float(x)
        elif isinstance(x, str):
            try:
                s += float(x)
            except ValueError:
                pass
        elif isinstance(x, dict):
            for k in ("amount", "reward", "value", "balance"):
                if x.get(k) is not None:
                    s += _num(x[k])
                    break
    return s


def herominers(pool: dict, wallet: str) -> dict:
    """HeroMiners (<coin>.herominers.com). Для деяких алгоритмів хешрейт у своїх одиницях —
    множник pool.hashrateFactor (Pearl: 2^32). Суми — в атомарних одиницях / coinUnits."""
    base = f"https://{pool['coin']}.herominers.com/api"
    cfg = get_json(f"{base}/stats")["config"]
    units = _num(cfg.get("coinUnits")) or 1.0
    factor = _num(pool.get("hashrateFactor")) or 1.0
    th = _num(cfg.get("minPaymentThreshold")) / units
    s = get_json(f"{base}/stats_address", params={"address": wallet, "longpoll": "false"})
    if s.get("error"):
        # Адреса ще не майнила на цьому пулі
        return {"balance": {"total": 0.0, "confirmed": 0.0, "unconfirmed": 0.0, "threshold": th},
                "earned": 0.0, "workExact": True, "paid": {"total": 0.0, "last": None}, "workers": []}
    st = s.get("stats") or {}
    confirmed = _sum(st.get("balance")) / units
    pending = _sum(s.get("unconfirmed")) / units
    if _num(st.get("minPayoutLevel")) > 0:
        th = _num(st["minPayoutLevel"]) / units
    paid_total = _sum(st.get("paid")) / units
    last = None
    pl = s.get("payments") or []
    for i in range(0, len(pl) - 1, 2):
        parts = str(pl[i]).split(":")
        if len(parts) < 2:
            continue
        t = _num(pl[i + 1])
        if not last or t > last["time"] / 1000:
            last = {"amount": _num(parts[1]) / units, "time": t * 1000}
    if paid_total <= 0 and last:
        paid_total = last["amount"]
    workers = []
    for w in s.get("workers") or []:
        hr = _num(w.get("hashrate")) * factor
        workers.append({"name": str(w.get("name")), "online": hr > 0, "hr30m": hr,
                        "hr3h": _num(w.get("hashrate_6h")) * factor, "hr24h": _num(w.get("hashrate_24h")) * factor,
                        "valid": int(_num(w.get("shares_good"))), "stale": int(_num(w.get("shares_stale"))),
                        "invalid": int(_num(w.get("shares_invalid"))), "lastShare": _num(w.get("lastShare")) * 1000,
                        "work": _num(w.get("hashes"))})
    return {"balance": {"total": confirmed + pending, "confirmed": confirmed, "unconfirmed": pending, "threshold": th},
            "earned": paid_total + confirmed, "workExact": True, "paid": {"total": paid_total, "last": last}, "workers": workers}


def kryptex(pool: dict, wallet: str) -> dict:
    """Kryptex: розподіл за кількістю шар без складності — приблизний («≈»)."""
    api = f"https://pool.kryptex.com/{pool['coin']}/api"
    b = get_json(f"{api}/v1/miner/balance/{wallet}", 15)
    minpay = 0.0
    try:
        minpay = _num(get_json(f"{api}/v1/pool/info", 15).get("minpay"))
    except Exception:  # noqa: BLE001
        pass
    th = _num(b.get("threshold")) or minpay
    paid, last = 0.0, None
    try:
        for x in (get_json(f"{api}/v1/miner/payouts/{wallet}", 15).get("results") or []):
            amt = next((_num(x[k]) for k in ("amount", "value", "reward") if x.get(k) is not None), None)
            if amt is None:
                continue
            paid += amt
            tm = None
            for k in ("created_at", "timestamp", "time", "date", "paid_at"):
                v = x.get(k)
                if v is None:
                    continue
                if isinstance(v, (int, float)):
                    tm = float(v) * (1000 if v < 1e11 else 1)
                else:
                    try:
                        tm = datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp() * 1000
                    except ValueError:
                        pass
                break
            if tm and (not last or tm > last["time"]):
                last = {"amount": amt, "time": tm}
    except Exception:  # noqa: BLE001
        pass
    w = get_json(f"{api}/v3/miner/workers/{wallet}", 15)
    workers = [{"name": str(x.get("worker")), "online": x.get("status") == "online",
                "hr30m": _num(x.get("avg_hashrate_30m")), "hr3h": _num(x.get("avg_hashrate_3h")), "hr24h": _num(x.get("avg_hashrate_24h")),
                "valid": int(_num(x.get("valid"))), "stale": int(_num(x.get("stale"))), "invalid": int(_num(x.get("invalid"))),
                "lastShare": _num(x.get("last_share")), "work": _num(x.get("valid"))} for x in w.get("results") or []]
    return {"balance": {"total": _num(b.get("total")), "confirmed": _num(b.get("confirmed")),
                        "unconfirmed": _num(b.get("unconfirmed")), "threshold": th},
            "paid": {"total": paid, "last": last}, "earned": paid + _num(b.get("confirmed")), "workExact": False, "workers": workers}


def generic(pool: dict, wallet: str) -> dict:
    """Будь-який пул за адресою stratum: майнінг працює, балансу і воркерів немає."""
    return {"balance": None, "workers": []}


# Російські або пов'язані з Росією пули позначені, щоб майстер і вибір пулу їх не пропонували першими
POOLS: dict[str, dict[str, Any]] = {
    "herominers": {"name": "HeroMiners", "fetch": herominers, "page": "https://{coin}.herominers.com/#/dashboard?addr={wallet}", "ru": False},
    "kryptex": {"name": "Kryptex", "fetch": kryptex, "page": "https://pool.kryptex.com/{coin}/miner/stats/{wallet}", "ru": True},
    "generic": {"name": "Пул", "fetch": generic, "page": "{page}", "ru": False},
}


def pool_name(coin: dict) -> str:
    t = str((coin.get("pool") or {}).get("type"))
    return POOLS[t]["name"] if t in POOLS else t


def page_url(coin: dict) -> str | None:
    p = coin.get("pool") or {}
    a = POOLS.get(str(p.get("type")))
    if not a:
        return None
    url = a["page"].replace("{coin}", str(p.get("coin", ""))).replace("{wallet}", str(coin.get("wallet", ""))).replace("{page}", str(p.get("page", "")))
    return url or None


def fetch(coin: dict) -> dict:
    f: Callable = POOLS.get(str((coin.get("pool") or {}).get("type")), POOLS["generic"])["fetch"]
    return f(coin.get("pool") or {}, str(coin.get("wallet") or ""))
