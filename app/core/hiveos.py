"""Ферма HiveOS через офіційний API (специфікація: api.swaggerhub.com/apis/HiveOS/public/2.1-beta).
Персональний токен — HiveOsToken у settings.json; він дає повний доступ до акаунта і ніде не логується.
Хешрейт у HiveOS — у kH/s."""
from __future__ import annotations

import time
from typing import Any

from .net import HttpError, get_json, send_json

API = "https://api2.hiveos.farm/api/v2"


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def error_text(e: Exception) -> str:
    st = getattr(e, "status", 0)
    if st == 401:
        return "невірний або відкликаний токен (401) — створи новий у HiveOS → Account → API tokens"
    if st == 403:
        return "доступ заборонено (403) — перевір токен і права доступу до ферми"
    return str(e)


def normalize_worker(w: dict, farm: dict) -> dict:
    hr = 0.0
    acc = rej = 0
    coin = algo = miner = ""
    hashrates = [m for m in ((w.get("miners_summary") or {}).get("hashrates") or []) if m]
    for m in hashrates:
        hr += float(m.get("hash") or 0) * 1000
        sh = m.get("shares") or {}
        acc += int(sh.get("accepted") or 0)
        rej += int(sh.get("rejected") or 0)
        if not coin:
            coin, algo, miner = str(m.get("coin") or ""), str(m.get("algo") or ""), str(m.get("miner") or "")
    stats_list = (w.get("miners_stats") or {}).get("hashrates") or []
    per_gpu = list((stats_list[0] or {}).get("hashes") or []) if stats_list else []
    info = {str(g.get("bus_number")): g for g in w.get("gpu_info") or [] if g}
    gpus = []
    for i, g in enumerate([g for g in w.get("gpu_stats") or [] if g]):
        gi = info.get(str(g.get("bus_number")))
        gpus.append({"idx": int(gi.get("index", i)) if gi else i, "name": str(gi.get("model", "")) if gi else "",
                     "temp": int(g.get("temp") or 0), "fan": int(g.get("fan") or 0), "power": float(g.get("power") or 0),
                     "core": int(g.get("coreclk") or 0), "mem": int(g.get("memclk") or 0),
                     "hr": float(per_gpu[i]) * 1000 if i < len(per_gpu) else 0.0})
    st = w.get("stats") or {}
    power = float(st.get("power_draw") or 0) or float(w.get("hardware_power_draw") or 0) or sum(g["power"] for g in gpus)
    fs = w.get("flight_sheet") or {}
    return {"id": int(w.get("id") or 0), "farmId": int(farm.get("id") or 0), "farm": str(farm.get("name") or ""),
            "name": str(w.get("name") or ""), "online": bool(st.get("online")), "minerOn": bool(hashrates),
            "power": power, "hr": hr, "coin": coin, "algo": algo, "miner": miner, "acc": acc, "rej": rej,
            "maxTemp": int((w.get("gpu_summary") or {}).get("max_temp") or 0),
            "minerStart": float(st.get("miner_start_time") or 0), "bootTime": float(st.get("boot_time") or 0),
            "fsId": int(fs.get("id") or 0), "fsName": str(fs.get("name") or ""),
            "fsPools": [str(x.get("pool")) for x in fs.get("items") or [] if x and x.get("pool")],
            "ocId": int(w.get("oc_id") or 0), "gpus": gpus}


