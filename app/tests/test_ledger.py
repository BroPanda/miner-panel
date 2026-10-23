"""Бухгалтерія: розподіл, скидання лічильника, КТ і код, сумісність із PowerShell-версією до біта."""
import json
import random
import shutil
import struct
import subprocess
import sys
from pathlib import Path

import pytest

from app.core import ledger

COIN = {"id": "x", "ticker": "PRL", "wallet": "w1", "worker": "me", "pool": {"type": "herominers", "coin": "pearl"}}


def fresh():
    return {"ledger": {}, "payouts": [], "local": {}}


def snap(stats, earned, workers):
    ledger.add_pool_snapshot(stats, COIN, {"earned": earned, "workExact": True,
                                           "workers": [{"name": n, "work": w} for n, w in workers.items()]}, "HeroMiners")
    return ledger.account_coins(stats["ledger"][ledger.ledger_key(COIN)])


def test_split_and_reset():
    s = fresh()
    r = snap(s, 1.0, {"me": 300, "friend": 100})
    assert r["Coins"] == {"friend": 0.25, "me": 0.75}
    r = snap(s, 1.5, {"me": 400, "friend": 200})
    assert r["Coins"] == {"friend": 0.5, "me": 1.0}
    ledger.close_period(s)
    snap(s, 1.8, {"me": 450, "friend": 260})
    r = snap(s, 2.0, {"me": 500, "friend": 50})      # пул скинув лічильник friend
    assert r["Coins"]["me"] == 1.0 + 0.5 * 100 / 210
    assert r["Coins"]["friend"] == 0.5 + 0.5 * 110 / 210
    assert any("скинув лічильник" in w for w in r["Warn"])
    assert ledger.reconciled(s["ledger"][ledger.ledger_key(COIN)], r)


def test_code_roundtrip_bit_exact_and_payouts():
    s, settings = fresh(), {"WorkerOwners": {"friend": "Петро"}}
    snap(s, 1.0, {"me": 300, "friend": 100})
    snap(s, 1.3713371337, {"me": 411, "friend": 173})
    ledger.close_period(s)
    ledger.add_payout(s, "Петро", "PRL", 0.1, "тест")
    code = ledger.export_code(settings, s)
    x = snap(s, 1.9123456789, {"me": 523, "friend": 251})
    s2, settings2 = fresh(), {"WorkerOwners": {}}
    assert "нових рахунків 1" in ledger.import_code(settings2, s2, code)
    y = snap(s2, 1.9123456789, {"me": 523, "friend": 251})
    assert x["Coins"] == y["Coins"]
    assert settings2["WorkerOwners"] == {"friend": "Петро"}
    t = ledger.owner_totals(settings2, s2, ["me"])
    assert t["Петро"]["PRL"]["Paid"] == 0.1
    assert ledger.import_code(settings2, s2, code).endswith("(у тебе контрольна точка новіша або та сама).")


def test_bad_code():
    with pytest.raises(ledger.CodeError):
        ledger.import_code({}, fresh(), "MPK1:сміття")
    with pytest.raises(ledger.CodeError):
        ledger.import_code({}, fresh(), "hello")


def test_migration_from_old_pool_journal():
    old = {"Ticker": "PRL", "Pool": "HeroMiners", "Wallet": "w1", "Exact": True, "Earned": 1.27971119,
           "Work": {"rtx3060": 1365245952, "apitest": 4194304}, "Pending": {"rtx3060": 16777216},
           "Coins": {"rtx3060": 1.2746406033660267, "apitest": 0.0050705866339733089}, "Since": "2026-10-20T15:01:27.2247484+03:00"}
    a = ledger.from_old_ledger(old)
    r = ledger.account_coins(a)
    assert abs(r["Coins"]["rtx3060"] - 1.2746406033660267) < 1e-9
    assert abs(r["Coins"]["apitest"] - 0.0050705866339733089) < 1e-9
    assert a["Cp"]["Counters"]["rtx3060"] == 1365245952 - 16777216


# ---- Перехресна перевірка з lib\Ledger.ps1 ---------------------------------
HARNESS = Path(__file__).with_name("ps_ledger_harness.ps1")


def bits(x: float) -> str:
    return str(struct.unpack("<q", struct.pack("<d", x))[0])


