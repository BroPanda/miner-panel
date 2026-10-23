"""Час у форматі, сумісному з PowerShell ('o': 2026-10-20T15:01:27.2247484+03:00)."""
from __future__ import annotations

import re
from datetime import datetime, timezone

_FRAC = re.compile(r"(\.\d{6})\d+")


def now() -> datetime:
    return datetime.now().astimezone()


def iso(dt: datetime | None = None) -> str:
    return (dt or now()).isoformat()


def parse(s: str | None) -> datetime | None:
    """ISO-рядок → datetime з часовим поясом. PowerShell пише 7 знаків дробу секунд,
    Python 3.11 приймає не більше 6 — зайві відкидаємо."""
    if not s:
        return None
    s = str(s).strip().replace("Z", "+00:00")
    s = _FRAC.sub(r"\1", s)
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.astimezone()
    return dt


def from_unix_ms(ms: float) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone()
