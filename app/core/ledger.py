"""Бухгалтерія: скільки монет намайнив кожен воркер і кожен власник.

Точна копія lib\\Ledger.ps1 — та сама формула, той самий порядок обчислень і той самий код
контрольної точки `MPK1:` (gzip + base64 JSON, v2), тож PowerShell- і Python-версія на різних ПК
дають однакові числа до біта.

  монети воркера = КТ.Coins + (Earned − КТ.Earned) × робота воркера після КТ / уся робота після КТ

Робота — накопичувальні лічильники пулу (HeroMiners: hashes; Kryptex: кількість шар, «≈»),
Earned — виплачено + підтверджений баланс. КТ зберігається цілими числами (EarnedQ, CoinsQ — нано-монети
×10⁹; Counters — цілі), бо дробові числа різні парсери JSON можуть прочитати з різницею в останньому біті.
Ключі сортуються ординально (sorted()), як [StringComparer]::Ordinal у PowerShell-версії.
"""
from __future__ import annotations

import base64
import gzip
import json
import uuid
from typing import Any, Iterable

from . import timeutil

SCALE = 1e9
CODE_PREFIX = "MPK1:"
REFRESH_MIN = 10        # інші рахунки (не поточна монета) — не частіше ніж раз на 10 хв
OWNER_ME = "Я"
OWNER_NONE = "без власника"


def to_q(x: float) -> int:
    # round() у Python округлює до парного — як [Math]::Round у .NET
    return int(round(float(x) * SCALE))


def from_q(q: Any) -> float:
    return float(int(q)) / SCALE


def to_counters(h: dict | None) -> dict[str, int]:
    return {str(n): int(round(float(v))) for n, v in (h or {}).items()}


def ledger_key(coin: dict) -> str:
    pool = coin.get("pool") or {}
    return f"{pool.get('type')}|{pool.get('coin')}|{coin.get('wallet')}"


def repair_cp(cp: dict) -> dict:
    """КТ першої версії (Earned, Coins — дробові) → цілі числа."""
    if cp.get("EarnedQ") is None:
        cp["EarnedQ"] = to_q(float(cp.pop("Earned", 0) or 0))
    if not isinstance(cp.get("CoinsQ"), dict):
        coins = cp.pop("Coins", None)
        cp["CoinsQ"] = {str(n): to_q(float(v)) for n, v in coins.items()} if isinstance(coins, dict) else {}
    else:
        cp["CoinsQ"] = {str(n): int(v) for n, v in cp["CoinsQ"].items()}
    cp["EarnedQ"] = int(cp["EarnedQ"])
    cp["Counters"] = to_counters(cp.get("Counters") if isinstance(cp.get("Counters"), dict) else {})
    cp.setdefault("Time", timeutil.iso())
    return cp


def new_account(ticker: str, pool: str, wallet: str, exact: bool) -> dict:
    return {"Ticker": ticker, "Pool": pool, "Wallet": wallet, "Exact": exact,
            "Cp": {"Time": timeutil.iso(), "EarnedQ": 0, "Counters": {}, "CoinsQ": {}},
            "Raw": {}, "Base": {}, "Acc": {}, "Resets": {}, "Hr": {}, "Online": {},
            "Earned": 0.0, "Time": None, "Unconfirmed": 0.0}


def from_old_ledger(L: dict) -> dict:
    """Старий журнал (stats.json → pool) → рахунок з КТ на момент його останнього нарахування."""
    a = new_account(str(L.get("Ticker", "")), str(L.get("Pool", "")), str(L.get("Wallet", "")), bool(L.get("Exact")))
    if L.get("Since"):
        a["Cp"]["Time"] = str(L["Since"])
    a["Cp"]["EarnedQ"] = to_q(float(L.get("Earned") or 0))
    a["Cp"]["CoinsQ"] = {str(n): to_q(float(v)) for n, v in (L.get("Coins") or {}).items()}
    work, pending = L.get("Work") or {}, L.get("Pending") or {}
    for n, v in work.items():
        # [long] у PowerShell округлює (до парного), а не відкидає дробову частину
        a["Cp"]["Counters"][n] = int(round(max(0.0, float(v) - float(pending.get(n, 0)))))
        a["Raw"][n] = float(v)
    a["Base"] = {n: float(v) for n, v in a["Cp"]["Counters"].items()}
    a["Earned"] = float(L.get("Earned") or 0)
    return a