def scenario(seed: int) -> list[dict]:
    rnd = random.Random(seed)
    names = ["rtx3060", "friend", "Rig_2", "apitest"][: rnd.randint(2, 4)]
    work = {n: rnd.randint(0, 10**9) for n in names}
    earned = rnd.randint(0, 10**7)
    steps = []
    for i in range(12):
        for n in names:
            if rnd.random() < 0.08:
                work[n] = rnd.randint(0, 10**6)          # скидання лічильника
            else:
                work[n] += rnd.randint(0, 10**8)
        earned += rnd.randint(0, 5 * 10**6)
        steps.append({"op": "snap", "earnedAtomic": earned, "units": 10**8,
                      "workers": [{"name": n, "work": work[n]} for n in names if rnd.random() > 0.1]})
        if i in (4, 9):
            steps.append({"op": "close"})
        if i == 5:
            steps.append({"op": "export"})
    return steps


def run_python(steps: list[dict], codes_in: list[str] | None = None) -> dict:
    s, settings = fresh(), {"WorkerOwners": {}}
    out = {"codes": [], "results": []}
    for st in steps:
        if st["op"] == "snap":
            earned = float(int(st["earnedAtomic"])) / float(int(st["units"]))
            ledger.add_pool_snapshot(s, COIN, {"earned": earned, "workExact": True,
                                               "workers": [{"name": w["name"], "work": float(w["work"])} for w in st["workers"]]}, "HeroMiners")
        elif st["op"] == "close":
            ledger.close_period(s)
        elif st["op"] == "export":
            out["codes"].append(ledger.export_code(settings, s))
        elif st["op"] == "import":
            ledger.import_code(settings, s, st["code"])
        elif st["op"] == "reset":
            s = fresh()
        L = s["ledger"].get(ledger.ledger_key(COIN))
        if L:
            r = ledger.account_coins(L)
            out["results"].append({"bits": {n: bits(r["Coins"][n]) for n in r["Names"]}, "dist": bits(r["Distributed"])})
        else:
            out["results"].append({"bits": {}, "dist": "0"})
    return out


def run_ps(steps: list[dict], tmp_path: Path) -> dict:
    f = tmp_path / "scenario.json"
    f.write_text(json.dumps({"steps": steps}), encoding="utf-8-sig")
    p = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(HARNESS), "-ScenarioFile", str(f),
                        "-LedgerPath", str(HARNESS.parents[2] / "old-panel" / "lib" / "Ledger.ps1")], capture_output=True, timeout=180)
    assert p.returncode == 0, p.stderr.decode("utf-8", "replace")
    o = json.loads(p.stdout.decode("utf-8-sig"))
    for r in o["results"]:
        r["bits"] = r["bits"] or {}
    return o


ps_only = pytest.mark.skipif(sys.platform != "win32" or not shutil.which("powershell"), reason="потрібен Windows PowerShell")


def same(a: dict, b: dict) -> bool:
    return all(x["bits"] == y["bits"] and x["dist"] == y["dist"] for x, y in zip(a["results"], b["results"])) and \
        len(a["results"]) == len(b["results"])


@ps_only
@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
def test_same_bits_as_powershell(seed, tmp_path):
    steps = scenario(seed)
    py, ps = run_python(steps), run_ps(steps, tmp_path)
    assert same(py, ps), (py["results"][-1], ps["results"][-1])


@ps_only
def test_codes_cross_import(tmp_path):
    steps = scenario(7)
    py, ps = run_python(steps), run_ps(steps, tmp_path)
    tail = [{"op": "snap", "earnedAtomic": 99_000_000, "units": 10**8,
             "workers": [{"name": "rtx3060", "work": 9 * 10**9}, {"name": "friend", "work": 8 * 10**9}]}]
    # Код із PowerShell → Python і код із Python → PowerShell дають однакові числа
    a = run_python([{"op": "reset"}, {"op": "import", "code": ps["codes"][0]}] + tail)
    b = run_ps([{"op": "reset"}, {"op": "import", "code": py["codes"][0]}] + tail, tmp_path)
    c = run_python([{"op": "reset"}, {"op": "import", "code": py["codes"][0]}] + tail)
    assert same(a, b) and same(a, c)
