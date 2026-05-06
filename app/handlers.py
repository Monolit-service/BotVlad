from __future__ import annotations

from datetime import datetime
import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command, StateFilter
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
    support_admin_keyboard,
    support_again_keyboard,
)
from app.services.calendar import build_calendar
from app.services.contracts import get_contract_pdf
from app.services.dates import format_iso_dates_ru, parse_dates_to_iso
from app.states import AdminSupportReply, BookingForm, RobotSettings, SupportChat
from app.texts import CONTACT_TEXT, PRICES_TEXT, SUPPORT_PROMPT_TEXT, admin_welcome, booking_card, client_welcome

router = Router()
logger = logging.getLogger(__name__)
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
            logger.exception("Не удалось отправить уведомление админу %s", admin_id)


async def robots_panel_text() -> str:
    summary = await db.robot_summary()
    active = summary.get("active", 0)
    maintenance = summary.get("maintenance", 0)
    total = summary.get("total", 0)
    return (
        "🤖 Учёт роботов\n\n"
        f"Всего роботов в базе: {total}\n"
        f"Доступны для бронирования: {active}\n"
        f"На обслуживании: {maintenance}\n\n"
        "Доступность календаря считается только по роботам, которые доступны для бронирования. "
        "Роботы на обслуживании остаются в общем парке, но не выдаются клиентам.\n\n"
        "➕/➖ меняют общее количество роботов. "
        "🛠️/✅ переводят роботов на обслуживание и обратно."
    )


async def safe_delete_message(bot: Bot, chat_id: int, message_id: int | None) -> None:
    return


async def delete_incoming(message: Message, bot: Bot) -> None:
    return


async def delete_last_ui_message(bot: Bot, chat_id: int, scope: str = "main") -> None:
    return


async def send_clean_message(
    bot: Bot,
    chat_id: int,
    text: str,
    *,
    reply_markup=None,
    scope: str = "main",
    remember: bool = True,
    **kwargs,
) -> Message:
    await delete_last_ui_message(bot, chat_id, scope=scope)
    sent = await bot.send_message(chat_id, text, reply_markup=reply_markup, **kwargs)
    if remember:
        await db.remember_ui_message(chat_id, sent.message_id, scope=scope)
    return sent


async def answer_clean(
    message: Message,
    bot: Bot,
    text: str,
    *,
    reply_markup=None,
    scope: str = "main",
    delete_user_message: bool = True,
    remember: bool = True,
    **kwargs,
) -> Message:
    if delete_user_message:
        await delete_incoming(message, bot)
    return await send_clean_message(
        bot,
        message.chat.id,
        text,
        reply_markup=reply_markup,
        scope=scope,
        remember=remember,
        **kwargs,
    )

@router.message(Command("start"))
async def cmd_start(message: Message, bot: Bot) -> None:
    assert settings is not None
    user = message.from_user
    if not user:
        return
    admin = is_admin(user.id)
    await db.ensure_user(user.id, user.full_name, user.username, admin)
    if admin:
        await answer_clean(message, bot, admin_welcome(), reply_markup=admin_menu())
    else:
        await answer_clean(message, bot, client_welcome(user), reply_markup=client_menu())


@router.message(Command("admin"))
async def cmd_admin(message: Message, bot: Bot) -> None:
    if not message.from_user or not is_admin(message.from_user.id):
        await answer_clean(message, bot, "Нет доступа.")
        return
    await answer_clean(message, bot, admin_welcome(), reply_markup=admin_menu())


@router.message(Command("whoami"))
async def cmd_whoami(message: Message, bot: Bot) -> None:
    if not message.from_user:
        return
    role = "admin" if is_admin(message.from_user.id) else "client"
    await answer_clean(
        message,
        bot,
        "Ваш Telegram ID:\n"
        f"`{message.from_user.id}`\n\n"
        f"Роль в этом боте: {role}",
        parse_mode="Markdown",
    )


@router.message(Command("debug_admins"))
async def cmd_debug_admins(message: Message, bot: Bot) -> None:
    assert settings is not None
    if not message.from_user or not is_admin(message.from_user.id):
        await answer_clean(message, bot, "Нет доступа.")
        return
    await answer_clean(
        message,
        bot,
        "Админы из ADMIN_IDS:\n" + ", ".join(str(admin_id) for admin_id in sorted(settings.admin_ids))
    )


