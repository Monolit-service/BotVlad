from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup


def client_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🧽 Забронировать робота"), KeyboardButton(text="📅 Свободные даты")],
            [KeyboardButton(text="📄 Договор аренды PDF"), KeyboardButton(text="💰 Цены и условия")],
            [KeyboardButton(text="📞 Связаться")],
        ],
        resize_keyboard=True,
    )


def admin_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📅 Календарь"), KeyboardButton(text="🆕 Новые заявки")],
            [KeyboardButton(text="✅ Активные брони"), KeyboardButton(text="🤖 Роботы")],
            [KeyboardButton(text="👀 Вид клиента")],
        ],
        resize_keyboard=True,
    )


def booking_admin_keyboard(booking_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"booking:approve:{booking_id}"),
                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"booking:decline:{booking_id}"),
            ],
            [
                InlineKeyboardButton(text="📄 PDF договора", callback_data=f"booking:contract:{booking_id}"),
                InlineKeyboardButton(text="📨 PDF клиенту", callback_data=f"booking:send_contract:{booking_id}"),
            ],
        ]
    )


def booking_short_keyboard(booking_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"Открыть заявку #{booking_id}", callback_data=f"booking:view:{booking_id}")]
        ]
    )


def client_day_keyboard(iso_date: str, year: int, month: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📝 Оставить заявку на эту дату", callback_data=f"bookdate:{iso_date}")],
            [InlineKeyboardButton(text="⬅️ Назад к календарю", callback_data=f"cal:client:{year}:{month}")],
        ]
    )


def admin_day_keyboard(iso_date: str, year: int, month: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔴 Занять дату полностью", callback_data=f"block:full:{iso_date}")],
            [InlineKeyboardButton(text="🧽 Занять 1 робота", callback_data=f"block:add:{iso_date}")],
            [InlineKeyboardButton(text="🟢 Снять ручную блокировку", callback_data=f"block:clear:{iso_date}")],
            [InlineKeyboardButton(text="⬅️ Назад к календарю", callback_data=f"cal:admin:{year}:{month}")],
        ]
    )


def robots_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="➕ +1 активный", callback_data="robots:add"),
                InlineKeyboardButton(text="➖ -1 активный", callback_data="robots:remove"),
            ],
            [InlineKeyboardButton(text="✏️ Установить точное число", callback_data="robots:set")],
            [InlineKeyboardButton(text="🔄 Обновить", callback_data="robots:refresh")],
        ]
    )
