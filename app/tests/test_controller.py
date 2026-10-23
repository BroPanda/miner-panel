"""Контролер у тестовому режимі на копії справжніх даних: дії користувача не падають і змінюють стан як треба.
Відеокарту не чіпає, файли не пише, команд у HiveOS не надсилає (test=True)."""
import json
import os
import shutil
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def ctl(tmp_path_factory):
    d = tmp_path_factory.mktemp("data")
    for f in ("settings.json", "coins.json", "wallets.json", "stats.json", "market-cache.json", "hashrateno-cache.json", "releases-cache.json"):
        if (ROOT / f).exists():
            shutil.copy(ROOT / f, d / f)
    if (ROOT / "bin" / "srbminer").exists():
        shutil.copytree(ROOT / "bin" / "srbminer", d / "bin" / "srbminer", dirs_exist_ok=True)
    else:                                   # чиста копія репозиторію (GitHub): «встановлений» порожній майнер
        from app.core.miners import MINERS
        (d / "bin" / "srbminer" / "0.0").mkdir(parents=True)
        (d / "bin" / "srbminer" / "current.txt").write_text("0.0")
        (d / "bin" / "srbminer" / "0.0" / MINERS["srbminer"].exe_name).write_bytes(b"")
    if not (d / "wallets.json").exists():   # і тестовий гаманець для типової монети (Pearl)
        (d / "wallets.json").write_text(json.dumps({"PRL": {"active": "prl1ci0", "list": [{"label": "CI", "address": "prl1ci0"}]}}))
    os.environ["MINERPANEL_HOME"] = str(d)
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from app import controller
    from app.ui import dialogs
    answers = {"confirm": True}
    dialogs.confirm = lambda *a, **k: answers["confirm"]
    dialogs.info = lambda *a, **k: None
    dialogs.code = lambda *a, **k: None
    dialogs.wallet = lambda parent, tk, *a, **k: {"label": "Тест", "address": "prl1testaddress000000000000000000000000"}
    dialogs.owner = lambda *a, **k: "Петро"
    dialogs.payout = lambda *a, **k: {"owner": "Петро", "ticker": "PRL", "coins": 0.001, "note": "тест"}
    c = controller.Controller(app, test=True, minimized=True)
    c.timer.stop()
    yield c
    c.pool_exec.shutdown(wait=False, cancel_futures=True)
    os.environ.pop("MINERPANEL_HOME", None)


def act(c, a):
    c.on_action(a)
    c.tick()
    return c.snapshot()


def test_snapshot_has_all_sections(ctl):
    s = ctl.snapshot()
    for k in ("status", "devices", "notices", "ledger", "coins", "miners", "settings", "journal", "forecast", "balance"):
        assert k in s
    assert s["devices"][0]["id"] == "local"


def test_modes_and_manual_tuning(ctl):
    act(ctl, "mode:eff")
    assert ctl.s["Mode"] == "eff"
    act(ctl, "tune:set:day:PL:120")
    assert ctl.s["Mode"] == "custom"
    coin = ctl.running_coin() or ctl.coin()
    assert ctl.s["Profiles"][coin["ticker"]]["customDay"]["PL"] == 120
    act(ctl, "tune:set:night:Mem:810")
    assert ctl.s["Profiles"][coin["ticker"]]["customNight"]["Mem"] == 810
    act(ctl, "night:0")
    assert ctl.wanted_zone() == "day"
    act(ctl, "tune:recommended")


def test_settings_and_theme(ctl):
    act(ctl, "set:TariffDay:5.1")
    assert ctl.s["TariffDay"] == 5.1
    act(ctl, "set:TwoZone:0")
    assert ctl.s["TwoZone"] is False
    act(ctl, "set:TwoZone:1")
    act(ctl, "font:huge")
    assert ctl.s["UiFont"] == "huge"
    act(ctl, "theme:light")
    act(ctl, "theme:dark")
    act(ctl, "set:Unknown:1")            # невідомий ключ ігнорується


def test_coin_wallet_and_apply(ctl):
    cur = ctl.coin()
    act(ctl, f"coins:preview:{cur['id']}")
    act(ctl, f"wallet:add:{cur['id']}")
    assert any(w["address"].startswith("prl1test") for w in ctl.store.wallet_book(cur["ticker"])["list"])
    d = {"coin": cur["id"], "miner": "srbminer", "wallet": ctl.store.wallet_book(cur["ticker"])["active"], "worker": "rtx3060", "price": "coingecko"}
    act(ctl, "coin:apply:" + json.dumps(d))
    assert ctl.s["Coin"] == cur["id"] and ctl.s["Miner"][cur["id"]] == "srbminer"
    act(ctl, f"wallet:remove:{cur['id']}:prl1testaddress000000000000000000000000")
    assert not any(w["address"].startswith("prl1test") for w in ctl.store.wallet_book(cur["ticker"])["list"])