def fetch(token: str) -> dict:
    """Усі ферми: воркери (риги), польотні листи, профілі розгону. {workers, fs, oc, error}."""
    r: dict[str, Any] = {"workers": [], "fs": {}, "oc": {}, "error": ""}
    try:
        for f in get_json(f"{API}/farms", headers=_h(token)).get("data") or []:
            fid = int(f["id"])
            r["fs"][str(fid)] = [{"id": int(x["id"]), "name": str(x.get("name") or ""),
                                  "coins": [str(i.get("coin")) for i in x.get("items") or [] if i.get("coin")],
                                  "pools": [str(i.get("pool")) for i in x.get("items") or [] if i.get("pool")]}
                                 for x in get_json(f"{API}/farms/{fid}/fs", headers=_h(token)).get("data") or []]
            try:
                r["oc"][str(fid)] = [{"id": int(x["id"]), "name": str(x.get("name") or "")}
                                     for x in get_json(f"{API}/farms/{fid}/oc", headers=_h(token)).get("data") or []]
            except HttpError:
                r["oc"][str(fid)] = []
            for w in get_json(f"{API}/farms/{fid}/workers", headers=_h(token), params={"platform": 1}).get("data") or []:
                r["workers"].append(normalize_worker(w, f))
    except Exception as e:  # noqa: BLE001
        r["error"] = error_text(e)
    return r


def command(token: str, w: dict, kind: str, value: Any) -> None:
    """kind = 'miner' (value = start|stop|restart), 'fs' або 'oc' (value = id). Кидає виняток при помилці."""
    path = f"{API}/farms/{w['farmId']}/workers/{w['id']}"
    if kind == "miner":
        send_json("POST", path + "/command", {"command": "miner", "data": {"action": str(value)}}, headers=_h(token))
    elif kind == "fs":
        send_json("PATCH", path, {"fs_id": int(value)}, headers=_h(token))
    elif kind == "oc":
        send_json("PATCH", path, {"oc_id": int(value)}, headers=_h(token))
    else:
        raise ValueError(kind)


def pool_worker_name(settings: dict, w: dict) -> str:
    """Воркер HiveOS → ім'я на пулі (HiveWorkerMap або те саме ім'я, як у %WORKER_NAME%)."""
    m = (settings.get("HiveWorkerMap") or {}).get(w["name"])
    return str(m) if m else w["name"]


def coin_for(coins: list[dict], w: dict) -> dict | None:
    """Запис coins.json, який майнить риг: тікер з майнера + пул (назва пулу в HiveOS містить тип)."""
    if not w.get("coin"):
        return None
    cands = [c for c in coins if str(c.get("ticker")) == w["coin"] and c.get("wallet")]
    by_pool = [c for c in cands if any(str((c.get("pool") or {}).get("type", "")).lower() in p.lower() for p in w.get("fsPools") or [])]
    if by_pool:
        return by_pool[0]
    return cands[0] if len(cands) == 1 else None


def miner_uptime_s(w: dict) -> float:
    return time.time() - w["minerStart"] if w.get("minerStart") else 0.0


class Watch:
    """Нагляд за ригами: попередження і (за налаштуванням) автоперезапуск майнера, що працює, але
    10 хв без хешрейту — не частіше ніж раз на 30 хв. Зупинений майнер не запускаємо."""

    def __init__(self):
        self.zero_since: dict[str, float] = {}
        self.restarted: dict[str, float] = {}

    def check(self, workers: list[dict], auto: bool, now: float | None = None) -> tuple[list[dict], list[dict]]:
        """→ (попередження [{key, worker, kind, text}], перезапустити [worker])."""
        now = time.time() if now is None else now
        alerts, restart = [], []
        for w in workers:
            k = f"{w['farmId']}/{w['id']}"
            if not w["online"]:
                alerts.append({"key": k, "worker": w, "kind": "offline", "text": f"{w['name']}: риг офлайн"})
                self.zero_since.pop(k, None)
                continue
            if not w["minerOn"]:
                alerts.append({"key": k, "worker": w, "kind": "stopped", "text": f"{w['name']}: майнер зупинено"})
                self.zero_since.pop(k, None)
                continue
            if w["hr"] > 0:
                self.zero_since.pop(k, None)
                continue
            since = self.zero_since.setdefault(k, now)
            mins = (now - since) / 60
            if mins < 5:
                continue
            alerts.append({"key": k, "worker": w, "kind": "nohash", "text": f"{w['name']}: немає хешрейту {mins:.0f} хв"})
            last = self.restarted.get(k)
            if auto and mins >= 10 and w.get("fsId") and (not last or now - last >= 1800):
                self.restarted[k] = now
                restart.append(w)
        return alerts, restart
