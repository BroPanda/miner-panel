"""Точка входу Miner Panel 2.

  MinerPanel                    — звичайний запуск (Windows сам попросить права адміністратора)
  MinerPanel --minimized        — запуск згорнутим біля годинника (автозапуск із системою)
  MinerPanel --test             — справжні дані, але відеокарту не чіпає, файли не змінює, команд у HiveOS не надсилає
  MinerPanel --demo             — макет на зразкових даних
  MinerPanel --install          — Linux: дозволити розгін (помічник + правило sudo) і додати ярлик у меню
  PANEL_TEST_SNAP=<тека>        — разом з --test або --demo: зберегти знімки всіх розділів і вийти
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def _settle(app) -> None:
    # Компонування в прокрутці перераховується за кілька проходів подій — у живому вікні це відбувається само
    for _ in range(4):
        app.processEvents()


def _grab_all(app, win, render, out: Path, prefix: str) -> list[Path]:
    saved = []
    win.resize(1240, 860)
    win.show()
    render()
    for key in win.pages:
        win.show_section(key)
        if key == "money":
            for i, sub in enumerate(("balance", "ledger", "energy")):
                win.pages["money"].tabs.setCurrentIndex(i)
                _settle(app)
                f = out / f"{prefix}-money-{sub}.png"
                win.grab().save(str(f))
                saved.append(f)
            continue
        if key == "devices":
            for dev in [d["id"] for d in win.snap["devices"]][:2]:
                win.pages["devices"].select(dev)
                win.show_section("devices")
                _settle(app)
                f = out / f"{prefix}-devices-{dev.replace(':', '_').replace('/', '_')}.png"
                win.grab().save(str(f))
                saved.append(f)
            continue
        _settle(app)
        f = out / f"{prefix}-{key}.png"
        win.grab().save(str(f))
        saved.append(f)
    return saved


def snapshots_demo(app, out: Path) -> list[Path]:
    from .ui import sample, theme
    from .ui.main_window import MainWindow
    from .ui.wizard import Wizard
    out.mkdir(parents=True, exist_ok=True)
    saved = []
    for tname in ("dark", "light"):
        theme.apply(app, tname)
        w = MainWindow()
        saved += _grab_all(app, w, lambda: w.render(sample.snapshot(True)), out, tname)
        w.close()
        wz = Wizard()
        wz.show()
        for i in (0, 2, 3):
            wz.go(i)
            _settle(app)
            f = out / f"{tname}-wizard-{i + 1}.png"
            wz.grab().save(str(f))
            saved.append(f)
        wz.close()
    return saved


def snapshots_live(app, out: Path) -> list[Path]:
    """Справжній контролер у тестовому режимі: дочекатися фонових даних і зняти всі розділи."""
    import time
    from .controller import Controller
    out.mkdir(parents=True, exist_ok=True)
    c = Controller(app, test=True, minimized=True)
    c.ping_next = 0              # одразу виміряти сервери пулу
    t0 = time.time()
    while time.time() - t0 < float(os.environ.get("PANEL_TEST_WAIT", "40")) and (c.jobs or not c.market or not c.pool_time):
        app.processEvents()
        c.tick()
        time.sleep(0.5)
    c.tick()
    saved = []
    saved += _grab_all(app, c.win, lambda: c.win.render(c.snapshot()), out, "live")
    c.timer.stop()
    c.pool_exec.shutdown(wait=False, cancel_futures=True)
    return saved


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="MinerPanel")
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--minimized", action="store_true")
    ap.add_argument("--install", action="store_true")
    ap.add_argument("--uninstall", action="store_true")
    ap.add_argument("--watchdog", nargs=2, type=int, metavar=("PANEL_PID", "MINER_PID"))
    args = ap.parse_args(argv)

    if args.watchdog:
        from .core import watchdog
        return watchdog.run(*args.watchdog)
    if args.install or args.uninstall:
        from .core import linux_install
        return linux_install.install() if args.install else linux_install.uninstall()

    from .core import platform
    if platform.IS_WIN and not (args.test or args.demo) and not platform.is_admin():
        # Ліміт потужності і частоти змінюються лише з правами адміністратора
        if platform.relaunch_elevated(["--minimized"] if args.minimized else []):
            return 0

    if os.environ.get("PANEL_TEST_SNAP"):
        # Знімки — без вікон на екрані (не заважають користувачу), шрифти Windows — щоб розміри були як у справжньому вікні
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        if platform.IS_WIN:
            os.environ.setdefault("QT_QPA_FONTDIR", os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"))
    from PySide6.QtWidgets import QApplication, QMessageBox
    app = QApplication(sys.argv[:1])
    app.setApplicationName("Miner Panel")
    app.setQuitOnLastWindowClosed(False)
    from .ui import sample, theme
    from .ui.tray import dot_icon
    app.setWindowIcon(dot_icon("#3987e5"))

    snap_dir = os.environ.get("PANEL_TEST_SNAP")
    if args.demo:
        if snap_dir:
            for f in snapshots_demo(app, Path(snap_dir)):
                print(f)
            return 0
        from .ui.main_window import MainWindow
        theme.apply(app, os.environ.get("PANEL_TEST_THEME", "dark"))
        w = MainWindow()
        w.closing.connect(lambda e: app.quit())
        w.render(sample.snapshot(True))
        w.action.connect(lambda a: w.render(sample.snapshot(True)))
        w.show()
        return app.exec()
    if args.test and snap_dir:
        for f in snapshots_live(app, Path(snap_dir)):
            print(f)
        return 0

    if not args.test and _old_panel_running():
        theme.apply(app, "dark")
        QMessageBox.warning(None, "Miner Panel", "Зараз працює стара панель (MinerPanel.ps1). Закрий її, а потім відкрий нову — "
                                                 "дві панелі одночасно керували б одним майнером і відеокартою.")
        return 1
    from .controller import run
    return run(app, test=args.test, minimized=args.minimized)


def _old_panel_running() -> bool:
    import psutil
    for p in psutil.process_iter(["name", "cmdline"]):
        try:
            if (p.info["name"] or "").lower().startswith("powershell") and any("MinerPanel.ps1" in a for a in p.info["cmdline"] or []):
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    if sys.platform == "win32":
        # Стара панель працює з правами адміністратора — її командний рядок може бути недоступний; шукаємо вікно
        import ctypes
        from ctypes import wintypes
        found = []

        def cb(hwnd, _l):
            n = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
            if n:
                b = ctypes.create_unicode_buffer(n + 1)
                ctypes.windll.user32.GetWindowTextW(hwnd, b, n + 1)
                if b.value.startswith("Miner Panel — "):
                    found.append(hwnd)
            return True
        ctypes.windll.user32.EnumWindows(ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)(cb), 0)
        return bool(found)
    return False


if __name__ == "__main__":
    sys.exit(main())
