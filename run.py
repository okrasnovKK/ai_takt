"""ai-takt — Quick start script.

Run the bot:
    python run.py

Or start with polling in background (Windows):
    start /B python run.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.bot import main

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())