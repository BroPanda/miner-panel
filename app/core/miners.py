"""Адаптери майнерів (порт miners\\*.ps1): параметри запуску, читання API, архіви релізів для Windows і Linux.
build_args(c) отримує c: algo, pools (host:port), login (гаманець.воркер), tls, log_file, api_port.
read_stats(port) повертає {hr (H/s), hr15 | None, accepted, rejected, uptime (с), pool} або None.
Розгін робить панель (nvidia-smi / NVAPI) — ключі розгону майнерам не передаються."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import requests

from .platform import OS_KEY


def _get(url: str):
    try:
        r = requests.get(url, timeout=1)
        return r.json()
    except (requests.RequestException, ValueError):
        return None


def _split_login(login: str) -> tuple[str, str]:
    w, _, worker = login.partition(".")
    return w, worker


@dataclass
class Miner:
    id: str
    name: str
    repo: str
    asset: dict[str, str]          # ОС → шаблон назви файлу релізу (regex)
    exe: dict[str, str]            # ОС → назва виконуваного файлу
    api_port: int
    build_args: Callable[[dict], list[str]]
    read_stats: Callable[[int], dict | None]
    legacy: list[str] = field(default_factory=list)

    @property
    def exe_name(self) -> str:
        return self.exe[OS_KEY]

    @property
    def process_name(self) -> str:
        n = self.exe_name
        return n[:-4] if n.lower().endswith(".exe") else n


# ---- SRBMiner-MULTI --------------------------------------------------------
def _srb_args(c):
    pools = ",".join(c["pools"])
    logins = ",".join(c["login"] for _ in c["pools"])
    a = ["--disable-cpu", "--algorithm-gpu", c["algo"], "--pool", pools, "--wallet", logins,
         "--api-enable", "--api-port", str(c["api_port"]), "--log-file", c["log_file"]]
    if c.get("tls"):
        a += ["--tls", "true"]
    return a


def _srb_stats(port):
    j = _get(f"http://127.0.0.1:{port}")
    if not j:
        return None
    a = (j.get("algorithms") or [None])[0]
    if not a:
        return None
    hr = a.get("hashrate") or {}
    return {"hr": float((hr.get("gpu") or {}).get("total") or 0), "hr15": float(hr.get("15min") or 0) if hr.get("15min") is not None else None,
            "accepted": int((a.get("shares") or {}).get("accepted") or 0), "rejected": int((a.get("shares") or {}).get("rejected") or 0),
            "uptime": float(j.get("mining_time") or 0), "pool": str((a.get("pool") or {}).get("pool") or "")}


# ---- lolMiner ----------------------------------------------------------------
def _lol_args(c):
    a = ["--algo", c["algo"]]
    for p in c["pools"]:
        a += ["--pool", p, "--user", c["login"]]
    if c.get("tls"):
        a += ["--tls", "on"]
    return a + ["--apiport", str(c["api_port"]), "--apihost", "127.0.0.1", "--log", "on", "--logfile", c["log_file"]]


def _lol_stats(port):
    j = _get(f"http://127.0.0.1:{port}/summary")
    if not j:
        return None
    a = (j.get("Algorithms") or [None])[0]
    if not a:
        return None
    return {"hr": float(a.get("Total_Performance") or 0) * float(a.get("Performance_Factor") or 1), "hr15": None,
            "accepted": int(a.get("Total_Accepted") or 0), "rejected": int(a.get("Total_Rejected") or 0) + int(a.get("Total_Stales") or 0),
            "uptime": float((j.get("Session") or {}).get("Uptime") or 0), "pool": str(a.get("Pool") or "")}


# ---- Rigel -------------------------------------------------------------------
def _rigel_args(c):
    wallet, worker = _split_login(c["login"])
    scheme = "stratum+ssl" if c.get("tls") else "stratum+tcp"
    a = ["-a", c["algo"]]
    for p in c["pools"]:
        a += ["-o", f"{scheme}://{p}"]
    a += ["-u", wallet]
    if worker:
        a += ["-w", worker]
    return a + ["--api-bind", f"127.0.0.1:{c['api_port']}", "--no-tui", "--log-file", c["log_file"]]


def _rigel_stats(port):
    j = _get(f"http://127.0.0.1:{port}/")
    if not j:
        return None
    algo = str(j.get("algorithm") or "")
    sol = (j.get("solution_stat") or {}).get(algo) or {}
    pool = ((j.get("pools") or {}).get(algo) or [{}])[0] or {}
    cd = pool.get("connection_details") or {}
    return {"hr": float((j.get("hashrate") or {}).get(algo) or 0), "hr15": None,
            "accepted": int(sol.get("accepted") or 0), "rejected": int(sol.get("rejected") or 0) + int(sol.get("invalid") or 0),
            "uptime": float(j.get("uptime") or 0), "pool": f"{cd.get('hostname', '')}:{cd.get('port', '')}"}


# ---- BzMiner -----------------------------------------------------------------
def _bz_args(c):
    wallet, worker = _split_login(c["login"])
    scheme = "stratum+ssl" if c.get("tls") else "stratum+tcp"
    a = ["-a", c["algo"]]
    for p in c["pools"]:
        a += ["-p", f"{scheme}://{p}"]
    a += ["-w", wallet]
    if worker:
        a += ["--worker", worker]
    # Без --cpu 0 --amd 0 --intel 0 BzMiner майнить ще й на процесорі та вбудованій графіці
    return a + ["--cpu", "0", "--amd", "0", "--intel", "0", "--disable_udp",
                "--set", "http_enabled=true", "--set", "http_address=127.0.0.1", "--set", f"http_port={c['api_port']}",
                "--logfile", c["log_file"], "--logfile-mode", "overwrite", "--nc", "1"]


def _bz_stats(port):
    j = _get(f"http://127.0.0.1:{port}/status")
    if not j:
        return None
    p = (j.get("pools") or [None])[0]
    if not p:
        return None
    return {"hr": float(p.get("hashrate") or 0), "hr15": None, "accepted": int(p.get("valid_solutions") or 0),
            "rejected": int(p.get("rejected_solutions") or 0) + int(p.get("invalid_solutions") or 0) + int(p.get("stale_solutions") or 0),
            "uptime": float(p.get("uptime_s") or 0), "pool": str(p.get("current_url") or "")}


# ---- OneZeroMiner --------------------------------------------------------------
def _ozm_args(c):
    wallet, worker = _split_login(c["login"])
    scheme = "ssl" if c.get("tls") else "stratum+tcp"
    a = ["-a", c["algo"]]
    for p in c["pools"]:
        a += ["-o", f"{scheme}://{p}"]
    a += ["-w", wallet]
    if worker:
        a += ["--worker", worker]
    # Хешрейт в API усереднюється за 30 с (за замовчуванням 10 с — сильно скаче)
    return a + ["--api-host", "127.0.0.1", "--api-port", str(c["api_port"]), "--log-file", c["log_file"],
                "--disable-telemetry", "--hashrate-avg", "30"]


def _ozm_stats(port):
    j = _get(f"http://127.0.0.1:{port}/")
    if not j:
        return None
    a = (j.get("algos") or [None])[0]
    if not a:
        return None
    pool = str(a.get("pool") or "")
    return {"hr": float(a.get("total_hashrate") or 0), "hr15": None, "accepted": int(a.get("total_accepted_shares") or 0),
            "rejected": int(a.get("total_rejected_shares") or 0) + int(a.get("total_invalid_shares") or 0),
            "uptime": float(j.get("uptime_seconds") or 0), "pool": pool.split("://", 1)[-1]}


MINERS: dict[str, Miner] = {m.id: m for m in [
    Miner("bzminer", "BzMiner", "bzminer/bzminer", {"win": r"_windows\.zip$", "linux": r"_linux\.tar\.gz$"},
          {"win": "bzminer.exe", "linux": "bzminer"}, 4014, _bz_args, _bz_stats),
    Miner("lolminer", "lolMiner", "Lolliedieb/lolMiner-releases", {"win": r"_Win64\.zip$", "linux": r"_Lin64\.tar\.gz$"},
          {"win": "lolMiner.exe", "linux": "lolMiner"}, 4067, _lol_args, _lol_stats),
    Miner("onezerominer", "OneZeroMiner", "OneZeroMiner/onezerominer", {"win": r"-win64-[\d.]+\.zip$", "linux": r"-linux-[\d.]+\.tar\.gz$"},
          {"win": "onezerominer.exe", "linux": "onezerominer"}, 3001, _ozm_args, _ozm_stats),
    Miner("rigel", "Rigel", "rigelminer/rigel", {"win": r"-win\.zip$", "linux": r"-linux\.tar\.gz$"},
          {"win": "rigel.exe", "linux": "rigel"}, 5000, _rigel_args, _rigel_stats),
    Miner("srbminer", "SRBMiner-MULTI", "doktor83/SRBMiner-Multi", {"win": r"-win64\.zip$", "linux": r"-Linux\.tar\.gz$"},
          {"win": "SRBMiner-MULTI.exe", "linux": "SRBMiner-MULTI"}, 21550, _srb_args, _srb_stats, legacy=["miner/SRBMiner-MULTI.exe"]),
]}


# Комісія розробника майнера (частка часу, %) за алгоритмом. Джерела: SRBMiner --list-algorithms,
# bzminer --list-algos, README Rigel. Немає в таблиці — комісія невідома (показується «?»).
DEV_FEE: dict[str, dict[str, float]] = {
    "srbminer": {"autolykos2": 1.0, "kawpow": 0.85, "pearlhash": 2.0, "progpow_zano": 0.85, "qhash": 1.5,
                 "quantus": 2.0, "xelishashv3": 1.5},
    "bzminer": {"ergo": 1.0, "pearl": 2.0, "quantus": 2.0, "rvn": 1.0, "xelis": 1.0},
    "rigel": {"autolykos2": 1.0, "karlsenhashv2": 1.0, "kawpow": 1.0, "octopus": 2.0, "progpowz": 1.0,
              "xelishashv3": 2.0},
}


def dev_fee(miner_id: str, coin: dict) -> float | None:
    """Комісія майнера (%) для алгоритму монети або None, якщо невідома."""
    algo = (coin.get("miners") or {}).get(miner_id)
    return DEV_FEE.get(miner_id, {}).get(str(algo)) if algo else None


def coin_miner_id(settings: dict, coin: dict) -> str:
    """Майнер монети: вибір користувача, якщо він підходить, інакше типовий з coins.json."""
    sel = (settings.get("Miner") or {}).get(coin.get("id"))
    if sel and (coin.get("miners") or {}).get(sel) and sel in MINERS:
        return sel
    return str(coin.get("miner"))


def all_process_names() -> list[str]:
    return [m.process_name for m in MINERS.values()]
