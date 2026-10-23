"""Знімок стану для вікна — та сама структура, що в app/ui/sample.py (макет)."""
from __future__ import annotations

import time
from datetime import date, datetime, timedelta

from .core import economics as ec
from .core import events as ev
from .core import hiveos, ledger, pools, updater
from .core.miners import MINERS, coin_miner_id, dev_fee
from .core.timeutil import from_unix_ms, parse
from . import i18n
from .i18n import num, tr

PERIOD_S = {"day": (86400, 600), "week": (7 * 86400, 3600), "month": (30 * 86400, 4 * 3600)}


def _n(v: float, d: int = 4) -> str:
    return ec.fmt_num(v, d)


def _pct(v: float) -> str:
    return num(f"{v:.2f}".rstrip("0").rstrip(".")) + " %"


def _fees(s: dict, coin: dict) -> dict:
    """Комісії для рядка рейтингу: пул (з coins.json) і майнер (dev fee для його алгоритму)."""
    mid = coin_miner_id(s, coin)
    m = MINERS.get(mid)
    mf = dev_fee(mid, coin)
    return {"pool_fee": _pct(float((coin.get("pool") or {}).get("fee") or 0) * 100),
            "miner_fee": _pct(mf) if mf is not None else "?", "miner_name": m.name if m else mid}


def _owner(o: str) -> str:
    """«Я» і «без власника» зберігаються українською (спільний формат обліку) — перекладається лише показ."""
    return tr(o) if o in (ledger.OWNER_ME, ledger.OWNER_NONE) else o


