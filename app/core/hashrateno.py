"""hashrate.no — еталони відеокарт і найвигідніша монета для карти (lib\\HashrateNo.ps1).
Безкоштовний план — 100 запитів на місяць: gpuEstimates раз на добу, benchmarks раз на 30 днів;
усе кешується в hashrateno-cache.json, тож перезапуск запитів не витрачає."""
from __future__ import annotations

from pathlib import Path

from . import storage, timeutil
from .net import HttpError, get_json
from ..i18n import tr

API = "https://hashrate.no/api/v2"
CACHE = "hashrateno-cache.json"
BEST_HOURS = 24
BENCH_DAYS = 30


def empty() -> dict:
    return {"best": {}, "bestTime": None, "bench": {}}


def load_cache(root: Path) -> dict:
    c = storage.read_json(root / CACHE, {})
    h = empty()
    if isinstance(c, dict):
        h["best"] = c.get("best") or {}
        h["bestTime"] = c.get("bestTime")
        h["bench"] = c.get("bench") or {}
    return h


def save_cache(root: Path, h: dict) -> None:
    storage.write_json(root / CACHE, {"bestTime": h.get("bestTime"), "best": h.get("best") or {}, "bench": h.get("bench") or {}}, indent=None)


def due_tickers(h: dict, tickers: list[str]) -> list[str]:
    now = timeutil.now()
    out = []
    for t in sorted({x for x in tickers if x}):
        b = h["bench"].get(t)
        bt = timeutil.parse(b.get("time")) if b else None
        if not bt or (now - bt).days >= BENCH_DAYS:
            out.append(t)
    return out


def best_due(h: dict, force: bool = False) -> bool:
    bt = timeutil.parse(h.get("bestTime"))
    return force or not bt or (timeutil.now() - bt).total_seconds() >= BEST_HOURS * 3600


def _get(url: str):
    x = get_json(url, 30)
    # Помилки API приходять з кодом 200 як { title, detail }
    if isinstance(x, dict) and x.get("title") and x.get("detail"):
        raise HttpError(f"API: {x['detail']}", 200)
    return x


def fetch(key: str, best: bool, tickers: list[str]) -> dict:
    r: dict = {"best": None, "bench": {}, "error": "", "auth": False}

    def is_auth(e: Exception) -> bool:
        s = str(e).lower()
        return "credential" in s or "api key" in s or "apikey" in s

    if best:
        try:
            g = _get(f"{API}/gpuEstimates?apiKey={key}&powerCost=0")
            r["best"] = {}
            for v in (g.values() if isinstance(g, dict) else g):
                dev, rev = (v.get("device") or {}), (v.get("revenue") or {})
                if dev.get("name") and rev.get("ticker"):
                    r["best"][str(dev["name"])] = {"ticker": str(rev["ticker"]), "usd": float(rev.get("revenue") or 0),
                                                   "coins": float(rev.get("yield") or 0)}
        except Exception as e:  # noqa: BLE001
            r["auth"] = r["auth"] or is_auth(e)
            r["error"] += f"gpuEstimates: {e} "
    for t in tickers:
        if r["auth"]:
            break
        try:
            b = _get(f"{API}/benchmarks?apiKey={key}&coin={t}")
            dev = {}
            for v in (b.values() if isinstance(b, dict) else b):
                if v.get("deviceType") == "gpus" and v.get("name"):
                    dev[str(v["name"])] = {"hr": float(v.get("hashrate") or 0), "watts": float(v.get("power") or 0)}
            r["bench"][t] = dev
        except Exception as e:  # noqa: BLE001
            if is_auth(e):
                r["auth"] = True
            elif isinstance(e, HttpError) and e.status:
                r["bench"][t] = {}      # монети немає на hashrate.no — не питаємо до наступного разу
            r["error"] += f"benchmarks {t}: {e} "
    return r


def apply(h: dict, d: dict) -> str | None:
    """Результат запиту → кеш у пам'яті; повертає текст помилки або None."""
    now = timeutil.iso()
    if d.get("best"):
        h["best"], h["bestTime"] = d["best"], now
    for t, dev in (d.get("bench") or {}).items():
        h["bench"][t] = {"time": now, "devices": dev}
    if d.get("auth"):
        return tr('hashrate.no не прийняв ключ API')
    return d.get("error") or None


def best_for(h: dict, gpu_name: str | None) -> dict | None:
    return (h.get("best") or {}).get(gpu_name) if gpu_name else None
