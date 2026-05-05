from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class BookingForm(StatesGroup):
    dates = State()
    name = State()
    phone = State()
    address = State()
    delivery = State()
    comment = State()


class RobotSettings(StatesGroup):
    count = State()


class SupportChat(StatesGroup):
    message = State()


class AdminSupportReply(StatesGroup):
    message = State()
