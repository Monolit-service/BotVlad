from __future__ import annotations

import re
from datetime import date, datetime, timedelta

MONTHS_RU = {
    "января": 1,
    "январь": 1,
    "февраля": 2,
    "февраль": 2,
    "марта": 3,
    "март": 3,
    "апреля": 4,
    "апрель": 4,
    "мая": 5,
    "май": 5,
    "июня": 6,
    "июнь": 6,
    "июля": 7,
    "июль": 7,
    "августа": 8,
    "август": 8,
    "сентября": 9,
    "сентябрь": 9,
    "октября": 10,
    "октябрь": 10,
    "ноября": 11,
    "ноябрь": 11,
    "декабря": 12,
    "декабрь": 12,
}

RANGE_SEP = re.compile(r"\s*(?:-|–|—|по)\s*", re.IGNORECASE)
ITEM_SEP = re.compile(r"[,;\n]+")


def _default_year(month: int, today: date | None = None) -> int:
    today = today or date.today()
    year = today.year
    # Если месяц уже сильно в прошлом, считаем, что клиент имел в виду следующий год.
    if month < today.month - 1:
        year += 1
    return year


def _parse_single_date(text: str, today: date | None = None, inherit_month: int | None = None, inherit_year: int | None = None) -> date:
    original = text
    text = text.strip().lower().replace("г.", "").replace("г", "")
    text = re.sub(r"\s+", " ", text)

    # 2026-05-12
    match = re.fullmatch(r"(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})", text)
    if match:
        year, month, day = map(int, match.groups())
        return date(year, month, day)

    # 12.05.2026 / 12.05.26 / 12.05
    match = re.fullmatch(r"(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?", text)
    if match:
        day = int(match.group(1))
        month = int(match.group(2))
        year_raw = match.group(3)
        if year_raw:
            year = int(year_raw)
            if year < 100:
                year += 2000
        else:
            year = inherit_year or _default_year(month, today)
        return date(year, month, day)

    # 12 мая 2026 / 12 мая
    month_names = "|".join(MONTHS_RU.keys())
    match = re.fullmatch(rf"(\d{{1,2}})\s+({month_names})(?:\s+(20\d{{2}}|\d{{2}}))?", text)
    if match:
        day = int(match.group(1))
        month = MONTHS_RU[match.group(2)]
        year_raw = match.group(3)
        if year_raw:
            year = int(year_raw)
            if year < 100:
                year += 2000
        else:
            year = inherit_year or _default_year(month, today)
        return date(year, month, day)

    # 12 (только если месяц наследуется из правой части диапазона)
    match = re.fullmatch(r"\d{1,2}", text)
    if match and inherit_month:
        day = int(text)
        year = inherit_year or _default_year(inherit_month, today)
        return date(year, inherit_month, day)

    raise ValueError(
        f"Не удалось распознать дату '{original}'. Используйте формат 12.05.2026 или 12.05-14.05.2026."
    )


def _expand_range(start: date, end: date) -> list[date]:
    if end < start:
        raise ValueError("Дата окончания диапазона раньше даты начала.")
    days: list[date] = []
    cur = start
    while cur <= end:
        days.append(cur)
        cur += timedelta(days=1)
    return days


def parse_dates(text: str, today: date | None = None) -> list[date]:
    """Parse user input into a sorted unique list of dates.

    Supported examples:
    - 12.05.2026
    - 12.05, 14.05
    - 12.05.2026-14.05.2026
    - 12-14 мая 2026
    - 2026-05-12
    """
    today = today or date.today()
    text = text.strip()
    if not text:
        raise ValueError("Введите даты аренды.")

    found: set[date] = set()
    items = [item.strip() for item in ITEM_SEP.split(text) if item.strip()]

    for item in items:
        # ISO-дата содержит дефисы, поэтому сначала обрабатываем ее как одиночную дату.
        if re.fullmatch(r"20\d{2}[-/.]\d{1,2}[-/.]\d{1,2}", item.strip()):
            found.add(_parse_single_date(item, today=today))
            continue

        # Спец-случай: 12-14 мая 2026, где левая часть без месяца.
        month_names = "|".join(MONTHS_RU.keys())
        match_ru_range = re.fullmatch(
            rf"(\d{{1,2}})\s*(?:-|–|—|по)\s*(\d{{1,2}})\s+({month_names})(?:\s+(20\d{{2}}|\d{{2}}))?",
            item.lower().strip(),
        )
        if match_ru_range:
            start_day = int(match_ru_range.group(1))
            end_day = int(match_ru_range.group(2))
            month = MONTHS_RU[match_ru_range.group(3)]
            year_raw = match_ru_range.group(4)
            if year_raw:
                year = int(year_raw)
                if year < 100:
                    year += 2000
            else:
                year = _default_year(month, today)
            found.update(_expand_range(date(year, month, start_day), date(year, month, end_day)))
            continue

        parts = RANGE_SEP.split(item, maxsplit=1)
        if len(parts) == 2:
            left, right = parts
            end = _parse_single_date(right, today=today)
            start = _parse_single_date(left, today=today, inherit_month=end.month, inherit_year=end.year)
            found.update(_expand_range(start, end))
        else:
            found.add(_parse_single_date(item, today=today))

    result = sorted(found)
    if not result:
        raise ValueError("Не удалось распознать даты.")
    return result


def parse_dates_to_iso(text: str, today: date | None = None) -> list[str]:
    return [d.isoformat() for d in parse_dates(text, today=today)]


def format_iso_dates_ru(iso_dates: list[str]) -> str:
    if not iso_dates:
        return "-"
    dates = [datetime.strptime(item, "%Y-%m-%d").date() for item in iso_dates]
    dates = sorted(dates)
    if len(dates) == 1:
        return dates[0].strftime("%d.%m.%Y")
    # Сжимаем непрерывные диапазоны.
    ranges: list[tuple[date, date]] = []
    start = prev = dates[0]
    for cur in dates[1:]:
        if cur == prev + timedelta(days=1):
            prev = cur
        else:
            ranges.append((start, prev))
            start = prev = cur
    ranges.append((start, prev))

    formatted: list[str] = []
    for start, end in ranges:
        if start == end:
            formatted.append(start.strftime("%d.%m.%Y"))
        else:
            formatted.append(f"{start.strftime('%d.%m.%Y')}-{end.strftime('%d.%m.%Y')}")
    return ", ".join(formatted)
