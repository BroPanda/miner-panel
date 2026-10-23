@echo off
rem Build MinerPanel.exe (single file, Python inside). Output: dist\MinerPanel.exe
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe python -m venv .venv
.venv\Scripts\python.exe -m pip install -q -r requirements.txt pyinstaller==6.11.1
.venv\Scripts\python.exe build\make_icon.py
.venv\Scripts\pyinstaller.exe --noconfirm --clean --onefile --windowed --uac-admin --name MinerPanel --icon "%~dp0build\icon.ico" --distpath dist --workpath build\work --specpath build run_minerpanel.py
echo.
echo Done: dist\MinerPanel.exe