def _dur(sec: float) -> str:
    t = timedelta(seconds=int(sec))
    return tr('{0} д {1} год').format(t.days, t.seconds // 3600) if t.days else tr('{0} год {1:02d} хв').format(t.seconds // 3600, t.seconds % 3600 // 60)


def _addr(a: str) -> str:
    return f"{a[:9]}…{a[-6:]}" if len(a) > 18 else a


def _servers(c, coin: dict) -> list[dict]:
    """Сервери пулу з затримкою: що зараз, медіана за 30 хв, стан; поточний — той, до якого підключений майнер."""
    from .core import servers as sv
    cur = c.current_server() if c.runner.alive() and c.running_coin() and c.running_coin().get("id") == coin.get("id") else None
    out = []
    now = time.time()
    for u in (coin.get("pool") or {}).get("urls") or []:
        st = c.sel.stats(u)
        if not st["n"]:
            state, level = tr('ще не перевірено'), "none"
        elif st["last"] is None:
            state, level = tr('не відповідає'), "bad"
        elif not c.sel.alive(u, now):
            state, level = tr('нещодавно падав'), "warn"
        elif st["success"] < sv.MIN_SUCCESS:
            state, level = tr('нестабільний ({0:.0f} % відповідей)').format(st['success'] * 100), "warn"
        else:
            state, level = tr('працює'), "good"
        out.append({"url": u, "current": bool(cur and sv.same_server(cur, u)), "level": level, "state": state,
                    "now": tr('{0:.0f} мс').format(st['last']) if st["last"] is not None else "—",
                    "median": tr('{0:.0f} мс').format(st['median']) if st["median"] is not None else "—",
                    "_sort": ({"good": 0, "warn": 1, "none": 2, "bad": 3}[level],
                              st["median"] if st["median"] is not None else 1e9)})
    # Найшвидші робочі — зверху; ті, що не відповідають або ще не перевірені, — внизу
    out.sort(key=lambda x: x.pop("_sort"))
    return out


def _is_ru(c: dict) -> bool:
    """Пул, пов'язаний з Росією: за типом адаптера або за адресою сервера (напр. generic з kryptex.network)."""
    pool = c.get("pool") or {}
    if pools.POOLS.get(str(pool.get("type")), {}).get("ru"):
        return True
    return any("kryptex" in str(u).lower() for u in pool.get("urls") or [])


def _pool_name(c: dict) -> str:
    """Назва пулу: з назви запису («Pearl (PRL) · HeroMiners»), за типом адаптера або за доменом сервера."""
    name = str(c.get("name") or "")
    if " · " in name:
        return name.split(" · ", 1)[1]
    pool = c.get("pool") or {}
    if pool.get("type") in pools.POOLS and pool.get("type") != "generic":
        return pools.POOLS[pool["type"]]["name"]
    host = str((pool.get("urls") or [""])[0]).split("://")[-1].split(":")[0]
    return ".".join(host.split(".")[-2:]) if "." in host else tr('Пул')


def _coin_name(c: dict) -> str:
    return str(c.get("name") or c.get("id")).split(" · ", 1)[0]


def pool_items(s: dict, coins: list[dict], ticker: str) -> list[tuple[str, str]]:
    """Пули монети для списку вибору: (id запису, «Пул · комісія N %»), пов'язані з Росією — у кінці."""
    own = [x for x in coins if str(x.get("ticker") or x["id"]) == ticker]
    return [(x["id"], tr('{0} · комісія {1}').format(_pool_name(x), _fees(s, x)['pool_fee']) + (tr(" (пов'язаний з Росією)") if _is_ru(x) else ""))
            for x in sorted(own, key=_is_ru)]


def miner_items(root, coin: dict) -> list[tuple[str, str]]:
    """Майнери монети: (id, «Майнер · комісія N %»), ще не завантажені — з приміткою."""
    return [(mid, tr('{0} · комісія {1}').format(MINERS[mid].name, _pct(f) if (f := dev_fee(mid, coin)) is not None else '?') +
             ("" if updater.miner_exe(root, MINERS[mid]) else tr(' (буде завантажено)')))
            for mid in (coin.get("miners") or {}) if mid in MINERS]


def _coin_label(c: dict) -> str:
    name = str(c.get("name") or c.get("id"))
    if _is_ru(c) and tr('Росі') not in name:
        name += tr(" (пов'язаний з Росією)")
    return name


def build(c) -> dict:
    s, st, now = c.s, c.store.stats, time.time()
    coin = c.coin() or {}
    rcoin = c.running_coin()
    running = c.runner.alive()
    g = c.g
    live = {"coin_id": c.runner.coin_id, "hr": c.hr, "watts": g.draw if g else 0} if running and c.hr > 0 else None
    perf = ec.coin_perf(coin, s, c.hrn, c.gpu_name, live) if coin else None
    fc = ec.forecast(c.market, s, coin, perf) if coin and perf else None
    econ = ec.coin_economics(c.market, s, coin, 1) if coin else None

    # ---- стан угорі ----
    if c.tuner:
        status = {"level": "info", "text": tr('Автопідбір'), "running": True}
    elif running and c.st and c.hr > 0:
        status = {"level": "mining", "text": tr('Майнить'), "running": True}
    elif running:
        status = {"level": "info", "text": tr('Запуск…'), "running": True}
    elif c.fo.want_running:
        status = {"level": "warn", "text": tr('Перезапуск…'), "running": False}
    else:
        status = {"level": "off", "text": tr('Зупинено'), "running": False}
    detail = [str((rcoin or coin).get("name", ""))]
    if running and c.hr:
        detail.append(ec.fmt_hr(c.hr))
    if g:
        detail.append(tr('{0:.0f} Вт · {1} °C').format(g.draw, g.temp))
    status["detail"] = " · ".join(x for x in detail if x)

    # ---- ферма ----
    hive_devs, farm_profit = [], 0.0
    for w in (c.hive or {}).get("workers", []):
        wc = hiveos.coin_for(c.store.coins, w)
        profit = None
        if w["online"] and w["hr"] > 0 and wc:
            profit = ec.day_profit(c.market, s, wc, {"hr": w["hr"], "watts": w["power"]})
            farm_profit += profit or 0
        key = f"{w['farmId']}/{w['id']}"
        state = "offline" if not w["online"] else "warn" if not w["minerOn"] or w["hr"] <= 0 else "mining"
        fs_list = (c.hive.get("fs") or {}).get(str(w["farmId"]), [])
        oc_list = (c.hive.get("oc") or {}).get(str(w["farmId"]), [])
        span, bucket = PERIOD_S[c.period]
        series = c.history.series(f"hive:{key}", span, bucket)
        models = {}
        for gp in w["gpus"]:
            models[gp["name"]] = models.get(gp["name"], 0) + 1
        hive_devs.append({
            "id": f"hive:{key}", "kind": "hive", "name": w["name"], "farm": w["farm"],
            "model": " + ".join(f"{n} × {m.replace('NVIDIA GeForce ', '')}" for m, n in models.items()) or tr('риг HiveOS'),
            "state": state, "state_text": {"offline": tr('Офлайн'), "mining": tr('Майнить')}.get(state, tr('Майнер зупинено') if not w["minerOn"] else tr('Немає хешрейту')),
            "coin": w["coin"] or "—", "pool": ", ".join(w["fsPools"]), "miner": w["miner"], "hr": w["hr"],
            "temp": w["maxTemp"] if w["online"] else None, "watts": w["power"], "profit_day": profit,
            "uptime": _dur(hiveos.miner_uptime_s(w)) if w["minerStart"] else "—", "accepted": w["acc"], "rejected": w["rej"],
            "fs_list": [f"{x['name']}  ({', '.join(x['coins'])})" if x["coins"] else x["name"] for x in fs_list],
            "fs_index": next((i for i, x in enumerate(fs_list) if x["id"] == w["fsId"]), -1),
            "oc_list": [x["name"] for x in oc_list], "oc_index": next((i for i, x in enumerate(oc_list) if x["id"] == w["ocId"]), -1),
            "auto_restart": bool(s.get("HiveAutoRestart")),
            "gpus": [{**gp, "watts": gp["power"]} for gp in w["gpus"]],
            "actions": ([] if not w["online"] else ["start"] if not w["minerOn"] else ["stop", "restart"]),
            "series": {"hr": [(t, h) for t, h, _, _ in series], "temp": [(t, x) for t, _, x, _ in series], "watts": [(t, x) for t, _, _, x in series]},
            "message": c.hive_msg,
        })

    # ---- цей ПК ----
    profit_day = fc["profit"] if fc else None
    span, bucket = PERIOD_S[c.period]
    ser = c.history.series("local", span, bucket)
    hr_tk = str((rcoin or coin).get("ticker") or "")
    ser_hr = c.history.series("local", span, bucket, ticker=hr_tk) if hr_tk else ser
    lim = c.gpu.limits
    p_day = c.profile(rcoin or coin, c.zone_key(str(s.get("Mode")), "day")) if coin else {}
    p_night = c.profile(rcoin or coin, c.zone_key(str(s.get("Mode")), "night")) if coin else {}
    miner = c.runner.miner or MINERS.get(coin_miner_id(s, coin)) if coin else None
    if c.tuner:
        lstate, ltext = "starting", tr('Автопідбір')
    elif running and c.hr > 0:
        lstate, ltext = "mining", tr('Майнить')
    elif running:
        lstate, ltext = "starting", tr('Запуск…')
    else:
        lstate, ltext = "stopped", tr('Зупинено')
    upt = c.st["uptime"] if c.st else 0
    local = {
        "id": "local", "kind": "local", "name": tr('Цей ПК'), "model": c.gpu_name, "state": lstate, "state_text": ltext,
        "coin": (rcoin or coin).get("name", "—").split(" · ")[0], "pool": pools.pool_name(rcoin or coin) if coin else "",
        "server": (c.st or {}).get("pool", "").split("://")[-1], "miner": miner.name if miner else "",
        "hr": c.hr, "temp": g.temp if g else None, "watts": g.draw if g else 0, "profit_day": profit_day if running else None,
        "uptime": _dur(upt) if upt else "—", "accepted": (c.st or {}).get("accepted", 0), "rejected": (c.st or {}).get("rejected", 0),
        "core": g.core if g else 0, "mem": g.mem if g else 0, "eff": tr('{0} на 1 Вт').format(ec.fmt_hr(c.hr / g.draw)) if g and g.draw and c.hr else "—",
        "mode": str(s.get("Mode")), "night_split": c.night_split(), "two_zone": bool(s.get("TwoZone", True)), "zone": c.zone,
        "zone_text": (tr('нічний') if c.zone == "night" else tr('денний')) + tr(' тариф') + (tr(' до {0:02d}:00').format(int(s['NightTo']) if c.zone == 'night' else int(s['NightFrom'])) if c.night_split() else ""),
        "tuning": {"day": p_day, "night": p_night}, "mem_clocks": [m for m in c.gpu.mem_clocks if m],
        "pl_range": (c.pl_range[0], max(c.pl_range[0], int(s.get("MaxPower", 150)))), "core_range": (0, lim["core_max"]),
        "mem_off_range": (c.mem_off_lim["min"], c.mem_off_lim["max"]),
        "limits": tr("ядро {0}–{1} МГц · ліміт {2}–{3} Вт · зсув пам'яті ").format(lim['core_min'], lim['core_max'], c.pl_range[0], c.pl_range[1])
                  + (tr('{0}…+{1} МГц').format(c.mem_off_lim['min'], c.mem_off_lim['max']) if c.mem_off_lim["available"] else tr('недоступний')),
        "tune_note": (c.tuner.status if c.tuner else "") + ("" if not c.gpu.mem_lock_error else tr(" · обмеження пам'яті не підтримується драйвером")),
        "tuning_active": bool(c.tuner),
        "actions": ["stop", "restart"] if running else ["start"],
        "series": {"hr": [(t, h) for t, h, _, _ in ser_hr], "temp": [(t, x) for t, _, x, _ in ser], "watts": [(t, x) for t, _, _, x in ser]},
        "hr_coin": hr_tk,
        "tune_log": (c.tuner.log if c.tuner else getattr(c, "_tune_log", []))[-12:],
    }

    # ---- пул поточної монети ----
    d = c.pool_data or {}
    tk = coin.get("ticker", "")
    bal = d.get("balance")
    price_uah = econ["price_uah"] if econ else None
    if bal:
        eta = ec.payout_eta(c.market, s, coin, d, c.hr, running and c.runner.coin_id == coin.get("id"))
        th = eta["threshold"]
        if eta["days"] is None:
            eta_text = eta["text"]
        elif eta["days"] == 0:
            eta_text = eta["text"]
        else:
            when = datetime.now() + timedelta(days=eta["days"])
            eta_text = f"≈ {ec.fmt_duration_days(eta['days'])} ({when:%d.%m ~%H:%M}) · {eta['workers']} {ec.worker_word(eta['workers'])}, {ec.fmt_hr(eta['hr'])}"
        sw = ec.can_switch(coin, d)
        payout = {"pct": eta["pct"], "text": eta_text, "threshold": f"{_n(th, 4).rstrip('0').rstrip(',')} {tk}", "switch_ok": sw["ok"], "switch_text": sw["text"]}
        paid = d.get("paid") or {}
        ptxt = f"{_n(float(paid.get('total') or 0))} {tk}"
        if price_uah and paid.get("total"):
            ptxt += f" ≈ {_n(float(paid['total']) * price_uah, 2)} ₴"
        if paid.get("last"):
            ptxt += tr(' · остання {0} {1}, {2:%d.%m.%Y %H:%M}').format(_n(paid['last']['amount']), tk, from_unix_ms(paid['last']['time']))
        elif not paid.get("total"):
            ptxt = tr('0 {0} · виплат ще не було').format(tk)
        balance = {"available": True, "title": tr('Пул {0} · {1}').format(pools.pool_name(coin), tk),
                   "total": f"{_n(float(bal['total']))} {tk}", "uah": f"≈ {_n(float(bal['total']) * price_uah, 2)} ₴" if price_uah else "",
                   "confirmed": _n(float(bal["confirmed"])), "pending": _n(float(bal["unconfirmed"])), "paid": ptxt}
    else:
        payout = {"pct": 0, "text": "—", "threshold": "—", "switch_ok": None, "switch_text": "—"}
        msg = (tr('Завантажую дані пулу…') if "pool" in c.jobs or not c.pool_time else tr('Пул не надає статистики — баланс дивись на сайті пулу.'))
        if c.pool_error:
            msg = tr('Пул не відповідає: {0}. Повтор за кілька хвилин.').format(c.pool_error)
        balance = {"available": False, "title": tr('Пул {0} · {1}').format(pools.pool_name(coin), tk) if coin else tr('Пул'), "message": msg,
                   "total": "—", "uah": "", "confirmed": "—", "pending": "—", "paid": "—"}
    balance["price"] = (f"{tk} = ${_n(econ['price_usd'])} · {_n(econ['price_uah'], 2)} ₴ ({econ['price_source']})" if econ
                        else (tr('завантажую ринкові дані…') if not c.market else tr('немає ринкових даних для {0}').format(tk)))
    balance["updated"] = (tr('{0:%H:%M:%S} (кожні 5 хв)').format(c.pool_time) if c.pool_time else "—")
    balance["page"] = pools.page_url(coin) if coin and coin.get("wallet") else None

    forecast = None
    if fc:
        forecast = {"zones": [{**z, "now": z["night"] == fc["now_tariff"]["night"]} for z in fc["zones"]],
                    "income": fc["income"], "cost": fc["cost"], "profit": fc["profit"], "src": fc["src"],
                    "now_text": tr('{0} тариф {1} ₴/кВт·год → {2} за годину').format(fc['now_tariff']['name'], _n(fc['now_tariff']['price'], 2), ec.fmt_uah(fc['now_profit_hour']))}

    # ---- 7 днів ----
    days_hist = {d_: (i, cst) for d_, i, cst in c.history.days(7)}
    days = []
    for k in range(6, -1, -1):
        dd = (date.today() - timedelta(days=k)).isoformat()
        inc, cst = days_hist.get(dd, (0.0, 0.0))
        if k == 0:
            a = c.day_acc.get("local") or {}
            inc, cst = inc + a.get("income", 0), cst + a.get("cost", 0)
        lab = f"{dd[8:10]}.{dd[5:7]}"
        days.append((lab, inc - cst, tr('{0}: дохід {1} ₴ − світло {2} ₴ = {3}').format(lab, _n(inc, 2), _n(cst, 2), ec.fmt_uah(inc - cst))))
    if all(v == 0 for _, v, _ in days):
        days = []

    # ---- рейтинг і «що майнити» ----
    rank = ec.ranking(c.store.coins, c.market, s, c.hrn, c.gpu_name, live)
    best = next((r for r in rank if r["profit"] is not None), None)
    cur_row = next((r for r in rank if r["coin"].get("id") == coin.get("id")), None)
    best_info = {"coin": best["coin"]["name"] if best else "—", "profit": best["profit"] if best else None,
                 "current": bool(best and best["coin"]["id"] == coin.get("id")), "mine": cur_row["my_profit"] if cur_row else None}
    ranking = [{"id": r["coin"]["id"], "name": _coin_label(r["coin"]), "profit": r["profit"],
                "mine": ec.fmt_uah(r["my_profit"]) if r["my_profit"] is not None else "",
                "bench": tr('{0} · {1:.0f} Вт').format(ec.fmt_hr(r['bench']['hr']), r['bench']['watts']) if r["bench"]["hr"] else "—",
                "src": r["bench"]["src"], "has_wallet": bool(r["coin"].get("wallet")), "current": r["coin"].get("id") == coin.get("id"),
                **_fees(s, r["coin"])}
               for r in rank]
    pc = c.coin(c.preview_coin) if c.preview_coin else coin
    pc = pc or coin
    book = c.store.wallet_book(str(pc.get("ticker"))) if pc else {"list": [], "active": ""}
    prices = [("coingecko", tr('CoinGecko (середня по біржах)'))] if pc.get("coingecko") else []
    prices += [(t["id"], f"{t['name']} ({t['pair']})") for t in ec.coin_tickers(c.market, pc)[:12]]
    prices += [("wtm", "WhatToMine")]
    non_ru = [x for x in c.store.coins if not _is_ru(x)]
    ru = [x for x in c.store.coins if x not in non_ru]
    # Монета і пул — окремі списки: монети (за тикером) і пули вибраної монети з комісією
    tickers: dict[str, tuple[str, str]] = {}            # тикер → (назва монети, пул за замовчуванням)
    for x in non_ru + ru:
        xt = str(x.get("ticker") or x["id"])
        if xt not in tickers or x.get("id") == coin.get("id"):
            tickers[xt] = (_coin_name(x), x["id"])
    pc_tk = str(pc.get("ticker") or pc.get("id"))
    form = {"coins": [(t_, n) for t_, (n, _) in tickers.items()], "coin_default": {t_: d for t_, (_, d) in tickers.items()},
            "pools": pool_items(s, c.store.coins, pc_tk),
            "coin": pc.get("id"), "ticker": str(pc.get("ticker") or ""),
            "miners": miner_items(c.root, pc),
            "miner": coin_miner_id(s, pc) if pc else None,
            "wallets": [(w["address"], f"{w.get('label', '')} · {_addr(w['address'])}") for w in book["list"]],
            "wallet": book.get("active"), "worker": str(pc.get("worker") or ""),
            "prices": prices, "price": ec.price_source(s, pc) if pc else None,
            "servers": _servers(c, pc), "server_auto": bool(s.get("ServerAuto", True)),
            "ping_time": f"{c.ping_time:%H:%M}" if c.ping_time else None, "is_current": pc.get("id") == coin.get("id"),
            "note": (tr("Пули, пов'язані з Росією, позначені й стоять у кінці списку. ") if ru else "") +
                    (tr('Для цієї монети ще немає гаманця — додай його кнопкою «+ Додати».') if pc and not book["list"] else "")}

    # ---- бухгалтерія ----
    names_local = c.local_names()
    owners_rows = []
    for o, x in sorted(ledger.owner_totals(s, st, names_local).items(), key=lambda kv: (kv[0] != ledger.OWNER_ME, kv[0])):
        for t_, v in sorted(x.items()):
            owners_rows.append([_owner(o), t_, _n(v["Mined"], 6), _n(v["Paid"], 6), _n(v["Mined"] - v["Paid"], 6)])
    workers, wnames, offs, totals, recon, warn = [], [], [], [], [], []
    hive_src = {}
    for w in (c.hive or {}).get("workers", []):
        wc = hiveos.coin_for(c.store.coins, w)
        if wc and w["online"] and w["hr"] > 0:
            hive_src[(ledger.ledger_key(wc), hiveos.pool_worker_name(s, w))] = (w["hr"], hiveos.miner_uptime_s(w) >= 21600)
    for key in sorted(st["ledger"]):
        L = st["ledger"][key]
        r = ledger.account_coins(L)
        acc = f"{L['Ticker']} · {L['Pool']}" + ("" if L.get("Exact") else " (≈)")
        for n in sorted(r["Names"], key=lambda x: -r["Coins"][x]):
            pool_hr = float(L["Hr"].get(n) or 0)
            src_txt, off = "", False
            if rcoin and ledger.ledger_key(rcoin) == key and str(rcoin.get("worker")) == n and c.hr15 > 0:
                src_txt = tr('ПК {0}').format(ec.fmt_hr(c.hr15))
                long_ = bool(c.st and c.st["uptime"] >= 21600)
                off = long_ and pool_hr > 0 and abs(pool_hr - c.hr15) / c.hr15 > 0.25
            elif (key, n) in hive_src:
                h, long_ = hive_src[(key, n)]
                src_txt = f"HiveOS {ec.fmt_hr(h)}"
                off = long_ and pool_hr > 0 and abs(pool_hr - h) / h > 0.25
            workers.append([n + (tr(' (цей ПК)') if n in names_local else ""), _owner(ledger.worker_owner(s, names_local, n)), acc,
                            f"{_n(r['Share'][n] * 100, 1)} %", _n(r["Coins"][n], 6),
                            ec.fmt_hr(pool_hr) if L["Online"].get(n) else ("offline" if n in L["Raw"] else "—"), src_txt])
            wnames.append(n)
            offs.append(off)
        if L.get("Time"):
            ok = ledger.reconciled(L, r)
            line = tr('{0}: розподілено {1} {2}').format(acc, _n(r['Distributed'], 6), '= нараховано пулом ✓' if ok else '≠ нараховано пулом ' + _n(float(L['Earned']), 6))
        else:
            line = tr('{0}: пул ще не опитано').format(acc)
        cp = parse(L["Cp"]["Time"])
        line += tr(' · контрольна точка {0:%d.%m %H:%M}').format(cp) if cp else ""
        if float(L.get("Unconfirmed") or 0) > 0:
            line += tr(' · очікує дозрівання {0}').format(_n(float(L['Unconfirmed']), 6))
        if r["Undistributed"] > 0:
            line += tr(' · ще не розподілено {0} (немає роботи)').format(_n(r['Undistributed'], 6))
        recon.append(line)
        warn += [f"{acc}: {w}" for w in r["Warn"]]
    if c.ledger_error:
        warn.append(c.ledger_error)

    # ---- світло ----
    loc_rows = []
    actual = {}
    for key, L in st["ledger"].items():
        r = ledger.account_coins(L)
        for n in r["Names"]:
            if n in names_local:
                actual[L["Ticker"]] = actual.get(L["Ticker"], 0.0) + r["Coins"][n]
    for t_, x in sorted((st.get("local") or {}).items()):
        pr = next((ec.coin_price(c.market, s, cc) for cc in c.store.coins if cc.get("ticker") == t_), None)
        coins_ = actual.get(t_, float(x.get("Coins") or 0))
        net = coins_ * pr["uah"] - float(x.get("Cost") or 0) if pr else None
        loc_rows.append([t_, _dur(float(x.get("Seconds") or 0)), f"{_n(float(x.get('KWhMine') or 0), 3)} / {_n(float(x.get('KWhGpu') or 0), 3)}",
                         _n(float(x.get("Cost") or 0), 2), ec.fmt_uah(net) if net is not None else tr('н/д')])
    farm_rows = [[k, _dur(float(x.get("Seconds") or 0)), _n(float(x.get("KWh") or 0), 2), _n(float(x.get("Cost") or 0), 2)]
                 for k, x in sorted((st.get("farm") or {}).items())]

    # ---- підсумок для «Огляду»: ціна, скільки добуто, гроші за періоди ----
    summary = {"ticker": tk, "price": "—", "price_sub": balance["price"] if not econ else tr('за 1 {0} · ${1} · {2}').format(tk, _n(econ['price_usd']), econ['price_source']),
               "mined": "—", "mined_sub": "", "light": "—", "light_sub": "", "periods": []}
    if econ:
        summary["price"] = f"{_n(econ['price_uah'], 2)} ₴"
    if bal:
        paid_t = float((d.get("paid") or {}).get("total") or 0)
        all_t = paid_t + float(bal["total"])
        summary["mined"] = f"{_n(all_t)} {tk}"
        summary["mined_sub"] = (f"≈ {_n(all_t * price_uah, 2)} ₴ · " if price_uah else "") + tr('виплачено {0} + на пулі {1}').format(_n(paid_t), _n(float(bal['total'])))
        if actual.get(tk):
            summary["mined_sub"] += tr('\nз них цей ПК ≈ {0} {1}').format(_n(actual[tk]), tk)
    elif actual.get(tk) or (st.get("local") or {}).get(tk):
        mine_c = actual.get(tk, float(((st.get("local") or {}).get(tk) or {}).get("Coins") or 0))
        summary["mined"] = f"{_n(mine_c)} {tk}"
        summary["mined_sub"] = tr('цей ПК (пул не надає баланс)') + (f" · ≈ {_n(mine_c * price_uah, 2)} ₴" if price_uah else "")
    a = c.day_acc.get("local") or {}
    t_inc = days_hist.get(date.today().isoformat(), (0.0, 0.0))[0] + a.get("income", 0)
    t_cst = days_hist.get(date.today().isoformat(), (0.0, 0.0))[1] + a.get("cost", 0)
    w_inc = sum(i for i, _ in days_hist.values()) + a.get("income", 0)
    w_cst = sum(x for _, x in days_hist.values()) + a.get("cost", 0)
    all_inc = all_cst = all_kwh = all_sec = 0.0
    for t_, x in (st.get("local") or {}).items():
        # Монети — справжні (за пулом, якщо є), ціна — середня на момент майнінгу (Income / IncomeCoins);
        # якщо облік ціни ще не вели — поточна
        pr = next((ec.coin_price(c.market, s, cc) for cc in c.store.coins if cc.get("ticker") == t_), None)
        ic = float(x.get("IncomeCoins") or 0)
        avg = float(x.get("Income") or 0) / ic if ic > 0 else (pr["uah"] if pr else 0.0)
        all_inc += actual.get(t_, float(x.get("Coins") or 0)) * avg
        all_cst += float(x.get("Cost") or 0)
        all_kwh += float(x.get("KWhMine") or 0)
        all_sec += float(x.get("Seconds") or 0)
    for name, inc, cst in ((tr('Сьогодні'), t_inc, t_cst), (tr('7 днів'), w_inc, w_cst), (tr('Весь час'), all_inc, all_cst)):
        summary["periods"].append([name, f"{_n(inc, 2)} ₴", f"{_n(cst, 2)} ₴", ec.fmt_uah(inc - cst), False])
    if fc:   # прогноз за поточним хешрейтом (або еталоном, якщо майнер стоїть), ціною і тарифом день/ніч
        for name, k in ((tr('На добу'), 1), (tr('На 7 днів'), 7), (tr('На 30 днів'), 30)):
            summary["periods"].append([name, f"{_n(fc['income'] * k, 2)} ₴", f"{_n(fc['cost'] * k, 2)} ₴", ec.fmt_uah(fc["profit"] * k), True])

    # Уся адреса на пулі (усі воркери на цьому гаманці, разом з цим ПК): лише монети і ₴ — світло інших ригів невідоме
    summary["pool_title"], summary["pool_sub"], summary["pool_periods"] = "", "", []
    P = (st.get("pools") or {}).get(ledger.ledger_key(coin)) if coin else None
    if bal:
        total_now = float((d.get("paid") or {}).get("total") or 0) + float(bal["total"])
        pdays = (P or {}).get("Days") or {}
        today_s = date.today().isoformat()
        week = [k for k in sorted(pdays) if k >= (date.today() - timedelta(days=6)).isoformat()]
        rows_p = []
        if today_s in pdays:
            since = parse((P or {}).get("Since"))
            # Облік почався сьогодні посеред дня — чесно підписуємо, з котрої години
            first_day = since is not None and since.date() == date.today() and min(pdays) == today_s
            rows_p.append((tr('Сьогодні (з {0:%H:%M})').format(since) if first_day else tr('Сьогодні'), total_now - pdays[today_s]))
        if week and week[0] != today_s:
            rows_p.append((tr('7 днів') if week[0] == (date.today() - timedelta(days=6)).isoformat()
                           else tr('з {0}.{1}').format(week[0][8:10], week[0][5:7]), total_now - pdays[week[0]]))
        rows_p.append((tr('Весь час'), total_now))
        for name, v in rows_p:
            summary["pool_periods"].append([name, f"{_n(v)} {tk}", f"{_n(v * price_uah, 2)} ₴" if price_uah else "—", False])
        hr_all = sum(float(w.get("hr24h") or w.get("hr3h") or 0) for w in d.get("workers") or [])
        e_all = ec.coin_economics(c.market, s, coin, hr_all) if hr_all else None
        if e_all:
            for name, k in ((tr('На добу'), 1), (tr('На 7 днів'), 7), (tr('На 30 днів'), 30)):
                cpd = e_all["coins_per_day"] * k
                summary["pool_periods"].append([name, f"{_n(cpd)} {tk}", f"{_n(cpd * e_all['price_uah'], 2)} ₴", True])
        workers_n = len(d.get("workers") or [])
        summary["pool_title"] = tr('Уся адреса на пулі {0}').format(pools.pool_name(coin))
        summary["pool_sub"] = f"{workers_n} {ec.worker_word(workers_n)}" + (tr(' · {0} за добу').format(ec.fmt_hr(hr_all)) if hr_all else "")
    # Усі монети: скільки добув цей ПК і скільки лежить на пулах — і після перемикання на іншу монету
    rows_c = []
    pools_by_tk: dict[str, list[dict]] = {}
    for P in (st.get("pools") or {}).values():
        pools_by_tk.setdefault(str(P.get("Ticker")), []).append(P)
    for t_ in sorted(set(st.get("local") or {}) | set(pools_by_tk), key=lambda x: (x != tk, x)):
        x = (st.get("local") or {}).get(t_) or {}
        cc = next((y for y in c.store.coins if y.get("ticker") == t_), None)
        pr = ec.coin_price(c.market, s, cc) if cc else None
        mine_c = actual.get(t_, float(x.get("Coins") or 0))
        on_pool = sum(float(P.get("Balance") or 0) for P in pools_by_tk.get(t_, []))
        if t_ == tk and bal:
            on_pool = float(bal["total"])
        if t_ == tk:
            note, level = (tr('майниш зараз') if running else tr('вибрана')), "good"
        elif on_pool > 0:
            th = max((float(P.get("Threshold") or 0) for P in pools_by_tk.get(t_, [])), default=0)
            note = tr('лишилось на пулі{0}').format(f' · {on_pool / th * 100:.0f} % до виплати' if th else '')
            level = "warn"
        else:
            note, level = "", ""
        rows_c.append({"ticker": t_, "mined": f"{_n(mine_c)} {t_}" if mine_c else "—",
                       "pool": f"{_n(on_pool)} {t_}" if on_pool else "—",
                       "uah": ec.fmt_uah(on_pool * pr["uah"], False) if pr and on_pool else "—", "note": note, "level": level})
    summary["coins"] = rows_c
    summary["now_text"] = forecast["now_text"] if forecast else ""
    if all_sec:
        summary["light"] = f"{_n(all_cst, 2)} ₴"
        summary["light_sub"] = tr('{0} кВт·год за {1} майнінгу').format(_n(all_kwh, 2), _dur(all_sec)) + (
            tr('\nзараз {0}').format(forecast['now_text']) if forecast else "")

    # ---- майнери ----
    mins = []
    for m in MINERS.values():
        cur = updater.current_version(c.root, m.id)
        inst = cur or (tr('вручну') if updater.miner_exe(c.root, m) else "—")
        rel = c.releases.get(m.id) or {}
        latest = rel.get("Version") or (tr('перевіряю…') if "releases" in c.jobs else "—")
        state = (tr('не встановлено') if inst == "—" else tr('є оновлення') if updater.update_available(c.root, m, c.releases)
                 else tr('актуальна') if rel.get("Version") else tr('встановлено'))
        if "install" in c.jobs and getattr(c, "_install_id", "") == m.id:
            state = tr('завантажую…')
        mins.append({"id": m.id, "name": m.name, "installed": inst, "latest": latest, "state": state})

    # ---- журнал і повідомлення ----
    journal = [(datetime.fromtimestamp(t).strftime("%d.%m %H:%M"), lv, txt) for t, lv, txt in reversed(c.events.history[-200:])]
    notices = c.events.sorted_active()
    if c.market_error and not c.market:
        notices = notices + [ev.Notice("market", ev.INFO, tr('Ринкові дані ще не завантажились'),
                                       tr("{0}. Прогноз і рейтинг з'являться, щойно WhatToMine/CoinGecko відповідять.").format(c.market_error), None, None)]

    total_profit = (profit_day or 0) if running else 0.0
    return {
        "test": c.test, "status": status, "profit_day": total_profit if running else None,
        "income_day": fc["income"] if fc and running else 0.0, "cost_day": fc["cost"] if fc and running else 0.0,
        "coins_day": tr('≈ {0} {1} на добу').format(_n(fc['coins_per_day'], 3), tk) if fc and running else tr('майнер зупинено'),
        "farm_profit_day": farm_profit if hive_devs else None,
        "payout": payout, "balance": balance, "forecast": forecast, "days": days, "summary": summary,
        "devices": [local] + hive_devs, "notices": notices, "best": best_info,
        "ledger": {"owners": owners_rows, "workers": workers, "worker_names": wnames, "off": offs, "recon": recon, "warn": warn},
        "energy": {"local": loc_rows, "farm": farm_rows},
        "coins": {"ranking": ranking, "form": form},
        "miners": mins, "miners_note": c.install_msg or (tr('Не вдалося перевірити оновлення: {0}').format(c.releases_error) if c.releases_error else ""),
        "settings": {**{k: s.get(k) for k in ("TariffDay", "TariffNight", "TwoZone", "NightFrom", "NightTo", "MaxTemp", "MaxPower",
                                               "TuneCoreMax", "UiTheme", "UiFont", "Autostart", "MinimizeToTray")}, "UiLang": i18n.LANG,
                     "HiveOsToken": bool(s.get("HiveOsToken")), "HashrateNoKey": bool(s.get("HashrateNoKey")),
                     "PlMin": c.pl_range[0], "PlMax": c.pl_range[1], "TempMaxDriver": c.gpu.limits["temp_max"] + 5,
                     "CoreMaxDriver": c.gpu.limits["core_max"],
                     "DefenderAction": c.events.active["defender"].action_id if "defender" in c.events.active else None,
                     "HiveStatus": (f"HiveOS: {c.hive_error}" if c.hive_error else
                                    tr('HiveOS: підключено, ригів: {0}').format(len(c.hive['workers'])) if c.hive else
                                    tr('HiveOS: підключаюсь…') if s.get("HiveOsToken") else "")},
        "journal": journal, "miner_log": c.runner.log_tail(80),
    }
