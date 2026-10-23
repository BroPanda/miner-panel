"""Сторож майнера — окремий процес (порт Get-WatchdogScript з lib\\Gpu.ps1):
  панель закрилась або впала → зупинити майнер і скинути відеокарту;
  майнер зник, а панель жива → почекати 5 с; якщо вже працює інший майнер (перезапуск) — вийти
  без скидання, інакше (аварія майнера) — скинути карту.
Запуск: <програма> --watchdog <pid панелі> <pid майнера>"""
from __future__ import annotations

import time

import psutil

from .gpu import Gpu
from .miners import all_process_names
from .platform import find_processes, hidden_popen, kill_tree, self_command


def start(miner_pid: int) -> int | None:
    import os
    p = hidden_popen(self_command() + ["--watchdog", str(os.getpid()), str(miner_pid)])
    return p.pid


def run(panel_pid: int, miner_pid: int) -> int:
    def alive(pid):
        try:
            return psutil.pid_exists(pid) and psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
        except psutil.NoSuchProcess:
            return False

    while alive(panel_pid) and alive(miner_pid):
        time.sleep(2)
    if alive(panel_pid):
        time.sleep(5)
        if find_processes(all_process_names()):
            return 0
    else:
        try:
            kill_tree(psutil.Process(miner_pid))
        except psutil.NoSuchProcess:
            pass
    Gpu().reset()
    return 0