@pytest.mark.skipif(not (ROOT / "stats.json").exists(), reason="потрібні справжні нарахування (stats.json); логіку обліку перевіряє test_ledger")
def test_ledger_actions(ctl):
    act(ctl, "ledger:owner:apitest")
    assert ctl.s["WorkerOwners"]["apitest"] == "Петро"
    act(ctl, "ledger:payout")
    assert ctl.store.stats["payouts"][-1]["Owner"] == "Петро"
    act(ctl, "ledger:close")
    act(ctl, "ledger:export")
    s = ctl.snapshot()
    assert any(r[0] == "Петро" for r in s["ledger"]["owners"])


def test_start_stop_in_test_mode(ctl):
    ctl.runner.proc = None
    ctl.s["Miner"][ctl.coin()["id"]] = "srbminer"
    ctl.start_mining(manual=True)
    assert ctl.fo.want_running and ctl.runner.servers
    ctl.stop_mining()
    assert not ctl.fo.want_running
    ctl.install_miner("bzminer")                 # у тестовому режимі нічого не завантажує
    assert "install" not in ctl.jobs and "тестовий режим" in ctl.install_msg


def test_hive_flow(ctl):
    w = {"id": 101, "farmId": 1, "farm": "Дім", "name": "rig1", "online": True, "minerOn": False, "power": 120, "hr": 0, "coin": "",
         "algo": "", "miner": "", "acc": 0, "rej": 0, "maxTemp": 41, "minerStart": 0, "bootTime": 0, "fsId": 11, "fsName": "PRL",
         "fsPools": ["HeroMiners"], "ocId": 0, "gpus": []}
    ctl.hive = {"workers": [w], "fs": {"1": [{"id": 11, "name": "PRL", "coins": ["PRL"], "pools": ["HeroMiners"]}]}, "oc": {"1": []}}
    ctl.tick_hive(0)
    s = ctl.snapshot()
    assert any(n.key == "hive:1/101" for n in s["notices"]) and s["devices"][1]["state"] == "warn"
    act(ctl, "device:start:hive:1/101")
    assert "тестовий режим" in ctl.hive_msg
    act(ctl, "hive:fs:x:1/101:0")
    act(ctl, "hive:auto:1")
    assert ctl.s["HiveAutoRestart"] is True


def test_tick_rebuilds_page(ctl):
    # Без дій користувача такт сам перебудовує сторінку (була вада: user_busy() завжди True)
    assert not ctl.user_busy()
    ctl.last_rebuild = 0
    ctl.tick()
    assert ctl.last_rebuild > 0


def test_render_every_page(ctl):
    ctl.win.render(ctl.snapshot())
    for k in ctl.win.pages:
        ctl.win.show_section(k)


def test_wizard_saves_choice(ctl):
    from app.ui.wizard import Wizard
    d = ctl.wizard_data()
    assert d["coins"] and all(d["pools"][tk] for tk, _ in d["coins"])
    wz = Wizard(None, d)                                   # справжні дані відмальовуються без помилок
    wz.addr.setText("prl1wizardaddress0000000000000000000000")
    r = wz.result_data()
    assert any(r["coin"] == i for i, _ in d["pools"][wz.coin.currentData()])     # пул — з вибраної монети
    r.update(day=5.5, night=2.5, worker="Wizard PC")
    ctl.wizard_done(r)
    c = ctl.coin()
    assert c["id"] == r["coin"] and ctl.s["TariffDay"] == 5.5 and ctl.s["TariffNight"] == 2.5
    assert ctl.store.wallet_book(c["ticker"])["active"] == "prl1wizardaddress0000000000000000000000"
    assert c["worker"] == "WizardPC"                        # пробіл у імені воркера прибрано
    ctl.stop_mining()


def test_first_run_has_default_coins(tmp_path):
    from app.core.default_coins import DEFAULT_COINS
    from app.core.storage import Store
    s = Store(root=tmp_path).load()                        # порожня тека — новий користувач
    assert len(s.coins) == len(DEFAULT_COINS) and not s.wallets
    assert not any(c.get("wallet") or c.get("worker") for c in s.coins)
    assert s.settings["Coin"] == "pearl-herominers" and not s.settings["HiveOsToken"] and not s.settings["HashrateNoKey"]
    assert (tmp_path / "coins.json").exists()


def test_switch_language(ctl):
    from app import i18n
    act(ctl, "lang:en")
    assert i18n.LANG == "en" and ctl.s["UiLang"] == "en"
    assert ctl.win.nav_buttons["settings"].text().strip() == "Settings"     # вікно перебудовано англійською
    act(ctl, "lang:uk")
    assert i18n.LANG == "uk" and ctl.win.nav_buttons["settings"].text().strip() == "Налаштування"


def test_summary_ticker_is_current_coin(ctl):
    # Регресія: цикл форми «Монета / Пул» перезаписував тикер поточної монети (на «Огляді» був QUAN замість PRL)
    s = ctl.snapshot()
    assert s["summary"]["ticker"] == ctl.coin()["ticker"]
