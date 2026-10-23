"""Події простою мовою: журнал (logs/panel.log), активні повідомлення в «Огляді» і сповіщення в треї.
Кожне повідомлення каже, що сталося, що панель уже зробила і що робити користувачу.
Однакове сповіщення (той самий key) — не частіше ніж раз на 30 хв."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import timeutil

INFO, OK, WARN, ERROR = "info", "ok", "warn", "error"
REPEAT_S = 1800


@dataclass
class Notice:
    key: str
    level: str
    title: str
    text: str
    action: str | None = None          # підпис кнопки дії («Запустити», «Відкрити»)
    action_id: str | None = None       # що зробити: 'hive:start:1/101', 'open:devices' …
    time: float = field(default_factory=time.time)


class Events:
    def __init__(self, log_file: Path | None, notify: Callable[[Notice], None] | None = None):
        self.log_file = log_file
        self.notify = notify
        self.active: dict[str, Notice] = {}      # показані в «Огляді», доки причина не зникне
        self.history: list[tuple[float, str, str]] = []
        self._last_notified: dict[str, float] = {}

    def log(self, text: str, level: str = INFO) -> None:
        self.history.append((time.time(), level, text))
        del self.history[:-500]
        if self.log_file:
            try:
                with open(self.log_file, "a", encoding="utf-8") as f:
                    f.write(f"[{timeutil.now():%Y-%m-%d %H:%M:%S}] {text}\n")
            except OSError:
                pass

    def raise_(self, n: Notice, toast: bool = True) -> None:
        """Повідомлення активне, доки не викличуть clear(key). Сповіщення — з антиповтором."""
        new = n.key not in self.active
        self.active[n.key] = n
        if new:
            self.log(f"{n.title}. {n.text}", n.level)
        last = self._last_notified.get(n.key, 0)
        if toast and self.notify and n.level in (WARN, ERROR) and time.time() - last >= REPEAT_S:
            self._last_notified[n.key] = time.time()
            self.notify(n)

    def once(self, n: Notice) -> None:
        """Разова подія (перезапуск, виплата): журнал + сповіщення, без активного повідомлення."""
        self.log(f"{n.title}. {n.text}", n.level)
        last = self._last_notified.get(n.key, 0)
        if self.notify and time.time() - last >= REPEAT_S:
            self._last_notified[n.key] = time.time()
            self.notify(n)

    def clear(self, key: str) -> None:
        self.active.pop(key, None)

    def clear_prefix(self, prefix: str, keep: set[str] | None = None) -> None:
        for k in [k for k in self.active if k.startswith(prefix) and k not in (keep or set())]:
            del self.active[k]

    def sorted_active(self) -> list[Notice]:
        order = {ERROR: 0, WARN: 1, INFO: 2, OK: 3}
        return sorted(self.active.values(), key=lambda n: (order.get(n.level, 9), -n.time))
