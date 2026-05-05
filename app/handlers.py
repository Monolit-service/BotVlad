from __future__ import annotations

from datetime import datetime

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, FSInputFile, Message

from app import db
from app.config import Settings
from app.keyboards import (
    admin_day_keyboard,
    admin_menu,
    booking_admin_keyboard,
    booking_short_keyboard,
    client_day_keyboard,
    client_menu,
    robots_keyboard,
)
from app.services.calendar import build_calendar
from app.services.contracts import generate_contract_pdf
from app.services.dates import format_iso_dates_ru, parse_dates_to_iso
from app.states import BookingForm
from app.texts import CONTACT_TEXT, PRICES_TEXT, admin_welcome, booking_card, client_welcome

router = Router()
settings: Settings | None = None


def setup_router(app_settings: Settings) -> Router:
    global settings
    settings = app_settings
    return router


def is_admin(user_id: int) -> bool:
    assert settings is not None
    return user_id in settings.admin_ids


async def notify_admins(bot: Bot, text: str, booking_id: int | None = None) -> None:
    assert settings is not None
    for admin_id in settings.admin_ids:
        try:
            await bot.send_message(
                admin_id,
                text,
                reply_markup=booking_admin_keyboard(booking_id) if booking_id else None,
            )
        except Exception:
            # Не ломаем клиентский сценарий, если один из админов временно недоступен.
            pass


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    assert settings is not None
    user = message.from_user
    if not user:
        return
    admin = is_admin(user.id)
    await db.ensure_user(user.id, user.full_name, user.username, admin)
    if admin:
        await message.answer(admin_welcome(), reply_markup=admin_menu())
    else:
        await message.answer(client_welcome(user), reply_markup=client_menu())


@router.message(Command("admin"))
async def cmd_admin(message: Message) -> None:
    if not message.from_user or not is_admin(message.from_user.id):
        await message.answer("Нет доступа.")
        return
    await message.answer(admin_welcome(), reply_markup=admin_menu())


@router.message(F.text == "👀 Вид клиента")
async def client_view_for_admin(message: Message) -> None:
    await message.answer("Клиентское меню:", reply_markup=client_menu())


@router.message(F.text == "💰 Цены и условия")
async def prices(message: Message) -> None:
    await message.answer(PRICES_TEXT)


@router.message(F.text == "📞 Связаться")
async def contacts(message: Message) -> None:
    await message.answer(CONTACT_TEXT)


@router.message(F.text == "📄 Договор аренды PDF")
async def send_contract_template(message: Message) -> None:
    assert settings is not None
    path = generate_contract_pdf(settings)
    await message.answer_document(
        FSInputFile(path),
        caption="📄 Шаблон договора аренды робота-мойщика окон."
    )


@router.message(F.text.in_({"📅 Свободные даты", "📅 Календарь"}))
async def show_calendar(message: Message) -> None:
    if not message.from_user:
        return
    mode = "admin" if is_admin(message.from_user.id) and message.text == "📅 Календарь" else "client"
    now = datetime.now(settings.tz) if settings else datetime.now()
    text, keyboard = await build_calendar(now.year, now.month, mode=mode)
    await message.answer(text, reply_markup=keyboard)


@router.callback_query(F.data.startswith("cal:"))
async def cb_calendar(callback: CallbackQuery) -> None:
    if not callback.data:
        return
    _, mode, year, month = callback.data.split(":")
    if mode == "admin" and (not callback.from_user or not is_admin(callback.from_user.id)):
        await callback.answer("Нет доступа", show_alert=True)
        return
    text, keyboard = await build_calendar(int(year), int(month), mode=mode)
    if callback.message:
        await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data == "noop")
async def cb_noop(callback: CallbackQuery) -> None:
    await callback.answer()


