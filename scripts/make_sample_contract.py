from __future__ import annotations

import sys
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import Settings
from app.services.contracts import generate_contract_pdf

settings = Settings(
    bot_token="dummy",
    admin_ids={1},
    initial_robots=2,
    company_name="ИП Иванов Иван Иванович",
    company_inn="000000000000",
    company_phone="+7 999 000-00-00",
    company_address="г. Москва, ул. Примерная, 1",
    company_email="info@example.com",
    tz=ZoneInfo("Europe/Amsterdam"),
)

path = generate_contract_pdf(settings)
print(path)
