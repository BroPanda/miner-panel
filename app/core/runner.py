"""Запуск і зупинка майнера цього ПК; читання його API і логу.
Майнер, запущений до відкриття панелі (або старою PowerShell-версією), підхоплюється, а не дублюється."""
from __future__ import annotations

import os
import time
from pathlib import Path

import psutil

from . import updater
from .miners import MINERS, Miner
from .platform import find_processes, hidden_popen, kill_tree


class Runner:
    def __init__(self, root: Path, test: bool = False):
        self.root = root
        self.test = test
        self.proc: psutil.Process | None = None
        self.miner: Miner | None = None
        self.coin_id: str | None = None
        self.started_at = 0.0
        self.servers: list[str] = []
        self.log_file = root / "logs" / "miner.log"
        self.prev_log = root / "logs" / "miner-prev.log"

    # ---- стан ----
    def alive(self) -> bool:
        if self.proc:
            try:
                if self.proc.is_running() and self.proc.status() != psutil.STATUS_ZOMBIE:
                    return True
            except psutil.NoSuchProcess:
                pass
            self.proc = None
        return False

    def adopt(self, current_coin: dict | None, miner_id_for) -> bool:
        """Підхопити майнер, що вже працює (будь-який із відомих). True — знайдено."""
        for m in MINERS.values():
            ps = find_processes([m.process_name])
            if ps:
                self.proc, self.miner = ps[0], m
                self.started_at = ps[0].create_time()
                if current_coin and miner_id_for(current_coin) == m.id:
                    self.coin_id = current_coin["id"]
                return True
        return False

    def stats(self) -> dict | None:
        if not self.miner or not self.alive():
            return None
        return self.miner.read_stats(self.miner.api_port)

    def log_tail(self, n: int = 80) -> str:
        try:
            with open(self.log_file, "r", encoding="utf-8", errors="replace") as f:
                lines = [ln.rstrip("\n") for ln in f.readlines()[-n:]]
        except OSError:
            return ""
        import re
        return "\n".join(re.sub(r"\x1b\[[0-9;]*m", "", ln) for ln in lines if ln)

    # ---- керування ----
    def stop_all(self) -> None:
        if self.test:
            return
        for p in find_processes([m.process_name for m in MINERS.values()]):
            kill_tree(p)
        self.proc = None

    def start(self, coin: dict, m: Miner, urls: list[str]) -> tuple[bool, str]:
        """Запустити майнер для монети з серверами в заданому порядку (перший — основний). → (успіх, текст помилки)."""
        exe = updater.miner_exe(self.root, m)
        if not exe:
            return False, f"{m.name} ще не встановлено"
        if not urls:
            return False, "для монети не вказано адресу пулу"
        login = str(coin.get("wallet") or "")
        if coin.get("worker"):
            login += f".{coin['worker']}"
        args = m.build_args({"algo": str((coin.get("miners") or {}).get(m.id)), "pools": urls, "login": login,
                             "tls": bool((coin.get("pool") or {}).get("tls")), "log_file": str(self.log_file), "api_port": m.api_port})
        self.servers = urls
        if self.test:
            return True, ""
        self.stop_all()
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        # Попередній лог зберігаємо — після автоперезапуску в ньому видно причину
        if self.log_file.exists():
            try:
                os.replace(self.log_file, self.prev_log)
            except OSError:
                pass
        p = hidden_popen([str(exe), *args], cwd=str(exe.parent))
        self.proc = psutil.Process(p.pid)
        self.miner, self.coin_id, self.started_at = m, coin["id"], time.time()
        return True, ""
