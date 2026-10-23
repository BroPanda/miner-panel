"""HTTP для всіх джерел: таймаути, User-Agent, помилки з кодом відповіді."""
from __future__ import annotations

from typing import Any

import requests

UA = "MinerPanel/2.0"


class HttpError(RuntimeError):
    def __init__(self, msg: str, status: int = 0):
        super().__init__(msg)
        self.status = status


def get_json(url: str, timeout: float = 20, headers: dict | None = None, params: dict | None = None) -> Any:
    try:
        r = requests.get(url, timeout=timeout, params=params, headers={"User-Agent": UA, **(headers or {})})
    except requests.RequestException as e:
        raise HttpError(str(e)) from e
    if r.status_code >= 400:
        raise HttpError(f"{r.status_code} {r.reason}", r.status_code)
    try:
        return r.json()
    except ValueError as e:
        raise HttpError("відповідь не JSON") from e


def send_json(method: str, url: str, body: Any, timeout: float = 20, headers: dict | None = None) -> Any:
    try:
        r = requests.request(method, url, json=body, timeout=timeout, headers={"User-Agent": UA, **(headers or {})})
    except requests.RequestException as e:
        raise HttpError(str(e)) from e
    if r.status_code >= 400:
        raise HttpError(f"{r.status_code} {r.reason}", r.status_code)
    return r.json() if r.content else None
