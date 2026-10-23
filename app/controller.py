"""Контролер: стан панелі, такт 2 с, фонові запити, керування майнером і відеокартою, знімок для вікна, дії.

Порядок такту (як $timer у MinerPanel.ps1): фонові результати → нові запити → карта і майнер (облік,
резерв, перегрів, день/ніч, повторне застосування розгону, автопідбір) → ферма HiveOS → повідомлення → вікно.
Сторінки перебудовуються не частіше ніж раз на 10 с і ніколи, поки користувач щось редагує;
верхній рядок і значок біля годинника — щотакту."""
from __future__ import annotations

import json
import os
import socket
import time
import webbrowser
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer
from PySide6.QtWidgets import QApplication, QLineEdit, QAbstractSpinBox, QComboBox

from .core import economics as ec
from .core import events as ev
from .core import failover, hashrateno, hiveos, ledger, market, pools, servers, stats, storage, timeutil, updater
from .core import watchdog
from .core.gpu import Gpu
from .core.history import History
from .core.miners import MINERS, coin_miner_id
from .core.platform import IS_LINUX, IS_WIN, find_processes, kill_tree, set_autostart
from .core.runner import Runner
from .core.tuner import Phase, Tuner
from .ui import dialogs, theme
from .ui.main_window import MainWindow
from .ui.tray import Tray
from .ui.wizard import Wizard
from . import i18n
from .i18n import tr

TICK_MS = 2000
REBUILD_S = 10
POOL_MIN = 5
HIVE_S = 60