@router.callback_query(F.data.startswith("day:client:"))
async def cb_client_day(callback: CallbackQuery) -> None:
    if not callback.data or not callback.message:
        return
    iso_date = callback.data.split(":", 2)[2]
    usage = await db.day_usage(iso_date)
    dt = datetime.strptime(iso_date, "%Y-%m-%d").date()
    if usage.available <= 0:
        await callback.answer("Эта дата занята. Выберите другую.", show_alert=True)
        return
    text = (
        f"📅 {dt.strftime('%d.%m.%Y')}\n\n"
        f"Свободно роботов: {usage.available} из {usage.active_robots}.\n"
        "Вы можете оставить заявку. Окончательно бронь подтверждает администратор."
    )
    await callback.message.edit_text(text, reply_markup=client_day_keyboard(iso_date, dt.year, dt.month))
    await callback.answer()


@router.callback_query(F.data.startswith("day:admin:"))
async def cb_admin_day(callback: CallbackQuery) -> None:
    if not callback.from_user or not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    if not callback.data or not callback.message:
        return
    iso_date = callback.data.split(":", 2)[2]
    usage = await db.day_usage(iso_date)
    dt = datetime.strptime(iso_date, "%Y-%m-%d").date()
    text = (
        f"🔧 Управление датой {dt.strftime('%d.%m.%Y')}\n\n"
        f"Всего активных роботов: {usage.active_robots}\n"
        f"Подтверждённых броней: {usage.confirmed_bookings}\n"
        f"Ручных блокировок: {usage.manual_blocks}\n"
        f"Свободно: {usage.available}\n\n"
        "Клиенты эту дату менять не могут. Они видят только статус свободно/занято."
    )
    await callback.message.edit_text(text, reply_markup=admin_day_keyboard(iso_date, dt.year, dt.month))
    await callback.answer()


@router.callback_query(F.data.startswith("block:"))
async def cb_admin_block(callback: CallbackQuery) -> None:
    if not callback.from_user or not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    if not callback.data or not callback.message:
        return
    _, action, iso_date = callback.data.split(":", 2)
    if action == "full":
        qty = await db.block_remaining_robots(iso_date)
        await callback.answer(f"Дата занята полностью. Блокировка: {qty}")
    elif action == "add":
        qty = await db.increment_manual_block(iso_date, 1)
        await callback.answer(f"Ручная блокировка: {qty}")
    elif action == "clear":
        await db.clear_manual_block(iso_date)
        await callback.answer("Ручная блокировка снята")
    dt = datetime.strptime(iso_date, "%Y-%m-%d").date()
    usage = await db.day_usage(iso_date)
    text = (
        f"🔧 Управление датой {dt.strftime('%d.%m.%Y')}\n\n"
        f"Всего активных роботов: {usage.active_robots}\n"
        f"Подтверждённых броней: {usage.confirmed_bookings}\n"
        f"Ручных блокировок: {usage.manual_blocks}\n"
        f"Свободно: {usage.available}"
    )
    await callback.message.edit_text(text, reply_markup=admin_day_keyboard(iso_date, dt.year, dt.month))


