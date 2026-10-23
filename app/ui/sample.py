"""Зразкові дані для макета інтерфейсу (--test). Та сама структура знімка, яку потім будує app/controller.py:
сторінки лише показують знімок і надсилають дії, тож макет і справжня панель виглядають однаково."""
from __future__ import annotations

import math
import random
import time
from datetime import date, timedelta

from ..core.events import ERROR, INFO, WARN, Notice


def _series(hours: float, base: float, noise: float, step_s: int = 600, dip_at: float | None = None):
    rnd = random.Random(int(base) % 1000 + int(hours))
    now = time.time()
    pts = []
    n = int(hours * 3600 / step_s)
    for i in range(n + 1):
        ts = now - (n - i) * step_s
        v = base * (1 + noise * math.sin(i / 7) + noise * (rnd.random() - 0.5))
        if dip_at is not None and abs(i / n - dip_at) < 0.015:
            v = 0
        pts.append((ts, max(0.0, v)))
    return pts


def wizard_data() -> dict:
    """Дані майстра першого запуску (як Controller.wizard_data)."""
    return {"gpu": "NVIDIA GeForce RTX 3060", "two": True, "day": 4.32, "night": 2.16, "night_hours": "23:00–07:00",
            "coins": [("PRL", "Pearl (PRL) — ≈ +55,67 ₴/добу"), ("XEL", "Xelis (XEL) — ≈ +3,05 ₴/добу"), ("ZANO", "Zano (ZANO) — ≈ -0,11 ₴/добу")],
            "ticker": "PRL", "coin_default": {"PRL": "pearl-herominers", "XEL": "xelis-herominers", "ZANO": "zano-herominers"},
            "pools": {"PRL": [("pearl-herominers", "HeroMiners · комісія 0 %"), ("pearl-kryptex", "Kryptex · комісія 3 % (пов'язаний з Росією)")],
                      "XEL": [("xelis-herominers", "HeroMiners · комісія 0,9 %")], "ZANO": [("zano-herominers", "HeroMiners · комісія 0,9 %")]},
            "miners": {"pearl-herominers": [("srbminer", "SRBMiner-MULTI · комісія 2 %"), ("bzminer", "BzMiner · комісія 2 % (буде завантажено)")],
                       "pearl-kryptex": [("srbminer", "SRBMiner-MULTI · комісія 2 %")],
                       "xelis-herominers": [("rigel", "Rigel · комісія 2 % (буде завантажено)")],
                       "zano-herominers": [("rigel", "Rigel · комісія 1 % (буде завантажено)")]},
            "miner_default": {"pearl-herominers": "srbminer", "pearl-kryptex": "srbminer", "xelis-herominers": "rigel", "zano-herominers": "rigel"},
            "wallets": {}, "worker": "MY-PC", "coins_note": ""}