@router.message(F.text == "👀 Вид клиента")
async def client_view_for_admin(message: Message, bot: Bot) -> None:
    await answer_clean(message, bot, "Клиентское меню:", reply_markup=client_menu())


@router.message(F.text == "💰 Цены и условия")
async def prices(message: Message, bot: Bot) -> None:
    await answer_clean(message, bot, PRICES_TEXT)


@router.message(F.text == "📞 Связаться")
@router.message(F.text == "Связаться")
@router.message(Command("contact"))
@router.message(
    StateFilter(None),
    lambda message: bool(message.text and ("связ" in message.text.lower() or "контакт" in message.text.lower())),
)
async def contacts(message: Message, state: FSMContext, bot: Bot) -> None:
    if not message.from_user:
        return
    await state.clear()

    if is_admin(message.from_user.id):
        await answer_clean(
            message,
            bot,
            "Вы открыли клиентскую кнопку связи. Для ответа клиентам используйте кнопку "
            "«💬 Ответить клиенту» под входящим сообщением.",
            reply_markup=admin_menu(),
        )
        return

    await db.set_client_waiting_support(message.from_user.id)
    await state.set_state(SupportChat.message)
    await answer_clean(message, bot, CONTACT_TEXT + "\n\n" + SUPPORT_PROMPT_TEXT)


@router.message(F.text == "📄 Договор аренды PDF")
async def send_contract_template(message: Message, bot: Bot) -> None:
    assert settings is not None
    await delete_incoming(message, bot)
    await delete_last_ui_message(bot, message.chat.id)
    path = get_contract_pdf(settings)
    await message.answer_document(
        FSInputFile(path),
        caption="📄 Шаблон договора аренды робота-мойщика окон."
    )


@router.message(F.text.in_({"📅 Свободные даты", "📅 Календарь"}))
async def show_calendar(message: Message, bot: Bot) -> None:
    if not message.from_user:
        return
    mode = "admin" if is_admin(message.from_user.id) and message.text == "📅 Календарь" else "client"
    now = datetime.now(settings.tz) if settings else datetime.now()
    text, keyboard = await build_calendar(now.year, now.month, mode=mode)
    await answer_clean(message, bot, text, reply_markup=keyboard)


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
        f"Занято всего: {usage.occupied_total} из {usage.active_robots}\n"
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
        f"Занято всего: {usage.occupied_total} из {usage.active_robots}\n"
        f"Подтверждённых броней: {usage.confirmed_bookings}\n"
        f"Ручных блокировок: {usage.manual_blocks}\n"
        f"Свободно: {usage.available}"
    )
    await callback.message.edit_text(text, reply_markup=admin_day_keyboard(iso_date, dt.year, dt.month))


@router.message(F.text == "🧽 Забронировать робота")
async def start_booking(message: Message, state: FSMContext, bot: Bot) -> None:
    await state.clear()
    await state.set_state(BookingForm.dates)
    await answer_clean(
        message,
        bot,
        "📅 Напишите нужные даты аренды.\n\n"
        "Форматы:\n"
        "• 12.05.2026\n"
        "• 12.05.2026-14.05.2026\n"
        "• 12-14 мая 2026\n"
        "• 12.05, 15.05"
    )


