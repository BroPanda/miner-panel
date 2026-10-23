"""Файли даних панелі — ті самі, що й у PowerShell-версії, у тих самих форматах:
settings.json, coins.json, wallets.json, stats.json (+ кеші market/hashrate.no).

PowerShell 5.1 пише UTF-8 з BOM і читає без нього теж, тож читаємо `utf-8-sig`, а пишемо з BOM,
щоб обидві версії могли працювати з однією текою, поки нова не замінить стару.
Тека даних: MINERPANEL_HOME, інакше поруч із програмою (зібраний .exe / AppImage),
інакше корінь репозиторію (батьківська тека app/)."""
from __future__ import annotations

import copy
import json
import os
import sys
from pathlib import Path
from typing import Any
from ..i18n import tr


def data_dir() -> Path:
    env = os.environ.get("MINERPANEL_HOME")
    if env:
        return Path(env)
    if getattr(sys, "frozen", False):
        # AppImage розпаковується в тимчасову теку — дані поруч із самим файлом AppImage
        appimage = os.environ.get("APPIMAGE")
        return Path(appimage).parent if appimage else Path(sys.executable).parent
    return Path(__file__).resolve().parents[2]


def read_json(path: Path, default: Any = None) -> Any:
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except (OSError, ValueError):
        return copy.deepcopy(default)


def write_json(path: Path, obj: Any, indent: int | None = 4) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8-sig") as f:
        json.dump(obj, f, ensure_ascii=False, indent=indent)
    os.replace(tmp, path)


# Типові налаштування — як $Settings у MinerPanel.ps1
DEFAULT_SETTINGS: dict[str, Any] = {
    "Coin": "pearl-herominers", "Mode": "eff", "NightProfile": True,
    "TariffDay": 4.32, "TariffNight": 2.16, "NightFrom": 23, "NightTo": 7,
    "MaxTemp": 75, "MaxPower": 150, "TuneCoreMax": 1800,
    "Profiles": {}, "Miner": {}, "Measured": {}, "PriceSource": {}, "TwoZone": True, "UiTab": "main",
    "HashrateNoKey": "", "IdleWatts": 0,
    "WorkerOwners": {}, "HiveOsToken": "", "HiveWorkerMap": {}, "HiveAutoRestart": False,
    # Лише нова версія
    "UiExpert": False, "UiTheme": "dark", "UiFont": "large", "WizardDone": False, "UiLang": "", "Autostart": False, "MinimizeToTray": False, "ServerAuto": True,
}