@router.message(F.text == "🧽 Забронировать робота")
async def start_booking(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(BookingForm.dates)
    await message.answer(
        "📅 Напишите нужные даты аренды.\n\n"
        "Форматы:\n"
        "• 12.05.2026\n"
        "• 12.05.2026-14.05.2026\n"
        "• 12-14 мая 2026\n"
        "• 12.05, 15.05"
    )


@router.callback_query(F.data == "book:start")
async def cb_book_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(BookingForm.dates)
    if callback.message:
        await callback.message.answer(
            "📅 Напишите нужные даты аренды. Например: 12.05.2026-14.05.2026"
        )
    await callback.answer()


@router.callback_query(F.data.startswith("bookdate:"))
async def cb_book_date(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.data or not callback.message:
        return
    iso_date = callback.data.split(":", 1)[1]
    await state.clear()
    await state.update_data(dates=datetime.strptime(iso_date, "%Y-%m-%d").strftime("%d.%m.%Y"))
    await state.set_state(BookingForm.name)
    await callback.message.answer("👤 Введите ваше имя:")
    await callback.answer()


@router.message(BookingForm.dates)
async def form_dates(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer("Пожалуйста, напишите даты текстом.")
        return
    try:
        parsed = parse_dates_to_iso(message.text)
    except ValueError as exc:
        await message.answer(f"⚠️ {exc}")
        return
    availability = await db.availability_for_dates(parsed)
    unavailable = [iso for iso, info in availability.items() if info.available <= 0]
    if unavailable:
        await message.answer(
            "На эти даты свободных роботов нет: " + format_iso_dates_ru(unavailable) +
            "\nВыберите другие даты или отправьте заявку с комментарием."
        )
        return
    await state.update_data(dates=message.text)
    await state.set_state(BookingForm.name)
    await message.answer("👤 Введите ваше имя:")


@router.message(BookingForm.name)
async def form_name(message: Message, state: FSMContext) -> None:
    if not message.text or len(message.text.strip()) < 2:
        await message.answer("Введите имя, пожалуйста.")
        return
    await state.update_data(name=message.text.strip())
    await state.set_state(BookingForm.phone)
    await message.answer("📞 Введите телефон для связи:")


@router.message(BookingForm.phone)
async def form_phone(message: Message, state: FSMContext) -> None:
    if not message.text or len(message.text.strip()) < 5:
        await message.answer("Введите телефон, пожалуйста.")
        return
    await state.update_data(phone=message.text.strip())
    await state.set_state(BookingForm.address)
    await message.answer("📍 Введите адрес или район, где будет использоваться робот:")


@router.message(BookingForm.address)
async def form_address(message: Message, state: FSMContext) -> None:
    if not message.text or len(message.text.strip()) < 3:
        await message.answer("Введите адрес или район, пожалуйста.")
        return
    await state.update_data(address=message.text.strip())
    await state.set_state(BookingForm.delivery)
    await message.answer("🚚 Нужна доставка? Напишите: да / нет / обсудить")


@router.message(BookingForm.delivery)
async def form_delivery(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer("Напишите, нужна ли доставка.")
        return
    await state.update_data(delivery=message.text.strip())
    await state.set_state(BookingForm.comment)
    await message.answer("💬 Комментарий к заявке. Если комментария нет, напишите '-' .")


@router.message(BookingForm.comment)
async def form_comment(message: Message, state: FSMContext, bot: Bot) -> None:
    if not message.from_user:
        return
    data = await state.get_data()
    comment = "" if not message.text or message.text.strip() == "-" else message.text.strip()
    booking_id = await db.create_booking(
        user_telegram_id=message.from_user.id,
        client_name=data["name"],
        phone=data["phone"],
        address=data["address"],
        delivery_required=data["delivery"],
        comment=comment,
        requested_dates_text=data["dates"],
    )
    await state.clear()
    await message.answer(
        f"✅ Заявка #{booking_id} отправлена.\n"
        "Администратор проверит наличие робота и подтвердит бронь.",
        reply_markup=client_menu(),
    )
    booking = await db.get_booking(booking_id)
    if booking:
        await notify_admins(bot, booking_card(booking), booking_id=booking_id)


@router.callback_query(F.data.startswith("booking:"))
async def cb_booking(callback: CallbackQuery, bot: Bot) -> None:
    if not callback.from_user or not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    if not callback.data:
        return
    _, action, booking_id_raw = callback.data.split(":", 2)
    booking_id = int(booking_id_raw)
    booking = await db.get_booking(booking_id)
    if not booking:
        await callback.answer("Заявка не найдена", show_alert=True)
        return

    if action == "view":
        if callback.message:
            await callback.message.answer(booking_card(booking), reply_markup=booking_admin_keyboard(booking_id))
        await callback.answer()
        return

    if action == "approve":
        ok, msg, dates = await db.confirm_booking(booking_id)
        await callback.answer(msg, show_alert=not ok)
        booking = await db.get_booking(booking_id)
        if callback.message and booking:
            await callback.message.edit_text(
                booking_card(booking, dates=dates),
                reply_markup=booking_admin_keyboard(booking_id),
            )
        if ok:
            try:
                await bot.send_message(
                    booking["user_telegram_id"],
                    "✅ Ваша бронь подтверждена.\n"
                    f"Даты: {format_iso_dates_ru(dates)}\n\n"
                    "Администратор может отправить вам PDF-договор аренды."
                )
            except Exception:
                pass
        return

    if action == "decline":
        ok = await db.decline_booking(booking_id)
        await callback.answer("Заявка отклонена" if ok else "Ошибка", show_alert=not ok)
        if ok:
            try:
                await bot.send_message(
                    booking["user_telegram_id"],
                    "❌ К сожалению, заявка отклонена. Вы можете выбрать другие даты."
                )
            except Exception:
                pass
            if callback.message:
                updated = await db.get_booking(booking_id)
                if updated:
                    await callback.message.edit_text(booking_card(updated), reply_markup=booking_admin_keyboard(booking_id))
        return

    if action in {"contract", "send_contract"}:
        dates = await db.get_booking_dates(booking_id)
        path = generate_contract_pdf(settings, booking=booking, dates=dates)
        if action == "contract":
            if callback.message:
                await callback.message.answer_document(
                    FSInputFile(path),
                    caption=f"📄 Договор по заявке #{booking_id}"
                )
            await callback.answer()
        else:
            try:
                await bot.send_document(
                    booking["user_telegram_id"],
                    FSInputFile(path),
                    caption="📄 Ваш договор аренды робота-мойщика окон."
                )
                await callback.answer("PDF отправлен клиенту")
            except Exception:
                await callback.answer("Не удалось отправить PDF клиенту", show_alert=True)
        return


@router.message(F.text == "🆕 Новые заявки")
async def new_bookings(message: Message) -> None:
    if not message.from_user or not is_admin(message.from_user.id):
        await message.answer("Нет доступа.")
        return
    rows = await db.list_bookings("new", limit=10)
    if not rows:
        await message.answer("Новых заявок нет.")
        return
    for booking in rows:
        await message.answer(booking_card(booking), reply_markup=booking_admin_keyboard(booking["id"]))


@router.message(F.text == "✅ Активные брони")
async def active_bookings(message: Message) -> None:
    if not message.from_user or not is_admin(message.from_user.id):
        await message.answer("Нет доступа.")
        return
    rows = await db.list_bookings("confirmed", limit=10)
    if not rows:
        await message.answer("Активных броней нет.")
        return
    for booking in rows:
        dates = await db.get_booking_dates(booking["id"])
        await message.answer(booking_card(booking, dates=dates), reply_markup=booking_short_keyboard(booking["id"]))


@router.message(F.text == "🤖 Роботы")
async def robots(message: Message) -> None:
    if not message.from_user or not is_admin(message.from_user.id):
        await message.answer("Нет доступа.")
        return
    summary = await db.robot_summary()
    await message.answer(
        "🤖 Роботы\n\n"
        f"Активных: {summary.get('active', 0)}\n"
        f"Неактивных: {summary.get('inactive', 0)}\n"
        f"На обслуживании: {summary.get('maintenance', 0)}\n\n"
        "Дата считается свободной, пока есть хотя бы один активный робот без брони или ручной блокировки.",
        reply_markup=robots_keyboard(),
    )


@router.callback_query(F.data.startswith("robots:"))
async def cb_robots(callback: CallbackQuery) -> None:
    if not callback.from_user or not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    if not callback.data:
        return
    action = callback.data.split(":", 1)[1]
    if action == "add":
        await db.add_robot()
        await callback.answer("Робот добавлен")
    elif action == "remove":
        ok = await db.remove_one_active_robot()
        await callback.answer("Один активный робот убран" if ok else "Нет активных роботов", show_alert=not ok)
    summary = await db.robot_summary()
    if callback.message:
        await callback.message.edit_text(
            "🤖 Роботы\n\n"
            f"Активных: {summary.get('active', 0)}\n"
            f"Неактивных: {summary.get('inactive', 0)}\n"
            f"На обслуживании: {summary.get('maintenance', 0)}",
            reply_markup=robots_keyboard(),
        )


@router.message()
async def fallback(message: Message) -> None:
    if message.from_user and is_admin(message.from_user.id):
        await message.answer("Выберите действие в админ-меню.", reply_markup=admin_menu())
    else:
        await message.answer("Выберите действие в меню.", reply_markup=client_menu())