def repair_accounts(accounts: dict) -> None:
    for L in accounts.values():
        if not isinstance(L.get("Cp"), dict):
            L["Cp"] = {"Time": timeutil.iso()}
        repair_cp(L["Cp"])
        for k in ("Raw", "Base", "Acc", "Resets", "Hr", "Online"):
            if not isinstance(L.get(k), dict):
                L[k] = {}


def get_account(stats: dict, coin: dict, pool_name: str, exact: bool) -> dict:
    key = ledger_key(coin)
    L = stats["ledger"].get(key)
    if not L:
        L = stats["ledger"][key] = new_account(str(coin.get("ticker", "")), pool_name, str(coin.get("wallet", "")), exact)
    for k in ("Raw", "Base", "Acc", "Resets", "Hr", "Online"):
        if not isinstance(L.get(k), dict):
            L[k] = {}
    return L


def add_pool_snapshot(stats: dict, coin: dict, d: dict, pool_name: str) -> bool:
    """Відповідь пулу (earned, workExact, workers[].name/work/hr3h/online) → рахунок. True — записано."""
    if d.get("earned") is None or not coin.get("wallet") or not coin.get("ticker"):
        return False
    L = get_account(stats, coin, pool_name, bool(d.get("workExact")))
    L["Exact"] = bool(d.get("workExact"))
    now = timeutil.iso()
    for w in d.get("workers") or []:
        if not w or not w.get("name"):
            continue
        n = str(w["name"])
        raw = float(w.get("work") or 0)
        if n not in L["Base"]:
            L["Base"][n] = float(L["Cp"]["Counters"][n]) if n in L["Cp"]["Counters"] else 0.0
        if n in L["Raw"] and raw < float(L["Raw"][n]):
            # Пул скинув лічильник: зароблене до скидання зберігаємо, далі рахуємо від нуля
            L["Acc"][n] = float(L["Acc"].get(n, 0)) + max(0.0, float(L["Raw"][n]) - float(L["Base"][n]))
            L["Base"][n] = 0.0
            L["Resets"][n] = now
        elif raw < float(L["Base"][n]):
            # Лічильник менший, ніж у КТ: скидання сталося, поки панель не бачила
            L["Base"][n] = 0.0
            L["Resets"][n] = now
        L["Raw"][n] = raw
        L["Hr"][n] = float(w.get("hr3h") or 0)
        L["Online"][n] = bool(w.get("online"))
    L["Earned"] = float(d["earned"])
    bal = d.get("balance")
    L["Unconfirmed"] = float(bal.get("unconfirmed") or 0) if isinstance(bal, dict) else 0.0
    L["Time"] = now
    return True


def account_coins(L: dict) -> dict:
    """Розподіл рахунку зараз: Names, Coins, Work, Share, Distributed, Undistributed, Warn."""
    cp = L["Cp"]
    names = sorted(set(cp["CoinsQ"]) | set(L["Raw"]))
    work: dict[str, float] = {}
    total = 0.0
    for n in names:
        if n in L["Base"]:
            base = float(L["Base"][n])
        elif n in cp["Counters"]:
            base = float(cp["Counters"][n])
        else:
            base = 0.0
        wk = float(L["Acc"].get(n, 0))
        if n in L["Raw"]:
            wk += max(0.0, float(L["Raw"][n]) - base)
        work[n] = wk
        total += wk
    cp_coins = {n: from_q(cp["CoinsQ"][n]) if n in cp["CoinsQ"] else 0.0 for n in names}
    coins = dict(cp_coins)
    dE = float(L.get("Earned") or 0) - from_q(cp["EarnedQ"])
    # Залишок округлення КТ до нано-монети — не нарахування і не втрата
    if abs(dE) < 1e-8:
        dE = 0.0
    und = 0.0
    warn: list[str] = []
    if dE > 0:
        if total > 0:
            for n in names:
                coins[n] += dE * work[n] / total
        else:
            # Нараховано без нової роботи (дозрів старий блок) — за часткою розподіленого раніше
            s2 = 0.0
            for n in names:
                s2 += cp_coins[n]
            if s2 > 0:
                for n in names:
                    coins[n] += dE * cp_coins[n] / s2
            else:
                und = dE
    elif dE < 0 and L.get("Time"):
        warn.append("пул показує менше нарахованого, ніж у контрольній точці — перевір гаманець на сайті пулу")
    for n in sorted(L["Resets"]):
        warn.append(f"{n}: пул скинув лічильник роботи — закрий період і передай код іншим")
    dist = 0.0
    for n in names:
        dist += coins[n]
    share = {n: (coins[n] / dist if dist > 0 else 0.0) for n in names}
    return {"Names": names, "Coins": coins, "Work": work, "Share": share,
            "Distributed": dist, "Undistributed": und, "Warn": warn}


