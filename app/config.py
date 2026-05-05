from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
GENERATED_DIR = BASE_DIR / "generated"
DB_PATH = DATA_DIR / "bot.db"


@dataclass(frozen=True)
class Settings:
    bot_token: str
    admin_ids: set[int]
    initial_robots: int
    company_name: str
    company_inn: str
    company_phone: str
    company_address: str
    company_email: str
    tz: ZoneInfo


def _parse_admin_ids(raw: str) -> set[int]:
    ids: set[int] = set()
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            ids.add(int(item))
        except ValueError as exc:
            raise ValueError(f"ADMIN_IDS содержит нечисловое значение: {item}") from exc
    return ids


def load_settings() -> Settings:
    load_dotenv(BASE_DIR / ".env")

    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("Не указан BOT_TOKEN. Скопируйте .env.example в .env и заполните токен.")

    admins = _parse_admin_ids(os.getenv("ADMIN_IDS", ""))
    if not admins:
        raise RuntimeError("Не указан ADMIN_IDS. Добавьте хотя бы один Telegram ID администратора.")

    tz_name = os.getenv("TZ", "Europe/Amsterdam")
    return Settings(
        bot_token=token,
        admin_ids=admins,
        initial_robots=int(os.getenv("INITIAL_ROBOTS", "1")),
        company_name=os.getenv("COMPANY_NAME", "ИП / ООО"),
        company_inn=os.getenv("COMPANY_INN", ""),
        company_phone=os.getenv("COMPANY_PHONE", ""),
        company_address=os.getenv("COMPANY_ADDRESS", ""),
        company_email=os.getenv("COMPANY_EMAIL", ""),
        tz=ZoneInfo(tz_name),
    )
