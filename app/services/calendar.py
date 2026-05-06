from __future__ import annotations

import calendar as py_calendar
from datetime import date

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app import db

MONTHS_RU = [
    "",
    "Январь",
    "Февраль",
    "Март",
    "Апрель",
    "Май",
    "Июнь",
    "Июль",
    "Август",
    "Сентябрь",
    "Октябрь",
    "Ноябрь",
    "Декабрь",
]
WEEKDAYS_RU = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


def month_shift(year: int, month: int, delta: int) -> tuple[int, int]:
    month += delta
    while month < 1:
        year -= 1
        month += 12
    while month > 12:
        year += 1
        month -= 12
    return year, month


def month_title(year: int, month: int) -> str:
    return f"{MONTHS_RU[month]} {year}"


async def build_calendar(year: int, month: int, mode: str = "client") -> tuple[str, InlineKeyboardMarkup]:
    """Build an inline calendar.

    mode='client': клиент видит только свободно/занято и не может менять занятость.
    mode='admin': админ видит счётчик подтверждённых броней и может нажать день для управления.
    """
    today = date.today()
    cal = py_calendar.Calendar(firstweekday=0)

    rows: list[list[InlineKeyboardButton]] = []
    rows.append([InlineKeyboardButton(text=day, callback_data="noop") for day in WEEKDAYS_RU])

    for week in cal.monthdatescalendar(year, month):
        row: list[InlineKeyboardButton] = []
        for cur in week:
            if cur.month != month:
                row.append(InlineKeyboardButton(text=" ", callback_data="noop"))
                continue

            iso = cur.isoformat()
            usage = await db.day_usage(iso)
            is_past = cur < today

            if is_past:
                text = f"⚪ {cur.day}"
                callback = "noop"
            elif usage.available > 0:
                if mode == "admin":
                    # В админском календаре счетчик показывает общую занятость:
                    # подтвержденные брони + ручные блокировки / активные роботы.
                    # Подробная разбивка открывается при нажатии на дату.
                    text = f"🟢 {cur.day} {usage.occupied_total}/{usage.active_robots}"
                else:
                    text = f"🟢 {cur.day}"
                callback = f"day:{mode}:{iso}"
            else:
                if mode == "admin":
                    text = f"🔴 {cur.day} {usage.occupied_total}/{usage.active_robots}"
                    callback = f"day:{mode}:{iso}"
                else:
                    text = f"🔴 {cur.day}"
                    callback = f"day:{mode}:{iso}"
            row.append(InlineKeyboardButton(text=text, callback_data=callback))
        rows.append(row)

    prev_year, prev_month = month_shift(year, month, -1)
    next_year, next_month = month_shift(year, month, 1)
    rows.append(
        [
            InlineKeyboardButton(text="⬅️", callback_data=f"cal:{mode}:{prev_year}:{prev_month}"),
            InlineKeyboardButton(text=month_title(year, month), callback_data="noop"),
            InlineKeyboardButton(text="➡️", callback_data=f"cal:{mode}:{next_year}:{next_month}"),
        ]
    )
    if mode == "client":
        rows.append([InlineKeyboardButton(text="📝 Оставить заявку", callback_data="book:start")])

    legend = (
        "🟢 свободно, 🔴 занято, ⚪ недоступно"
        if mode == "client"
        else "🟢 дата доступна, 🔴 мест нет, N/всего = занято всего/активные роботы"
    )
    text = f"📅 {month_title(year, month)}\n{legend}"
    return text, InlineKeyboardMarkup(inline_keyboard=rows)