class Store:
    """Усі дані панелі в пам'яті + запис на диск. У тестовому режимі нічого не записує."""

    def __init__(self, root: Path | None = None, test: bool = False):
        self.root = Path(root) if root else data_dir()
        self.test = test
        self.settings: dict[str, Any] = copy.deepcopy(DEFAULT_SETTINGS)
        self.coins: list[dict[str, Any]] = []
        self.wallets: dict[str, Any] = {}
        self.stats: dict[str, Any] = {"ledger": {}, "payouts": [], "local": {}, "farm": {}, "pools": {}}

    # ---- шляхи ----
    def path(self, name: str) -> Path:
        return self.root / name

    @property
    def logs(self) -> Path:
        p = self.root / "logs"
        if not self.test:
            p.mkdir(parents=True, exist_ok=True)
        return p

    # ---- завантаження ----
    def load(self) -> "Store":
        s = read_json(self.path("settings.json"), {})
        if isinstance(s, dict):
            for k, v in s.items():
                self.settings[k] = v
        for k in ("Profiles", "Miner", "Measured", "PriceSource", "WorkerOwners", "HiveWorkerMap"):
            if not isinstance(self.settings.get(k), dict):
                self.settings[k] = {}
        coins = read_json(self.path("coins.json"), None)
        if coins is None:
            # Новий користувач (немає coins.json): стартовий список без гаманців
            from .default_coins import DEFAULT_COINS
            self.coins = copy.deepcopy(DEFAULT_COINS)
            self.save_coins()
        else:
            self.coins = coins if isinstance(coins, list) else [coins]
        w = read_json(self.path("wallets.json"), None)
        if isinstance(w, dict):
            self.wallets = w
        else:
            # Перший запуск: адреси з coins.json → книга гаманців (як у PowerShell-версії)
            self.wallets = {}
            for c in self.coins:
                if c.get("ticker") and c.get("wallet"):
                    self.add_wallet(c["ticker"], tr('Імпортовано'), c["wallet"], activate=False)
            self.save_wallets()
        self.sync_coin_wallets()
        if not any(c.get("id") == self.settings.get("Coin") for c in self.coins) and self.coins:
            self.settings["Coin"] = self.coins[0]["id"]
        self.load_stats()
        return self

    def load_stats(self) -> None:
        from . import ledger  # уникаємо циклічного імпорту
        s = read_json(self.path("stats.json"), {})
        if not isinstance(s, dict):
            return
        self.stats["ledger"] = s.get("ledger") if isinstance(s.get("ledger"), dict) else {}
        p = s.get("payouts")
        self.stats["payouts"] = [x for x in (p if isinstance(p, list) else [p] if p else []) if x]
        self.stats["local"] = s.get("local") if isinstance(s.get("local"), dict) else {}
        self.stats["farm"] = s.get("farm") if isinstance(s.get("farm"), dict) else {}
        # Останній відомий баланс кожного пулу — щоб бачити монети, що лишились після перемикання
        self.stats["pools"] = s.get("pools") if isinstance(s.get("pools"), dict) else {}
        old = s.get("pool")
        if isinstance(old, dict) and old:
            for k, v in old.items():
                self.stats["ledger"].setdefault(k, ledger.from_old_ledger(v))
        ledger.repair_accounts(self.stats["ledger"])

    # ---- запис ----
    def save_settings(self) -> None:
        if not self.test:
            write_json(self.path("settings.json"), self.settings)

    def save_coins(self) -> None:
        if not self.test:
            # Адреси гаманців живуть у wallets.json, у coins.json їх не пишемо
            write_json(self.path("coins.json"), [{k: v for k, v in c.items() if k != "wallet"} for c in self.coins])

    def save_wallets(self) -> None:
        if not self.test:
            write_json(self.path("wallets.json"), self.wallets)

    def save_stats(self) -> None:
        if not self.test:
            write_json(self.path("stats.json"), self.stats)

    # ---- монети і гаманці ----
    def coin(self, coin_id: str | None = None) -> dict[str, Any] | None:
        cid = coin_id or self.settings.get("Coin")
        return next((c for c in self.coins if c.get("id") == cid), None)

    def wallet_book(self, ticker: str) -> dict[str, Any]:
        b = self.wallets.get(ticker)
        if not isinstance(b, dict):
            b = self.wallets[ticker] = {"active": "", "list": []}
        if not isinstance(b.get("list"), list):
            b["list"] = [b["list"]] if b.get("list") else []
        return b

    def add_wallet(self, ticker: str, label: str, address: str, activate: bool = True) -> None:
        b = self.wallet_book(ticker)
        if not any(x.get("address") == address for x in b["list"]):
            b["list"].append({"label": label, "address": address})
        if activate or not b.get("active"):
            b["active"] = address
        self.sync_coin_wallets()

    def edit_wallet(self, ticker: str, old: str, label: str, address: str) -> None:
        b = self.wallet_book(ticker)
        b["list"] = [{"label": label, "address": address} if x.get("address") == old else x for x in b["list"]]
        if b.get("active") == old:
            b["active"] = address
        self.sync_coin_wallets()

    def remove_wallet(self, ticker: str, address: str) -> None:
        b = self.wallet_book(ticker)
        b["list"] = [x for x in b["list"] if x.get("address") != address]
        if b.get("active") == address:
            b["active"] = b["list"][0]["address"] if b["list"] else ""
        self.sync_coin_wallets()

    def sync_coin_wallets(self) -> None:
        """Ставить у записи монет (у пам'яті) активну адресу їхнього тікера."""
        for c in self.coins:
            b = self.wallets.get(str(c.get("ticker")))
            c["wallet"] = str(b.get("active", "")) if isinstance(b, dict) else ""
