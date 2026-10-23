"""Linux: встановлення помічника розгону, правила sudo і ярлика в меню (команда --install).
Помічник — короткий скрипт із білим списком дій nvidia-smi; кожен аргумент перевіряється як число.
Права root має лише він, сама панель працює від звичайного користувача."""
from __future__ import annotations

import getpass
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from .gpu import HELPER
from .platform import self_command
from ..i18n import tr

HELPER_SCRIPT = r"""#!/bin/sh
# Miner Panel: дозволені дії з відеокартою (лише знизити або скинути). Встановлено командою --install.
set -eu
SMI=$(command -v nvidia-smi || echo /usr/bin/nvidia-smi)
num() { case "$1" in ''|*[!0-9]*) echo "bad number: $1" >&2; exit 2;; esac; }
pair() { case "$1" in *,*) num "${1%%,*}"; num "${1#*,}";; *) echo "bad pair: $1" >&2; exit 2;; esac; }
case "${1:-}" in
  check) exit 0 ;;
  -pl)  num "$2"; [ "$2" -ge 50 ] && [ "$2" -le 600 ] || exit 2; exec "$SMI" -i 0 -pl "$2" ;;
  -lgc) pair "$2"; exec "$SMI" -i 0 -lgc "$2" ;;
  -lmc) pair "$2"; exec "$SMI" -i 0 -lmc "$2" ;;
  -rgc) exec "$SMI" -i 0 -rgc ;;
  -rmc) exec "$SMI" -i 0 -rmc ;;
  -pm)  exec "$SMI" -i 0 -pm 1 ;;
  *) echo "not allowed: ${1:-}" >&2; exit 2 ;;
esac
"""


def install() -> int:
    user = os.environ.get("SUDO_USER") or getpass.getuser()
    print(tr('Miner Panel: встановлюю помічника розгону (потрібен пароль адміністратора).'))
    with tempfile.TemporaryDirectory() as tmp:
        h = Path(tmp) / "minerpanel-gpu"
        h.write_text(HELPER_SCRIPT, encoding="utf-8")
        s = Path(tmp) / "minerpanel"
        s.write_text(f"{user} ALL=(root) NOPASSWD: {HELPER}\n", encoding="utf-8")
        cmds = [["install", "-m", "0755", "-o", "root", "-g", "root", str(h), HELPER],
                ["visudo", "-cf", str(s)],
                ["install", "-m", "0440", "-o", "root", "-g", "root", str(s), "/etc/sudoers.d/minerpanel"]]
        for c in cmds:
            if subprocess.run(["sudo", *c]).returncode != 0:
                print(tr('Не вдалося:'), " ".join(c))
                return 1
    # Ярлик у меню програм
    apps = Path.home() / ".local" / "share" / "applications"
    apps.mkdir(parents=True, exist_ok=True)
    (apps / "minerpanel.desktop").write_text(
        tr('[Desktop Entry]\nType=Application\nName=Miner Panel\nComment=Майнінг на відеокарті NVIDIA\nExec={0}\nTerminal=false\nCategories=Utility;\n').format(' '.join(self_command())), encoding="utf-8")
    print(tr('Готово. Запускай Miner Panel з меню програм або подвійним клацанням.'))
    return 0


def uninstall() -> int:
    for c in (["rm", "-f", HELPER], ["rm", "-f", "/etc/sudoers.d/minerpanel"]):
        subprocess.run(["sudo", *c])
    f = Path.home() / ".local" / "share" / "applications" / "minerpanel.desktop"
    if f.exists():
        f.unlink()
    return 0


if __name__ == "__main__":
    sys.exit(install())
