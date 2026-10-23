"""Запуск Miner Panel (точка входу для PyInstaller і для запуску з коду)."""
import sys

from app.main import main

if __name__ == "__main__":
    sys.exit(main())
