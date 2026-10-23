@echo off
rem New panel in test mode: real data, but does not touch the GPU and does not change files.
cd /d "%~dp0"
if not exist .venv\Scripts\pythonw.exe (
  python -m venv .venv
  .venv\Scripts\python.exe -m pip install -q -r requirements.txt
)
start "" .venv\Scripts\pythonw.exe -m app.main --test