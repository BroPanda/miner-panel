"""Встановлення та оновлення майнерів з офіційних релізів GitHub (порт lib\\Updater.ps1).
Кожна версія — окрема тека bin/<id>/<версія>/ (попередня лишається для відкату), активна — у current.txt.
Архів перевіряється за SHA256, який GitHub публікує для кожного файлу релізу; без нього не встановлюємо."""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
import tarfile
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

import requests

from . import storage, timeutil
from .miners import MINERS, Miner
from .platform import OS_KEY
from ..i18n import tr

CACHE = "releases-cache.json"


class UpdateError(RuntimeError):
    pass


class AntivirusBlocked(UpdateError):
    """Файл майнера зник або став недоступним під час запису — так поводиться антивірус."""


def looks_blocked(e: Exception) -> bool:
    return isinstance(e, AntivirusBlocked) or (isinstance(e, OSError) and e.errno in (13, 22, 2) and "miner-dl-" in str(e))


def latest_release(m: Miner) -> dict:
    r = requests.get(f"https://api.github.com/repos/{m.repo}/releases/latest", timeout=20, headers={"User-Agent": "MinerPanel"})
    if r.status_code in (403, 429) and r.headers.get("X-RateLimit-Remaining") == "0":
        reset = datetime.fromtimestamp(int(r.headers.get("X-RateLimit-Reset", "0")))
        raise UpdateError(tr('GitHub обмежив кількість запитів (60 на годину), повтор після {0:%H:%M}').format(reset))
    if r.status_code >= 400:
        raise UpdateError(f"GitHub: {r.status_code}")
    j = r.json()
    a = next((x for x in j.get("assets") or [] if re.search(m.asset[OS_KEY], x["name"])), None)
    if not a:
        raise UpdateError(tr('У релізі {0} немає файлу для цієї системи').format(j.get('tag_name')))
    return {"Version": str(j["tag_name"]), "Url": a["browser_download_url"], "Name": a["name"], "Digest": str(a.get("digest") or "")}


def bin_root(root: Path) -> Path:
    return root / "bin"


def installed_versions(root: Path, mid: str) -> list[str]:
    d = bin_root(root) / mid
    if not d.is_dir():
        return []
    return [p.name for p in sorted((p for p in d.iterdir() if p.is_dir()), key=lambda p: p.stat().st_mtime, reverse=True)]


def current_version(root: Path, mid: str) -> str | None:
    f = bin_root(root) / mid / "current.txt"
    try:
        return f.read_text(encoding="utf-8-sig").strip() or None
    except OSError:
        return None


def set_current(root: Path, mid: str, version: str) -> None:
    (bin_root(root) / mid / "current.txt").write_text(version, encoding="ascii")


def miner_exe(root: Path, m: Miner) -> Path | None:
    v = current_version(root, m.id)
    if v:
        d = bin_root(root) / m.id / v
        for p in d.rglob(m.exe_name):
            if p.is_file():
                return p
    for rel in m.legacy:
        p = root / rel
        if p.is_file() and p.name == m.exe_name:
            return p
    return None


def installed_version(root: Path, m: Miner) -> str | None:
    return current_version(root, m.id) or ((tr('вручну')) if miner_exe(root, m) else None)


def update_available(root: Path, m: Miner, releases: dict) -> bool:
    rel = releases.get(m.id) or {}
    cur = current_version(root, m.id)
    return bool(rel.get("Version") and cur and rel["Version"].lstrip("v") != cur.lstrip("v"))


def _safe_extract(archive: Path, dest: Path) -> None:
    """Розпаковка без виходу за межі теки (захист від «../» в архіві)."""
    dest = dest.resolve()
    if archive.name.endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            for n in z.namelist():
                if not (dest / n).resolve().is_relative_to(dest):
                    raise UpdateError(tr('архів містить небезпечні шляхи'))
            z.extractall(dest)
    else:
        with tarfile.open(archive) as t:
            try:
                # Вбудований фільтр 'data' відкидає абсолютні шляхи, «../», пристрої й посилання назовні
                t.extractall(dest, filter="data")
            except tarfile.FilterError as e:
                raise UpdateError(tr('архів містить небезпечні шляхи: {0}').format(e)) from e


def install(root: Path, m: Miner, rel: dict, progress=None) -> Path:
    """Завантажує реліз, перевіряє SHA256 і розпаковує в bin/<id>/<версія>/."""
    mt = re.fullmatch(r"sha256:([0-9a-f]{64})", rel.get("Digest") or "")
    if not mt:
        raise UpdateError(tr('GitHub не надав SHA256 для цього файлу — встановлення скасовано'))
    target = bin_root(root) / m.id / rel["Version"]
    # Завантажуємо в bin/.download, а не в системну TEMP: якщо теку майнерів дозволено в антивірусі,
    # виключення діє і на завантаження (Defender видаляє майнери з TEMP просто під час запису)
    dl = bin_root(root) / ".download"
    dl.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="miner-dl-", dir=dl) as tmp:
        arc = Path(tmp) / rel["Name"]
        h = hashlib.sha256()
        with requests.get(rel["Url"], stream=True, timeout=60, headers={"User-Agent": "MinerPanel"}) as r:
            r.raise_for_status()
            total = int(r.headers.get("Content-Length") or 0)
            done = 0
            with open(arc, "wb") as f:
                for chunk in r.iter_content(1 << 16):
                    f.write(chunk)
                    h.update(chunk)
                    done += len(chunk)
                    if progress and total:
                        progress(done / total)
        if not arc.exists():
            raise AntivirusBlocked(tr('антивірус видалив завантажений файл'))
        if h.hexdigest() != mt.group(1):
            raise UpdateError(tr('SHA256 не збігається (очікувано {0}, отримано {1}) — файл пошкоджений або підмінений').format(mt.group(1), h.hexdigest()))
        x = Path(tmp) / "x"
        x.mkdir()
        _safe_extract(arc, x)
        if not any(p.name == m.exe_name for p in x.rglob(m.exe_name)):
            raise UpdateError(tr('В архіві немає {0}').format(m.exe_name))
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(x, target)
    if OS_KEY == "linux":
        for p in target.rglob(m.exe_name):
            p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    set_current(root, m.id, rel["Version"])
    return target


def allow_in_defender(root: Path) -> str | None:
    """Windows: додати теку майнерів у виключення Microsoft Defender (лише bin/, панель має права адміністратора).
    None — успіх, інакше текст помилки."""
    from .platform import run_quiet
    path = str(bin_root(root).resolve())
    bin_root(root).mkdir(parents=True, exist_ok=True)
    r = run_quiet(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                   f"Add-MpPreference -ExclusionPath '{path}'"], 60)
    return None if r.returncode == 0 else (r.stderr or r.stdout or tr('невідома помилка')).strip()[:300]


def rollback(root: Path, mid: str) -> str | None:
    cur = current_version(root, mid)
    prev = next((v for v in installed_versions(root, mid) if v != cur), None)
    if prev:
        set_current(root, mid, prev)
    return prev


def load_cache(root: Path) -> dict:
    c = storage.read_json(root / CACHE, {})
    return (c.get("releases") or {}) if isinstance(c, dict) else {}


def save_cache(root: Path, releases: dict) -> None:
    storage.write_json(root / CACHE, {"time": timeutil.iso(), "releases": releases})


def check_all() -> tuple[dict, list[str]]:
    rel, errors = {}, []
    for m in MINERS.values():
        try:
            rel[m.id] = latest_release(m)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{m.name}: {e}")
    return rel, errors