def _fmt_dur(sec: float) -> str:
    t = timedelta(seconds=int(sec))
    return tr('{0} д {1} год').format(t.days, t.seconds // 3600) if t.days else tr('{0} год {1:02d} хв').format(t.seconds // 3600, t.seconds % 3600 // 60)


def _addr(a: str) -> str:
    return f"{a[:9]}…{a[-6:]}" if len(a) > 18 else a


class Controller(QObject):
    def __init__(self, app: QApplication, test: bool = False, minimized: bool = False):
        super().__init__()
        self.app, self.test = app, test
        self.store = storage.Store(test=test).load()
        self.s = self.store.settings
        self.root = self.store.root
        if not self.s.get("UiLang"):
            # Уже налаштована панель лишається українською; новий користувач — мова системи
            old = self.s.get("WizardDone") or any(c.get("wallet") for c in self.store.coins)
            self.s["UiLang"] = "uk" if old else i18n.system_lang()
            self.store.save_settings()
        i18n.set_lang(os.environ.get("PANEL_LANG") or str(self.s["UiLang"]))
        self.gpu = Gpu(test)
        g0 = self.gpu.info()
        self.gpu_name = g0.name if g0 else "GPU"
        self.gpu_found = g0 is not None
        self.pl_range = (int(g0.min), int(g0.max)) if g0 else (100, 170)
        self.mem_off_lim = self.gpu.mem_offset_limits(self.gpu_name)
        self.runner = Runner(self.root, test)
        self.fo = failover.Failover()
        self.idle = stats.IdleMeter()
        self.watch = hiveos.Watch()
        self.tray = Tray()
        self.events = ev.Events(None if test else self.store.logs / "panel.log", self.tray.notify)
        self.history = History(":memory:" if test else self.root / "history.db")
        self.pool_exec = ThreadPoolExecutor(max_workers=4)
        self.jobs: dict[str, Future] = {}
        now = time.time()
        # Ринок, hashrate.no, релізи — з кешу, щоб прогноз і рейтинг було видно одразу
        self.market, mt = market.load_cache(self.root)
        self.market_error, self.market_next = None, now
        self.hrn = hashrateno.load_cache(self.root)
        self.hrn_error, self.hrn_next = None, now + 5
        self.releases = updater.load_cache(self.root)
        self.releases_error, self.releases_next = None, now + 20
        self.pool_data: dict | None = None
        self.pool_error, self.pool_next, self.pool_time = None, now, None
        self.ledger_next, self.ledger_error = now + 30, None
        self.hive: dict | None = None
        self.hive_error, self.hive_next = None, now
        self.hive_msg = ""
        self.install_msg = ""
        # Сервери пулу: вимір затримки раз на 5 хв і розумне перемикання (core/servers.py)
        self.sel = servers.Selector()
        self.preferred_server: str | None = None
        self.ping_next = now + 15
        self.ping_time = None
        # Живі дані цього ПК
        self.g = g0
        self.st: dict | None = None
        self.hr = self.hr15 = 0.0
        self.samples: deque = deque()
        self.session = {"kwh": 0.0, "cost": 0.0, "coins": 0.0, "last": now}
        self.day_acc: dict[str, dict] = {}
        self.last_sample: dict[str, float] = {}
        self.last_flush = now
        self.zone = self.wanted_zone()
        self.reapply_at: float | None = None
        self.last_guard = 0.0
        self.tuner: Tuner | None = None
        self.preview_coin: str | None = None
        self.period = "day"
        self.last_rebuild = 0.0
        self.dirty = True
        self.last_paid: float | None = None
        # Майнер, що вже працює (запущений раніше), — підхоплюємо
        if self.runner.adopt(self.coin(), lambda c: coin_miner_id(self.s, c)) and not test:
            self.fo.want_running = True
            self.events.log(tr('Підхоплено майнер, що вже працював: {0}').format(self.runner.miner.name))
        if IS_LINUX and not test and not Gpu.helper_installed():
            self.events.raise_(ev.Notice("helper", ev.WARN, tr('Розгін ще не дозволено'),
                                         tr('Щоб панель могла знижувати частоти і потужність, один раз виконай у терміналі: ./MinerPanel --install (запитає пароль). Майнити можна й без цього.'), None, None), toast=False)
        # Вікно і значок біля годинника
        theme.apply(app, str(self.s.get("UiTheme") or "dark"), str(self.s.get("UiFont") or "large"))
        self.win = MainWindow()
        self.win.action.connect(self.on_action)
        self.win.closing.connect(self.on_close)
        self.tray.requested.connect(self.on_tray)
        self.tray.show()
        if not self.s.get("WizardDone") and any(c.get("wallet") for c in self.store.coins):
            self.s["WizardDone"] = True        # уже налаштована панель зі старої версії
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(TICK_MS)
        self.tick()
        if not minimized:
            self.win.show()
        if not self.s.get("WizardDone"):
            QTimer.singleShot(300, self.run_wizard)

    # ---- монети, профілі, зони ----------------------------------------------
    def coin(self, cid: str | None = None) -> dict | None:
        return self.store.coin(cid)

    def running_coin(self) -> dict | None:
        return self.coin(self.runner.coin_id) if self.runner.coin_id else None

    def local_names(self) -> list[str]:
        return sorted({str(c.get("worker") or "worker") for c in self.store.coins})

    def night_split(self) -> bool:
        return bool(self.s.get("TwoZone", True)) and bool(self.s.get("NightProfile", True))

    def wanted_zone(self) -> str:
        return "night" if self.night_split() and ec.tariff_now(self.s)["night"] else "day"

    @staticmethod
    def zone_key(mode: str, zone: str) -> str:
        if mode == "eff":
            return "effNight" if zone == "night" else "eff"
        return mode + ("Night" if zone == "night" else "Day")

    def profile(self, coin: dict, key: str) -> dict:
        pk = ec.profile_key(coin)
        allp = self.s.setdefault("Profiles", {}).setdefault(pk, {})
        if not allp.get(key):
            if key.endswith("Night"):
                allp[key] = dict(self.profile(coin, self.zone_key(key[:-5] if key != "effNight" else "eff", "day")))
            else:
                r = ec.recommended(coin, self.pl_range[0], int(self.s.get("MaxPower", 150)))
                allp[key] = {"PL": r["PL"], "Core": r["Core"], "Mem": 0, "MemOff": 0}
        p = allp[key]
        p.setdefault("Mem", 0)
        p.setdefault("MemOff", 0)
        return p

    def active_profile(self) -> dict:
        c = self.running_coin() or self.coin()
        return self.profile(c, self.zone_key(str(self.s.get("Mode", "eff")), self.zone))

    def apply_active(self) -> None:
        p = self.active_profile()
        pl = max(self.pl_range[0], min(int(self.s.get("MaxPower", 150)), int(p["PL"])))
        mo = max(self.mem_off_lim["min"], min(self.mem_off_lim["max"], int(p.get("MemOff") or 0)))
        self.gpu.set_tuning(pl, int(p["Core"]), int(p.get("Mem") or 0), mo)

    def mode_text(self) -> str:
        n = tr(ec.MODE_NAMES.get(str(self.s.get("Mode")), ""))
        return n + (" · " + (tr('ніч') if self.zone == 'night' else tr('день')) if self.night_split() else "")

    # ---- майнер ---------------------------------------------------------------
    def start_mining(self, manual: bool = True) -> None:
        coin = self.coin()
        if not coin:
            return
        if not coin.get("wallet"):
            dialogs.info(self.win, tr('Старт'), tr('Для «{0}» не вказано гаманець. Додай його в розділі «Монети».').format(coin['name']), True)
            self.win.show_section("coins")
            return
        m = MINERS.get(coin_miner_id(self.s, coin))
        if not m:
            return
        if not updater.miner_exe(self.root, m):
            if not manual:
                return
            if dialogs.confirm(self.win, tr('Майнер'), tr('{0} ще не встановлено. Завантажити з офіційного GitHub (з перевіркою SHA256)?').format(m.name), tr('Завантажити')):
                self.install_miner(m.id, then_start=True)
            return
        if manual:
            self.preferred_server = None
        self.zone = self.wanted_zone()
        if not self.test:
            self.runner.stop_all()
            self.apply_active()
        urls = list((coin.get("pool") or {}).get("urls") or [])
        pref = self.preferred_server if self.preferred_server in urls else None
        ok, err = self.runner.start(coin, m, self.sel.order(urls, first=pref))
        if not ok:
            dialogs.info(self.win, tr('Старт'), err, True)
            return
        if not self.test and self.runner.proc:
            self.stop_watchdog()
            self.watchdog_pid = watchdog.start(self.runner.proc.pid)
        self.fo.started(manual)
        self.events.clear("temp")
        self.reapply_at = time.time() + 6
        self.session = {"kwh": 0.0, "cost": 0.0, "coins": 0.0, "last": time.time()}
        self.samples.clear()
        self.pool_next = time.time()
        self.events.log(tr('Старт: {0}, {1}, режим «{2}», сервери: {3}').format(coin['name'], m.name, self.mode_text(), ', '.join(self.runner.servers)))
        self.dirty = True

    def stop_mining(self, reason: str = "") -> None:
        self.fo.stopped()
        if self.tuner:
            self.tuner = None
        if not self.test:
            # Скидання робить сама панель, сторож більше не потрібен
            self.stop_watchdog()
            self.runner.stop_all()
            self.gpu.reset()
        self.runner.proc = None
        self.flush()
        self.store.save_settings()
        self.store.save_stats()
        self.events.log(tr('Стоп') + (f": {reason}" if reason else ""))
        self.dirty = True

    def stop_watchdog(self) -> None:
        pid = getattr(self, "watchdog_pid", None)
        self.watchdog_pid = None
        if pid:
            try:
                import psutil
                kill_tree(psutil.Process(pid))
            except Exception:  # noqa: BLE001 — сторож уже завершився
                pass

    def install_miner(self, mid: str, then_start: bool = False) -> None:
        m = MINERS.get(mid)
        if not m or "install" in self.jobs:
            return
        if self.test:
            self.install_msg = tr('тестовий режим: {0} не встановлюю (нічого не записую на диск)').format(m.name)
            return
        if self.runner.alive() and self.runner.miner and self.runner.miner.id == mid:
            dialogs.info(self.win, tr('Майнери'), tr('{0} зараз працює — спершу натисни Стоп.').format(m.name))
            return
        rel = self.releases.get(mid)
        self.install_msg = tr('Завантажую {0}…').format(m.name)

        def job():
            r = rel if rel and rel.get("Url") and rel.get("Digest") else updater.latest_release(m)
            path = updater.install(self.root, m, r)
            return r, path
        self.jobs["install"] = self.pool_exec.submit(job)
        self._install_then_start = then_start
        self._install_id = mid
        self.dirty = True

    # ---- такт -------------------------------------------------------------------
    def tick(self) -> None:
        now = time.time()
        try:
            self.collect_jobs(now)
            self.schedule_jobs(now)
            self.tick_local(now)
            self.tick_hive(now)
        except Exception as e:  # noqa: BLE001 — такт не має зупинятись через одну помилку
            self.events.log(tr('Помилка такту: {0}').format(e), ev.ERROR)
        snap = self.snapshot()
        self.win.update_header(snap)
        lv = snap["status"]
        self.tray.update_state(lv["level"], lv["text"], lv["running"])
        if self.dirty or now - self.last_rebuild >= REBUILD_S:
            if not self.user_busy():
                try:
                    self.win.render(snap)
                except Exception as e:  # noqa: BLE001 — помилку сторінки видно в журналі, а не мовчазне порожнє вікно
                    self.events.log(tr('Помилка показу сторінки: {0!r}').format(e), ev.ERROR)
                    import traceback
                    traceback.print_exc()
                self.last_rebuild, self.dirty = now, False

    def user_busy(self) -> bool:
        """Користувач щось вводить або відкрив список — сторінку не перебудовувати."""
        w = self.app.focusWidget()
        if isinstance(w, (QLineEdit, QAbstractSpinBox)) or (isinstance(w, QComboBox) and w.view().isVisible()):
            return True
        # Прапорець Qt порівнюємо з Qt.NoButton: порівняння з 0 у PySide6 завжди «так» (сторінка не оновлювалась б ніколи)
        return (QApplication.mouseButtons() != Qt.NoButton or QApplication.activePopupWidget() is not None
                or QApplication.activeModalWidget() is not None)

    def submit(self, name: str, fn, *a) -> None:
        if name not in self.jobs:
            self.jobs[name] = self.pool_exec.submit(fn, *a)

    def schedule_jobs(self, now: float) -> None:
        if now >= self.market_next and "market" not in self.jobs:
            cg = sorted({str(c["coingecko"]) for c in self.store.coins if c.get("coingecko")})
            cur = self.coin()
            tick_ids = sorted({str(c["coingecko"]) for c in self.store.coins + ([cur] if cur else [])
                               if c and c.get("coingecko") and (c is cur or ec.price_source(self.s, c) not in ("coingecko", "wtm"))})
            self.market_next = now + 120
            self.submit("market", market.fetch, cg, tick_ids)
        if now >= self.hrn_next and self.s.get("HashrateNoKey") and "hrn" not in self.jobs:
            self.hrn_next = now + 3600
            tickers = hashrateno.due_tickers(self.hrn, [str(c.get("ticker")) for c in self.store.coins])
            best = hashrateno.best_due(self.hrn)
            if best or tickers:
                self.submit("hrn", hashrateno.fetch, str(self.s["HashrateNoKey"]), best, tickers)
        cur = self.coin()
        if now >= self.pool_next and cur and cur.get("wallet") and "pool" not in self.jobs:
            self.pool_next = now + POOL_MIN * 60
            self.submit("pool", lambda c=dict(cur): (c["id"], pools.fetch(c)))
        if now >= self.ledger_next and "ledger" not in self.jobs:
            self.ledger_next = now + 60
            hive_keys = {ledger.ledger_key(c) for w in (self.hive or {}).get("workers", []) if w["online"]
                         for c in [hiveos.coin_for(self.store.coins, w)] if c}
            due, due_t = None, None
            for c in ledger.coins_to_fetch(self.store.coins, self.store.stats, cur, self.runner.coin_id, pools.POOLS, hive_keys):
                L = self.store.stats["ledger"].get(ledger.ledger_key(c))
                t = timeutil.parse(L.get("Time")) if L else None
                ts = t.timestamp() if t else 0
                if now - ts >= ledger.REFRESH_MIN * 60 and (due_t is None or ts < due_t):
                    due, due_t = c, ts
            if due:
                self.submit("ledger", lambda c=dict(due): (c["id"], pools.fetch(c)))
        if now >= self.hive_next and self.s.get("HiveOsToken") and "hive" not in self.jobs:
            self.hive_next = now + HIVE_S
            self.submit("hive", hiveos.fetch, str(self.s["HiveOsToken"]))
        pc = self.running_coin() or cur
        if now >= self.ping_next and pc and "ping" not in self.jobs:
            self.ping_next = now + servers.PING_EVERY_S
            urls = list((pc.get("pool") or {}).get("urls") or [])
            if urls:
                self.submit("ping", lambda u=urls, cid=pc["id"]: (cid, servers.probe(u)))
        if now >= self.releases_next and "releases" not in self.jobs:
            self.releases_next = now + 86400
            self.submit("releases", updater.check_all)

    def collect_jobs(self, now: float) -> None:
        for name, fut in list(self.jobs.items()):
            if not fut.done():
                continue
            del self.jobs[name]
            try:
                res = fut.result()
                err = None
            except Exception as e:  # noqa: BLE001
                res, err = None, str(e)
            self.dirty = True
            getattr(self, f"on_{name.split(':')[0]}")(res, err, name)

    # ---- результати фонових запитів ----
    def on_market(self, d, err, _n):
        if d:
            d = market.merge(self.market, d)
        if market.usable(d):
            self.market, self.market_error = d, None
            self.market_next = time.time() + market.next_delay(d, True).total_seconds()
            if not self.test:
                market.save_cache(self.root, d, timeutil.now())
        else:
            self.market_error = err or (d or {}).get("error") or tr('не вдалося завантажити')
            self.market_next = time.time() + market.next_delay(d or {}, False).total_seconds()

    def on_hrn(self, d, err, _n):
        if d:
            self.hrn_error = hashrateno.apply(self.hrn, d)
            if d.get("auth"):
                self.hrn_next = time.time() + 12 * 3600
            if not self.test:
                hashrateno.save_cache(self.root, self.hrn)
        else:
            self.hrn_error = err

    def on_pool(self, r, err, _n):
        cur = self.coin()
        if err or not r:
            self.pool_error = err or tr('немає відповіді')
            self.events.raise_(ev.Notice("pool:api", ev.INFO, tr('Статистика пулу тимчасово недоступна'),
                                         tr('Сайт пулу не відповідає ({0}). Майнінг від цього не залежить; повтор за {1} хв.').format(self.pool_error, POOL_MIN), None, None), toast=False)
            return
        cid, d = r
        if not cur or cid != cur["id"]:
            self.pool_next = time.time()
            return
        self.events.clear("pool:api")
        self.pool_data, self.pool_error, self.pool_time = d, None, timeutil.now()
        self._remember_pool(cur, d)
        if ledger.add_pool_snapshot(self.store.stats, cur, d, pools.pool_name(cur)):
            self.store.save_stats()
        paid = ((d.get("paid") or {}).get("total"))
        if paid is not None and self.last_paid is not None and paid > self.last_paid + 1e-9:
            self.events.once(ev.Notice("payout", ev.OK, tr('Пул зробив виплату'),
                                       tr('{0:.4f} {1} надіслано на твій гаманець.').format(paid - self.last_paid, cur['ticker']), None, None))
        if paid is not None:
            self.last_paid = paid

    def on_ledger(self, r, err, _n):
        if err or not r:
            self.ledger_error = err
            return
        cid, d = r
        c = self.coin(cid)
        if c:
            self._remember_pool(c, d)
        if c and ledger.add_pool_snapshot(self.store.stats, c, d, pools.pool_name(c)):
            self.ledger_error = None
            self.store.save_stats()

    def on_hive(self, d, err, _n):
        d = d or {"error": err}
        if d.get("error"):
            self.hive_error = d["error"]
            return
        self.hive_error = None
        self.hive = d
        stats.add_farm(self.store.stats, self.s, d["workers"])
        for w in d["workers"]:
            if w["online"] and w["power"] > 0:
                self._hist_sample(f"hive:{w['farmId']}/{w['id']}", w["hr"], w["maxTemp"], w["power"], time.time())

    def on_hivecmd(self, r, err, name):
        self.hive_msg = tr('{0} — {1} о {2:%H:%M:%S}').format(name.split(':', 1)[1], 'помилка: ' + err if err else 'виконано', datetime.now())
        self.events.log(f"HiveOS: {self.hive_msg}", ev.ERROR if err else ev.INFO)
        self.hive_next = time.time() + 5

    def current_server(self) -> str | None:
        return (self.st or {}).get("pool") or (self.runner.servers[0] if self.runner.servers else None)

    def on_ping(self, r, err, _n):
        if err or not r:
            return
        cid, res = r
        self.sel.add(res)
        self.ping_time = timeutil.now()
        coin = self.running_coin()
        if not coin or coin["id"] != cid or not self.runner.alive() or self.tuner or not self.s.get("ServerAuto", True):
            return
        urls = list((coin.get("pool") or {}).get("urls") or [])
        d = self.sel.decide(urls, self.current_server(), self.runner.started_at)
        if d and not self.test:
            self.sel.switched()
            self.preferred_server = d["url"]
            self.events.once(ev.Notice("server", ev.INFO, tr('Перехід на швидший сервер пулу'),
                                       d["reason"] + tr('. Майнер перезапуститься на кілька секунд.'), None, None))
            self.start_mining(manual=False)

    def on_pingp(self, r, err, _n):
        if r:
            self.sel.add(r)

    def on_releases(self, r, err, _n):
        rel, errors = r if r else ({}, [err])
        self.releases.update(rel)
        self.releases_error = errors[0] if errors else None
        if rel and not self.test:
            updater.save_cache(self.root, self.releases)
        if errors and not rel:
            self.releases_next = time.time() + 3600

    def on_install(self, r, err, _n):
        mid = getattr(self, "_install_id", "")
        m = MINERS.get(mid)
        if err:
            if IS_WIN and ("miner-dl-" in err or tr('антивірус') in err):
                self.install_msg = (tr('Windows Defender заблокував {0}. Антивіруси позначають майнери як «потенційно небажані» — файл з офіційного GitHub і перевіряється за SHA256.').format(m.name if m else mid))
                self.events.raise_(ev.Notice("defender", ev.WARN, tr('Defender заблокував майнер'),
                                             tr('Файл {0} з офіційного GitHub (SHA256 перевіряється) антивірус видалив під час завантаження. Можна дозволити лише теку майнерів (bin) — решта захисту лишається.').format(m.name if m else mid),
                                             tr('Дозволити теку bin'), f"defender:allow:{mid}"), toast=False)
            else:
                self.install_msg = tr('Не вдалося встановити {0}: {1}').format(m.name if m else mid, err)
            self.events.log(tr('Не вдалося встановити {0}: {1}').format(m.name if m else mid, err), ev.ERROR)
            return
        self.events.clear("defender")
        rel, path = r
        self.install_msg = tr('{0} {1} встановлено, SHA256 перевірено.').format(m.name, rel['Version'])
        self.events.log(self.install_msg, ev.OK)
        if getattr(self, "_install_then_start", False):
            self.start_mining(manual=True)

    # ---- цей ПК ----
    def tick_local(self, now: float) -> None:
        g = self.gpu.info()
        self.g = g or self.g
        running = self.runner.alive()
        if g:
            self.idle.update(self.s, g.draw, running)
        st = self.runner.stats() if running else None
        self.st = st
        if running and st:
            self.hr = float(st["hr"])
            if self.samples and st["uptime"] < self.samples[-1][2]:
                self.samples.clear()                                   # майнер перезапустився
            if self.hr > 0:
                self.samples.append((now, self.hr, st["uptime"]))
            while self.samples and now - self.samples[0][0] > 900:
                self.samples.popleft()
            self.hr15 = st["hr15"] if st.get("hr15") else (sum(x[1] for x in self.samples) / len(self.samples) if self.samples else 0.0)
            coin = self.running_coin()
            if coin and g:
                dt = min(10.0, now - self.session["last"])
                inc = stats.add_local(self.store.stats, self.s, self.market, coin, self.hr, g.draw, dt)
                self.session["kwh"] += inc["kwh"]
                self.session["cost"] += inc["cost"]
                self.session["coins"] += inc["coins"]
                old = self.day_acc.get("local")
                if old and old["ticker"] != coin["ticker"]:
                    # Перейшли на іншу монету — підсумок попередньої окремо, щоб монети різних тикерів не складались
                    self.history.add_daily("local", old["income"], old["cost"], old["kwh"], old["coins"], old["ticker"])
                    del self.day_acc["local"]
                acc = self.day_acc.setdefault("local", {"income": 0.0, "cost": 0.0, "kwh": 0.0, "coins": 0.0, "ticker": coin["ticker"]})
                for k in ("income", "cost", "kwh", "coins"):
                    acc[k] += inc[k]
                self._hist_sample("local", self.hr, g.temp, g.draw, now, str(coin["ticker"]))
                # Реальний хешрейт і споживання монети — для рейтингу і прогнозу
                if st["uptime"] > 120 and self.hr > 0:
                    mk = ec.profile_key(coin)
                    m = self.s.setdefault("Measured", {}).get(mk)
                    if not m:
                        self.s["Measured"][mk] = {"hr": self.hr, "watts": g.draw}
                    else:
                        m["hr"] = 0.95 * float(m["hr"]) + 0.05 * self.hr
                        m["watts"] = 0.95 * float(m["watts"]) + 0.05 * g.draw
            self.session["last"] = now
        else:
            self.hr = self.hr15 = 0.0
            self.session["last"] = now
            self.samples.clear()
        if now - self.last_flush >= 60:
            self.flush()
        # Резерв: автоперезапуск
        r = self.fo.tick(running, {"hr": self.hr, "accepted": st["accepted"]} if st else None, paused=bool(self.tuner))
        if r and not self.test:
            if r["shift"]:
                # Поточний сервер не працює — першим стане найшвидший із живих
                cur = self.current_server()
                for u in self.runner.servers:
                    if cur and servers.same_server(cur, u):
                        self.sel.mark_bad(u)
                self.preferred_server = None
            self.events.once(ev.Notice("failover", ev.WARN, tr('Майнер перезапущено'),
                                       tr('Причина: {0}. ').format(r['reason']) + (tr('Панель перейшла на найшвидший робочий сервер пулу. ') if r["shift"] else "")
                                       + tr('Нічого робити не треба.'), None, None))
            self.start_mining(manual=False)
        # Захист від перегріву
        if g and running and not self.test:
            mx = int(self.s.get("MaxTemp", 75))
            if g.temp >= mx + 8:
                self.stop_mining(tr('критична температура {0} °C').format(g.temp))
                self.events.raise_(ev.Notice("temp", ev.ERROR, tr('Майнінг зупинено: {0} °C').format(g.temp),
                                             tr('Карта нагрілась на 8 °C вище межі {0} °C. Розгін скинуто. Перевір охолодження, потім натисни Старт.').format(mx), tr('Старт'), "run:toggle"))
            elif not self.tuner and g.temp >= mx and now - self.last_guard >= 30:
                self.last_guard = now
                p = self.active_profile()
                core = int(p["Core"]) or g.core
                p["Core"] = max(1100, core - 100)
                self.apply_active()
                self.events.raise_(ev.Notice("temp", ev.WARN, tr('Гаряче: {0} °C').format(g.temp), tr('Панель знизила ядро до {0} МГц, щоб тримати ≤ {1} °C.').format(p['Core'], mx), None, None))
            elif g.temp < mx - 3:
                n = self.events.active.get("temp")
                if n and n.level == ev.WARN:         # аварійну зупинку прибирає лише новий старт
                    self.events.clear("temp")
        # День/ніч
        if not self.tuner:
            want = self.wanted_zone()
            if want != self.zone:
                self.zone = want
                if running:
                    self.apply_active()
                self.events.log(tr('Перемкнено на режим «{0}»').format(self.mode_text()))
                self.dirty = True
        if self.reapply_at and now >= self.reapply_at:
            self.reapply_at = None
            if running and not self.tuner:
                self.apply_active()
        if self.tuner:
            if not running:
                self.tuner = None
                self.events.log(tr('Майнер зупинився — автопідбір скасовано.'), ev.WARN)
            else:
                self.tuner.step(g.temp if g else None, int(self.s.get("MaxTemp", 75)), self.hr if st else None, g.draw if g else None, now)
                if self.tuner.done:
                    self.finish_tune()

    def _hist_sample(self, dev: str, hr: float, temp: float, watts: float, now: float, ticker: str = "") -> None:
        if now - self.last_sample.get(dev, 0) >= 60:
            self.last_sample[dev] = now
            self.history.add_sample(dev, hr, temp, watts, now, ticker)

    def _remember_pool(self, c: dict, d: dict) -> None:
        """Останній баланс і виплати пулу цієї монети — для «Усі монети» на Огляді (і після перемикання)."""
        bal, paid = d.get("balance") or {}, d.get("paid") or {}
        P = self.store.stats.setdefault("pools", {}).setdefault(ledger.ledger_key(c), {})
        P.update({"Coin": c.get("id"), "Ticker": c.get("ticker"), "Pool": pools.pool_name(c),
                  "Balance": float(bal.get("total") or 0), "Threshold": float(bal.get("threshold") or 0),
                  "Paid": float(paid.get("total") or 0), "Time": timeutil.iso()})
        # Усього нараховано адресі (виплачено + на балансі) на початок кожного дня — для «сьогодні / 7 днів» по всій адресі
        days = P.setdefault("Days", {})
        P.setdefault("Since", timeutil.iso())            # з якого моменту ведеться облік адреси
        days.setdefault(date.today().isoformat(), P["Balance"] + P["Paid"])
        for k in sorted(days)[:-40]:
            del days[k]

    def flush(self) -> None:
        """Підсумки доби → history.db; облік → stats.json; налаштування (виміри) → settings.json."""
        self.last_flush = time.time()
        for dev, a in self.day_acc.items():
            self.history.add_daily(dev, a["income"], a["cost"], a["kwh"], a["coins"], a["ticker"])
        self.day_acc.clear()
        self.store.save_stats()

    # ---- ферма ----
    def tick_hive(self, now: float) -> None:
        if not self.hive:
            return
        alerts, restart = self.watch.check(self.hive["workers"], bool(self.s.get("HiveAutoRestart")), now)
        keys = set()
        for a in alerts:
            k = "hive:" + a["key"]
            keys.add(k)
            w = a["worker"]
            if a["kind"] == "offline":
                n = ev.Notice(k, ev.ERROR, tr("{0} не на зв'язку").format(w['name']), tr('Риг {0} / {1} не відповідає HiveOS. Перевір живлення та інтернет рига.').format(w['farm'], w['name']),
                              tr('Відкрити'), f"open:device:hive:{a['key']}")
            elif a["kind"] == "stopped":
                n = ev.Notice(k, ev.WARN, tr('{0}: майнер зупинено').format(w['name']), tr('Риг онлайн, але майнер на ньому не працює, тож риг не заробляє.'),
                              tr('Запустити'), f"device:start:hive:{a['key']}")
            else:
                n = ev.Notice(k, ev.WARN, tr('{0}: немає хешрейту').format(w['name']), a["text"].split(": ", 1)[1].capitalize() + tr('. Перезапусти майнер, якщо так і лишиться.'),
                              tr('Перезапустити'), f"device:restart:hive:{a['key']}")
            self.events.raise_(n)
        self.events.clear_prefix("hive:", keep=keys)
        for w in restart:
            self.hive_command(w, "miner", "restart", tr('автоперезапуск майнера (немає хешрейту 10 хв)'))

    def hive_worker(self, key: str) -> dict | None:
        return next((w for w in (self.hive or {}).get("workers", []) if f"{w['farmId']}/{w['id']}" == key), None)

    def hive_command(self, w: dict, kind: str, value, what: str) -> None:
        if self.test:
            self.hive_msg = tr('тестовий режим: «{0}» не надіслано').format(what)
            return
        self.events.log(f"HiveOS {w['farm']}/{w['name']}: {what}")
        self.hive_msg = f"{w['name']}: {what}…"
        name = f"hivecmd:{w['name']}: {what}"
        self.jobs[name] = self.pool_exec.submit(hiveos.command, str(self.s["HiveOsToken"]), w, kind, value)

    # ---- автопідбір ----
    def start_tune(self) -> None:
        if not self.st:
            dialogs.info(self.win, tr('Автопідбір'), tr("Спочатку натисни Старт і дочекайся, поки з'явиться хешрейт."))
            return
        mode = str(self.s.get("Mode"))
        if mode == "custom":
            dialogs.info(self.win, tr('Автопідбір'), tr('«Свій» режим налаштовується вручну. Для автопідбору вибери «Економний» або «Максимальний дохід».'))
            return
        coin = self.running_coin()
        if mode == "profit" and not ec.coin_economics(self.market, self.s, coin, 1e9):
            dialogs.info(self.win, tr('Автопідбір'), tr('Для цієї монети ще немає ринкових даних — зачекай хвилину або вибери «Економний».'))
            return
        day, night = float(self.s["TariffDay"]), float(self.s["TariffNight"])
        if mode == "profit":
            if self.night_split():
                phases = [Phase(["profitDay"], day, tr('ДЕНЬ')), Phase(["profitNight"], night, tr('НІЧ'))]
            elif self.s.get("TwoZone", True):
                nh = ec.night_hours(self.s)
                phases = [Phase(["profitDay"], (nh * night + (24 - nh) * day) / 24, tr('ДОБА'))]
            else:
                phases = [Phase(["profitDay"], day, tr('ТАРИФ'))]
            base = int(self.profile(coin, "profitDay")["Core"]) or ec.recommended(coin, self.pl_range[0], int(self.s["MaxPower"]))["Core"]
        else:
            phases = [Phase(["eff", "effNight"], None, tr('ЕКОНОМНИЙ'))]
            base = ec.recommended(coin, self.pl_range[0], int(self.s["MaxPower"]))["Core"]
        p = self.active_profile()
        self.tuner = Tuner(phases, base, int(self.s.get("TuneCoreMax", 1800)), int(self.s.get("MaxPower", 150)),
                           int(p.get("Mem") or 0), int(p.get("MemOff") or 0),
                           lambda hr: ec.income_per_hour(self.market, self.s, coin, hr), self.gpu.set_tuning)
        self.tuner.add_log(tr('{0}, режим «{1}». Старт від {2} МГц, межі 1100–{3} МГц, {4} Вт, {5} °C').format(coin['name'], tr(ec.MODE_NAMES[mode]), base, self.s.get('TuneCoreMax'), self.s.get('MaxPower'), self.s.get('MaxTemp')))
        self.tuner.start()
        self.events.log(tr('Автопідбір розпочато'))
        self.dirty = True

    def finish_tune(self) -> None:
        t, coin = self.tuner, self.running_coin()
        self.tuner = None
        self._tune_log = t.log
        if not t.result:
            self.apply_active()
            return
        parts = []
        for ph, best, pl in t.result:
            pl = max(self.pl_range[0], min(int(self.s["MaxPower"]), pl))
            for k in ph.profiles:
                self.s["Profiles"].setdefault(ec.profile_key(coin), {})[k] = {"PL": pl, "Core": int(best["core"]), "Mem": t.mem, "MemOff": t.mem_off}
            parts.append(tr('{0}: {1} МГц / {2} Вт').format(ph.title.lower(), best['core'], pl))
        self.zone = self.wanted_zone()
        self.apply_active()
        self.store.save_settings()
        self.events.once(ev.Notice("tune", ev.OK, tr('Автопідбір завершено'), tr('Збережено — ') + ", ".join(parts) + ".", None, None))
        self.dirty = True

    # ---- дії ----------------------------------------------------------------
    def on_action(self, a: str) -> None:
        self.dirty = True
        parts = a.split(":")
        k = parts[0]
        try:
            if a == "run:toggle":
                self.stop_mining() if self.runner.alive() else self.start_mining()
            elif k == "theme":
                self.s["UiTheme"] = parts[1]
                self.store.save_settings()
                self.rebuild_window()
            elif k == "lang":
                self.set_lang(parts[1])
            elif k == "font":
                self.s["UiFont"] = parts[1]
                self.store.save_settings()
                self.rebuild_window()
            elif k == "mode":
                self.s["Mode"] = parts[1]
                if self.runner.alive():
                    self.apply_active()
                self.store.save_settings()
            elif k == "night":
                self.s["NightProfile"] = parts[1] == "1"
                self.store.save_settings()
            elif k == "tune":
                self.tune_action(parts[1:])
            elif k == "history":
                self.period = parts[1]
            elif k == "device":
                self.device_action(parts[1], ":".join(parts[2:]))
            elif k == "hive":
                self.hive_action(parts[1:])
            elif k == "coins" and parts[1] == "preview":
                self.preview_coin = ":".join(parts[2:])
                pc = self.coin(self.preview_coin)
                urls = list(((pc or {}).get("pool") or {}).get("urls") or [])
                if urls:
                    # Затримку серверів вибраної монети — одразу, щоб не було «ще не перевірено»
                    self.submit("pingp", lambda u=urls: servers.probe(u))
            elif k == "coin" and parts[1] == "apply":
                self.apply_coin(json.loads(a.split(":", 2)[2]))
            elif k == "wallet":
                self.wallet_action(parts[1], parts[2], ":".join(parts[3:]))
            elif k == "ledger":
                self.ledger_action(parts[1], ":".join(parts[2:]))
            elif k == "set":
                self.set_setting(parts[1], ":".join(parts[2:]))
            elif k == "hrn" and parts[1] == "key":
                v = ":".join(parts[2:])
                if v:
                    self.s["HashrateNoKey"] = v
                    self.store.save_settings()
                    self.hrn_next = time.time()
            elif k == "miner":
                if parts[1] == "check":
                    self.releases_next = 0
                elif parts[1] == "update" and len(parts) > 2 and parts[2]:
                    self.install_miner(parts[2])
                elif parts[1] == "rollback" and len(parts) > 2 and parts[2]:
                    prev = updater.rollback(self.root, parts[2])
                    self.install_msg = tr('Активна версія {0}.').format(prev) if prev else tr('Попередньої версії немає.')
                else:
                    dialogs.info(self.win, tr('Майнери'), tr('Вибери майнер у таблиці.'))
            elif k == "defender" and parts[1] == "allow":
                self.allow_defender(parts[2] if len(parts) > 2 else "")
            elif k == "wizard":
                self.run_wizard()
            elif k == "open" and parts[1] == "url":
                webbrowser.open(a.split(":", 2)[2])
            elif k == "open":
                self.win.show_section(parts[1])
        except Exception as e:  # noqa: BLE001
            self.events.log(tr('Помилка дії {0}: {1}').format(k, e), ev.ERROR)
            dialogs.info(self.win, tr('Помилка'), str(e), True)
        self.tick_soon()

    def tick_soon(self) -> None:
        QTimer.singleShot(50, self.tick)

    def tune_action(self, p: list[str]) -> None:
        if p[0] == "set":
            zone, key, val = p[1], p[2], int(float(p[3]))
            if self.s.get("Mode") != "custom":
                self.s["Mode"] = "custom"           # ручні значення — це «Свій» режим
            prof = self.profile(self.running_coin() or self.coin(), self.zone_key("custom", zone))
            prof[key] = val
            if self.runner.alive() and zone == self.zone:
                self.apply_active()
            self.store.save_settings()
        elif p[0] == "recommended":
            coin = self.running_coin() or self.coin()
            r = ec.recommended(coin, self.pl_range[0], int(self.s["MaxPower"]))
            for z in ("day", "night"):
                self.s["Profiles"].setdefault(ec.profile_key(coin), {})[self.zone_key(str(self.s["Mode"]), z)] = {"PL": r["PL"], "Core": r["Core"], "Mem": 0, "MemOff": 0}
            if self.runner.alive():
                self.apply_active()
            self.store.save_settings()
        elif p[0] == "auto":
            self.start_tune()
        elif p[0] == "cancel" and self.tuner:
            self._tune_log = self.tuner.log + [tr('Скасовано, попередні налаштування повернуто.')]
            self.tuner = None
            self.apply_active()

    def device_action(self, act: str, dev: str) -> None:
        if dev == "local":
            if act == "stop":
                self.stop_mining()
            elif act in ("start", "restart"):
                self.start_mining(manual=True)
            return
        w = self.hive_worker(dev.split(":", 1)[1])
        if not w:
            return
        if act == "stop" and not dialogs.confirm(self.win, "HiveOS", tr('Зупинити майнер на ризі {0}? Риг перестане майнити, доки не натиснеш «Старт».').format(w['name']), tr('Зупинити')):
            return
        self.hive_command(w, "miner", act, {"start": tr('старт майнера'), "stop": tr('зупинка майнера'), "restart": tr('перезапуск майнера')}[act])

    def hive_action(self, p: list[str]) -> None:
        if p[0] == "token":
            v = ":".join(p[1:])
            if v:
                self.s["HiveOsToken"] = v
                self.store.save_settings()
                self.hive, self.hive_error, self.hive_next = None, None, time.time()
        elif p[0] == "auto":
            self.s["HiveAutoRestart"] = p[1] == "1"
            self.store.save_settings()
        elif p[0] in ("fs", "oc"):
            key = p[2]
            w = self.hive_worker(key)
            idx = int(p[3])
            lst = (self.hive or {}).get(p[0], {}).get(str(w["farmId"]) if w else "", [])
            if not w or not (0 <= idx < len(lst)):
                return
            item = lst[idx]
            what = tr('польотний лист «{0}»').format(item['name']) if p[0] == "fs" else tr('профіль розгону «{0}»').format(item['name'])
            if dialogs.confirm(self.win, "HiveOS", tr('Застосувати {0} до рига {1}?').format(what, w['name']) +
                               (tr(' Майнер на ризі перезапуститься з монетою і пулом цього листа.') if p[0] == "fs" else ""), tr('Застосувати')):
                self.hive_command(w, p[0], item["id"], what)

    def apply_coin(self, d: dict, ask: bool = True) -> None:
        c = self.coin(d.get("coin"))
        if not c:
            return
        if d.get("miner") in MINERS:
            self.s.setdefault("Miner", {})[c["id"]] = d["miner"]
        worker = "".join(ch for ch in (d.get("worker") or "") if ch.isalnum() or ch in "_-")
        if worker and worker != c.get("worker"):
            c["worker"] = worker
            self.store.save_coins()
        if d.get("wallet"):
            self.store.wallet_book(c["ticker"])["active"] = d["wallet"]
            self.store.sync_coin_wallets()
            self.store.save_wallets()
        if d.get("price"):
            self.s.setdefault("PriceSource", {})[c["ticker"]] = d["price"]
        changed = self.s.get("Coin") != c["id"]
        self.s["Coin"] = c["id"]
        self.preview_coin = None
        self.pool_data, self.pool_error, self.pool_next = (self.pool_data if not changed else None), None, time.time()
        self.market_next = time.time()
        self.store.save_settings()
        if self.runner.alive():
            self.start_mining(manual=True)
        elif changed and ask and dialogs.confirm(self.win, tr('Монета'), tr('Вибрано {0}. Почати майнінг зараз?').format(c['name']), tr('Почати')):
            self.start_mining(manual=True)

    def wallet_action(self, act: str, cid: str, addr: str) -> None:
        c = self.coin(cid)
        if not c:
            return
        tk = c["ticker"]
        if act == "add":
            w = dialogs.wallet(self.win, tk)
            if w:
                self.store.add_wallet(tk, w["label"], w["address"])
        elif act == "edit" and addr:
            e = next((x for x in self.store.wallet_book(tk)["list"] if x["address"] == addr), {})
            w = dialogs.wallet(self.win, tk, e.get("label", ""), addr, edit=True)
            if w:
                self.store.edit_wallet(tk, addr, w["label"], w["address"])
        elif act == "remove" and addr:
            if dialogs.confirm(self.win, tr('Гаманець'), tr('Видалити з книги гаманець {0} для {1}? Монети на пулі від цього не зникнуть.').format(_addr(addr), tk), tr('Видалити')):
                self.store.remove_wallet(tk, addr)
        self.store.save_wallets()
        if self.runner.alive() and self.running_coin() and self.running_coin()["ticker"] == tk:
            self.events.log(tr('Гаманець змінено — нова адреса діятиме після перезапуску майнера.'))

    def ledger_action(self, act: str, arg: str) -> None:
        st, s = self.store.stats, self.s
        if act == "close":
            if not dialogs.confirm(self.win, tr('Бухгалтерія'), tr('Закрити період для всіх рахунків? Розподілене зараз зафіксується як нова контрольна точка. Після цього надішли код іншим учасникам, щоб у всіх були однакові числа.'), tr('Закрити період')):
                return
            ledger.close_period(st)
            self.store.save_stats()
            dialogs.code(self.win, tr('Код контрольної точки'), tr('Надішли цей код іншим учасникам (вони натиснуть «Вставити код від іншого учасника»):'),
                         ledger.export_code(s, st))
        elif act == "export":
            dialogs.code(self.win, tr('Код контрольної точки'), tr('Поточна контрольна точка, власники і видачі:'), ledger.export_code(s, st))
        elif act == "import":
            code = dialogs.code(self.win, tr('Імпорт контрольної точки'), tr('Встав код, який надіслав інший учасник (починається з MPK1:):'), "", readonly=False)
            if code:
                try:
                    msg = ledger.import_code(s, st, code)
                except ledger.CodeError as e:
                    dialogs.info(self.win, tr('Бухгалтерія'), tr('Не вдалося імпортувати: {0}').format(e), True)
                    return
                self.store.save_stats()
                self.store.save_settings()
                dialogs.info(self.win, tr('Бухгалтерія'), msg)
        elif act == "owner":
            if not arg:
                dialogs.info(self.win, tr('Бухгалтерія'), tr('Вибери воркера в таблиці.'))
                return
            cur = (s.get("WorkerOwners") or {}).get(arg) or ledger.worker_owner(s, self.local_names(), arg)
            o = dialogs.owner(self.win, arg, ledger.owner_names(s, st), cur)
            if o is not None:
                ledger.set_worker_owner(s, arg, o)
                self.store.save_settings()
        elif act == "payout":
            tickers = sorted({L["Ticker"] for L in st["ledger"].values()})
            if not tickers:
                dialogs.info(self.win, tr('Бухгалтерія'), tr('Ще немає нарахувань.'))
                return
            t = ledger.owner_totals(s, st, self.local_names())
            left = {(o, tk): v["Mined"] - v["Paid"] for o, x in t.items() for tk, v in x.items()}
            p = dialogs.payout(self.win, ledger.owner_names(s, st), tickers, left)
            if p:
                ledger.add_payout(st, p["owner"], p["ticker"], p["coins"], p["note"])
                self.store.save_stats()

    def allow_defender(self, mid: str) -> None:
        path = (self.root / "bin").resolve()
        if not dialogs.confirm(self.win, "Microsoft Defender",
                               tr("Додати теку {0} у виключення Microsoft Defender?\n\nDefender не перевірятиме лише файли в цій теці (там тільки майнери з офіційного GitHub, кожен перевіряється за SHA256). Решта комп'ютера захищена як і раніше. Прибрати виключення можна в «Безпека Windows» → «Захист від вірусів» → «Виключення».").format(path), tr('Дозволити')):
            return
        if self.test:
            self.install_msg = tr('тестовий режим: виключення не додано')
            return
        err = updater.allow_in_defender(self.root)
        if err:
            dialogs.info(self.win, "Microsoft Defender", tr('Не вдалося додати виключення: {0}').format(err), True)
            return
        self.events.clear("defender")
        self.events.log(tr('Додано виключення Defender для {0}').format(path))
        if mid in MINERS:
            self.install_miner(mid, then_start=getattr(self, "_install_then_start", False))

    def set_setting(self, key: str, v: str) -> None:
        types = {"TwoZone": bool, "Autostart": bool, "MinimizeToTray": bool, "ServerAuto": bool, "TariffDay": float, "TariffNight": float,
                 "NightFrom": int, "NightTo": int, "MaxTemp": int, "MaxPower": int, "TuneCoreMax": int}
        if key not in types:
            return
        t = types[key]
        val = (v == "1") if t is bool else t(float(v))
        self.s[key] = val
        if key == "Autostart" and not self.test:
            set_autostart(val)
        if key == "MaxPower" and self.runner.alive():
            self.apply_active()
        self.store.save_settings()

    def wizard_data(self) -> dict:
        """Справжні дані для майстра: карта, тариф, монети від найвигіднішої, пули й майнери з комісіями."""
        from .snapshot import _coin_name, _is_ru, miner_items, pool_items
        s, coins = self.s, self.store.coins
        rank = ec.ranking(coins, self.market, s, self.hrn, self.gpu_name)
        best: dict[str, tuple[str, float | None]] = {}       # тикер → (найвигідніший не-російський пул, прибуток)
        for r in rank:
            c = r["coin"]
            tk = str(c.get("ticker") or c["id"])
            if tk not in best or _is_ru(self.coin(best[tk][0]) or {}) and not _is_ru(c):
                best[tk] = (c["id"], r["profit"])
        items = [(tk, tr('{0} — ≈ {1}/добу').format(_coin_name(self.coin(cid) or {}), ec.fmt_uah(p)) if p is not None else _coin_name(self.coin(cid) or {}))
                 for tk, (cid, p) in best.items()]
        cur = self.coin() or {}
        worker = "".join(ch for ch in socket.gethostname() if ch.isalnum() or ch in "_-")[:32] or "rig"   # ім'я ПК — типове ім'я воркера
        name = self.gpu_name if self.gpu_name.upper().startswith("NVIDIA") else f"NVIDIA GeForce {self.gpu_name}"
        return {"gpu": name if self.gpu_found else None,
                "two": bool(s.get("TwoZone", True)), "day": float(s.get("TariffDay", 4.32)), "night": float(s.get("TariffNight", 2.16)),
                "night_hours": f"{int(s.get('NightFrom', 23)):02d}:00–{int(s.get('NightTo', 7)):02d}:00",
                "coins": items, "ticker": str(cur.get("ticker") or ""),
                "coin_default": {tk: (cur["id"] if cur.get("ticker") == tk else cid) for tk, (cid, _) in best.items()},
                "pools": {tk: pool_items(s, coins, tk) for tk in best},
                "miners": {c["id"]: miner_items(self.root, c) for c in coins},
                "miner_default": {c["id"]: coin_miner_id(s, c) for c in coins},
                "wallets": {tk: self.store.wallet_book(tk).get("active", "") for tk in best},
                "worker": str(cur.get("worker") or worker),
                "coins_note": "" if any(p is not None for _, p in best.values()) else
                              tr("Прибуток з'явиться, щойно завантажаться ринкові дані (до хвилини) — його видно на сторінці «Монети».")}

    def set_lang(self, code: str) -> None:
        self.s["UiLang"] = code if code in i18n.LANGS else "uk"
        i18n.set_lang(self.s["UiLang"])
        self.store.save_settings()
        self.tray.retranslate()
        self.rebuild_window()

    def run_wizard(self) -> None:
        while True:
            wz = Wizard(self.win, self.wizard_data())
            wz.finished_ok.connect(self.wizard_done)
            wz.exec()
            if not wz.new_lang:          # мову змінено — відкрити майстер заново вже цією мовою
                break
            self.set_lang(wz.new_lang)
        self.s["WizardDone"] = True              # і після «Пропустити» майстер більше сам не з'являється
        self.store.save_settings()

    def wizard_done(self, d: dict) -> None:
        self.s["TwoZone"], self.s["TariffDay"], self.s["TariffNight"] = bool(d["two"]), float(d["day"]), float(d["night"])
        if d.get("hive"):
            self.hive_action(["token", d["hive"]])
        c = self.coin(d.get("coin"))
        if not c:
            return
        if d.get("address"):
            self.store.add_wallet(c["ticker"], tr('Мій гаманець'), d["address"])
            self.store.save_wallets()
        self.apply_coin({"coin": c["id"], "miner": d.get("miner"), "wallet": d.get("address"), "worker": d.get("worker")}, ask=False)
        if d.get("address") and not self.runner.alive():
            self.start_mining(manual=True)

    def rebuild_window(self) -> None:
        geo, sec, vis = self.win.saveGeometry(), self.win.current_section(), self.win.isVisible()
        self.win.closing.disconnect()
        self.win.hide()
        self.win.deleteLater()
        theme.apply(self.app, str(self.s.get("UiTheme") or "dark"), str(self.s.get("UiFont") or "large"))
        self.win = MainWindow()
        self.win.restoreGeometry(geo)
        self.win.action.connect(self.on_action)
        self.win.closing.connect(self.on_close)
        self.win.render(self.snapshot())
        self.win.show_section(sec)
        if vis:
            self.win.show()

    # ---- закриття ----
    def on_close(self, e) -> None:
        if self.s.get("MinimizeToTray", False) and self.tray.isVisible() and not getattr(self, "_quitting", False):
            e.ignore()
            self.win.hide()
            if not getattr(self, "_tray_hint", False):
                self._tray_hint = True
                self.tray.showMessage(tr('Miner Panel працює'), tr('Панель згорнулась біля годинника, майнінг триває. Вийти — правий клік по значку.'))
            return
        self.quit()

    def on_tray(self, k: str) -> None:
        if k == "open":
            self.win.showNormal()
            self.win.raise_()
            self.win.activateWindow()
        elif k == "run:toggle":
            self.on_action("run:toggle")
        elif k == "quit":
            if self.runner.alive() and not dialogs.confirm(None, "Miner Panel", tr('Вийти? Майнінг зупиниться, розгін відеокарти скинеться.'), tr('Вийти')):
                return
            self.quit()

    def quit(self) -> None:
        self._quitting = True
        self.timer.stop()
        if self.runner.alive():
            self.stop_mining(tr('вихід з панелі'))
        else:
            self.flush()
            self.store.save_settings()
        self.pool_exec.shutdown(wait=False, cancel_futures=True)
        self.tray.hide()
        self.app.quit()

    # ---- знімок для вікна -------------------------------------------------------
    def snapshot(self) -> dict:
        from .snapshot import build
        return build(self)


def run(app: QApplication, test: bool = False, minimized: bool = False) -> int:
    c = Controller(app, test=test, minimized=minimized)
    app._controller = c          # тримати посилання
    return app.exec()
