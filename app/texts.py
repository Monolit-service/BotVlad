from __future__ import annotations

from aiogram.types import User

from app.services.dates import format_iso_dates_ru


def client_welcome(user: User) -> str:
    name = user.full_name or "Здравствуйте"
    return (
        f"👋 {name}, здравствуйте!\n\n"
        "Здесь можно посмотреть свободные даты и оставить заявку на аренду робота-мойщика окон.\n\n"
        "Клиент видит календарь только для просмотра и отправки заявки. "
        "Подтверждает бронь администратор."
    )


def admin_welcome() -> str:
    return (
        "🔐 Админ-панель\n\n"
        "Вы можете подтверждать заявки, управлять календарём, учитывать количество роботов "
        "и отправлять клиентам PDF-договор аренды."
    )


def booking_card(booking, dates: list[str] | None = None) -> str:
    dates_text = format_iso_dates_ru(dates or []) if dates else booking["requested_dates_text"]
    return (
        f"🆕 Заявка #{booking['id']}\n\n"
        f"👤 Клиент: {booking['client_name']}\n"
        f"📞 Телефон: {booking['phone']}\n"
        f"📅 Даты: {dates_text}\n"
        f"📍 Адрес/район: {booking['address']}\n"
        f"🚚 Доставка: {booking['delivery_required']}\n"
        f"💬 Комментарий: {booking['comment'] or '-'}\n"
        f"📌 Статус: {booking['status']}\n"
        f"🕒 Создана: {booking['created_at']}"
    )


PRICES_TEXT = (
    "💰 Цены и условия\n\n"
    "Укажите здесь ваши актуальные цены.\n\n"
    "Пример:\n"
    "• 1 день аренды - 1500 ₽\n"
    "• Залог - 5000 ₽\n"
    "• Доставка по городу - 300 ₽\n\n"
    "Файл можно изменить в app/texts.py."
)

CONTACT_TEXT = (
    "📞 Связаться\n\n"
    "Напишите сюда ваши контакты: телефон, WhatsApp, адрес, график работы.\n"
    "Текст можно изменить в app/texts.py."
)