def reconciled(L: dict, r: dict) -> bool:
    """Розподілене = нараховане пулом (допуск — округлення КТ до нано-монети)."""
    earned = float(L.get("Earned") or 0)
    return abs(r["Distributed"] + r["Undistributed"] - earned) <= 1e-9 * (len(r["Names"]) + 1) + 1e-12 * earned


# ---- Власники і видачі ----------------------------------------------------
def worker_owner(settings: dict, local_names: Iterable[str], name: str) -> str:
    o = (settings.get("WorkerOwners") or {}).get(name)
    if o:
        return str(o)
    return OWNER_ME if name in set(local_names) else OWNER_NONE


def set_worker_owner(settings: dict, name: str, owner: str) -> None:
    owners = settings.setdefault("WorkerOwners", {})
    if owner and owner != OWNER_NONE:
        owners[name] = owner
    else:
        owners.pop(name, None)


def owner_names(settings: dict, stats: dict) -> list[str]:
    o = {OWNER_ME} | {str(v) for v in (settings.get("WorkerOwners") or {}).values() if v}
    o |= {str(p.get("Owner")) for p in stats.get("payouts") or [] if p and p.get("Owner")}
    return sorted(o)


def payout_coins(p: dict) -> float:
    return from_q(p["CoinsQ"]) if p.get("CoinsQ") is not None else float(p.get("Coins") or 0)


def add_payout(stats: dict, owner: str, ticker: str, coins: float, note: str) -> dict:
    p = {"Id": uuid.uuid4().hex, "Time": timeutil.iso(), "Owner": owner, "Ticker": ticker, "CoinsQ": to_q(coins), "Note": note}
    stats.setdefault("payouts", []).append(p)
    return p


def owner_totals(settings: dict, stats: dict, local_names: Iterable[str]) -> dict[str, dict[str, dict[str, float]]]:
    """Власник → тікер → {Mined, Paid}."""
    local_names = list(local_names)
    t: dict[str, dict[str, dict[str, float]]] = {}
    for key in sorted(stats["ledger"]):
        L = stats["ledger"][key]
        r = account_coins(L)
        for n in r["Names"]:
            v = t.setdefault(worker_owner(settings, local_names, n), {}).setdefault(L["Ticker"], {"Mined": 0.0, "Paid": 0.0})
            v["Mined"] += r["Coins"][n]
    for p in stats.get("payouts") or []:
        if not p:
            continue
        v = t.setdefault(str(p.get("Owner")), {}).setdefault(str(p.get("Ticker")), {"Mined": 0.0, "Paid": 0.0})
        v["Paid"] += payout_coins(p)
    return t


# ---- Контрольна точка і обмін кодом -----------------------------------------
def close_period(stats: dict) -> None:
    """Закрити період для всіх рахунків: розподілене стає новою КТ."""
    now = timeutil.iso()
    for key in sorted(stats["ledger"]):
        L = stats["ledger"][key]
        r = account_coins(L)
        L["Cp"] = {"Time": now, "EarnedQ": to_q(float(L.get("Earned") or 0) - r["Undistributed"]),
                   "Counters": to_counters(L["Raw"]), "CoinsQ": {n: to_q(r["Coins"][n]) for n in r["Names"]}}
        L["Base"] = {n: float(v) for n, v in L["Cp"]["Counters"].items()}
        L["Acc"] = {}
        L["Resets"] = {}