def snapshot(expert: bool = False) -> dict:
    today = date.today()
    days = []
    rnd = random.Random(3)
    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        income = 62 + rnd.random() * 14 if i else 40.1
        cost = 8.2 + rnd.random() * 1.2 if i else 5.3
        days.append((d, income, cost))
    local = {
        "id": "local", "kind": "local", "name": "Цей ПК", "model": "RTX 3060 12 ГБ", "state": "mining", "state_text": "Майнить",
        "coin": "Pearl (PRL)", "pool": "HeroMiners", "server": "fi.pearl.herominers.com:1200", "miner": "SRBMiner-MULTI 3.7.8",
        "hr": 45.11e12, "hr15": 45.76e12, "temp": 60, "fan": 32, "watts": 101, "limit": 150, "core": 1695, "mem": 810,
        "profit_day": 59.54, "uptime": "2 год 14 хв", "accepted": 812, "rejected": 3, "eff": "446,6 GH/s на 1 Вт",
        "hr_coin": "PRL", "mode": "custom", "night_split": True, "two_zone": True, "zone": "day", "zone_text": "денний тариф до 23:00",
        "tuning": {"day": {"PL": 150, "Core": 1700, "Mem": 810, "MemOff": 0}, "night": {"PL": 120, "Core": 1500, "Mem": 0, "MemOff": 0}},
        "limits": "ядро 405–2130 МГц · ліміт 100–170 Вт · зсув пам'яті −500…+1000 МГц",
        "mem_clocks": [7501, 7301, 5001, 810, 405], "pl_range": (100, 150), "core_range": (0, 2130), "mem_off_range": (-500, 1000),
        "tuning_active": False, "tune_note": "", "actions": ["stop", "restart"],
        "series": {"hr": _series(24, 45e12, 0.05, dip_at=0.62), "temp": _series(24, 60, 0.03), "watts": _series(24, 101, 0.03)},
        "tune_log": ["21:59 Автопідбір: 1600 МГц → 44,8 TH/s, 97 Вт", "22:01 Автопідбір: 1700 МГц → 45,9 TH/s, 101 Вт — найкраще"],
    }
    rig1 = {
        "id": "hive:1/101", "kind": "hive", "name": "rig1", "farm": "Дім", "model": "6 × RTX 3070", "state": "mining",
        "state_text": "Майнить", "coin": "Pearl (PRL)", "pool": "HeroMiners", "miner": "srbminer", "hr": 312e12, "temp": 66,
        "watts": 690, "profit_day": 366.10, "uptime": "5 д 3 год", "accepted": 15812, "rejected": 21,
        "fs": "PRL HeroMiners", "fs_list": ["PRL HeroMiners  (PRL)", "XEL HeroMiners  (XEL)"], "fs_index": 0,
        "oc": "3070 pearl eff", "oc_list": ["3070 pearl eff", "3070 xelis"], "oc_index": 0, "auto_restart": False,
        "gpus": [{"idx": i, "name": "NVIDIA GeForce RTX 3070", "temp": 60 + i, "fan": 55, "watts": 115, "core": 1500, "mem": 7000, "hr": 52e12} for i in range(6)],
        "actions": ["stop", "restart"], "series": {"hr": _series(24, 312e12, 0.02), "temp": _series(24, 64, 0.02), "watts": _series(24, 690, 0.02)},
    }
    rig2 = {**rig1, "id": "hive:1/102", "name": "rig2", "model": "4 × RTX 3060 Ti", "state": "warn", "state_text": "Майнер зупинено",
            "coin": "Xelis (XEL)", "hr": 0, "temp": 41, "watts": 120, "profit_day": None, "fs": "XEL HeroMiners", "fs_index": 1,
            "accepted": 0, "rejected": 0, "actions": ["start"], "gpus": [], "series": {"hr": [], "temp": [], "watts": []}}
    rig3 = {**rig1, "id": "hive:2/201", "name": "rig3", "farm": "Гараж", "model": "2 × RTX 3080", "state": "offline", "state_text": "Офлайн",
            "coin": "—", "hr": 0, "temp": None, "watts": 0, "profit_day": None, "fs": "", "actions": [], "gpus": [],
            "series": {"hr": [], "temp": [], "watts": []}}
    notices = [
        Notice("hive:1/102", WARN, "rig2: майнер зупинено", "Риг онлайн, але майнер на ньому не працює, тож риг не заробляє. Запусти майнер, якщо зупинив його випадково.",
               "Запустити", "device:start:hive:1/102"),
        Notice("hive:2/201", ERROR, "rig3 не на зв'язку", "Риг у гаражі не відповідає HiveOS уже 40 хв. Перевір живлення та інтернет рига.",
               "Відкрити", "open:device:hive:2/201"),
        Notice("pool:de", INFO, "Сервер пулу de не відповідав", "Панель сама перейшла на резервний сервер fi.pearl.herominers.com. Нічого робити не треба.",
               None, None),
    ]
    ledger_owners = [["Я", "PRL", "1,528503", "0,000000", "1,528503"], ["Петро", "PRL", "0,628333", "0,500000", "0,128333"]]
    ledger_workers = [["rtx3060 (цей ПК)", "Я", "PRL · HeroMiners", "62,7 %", "1,528503", "39,53 TH/s", "ПК 45,11 TH/s"],
                      ["rig1", "Я", "PRL · HeroMiners", "27,1 %", "0,661220", "308,40 TH/s", "HiveOS 312,00 TH/s"],
                      ["friend", "Петро", "PRL · HeroMiners", "10,2 %", "0,248333", "offline", ""]]
    best = {"coin": "Pearl (PRL)", "profit": 67.05, "current": True, "mine": 59.54}
    ranking = [{"id": i, "name": n, "profit": p, "mine": m, "bench": b, "src": src, "has_wallet": hw, "current": i == "pearl-herominers",
                "pool_fee": pf, "miner_fee": mf, "miner_name": mn}
               for i, n, p, m, b, src, hw, pf, mf, mn in (
        ("pearl-herominers", "Pearl (PRL) · HeroMiners", 67.05, "+59,54 ₴", "43,75 TH/s · 71 Вт", "hashrate.no", True, "0 %", "2 %", "SRBMiner-MULTI"),
        ("pearl-kryptex", "Pearl (PRL) · Kryptex (пов'язаний з Росією)", 66.20, "", "43,75 TH/s · 71 Вт", "hashrate.no", True, "3 %", "?", "OneZeroMiner"),
        ("xelis-herominers", "Xelis (XEL) · HeroMiners", 31.40, "", "3,10 kH/s · 98 Вт", "hashrate.no", True, "0,9 %", "2 %", "Rigel"),
        ("zano-herominers", "Zano (ZANO) · HeroMiners", 18.70, "", "1,85 MH/s · 105 Вт", "оцінка", False, "0,9 %", "1 %", "Rigel"),
        ("ravencoin-herominers", "Ravencoin (RVN) · HeroMiners", -3.20, "", "28,1 MH/s · 140 Вт", "hashrate.no", False, "0,9 %", "0,85 %", "SRBMiner-MULTI"))]
    form = {"coins": [("PRL", "Pearl (PRL)"), ("XEL", "Xelis (XEL)"), ("ZANO", "Zano (ZANO)"), ("RVN", "Ravencoin (RVN)")],
            "coin_default": {"PRL": "pearl-herominers", "XEL": "xelis-herominers", "ZANO": "zano-herominers", "RVN": "ravencoin-herominers"},
            "pools": [("pearl-herominers", "HeroMiners · комісія 0 %"), ("pearl-kryptex", "Kryptex · комісія 3 % (пов'язаний з Росією)")],
            "coin": "pearl-herominers", "ticker": "PRL",
            "miners": [("srbminer", "SRBMiner-MULTI · комісія 2 %"), ("onezerominer", "OneZeroMiner · комісія ? (буде завантажено)"),
                       ("bzminer", "BzMiner · комісія 2 %")], "miner": "srbminer",
            "wallets": [("prl1pm3hn", "Імпортовано · prl1pm3hn…fvgwle")], "wallet": "prl1pm3hn", "worker": "rtx3060",
            "prices": [("coingecko", "CoinGecko (середня по біржах)"), ("ourbit", "Ourbit (PRL/USDT)"), ("wtm", "WhatToMine")], "price": "coingecko",
            "servers": [{"url": u, "current": u.startswith("fi"), "level": lv, "state": stt, "now": n, "median": md}
                        for u, lv, stt, n, md in (("de.pearl.herominers.com:1200", "bad", "не відповідає", "—", "31 мс"),
                                                  ("fi.pearl.herominers.com:1200", "good", "працює", "46 мс", "45 мс"),
                                                  ("tr.pearl.herominers.com:1200", "good", "працює", "62 мс", "61 мс"),
                                                  ("ca.pearl.herominers.com:1200", "good", "працює", "128 мс", "127 мс"),
                                                  ("us.pearl.herominers.com:1200", "good", "працює", "131 мс", "133 мс"))],
            "server_auto": True, "ping_time": "22:40", "is_current": True, "note": "Пули, пов'язані з Росією, позначені й стоять у кінці списку."}
    return {
        "test": True,
        "status": {"level": "mining", "text": "Майнить", "detail": "Pearl · HeroMiners · 45,11 TH/s · 101 Вт", "running": True},
        "profit_day": 59.54, "income_day": 68.23, "cost_day": 8.68, "coins_day": "≈ 0,672 PRL на добу",
        "farm_profit_day": 366.10,
        "summary": {"ticker": "PRL", "price": "5,08 ₴", "price_sub": "за 1 PRL · $0,1223 · CoinGecko",
                    "mined": "18,4127 PRL", "mined_sub": "≈ 93,54 ₴ · виплачено 17,0000 + на пулі 1,4127\nз них цей ПК ≈ 16,0311 PRL",
                    "light": "38,40 ₴", "light_sub": "11,62 кВт·год за 4 д 6 год майнінгу\nзараз денний тариф 4,32 ₴/кВт·год → +2,48 ₴ за годину",
                    "periods": [["Сьогодні", "40,10 ₴", "5,30 ₴", "+34,80 ₴", False], ["7 днів", "468,22 ₴", "62,15 ₴", "+406,07 ₴", False],
                                ["Весь час", "981,44 ₴", "138,40 ₴", "+843,04 ₴", False],
                                ["На добу", "68,23 ₴", "8,68 ₴", "+59,55 ₴", True], ["На 7 днів", "477,61 ₴", "60,76 ₴", "+416,85 ₴", True], ["На 30 днів", "2 046,90 ₴", "260,40 ₴", "+1 786,50 ₴", True]],
                    "now_text": "денний тариф 4,32 ₴/кВт·год → +2,48 ₴ за годину", "pool_title": "Уся адреса на пулі HeroMiners", "pool_sub": "3 воркери · 360,40 TH/s за добу",
                    "pool_periods": [["Сьогодні", "1,2140 PRL", "61,67 ₴", False], ["7 днів", "16,0300 PRL", "814,32 ₴", False],
                                     ["Весь час", "18,4127 PRL", "935,37 ₴", False], ["На добу", "5,3700 PRL", "272,80 ₴", True], ["На 7 днів", "37,5900 PRL", "1 909,57 ₴", True],
                                     ["На 30 днів", "161,1000 PRL", "8 183,88 ₴", True]],
                    "coins": [{"ticker": "PRL", "mined": "16,0311 PRL", "pool": "0,7377 PRL", "uah": "3,75 ₴", "note": "майниш зараз", "level": "good"},
                              {"ticker": "XEL", "mined": "0,8214 XEL", "pool": "0,3120 XEL", "uah": "41,20 ₴",
                               "note": "лишилось на пулі · 62 % до виплати", "level": "warn"},
                              {"ticker": "QTC", "mined": "2,1000 QTC", "pool": "—", "uah": "—", "note": "", "level": ""}]},
        "payout": {"pct": 74.0, "text": "≈ 9 год 21 хв (22.10 ~07:20)", "threshold": "1 PRL", "switch_ok": False,
                   "switch_text": "ні — до виплати бракує 0,2623 PRL"},
        "balance": {"available": True, "title": "Пул HeroMiners · PRL", "page": None,
                    "total": "0,7377 PRL", "uah": "≈ 74,84 ₴", "confirmed": "0,4843", "pending": "0,2534",
                    "paid": "1,0493 PRL ≈ 106,45 ₴ · остання 20.10.2026 20:11", "price": "PRL = $2,25 · 101,45 ₴ (CoinGecko)",
                    "updated": "22:41 (кожні 5 хв)"},
        "forecast": {"zones": [{"name": "Ніч (23:00–07:00)", "hours": 8, "price": 2.16, "income": 22.74, "cost": 1.74, "profit": 21.00, "now": False},
                               {"name": "День (07:00–23:00)", "hours": 16, "price": 4.32, "income": 45.48, "cost": 6.95, "profit": 38.54, "now": True}],
                     "income": 68.23, "cost": 8.68, "profit": 59.54, "src": "зараз", "now_text": "денний тариф 4,32 ₴/кВт·год → +2,41 ₴ за годину"},
        "days": [(d.strftime("%d.%m"), inc - cost, f"{d:%d.%m}: дохід {inc:.2f} ₴ − світло {cost:.2f} ₴ = {inc - cost:+.2f} ₴".replace(".", ","))
                 for d, inc, cost in days],
        "devices": [local, rig1, rig2, rig3],
        "notices": notices,
        "best": best,
        "ledger": {"owners": ledger_owners, "workers": ledger_workers, "worker_names": ["rtx3060", "rig1", "friend"], "off": [False, False, False],
                   "recon": ["PRL · HeroMiners: розподілено 2,438056 = нараховано пулом ✓ · контрольна точка 20.10 15:01 · очікує дозрівання 0,338601"],
                   "warn": []},
        "energy": {"local": [["PRL", "1 д 2 год", "2,069 / 2,543", "8,02", "150,18"]],
                   "farm": [["Дім / rig1", "5 д 3 год", "84,11", "296,40"], ["Дім / rig2", "5 д 3 год", "14,60", "51,40"]]},
        "coins": {"ranking": ranking, "form": form},
        "miners": [{"id": i, "name": n, "installed": a, "latest": b, "state": st} for i, n, a, b, st in (
            ("srbminer", "SRBMiner-MULTI", "3.7.8", "3.7.9", "є оновлення"), ("onezerominer", "OneZeroMiner", "v1.8.2", "v1.8.2", "актуальна"),
            ("bzminer", "BzMiner", "—", "v100.46", "не встановлено"), ("lolminer", "lolMiner", "—", "1.98a", "не встановлено"),
            ("rigel", "Rigel", "—", "1.23.2", "не встановлено"))],
        "miners_note": "",
        "settings": {"TariffDay": 4.32, "TariffNight": 2.16, "TwoZone": True, "NightFrom": 23, "NightTo": 7, "MaxTemp": 75, "MaxPower": 150,
                     "TuneCoreMax": 1800, "HiveOsToken": True, "HashrateNoKey": True, "UiTheme": "dark", "UiFont": "large", "Autostart": False, "MinimizeToTray": False,
                     "HiveStatus": "HiveOS: підключено, ригів: 3"},
        "journal": [("22:41", INFO, "Дані пулу оновлено"), ("22:30", WARN, "rig2: майнер зупинено"),
                    ("21:21", INFO, "Сервер пулу de не відповідав — перейшов на fi.pearl.herominers.com"),
                    ("21:18", INFO, "Старт: Pearl (PRL) · HeroMiners, SRBMiner-MULTI, розгін «Свій · день»"),
                    ("20:02", ERROR, "rig3 не на зв'язку")],
        "miner_log": "[2026-10-21 21:21:29] Reconnecting to de.pearl.herominers.com:1200 in 5 seconds [0]\n"
                     "[2026-10-21 21:21:42] Couldn't connect to pool de.pearl.herominers.com:1200\n"
                     "[2026-10-21 21:22:20] Connected to fi.pearl.herominers.com:1200 [1]\n"
                     "[2026-10-21 21:22:53] GPU1 RTX 3060: 47.83 TH/s [T:60C FAN:32% P:101.0W]\n",
    }
