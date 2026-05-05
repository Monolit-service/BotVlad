from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import load_settings
from app.db import init_db


async def main() -> None:
    settings = load_settings()
    await init_db(settings.initial_robots)
    print("База данных инициализирована")


if __name__ == "__main__":
    asyncio.run(main())
