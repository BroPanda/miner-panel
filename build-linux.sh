#!/bin/sh
# Збірка Miner Panel для Linux (один файл, Python усередині). Запускати на Linux x86_64.
# Результат: dist/MinerPanel — скопіюй у теку з даними, chmod +x, перший раз ./MinerPanel --install
set -eu
cd "$(dirname "$0")"
[ -d .venv ] || python3 -m venv .venv
. .venv/bin/activate
pip install -q -r requirements.txt pyinstaller==6.11.1
QT_QPA_PLATFORM=offscreen python build/make_icon.py
pyinstaller --noconfirm --clean --onefile --windowed --name MinerPanel \
  --icon "$PWD/build/icon.png" --distpath dist --workpath build/work --specpath build \
  run_minerpanel.py
echo "Готово: dist/MinerPanel"