@router.callback_query(F.data == "book:start")
async def cb_book_start(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    await state.clear()
    await state.set_state(BookingForm.dates)
    if callback.message:
        await send_clean_message(
            bot,
            callback.message.chat.id,
            "📅 Напишите нужные даты аренды. Например: 12.05.2026-14.05.2026"
        )
    await callback.answer()


@router.callback_query(F.data.startswith("bookdate:"))
async def cb_book_date(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    if not callback.data or not callback.message:
        return
    iso_date = callback.data.split(":", 1)[1]
    await state.clear()
    await state.update_data(dates=datetime.strptime(iso_date, "%Y-%m-%d").strftime("%d.%m.%Y"))
    await state.set_state(BookingForm.name)
    await send_clean_message(bot, callback.message.chat.id, "👤 Введите ваше имя:")
    await callback.answer()


@router.message(BookingForm.dates)
async def form_dates(message: Message, state: FSMContext, bot: Bot) -> None:
    if not message.text:
        await answer_clean(message, bot, "Пожалуйста, напишите даты текстом.")
        return
    try:
        parsed = parse_dates_to_iso(message.text)
    except ValueError as exc:
        await answer_clean(message, bot, f"⚠️ {exc}\n\nНапишите даты ещё раз.")
        return
    availability = await db.availability_for_dates(parsed)
    unavailable = [iso for iso, info in availability.items() if info.available <= 0]
    if unavailable:
        await answer_clean(
            message,
            bot,
            "На эти даты свободных роботов нет: " + format_iso_dates_ru(unavailable) +
            "\nВыберите другие даты или отправьте заявку с комментарием."
        )
        return
    await state.update_data(dates=message.text)
    await state.set_state(BookingForm.name)
    await answer_clean(message, bot, "👤 Введите ваше имя:")


@router.message(BookingForm.name)
async def form_name(message: Message, state: FSMContext, bot: Bot) -> None:
    if not message.text or len(message.text.strip()) < 2:
        await answer_clean(message, bot, "Введите имя, пожалуйста.")
        return
    await state.update_data(name=message.text.strip())
    await state.set_state(BookingForm.phone)
    await answer_clean(message, bot, "📞 Введите телефон для связи:")


@router.message(BookingForm.phone)
async def form_phone(message: Message, state: FSMContext, bot: Bot) -> None:
    if not message.text or len(message.text.strip()) < 5:
        await answer_clean(message, bot, "Введите телефон, пожалуйста.")
        return
    await state.update_data(phone=message.text.strip())
    await state.set_state(BookingForm.address)
    await answer_clean(message, bot, "📍 Введите адрес или район, где будет использоваться робот:")


@router.message(BookingForm.address)
async def form_address(message: Message, state: FSMContext, bot: Bot) -> None:
    if not message.text or len(message.text.strip()) < 3:
        await answer_clean(message, bot, "Введите адрес или район, пожалуйста.")
        return
    await state.update_data(address=message.text.strip())
    await state.set_state(BookingForm.delivery)
    await answer_clean(message, bot, "🚚 Нужна доставка? Напишите: да / нет / обсудить")


@router.message(BookingForm.delivery)
async def form_delivery(message: Message, state: FSMContext, bot: Bot) -> None:
    if not message.text:
        await answer_clean(message, bot, "Напишите, нужна ли доставка.")
        return
    await state.update_data(delivery=message.text.strip())
    await state.set_state(BookingForm.comment)
    await answer_clean(message, bot, "💬 Комментарий к заявке. Если комментария нет, напишите '-' .")


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
    await answer_clean(
        message,
        bot,
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
        path = get_contract_pdf(settings, booking=booking, dates=dates)
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
async def new_bookings(message: Message, bot: Bot) -> None:
    if not message.from_user or not is_admin(message.from_user.id):
        await answer_clean(message, bot, "Нет доступа.")
        return
    await delete_incoming(message, bot)
    await delete_last_ui_message(bot, message.chat.id)
    rows = await db.list_bookings("new", limit=10)
    if not rows:
        await send_clean_message(bot, message.chat.id, "Новых заявок нет.")
        return
    for booking in rows:
        await bot.send_message(message.chat.id, booking_card(booking), reply_markup=booking_admin_keyboard(booking["id"]))


@router.message(F.text == "✅ Активные брони")
async def active_bookings(message: Message, bot: Bot) -> None:
    if not message.from_user or not is_admin(message.from_user.id):
        await answer_clean(message, bot, "Нет доступа.")
        return
    await delete_incoming(message, bot)
    await delete_last_ui_message(bot, message.chat.id)
    rows = await db.list_bookings("confirmed", limit=10)
    if not rows:
        await send_clean_message(bot, message.chat.id, "Активных броней нет.")
        return
    for booking in rows:
        dates = await db.get_booking_dates(booking["id"])
        await bot.send_message(message.chat.id, booking_card(booking, dates=dates), reply_markup=booking_short_keyboard(booking["id"]))


@router.message(F.text == "🤖 Роботы")
async def robots(message: Message, state: FSMContext, bot: Bot) -> None:
    if not message.from_user or not is_admin(message.from_user.id):
        await answer_clean(message, bot, "Нет доступа.")
        return
    await state.clear()
    await answer_clean(message, bot, await robots_panel_text(), reply_markup=robots_keyboard())


@router.callback_query(F.data.startswith("robots:"))
async def cb_robots(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    if not callback.from_user or not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    if not callback.data:
        return
    action = callback.data.split(":", 1)[1]

    if action == "add":
        await db.add_robot()
        await callback.answer("Добавлен 1 робот в общий парк")
    elif action == "remove":
        ok = await db.remove_one_robot()
        await callback.answer("Удалён 1 робот из общего парка" if ok else "В базе нет роботов", show_alert=not ok)
    elif action == "maintenance_add":
        ok = await db.send_one_robot_to_maintenance()
        await callback.answer("1 робот отправлен на обслуживание" if ok else "Нет доступных роботов", show_alert=not ok)
    elif action == "maintenance_remove":
        ok = await db.return_one_robot_from_maintenance()
        await callback.answer("1 робот снят с обслуживания" if ok else "Нет роботов на обслуживании", show_alert=not ok)
    elif action == "set_total":
        await state.set_state(RobotSettings.count)
        if callback.message:
            await send_clean_message(
                bot,
                callback.message.chat.id,
                "Введите общее количество роботов в базе числом.\n\n"
                "Например: 3\n"
                "Если указать меньше текущего числа, лишние роботы будут удалены из базы. "
                "Сначала удаляются роботы на обслуживании, потом доступные."
            )
        await callback.answer()
        return
    elif action == "refresh":
        await callback.answer("Обновлено")

    if callback.message:
        await callback.message.edit_text(await robots_panel_text(), reply_markup=robots_keyboard())

@router.message(RobotSettings.count)
async def set_robot_count(message: Message, state: FSMContext, bot: Bot) -> None:
    if not message.from_user or not is_admin(message.from_user.id):
        await answer_clean(message, bot, "Нет доступа.")
        await state.clear()
        return
    if not message.text or not message.text.strip().isdigit():
        await answer_clean(message, bot, "Введите целое число: 0, 1, 2, 3 ...")
        return

    target_count = int(message.text.strip())
    if target_count > 100:
        await answer_clean(message, bot, "Слишком большое число. Введите значение до 100.")
        return

    await db.set_total_robot_count(target_count)
    await state.clear()
    await answer_clean(
        message,
        bot,
        f"✅ Общее количество роботов установлено: {target_count}\n\n" + await robots_panel_text(),
        reply_markup=robots_keyboard(),
    )

@router.callback_query(F.data == "support:start")
async def cb_support_start(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    if not callback.from_user or is_admin(callback.from_user.id):
        await callback.answer("Эта кнопка доступна клиенту", show_alert=True)
        return
    await state.clear()
    await db.set_client_waiting_support(callback.from_user.id)
    await state.set_state(SupportChat.message)
    if callback.message:
        await send_clean_message(bot, callback.message.chat.id, SUPPORT_PROMPT_TEXT)
    await callback.answer()


async def forward_support_message_to_admins(message: Message, state: FSMContext, bot: Bot) -> None:
    if not message.from_user:
        return
    if is_admin(message.from_user.id):
        await answer_clean(
            message,
            bot,
            "Администратор отвечает клиентам через кнопку под сообщением клиента.",
            reply_markup=admin_menu(),
        )
        await state.clear()
        return

    user = message.from_user
    await db.ensure_user(user.id, user.full_name, user.username, admin=False)
    client_label = user.full_name or "Без имени"
    username = f"@{user.username}" if user.username else "username не указан"
    body = message.text or message.caption or "[клиент отправил вложение без текста]"
    admin_text = (
        "💬 Сообщение от клиента\n\n"
        f"👤 Клиент: {client_label}\n"
        f"🔗 Telegram: {username}\n"
        f"🆔 ID: {user.id}\n\n"
        f"Текст сообщения:\n{body.strip()}"
    )

    assert settings is not None
    delivered = 0
    for admin_id in settings.admin_ids:
        try:
            await bot.send_message(
                admin_id,
                admin_text,
                reply_markup=support_admin_keyboard(user.id),
            )
            # Если клиент отправил не текст, дополнительно копируем вложение админу.
            if not message.text:
                try:
                    await message.copy_to(admin_id)
                except Exception:
                    logger.exception("Не удалось скопировать вложение клиента админу %s", admin_id)
            delivered += 1
        except Exception:
            logger.exception(
                "Не удалось доставить сообщение поддержки админу %s. "
                "Проверьте ADMIN_IDS и что админ нажал /start в боте.",
                admin_id,
            )

    await db.clear_support_session(user.id)
    await state.clear()
    await delete_incoming(message, bot)
    if delivered:
        await send_clean_message(
            bot,
            message.chat.id,
            "✅ Сообщение отправлено администратору. Ответ придёт сюда, в этот бот.",
            reply_markup=client_menu(),
        )
    else:
        await send_clean_message(
            bot,
            message.chat.id,
            "⚠️ Не удалось отправить сообщение администратору. "
            "Проверьте, что администратор уже запускал этого бота через /start.",
            reply_markup=client_menu(),
        )

@router.message(SupportChat.message)
async def support_client_message(message: Message, state: FSMContext, bot: Bot) -> None:
    await forward_support_message_to_admins(message, state, bot)


@router.callback_query(F.data.startswith("support:reply:"))
async def cb_support_reply(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    if not callback.from_user or not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    if not callback.data:
        return
    client_id_raw = callback.data.split(":", 2)[2]
    try:
        client_id = int(client_id_raw)
    except ValueError:
        await callback.answer("Некорректный ID клиента", show_alert=True)
        return

    await state.clear()
    await db.set_admin_reply_target(callback.from_user.id, client_id)
    await state.update_data(reply_client_id=client_id)
    await state.set_state(AdminSupportReply.message)
    if callback.message:
        await send_clean_message(
            bot,
            callback.message.chat.id,
            "💬 Напишите ответ клиенту одним сообщением.\n"
            "После отправки бот перешлёт ваш текст клиенту."
        )
    await callback.answer()


async def send_support_reply_to_client(message: Message, state: FSMContext, bot: Bot) -> None:
    if not message.from_user or not is_admin(message.from_user.id):
        await answer_clean(message, bot, "Нет доступа.")
        await state.clear()
        return

    data = await state.get_data()
    client_id = data.get("reply_client_id")
    if not client_id:
        client_id = await db.get_admin_reply_target(message.from_user.id)
    if not client_id:
        await answer_clean(message, bot, "Не найден клиент для ответа. Нажмите кнопку «Ответить клиенту» ещё раз.")
        await state.clear()
        return

    try:
        if message.text:
            await bot.send_message(
                int(client_id),
                "💬 Ответ администратора:\n\n" + message.text.strip(),
                reply_markup=support_again_keyboard(),
            )
        else:
            await bot.send_message(int(client_id), "💬 Ответ администратора:")
            await message.copy_to(int(client_id), reply_markup=support_again_keyboard())
    except Exception:
        logger.exception("Не удалось отправить ответ поддержки клиенту %s", client_id)
        await db.clear_support_session(message.from_user.id)
        await state.clear()
        await answer_clean(
            message,
            bot,
            "⚠️ Не удалось отправить ответ клиенту. Возможно, клиент заблокировал бота.",
            reply_markup=admin_menu(),
        )
        return

    await db.clear_support_session(message.from_user.id)
    await state.clear()
    await answer_clean(message, bot, "✅ Ответ отправлен клиенту.", reply_markup=admin_menu())


@router.message(AdminSupportReply.message)
async def support_admin_reply(message: Message, state: FSMContext, bot: Bot) -> None:
    await send_support_reply_to_client(message, state, bot)


@router.message()
async def fallback(message: Message, state: FSMContext, bot: Bot) -> None:
    if not message.from_user:
        return

    # Резервный путь: если FSM-состояние по какой-то причине не сработало
    # или бот был перезапущен между нажатием кнопки и сообщением, состояние
    # чата поддержки хранится в SQLite и сообщение всё равно уйдёт адресату.
    if is_admin(message.from_user.id):
        if await db.get_admin_reply_target(message.from_user.id):
            await send_support_reply_to_client(message, state, bot)
            return
        await answer_clean(message, bot, "Выберите действие в админ-меню.", reply_markup=admin_menu())
        return

    if await db.is_client_waiting_support(message.from_user.id):
        await forward_support_message_to_admins(message, state, bot)
        return

    await answer_clean(message, bot, "Выберите действие в меню.", reply_markup=client_menu())