def export_code(settings: dict, stats: dict) -> str:
    acc = {}
    for key in sorted(stats["ledger"]):
        L = stats["ledger"][key]
        acc[key] = {"Ticker": L["Ticker"], "Pool": L["Pool"], "Wallet": L["Wallet"], "Exact": L["Exact"], "Cp": L["Cp"]}
    p = {"v": 2, "time": timeutil.iso(), "acc": acc, "owners": settings.get("WorkerOwners") or {},
         "payouts": list(stats.get("payouts") or [])}
    raw = json.dumps(p, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return CODE_PREFIX + base64.b64encode(gzip.compress(raw)).decode("ascii")


class CodeError(ValueError):
    pass


def import_code(settings: dict, stats: dict, code: str) -> str:
    """Застосовує чужий код КТ (якщо його КТ новіша). Повертає підсумок; CodeError — якщо код поганий."""
    code = "".join(code.split())
    if not code.startswith(CODE_PREFIX):
        raise CodeError("це не код контрольної точки (має починатися з MPK1:)")
    try:
        p = json.loads(gzip.decompress(base64.b64decode(code[len(CODE_PREFIX):], validate=True)).decode("utf-8-sig"))
    except Exception as e:  # noqa: BLE001 — будь-яке пошкодження коду
        raise CodeError("код пошкоджений (скопіюй його повністю)") from e
    if int(p.get("v", 0)) not in (1, 2) or not isinstance(p.get("acc"), dict):
        raise CodeError("невідома версія коду (онови панель)")
    new = upd = old = 0
    for key in sorted(p["acc"]):
        a = p["acc"][key]
        cp = a.get("Cp")
        if not isinstance(cp, dict):
            continue
        repair_cp(cp)
        L = stats["ledger"].get(key)
        if not L:
            L = stats["ledger"][key] = new_account(str(a.get("Ticker", "")), str(a.get("Pool", "")), str(a.get("Wallet", "")), bool(a.get("Exact")))
            new += 1
        elif (timeutil.parse(cp["Time"]) or timeutil.now()) <= (timeutil.parse(L["Cp"]["Time"]) or timeutil.now()):
            old += 1
            continue
        else:
            upd += 1
        L["Cp"] = cp
        L["Base"] = {n: float(v) for n, v in cp["Counters"].items()}
        L["Acc"] = {}
        L["Resets"] = {}
    if isinstance(p.get("owners"), dict):
        settings.setdefault("WorkerOwners", {}).update({n: str(v) for n, v in p["owners"].items()})
    ids = {str(x.get("Id")) for x in stats.get("payouts") or [] if x}
    np_ = 0
    for x in p.get("payouts") or []:
        if x and str(x.get("Id")) not in ids:
            stats.setdefault("payouts", []).append(x)
            np_ += 1
    msg = f"Імпортовано: нових рахунків {new}, оновлено {upd}, видач {np_}."
    if old:
        msg += f" Пропущено {old} (у тебе контрольна точка новіша або та сама)."
    return msg


def coins_to_fetch(coins: list[dict], stats: dict, current: dict | None, running_coin_id: str | None,
                   pools: dict, hive_keys: set[str] | None = None) -> list[dict]:
    """Рахунки для опитування, крім поточної монети: є журнал, або монету майнить цей ПК чи риг HiveOS."""
    seen = {ledger_key(current)} if current else set()
    out = []
    for c in coins:
        ptype = str((c.get("pool") or {}).get("type"))
        if not c.get("wallet") or ptype == "generic" or ptype not in pools:
            continue
        key = ledger_key(c)
        if key in seen:
            continue
        seen.add(key)
        if key in stats["ledger"] or c.get("id") == running_coin_id or key in (hive_keys or set()):
            out.append(c)
    return out
