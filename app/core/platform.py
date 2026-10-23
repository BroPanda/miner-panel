"""Відмінності Windows і Linux: права, процеси, автозапуск, запуск прихованих процесів."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import psutil

IS_WIN = sys.platform == "win32"
IS_LINUX = sys.platform.startswith("linux")
OS_KEY = "win" if IS_WIN else "linux"


def is_admin() -> bool:
    if IS_WIN:
        import ctypes
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except OSError:
            return False
    return os.geteuid() == 0


def self_command() -> list[str]:
    """Як запустити цю програму ще раз (зібраний exe/AppImage або python -m app.main)."""
    if getattr(sys, "frozen", False):
        return [os.environ.get("APPIMAGE") or sys.executable]
    return [sys.executable, "-m", "app.main"]


def relaunch_elevated(args: list[str]) -> bool:
    """Windows: перезапуск з правами адміністратора (UAC). True — запит показано, поточний процес має вийти."""
    if not IS_WIN:
        return False
    import ctypes
    cmd = self_command()
    exe, params = cmd[0], subprocess.list2cmdline(cmd[1:] + args)
    cwd = str(Path(__file__).resolve().parents[2]) if not getattr(sys, "frozen", False) else None
    r = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, cwd, 1)
    return r > 32


def hidden_popen(cmd: list[str], cwd: str | None = None, log=None) -> subprocess.Popen:
    """Процес без вікна консолі (майнер, сторож)."""
    kw: dict = {"cwd": cwd, "stdin": subprocess.DEVNULL, "stdout": log or subprocess.DEVNULL, "stderr": subprocess.STDOUT if log else subprocess.DEVNULL}
    if IS_WIN:
        kw["creationflags"] = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kw["start_new_session"] = True
    return subprocess.Popen(cmd, **kw)


def run_quiet(cmd: list[str], timeout: float = 15) -> subprocess.CompletedProcess:
    kw: dict = {"capture_output": True, "text": True, "timeout": timeout}
    if IS_WIN:
        kw["creationflags"] = subprocess.CREATE_NO_WINDOW
    return subprocess.run(cmd, **kw)


def find_processes(names: list[str]) -> list[psutil.Process]:
    """Процеси за назвою exe (без розширення, без регістру)."""
    want = {n.lower() for n in names}
    out = []
    for p in psutil.process_iter(["name"]):
        try:
            nm = (p.info["name"] or "").lower()
            if nm.endswith(".exe"):
                nm = nm[:-4]
            if nm in want:
                out.append(p)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return out


def kill_tree(p: psutil.Process) -> None:
    try:
        for c in p.children(recursive=True):
            c.kill()
        p.kill()
    except psutil.NoSuchProcess:
        pass


# ---- Автозапуск із системою ----------------------------------------------
def set_autostart(on: bool) -> None:
    cmd = self_command()
    if IS_WIN:
        # Програму з правами адміністратора Windows не запускає з розділу Run реєстру — лише через
        # Планувальник завдань («при вході в систему», найвищі права)
        if on:
            tr = subprocess.list2cmdline(cmd + ["--minimized"])
            run_quiet(["schtasks", "/Create", "/TN", "MinerPanel", "/TR", tr, "/SC", "ONLOGON", "/RL", "HIGHEST", "/F"])
        else:
            run_quiet(["schtasks", "/Delete", "/TN", "MinerPanel", "/F"])
    else:
        d = Path.home() / ".config" / "autostart"
        f = d / "minerpanel.desktop"
        if on:
            d.mkdir(parents=True, exist_ok=True)
            f.write_text("[Desktop Entry]\nType=Application\nName=Miner Panel\n"
                         f"Exec={' '.join(cmd)} --minimized\nX-GNOME-Autostart-enabled=true\n", encoding="utf-8")
        elif f.exists():
            f.unlink()
