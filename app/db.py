from __future__ import annotations

import sqlite3
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import AsyncIterator, Iterable

import aiosqlite

from app.config import DB_PATH, DATA_DIR
from app.services.dates import parse_dates_to_iso


SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER NOT NULL UNIQUE,
    full_name TEXT,
    username TEXT,
    phone TEXT,
    role TEXT NOT NULL DEFAULT 'client',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS robots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    note TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS bookings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_telegram_id INTEGER NOT NULL,
    client_name TEXT NOT NULL,
    phone TEXT NOT NULL,
    address TEXT NOT NULL,
    delivery_required TEXT NOT NULL,
    comment TEXT,
    requested_dates_text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'new',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    confirmed_at TEXT,
    declined_at TEXT,
    decline_reason TEXT
);

CREATE TABLE IF NOT EXISTS booking_dates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    booking_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(booking_id, date),
    FOREIGN KEY(booking_id) REFERENCES bookings(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS manual_blocks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL UNIQUE,
    quantity INTEGER NOT NULL DEFAULT 1,
    note TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Простое постоянное состояние чата поддержки.
-- Оно не теряется при перезапуске контейнера, в отличие от MemoryStorage FSM.
CREATE TABLE IF NOT EXISTS support_sessions (
    telegram_id INTEGER PRIMARY KEY,
    mode TEXT NOT NULL,
    target_client_id INTEGER,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Последнее сервисное сообщение бота в личном чате.
-- Нужно, чтобы заменять старые меню/календарь/шаги формы новыми сообщениями
-- и не оставлять в чате неактуальные кнопки.
CREATE TABLE IF NOT EXISTS ui_messages (
    telegram_id INTEGER NOT NULL,
    scope TEXT NOT NULL DEFAULT 'main',
    message_id INTEGER NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (telegram_id, scope)
);

CREATE INDEX IF NOT EXISTS idx_bookings_status ON bookings(status);
CREATE INDEX IF NOT EXISTS idx_booking_dates_date ON booking_dates(date);
CREATE INDEX IF NOT EXISTS idx_manual_blocks_date ON manual_blocks(date);
"""


@dataclass(frozen=True)
class DayAvailability:
    iso_date: str
    active_robots: int
    confirmed_bookings: int
    manual_blocks: int
    available: int

    @property
    def occupied_total(self) -> int:
        """Confirmed bookings plus manual blocks for this date."""
        return self.confirmed_bookings + self.manual_blocks

    @property
    def is_free(self) -> bool:
        return self.available > 0


async def init_db(initial_robots: int = 1) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(SCHEMA_SQL)
        # Старые версии использовали статус inactive. Теперь это обслуживание.
        await db.execute("UPDATE robots SET status='maintenance' WHERE status='inactive'")

        # Миграция для старых подтверждённых броней: если бронь уже была
        # подтверждена, но строки в booking_dates по какой-то причине не были
        # созданы, админский календарь не сможет посчитать занятых роботов.
        cursor = await db.execute(
            """
            SELECT b.id, b.requested_dates_text
            FROM bookings b
            WHERE b.status='confirmed'
              AND NOT EXISTS (SELECT 1 FROM booking_dates bd WHERE bd.booking_id=b.id)
            """
        )
        confirmed_without_dates = await cursor.fetchall()
        for booking_id, requested_dates_text in confirmed_without_dates:
            try:
                iso_dates = parse_dates_to_iso(requested_dates_text or "")
            except ValueError:
                continue
            for iso in iso_dates:
                await db.execute(
                    "INSERT OR IGNORE INTO booking_dates(booking_id, date) VALUES (?, ?)",
                    (booking_id, iso),
                )

        await db.commit()
        cursor = await db.execute("SELECT COUNT(*) FROM robots")
        row = await cursor.fetchone()
        robot_count = int(row[0]) if row else 0
        if robot_count == 0:
            count = max(1, int(initial_robots))
            for idx in range(1, count + 1):
                await db.execute(
                    "INSERT INTO robots(name, status) VALUES (?, 'active')",
                    (f"Робот #{idx}",),
                )
            await db.commit()


@asynccontextmanager
async def get_db() -> AsyncIterator[aiosqlite.Connection]:
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA foreign_keys=ON")
    try:
        yield db
        await db.commit()
    finally:
        await db.close()


async def ensure_user(telegram_id: int, full_name: str | None, username: str | None, is_admin: bool) -> None:
    role = "admin" if is_admin else "client"
    async with get_db() as db:
        await db.execute(
            """
            INSERT INTO users(telegram_id, full_name, username, role)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET
                full_name=excluded.full_name,
                username=excluded.username,
                role=CASE WHEN users.role='admin' THEN 'admin' ELSE excluded.role END
            """,
            (telegram_id, full_name, username, role),
        )




async def set_client_waiting_support(telegram_id: int) -> None:
    async with get_db() as db:
        await db.execute(
            """
            INSERT INTO support_sessions(telegram_id, mode, target_client_id, updated_at)
            VALUES (?, 'client_waiting', NULL, CURRENT_TIMESTAMP)
            ON CONFLICT(telegram_id) DO UPDATE SET
                mode='client_waiting',
                target_client_id=NULL,
                updated_at=CURRENT_TIMESTAMP
            """,
            (telegram_id,),
        )


async def is_client_waiting_support(telegram_id: int) -> bool:
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT mode FROM support_sessions WHERE telegram_id=?",
            (telegram_id,),
        )
        row = await cursor.fetchone()
    return bool(row and row["mode"] == "client_waiting")


async def clear_support_session(telegram_id: int) -> None:
    async with get_db() as db:
        await db.execute("DELETE FROM support_sessions WHERE telegram_id=?", (telegram_id,))


async def set_admin_reply_target(admin_telegram_id: int, client_telegram_id: int) -> None:
    async with get_db() as db:
        await db.execute(
            """
            INSERT INTO support_sessions(telegram_id, mode, target_client_id, updated_at)
            VALUES (?, 'admin_reply', ?, CURRENT_TIMESTAMP)
            ON CONFLICT(telegram_id) DO UPDATE SET
                mode='admin_reply',
                target_client_id=excluded.target_client_id,
                updated_at=CURRENT_TIMESTAMP
            """,
            (admin_telegram_id, client_telegram_id),
        )


async def get_admin_reply_target(admin_telegram_id: int) -> int | None:
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT target_client_id FROM support_sessions WHERE telegram_id=? AND mode='admin_reply'",
            (admin_telegram_id,),
        )
        row = await cursor.fetchone()
    if not row or row["target_client_id"] is None:
        return None
    return int(row["target_client_id"])

async def active_robot_count() -> int:
    async with get_db() as db:
        cursor = await db.execute("SELECT COUNT(*) FROM robots WHERE status='active'")
        row = await cursor.fetchone()
        return int(row[0]) if row else 0


async def robot_summary() -> dict[str, int]:
    async with get_db() as db:
        cursor = await db.execute("SELECT status, COUNT(*) AS cnt FROM robots GROUP BY status")
        rows = await cursor.fetchall()
    summary = {"active": 0, "maintenance": 0, "inactive": 0, "total": 0}
    for row in rows:
        status = row["status"]
        count = int(row["cnt"])
        if status == "inactive":
            status = "maintenance"
        summary[status] = summary.get(status, 0) + count
        summary["total"] += count
    return summary


async def add_robot() -> int:
    """Add one new robot to the total fleet and make it available."""
    async with get_db() as db:
        cursor = await db.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM robots")
        next_num = int((await cursor.fetchone())[0])
        cursor = await db.execute(
            "INSERT INTO robots(name, status) VALUES (?, 'active')",
            (f"Робот #{next_num}",),
        )
        return int(cursor.lastrowid)


async def remove_one_robot() -> bool:
    """Remove one robot from the total fleet.

    Prefer deleting a robot that is on maintenance so active availability is not
    reduced unexpectedly. If there are no maintenance robots, remove the last
    active robot.
    """
    async with get_db() as db:
        cursor = await db.execute(
            """
            SELECT id FROM robots
            ORDER BY CASE WHEN status='maintenance' THEN 0 WHEN status='inactive' THEN 1 ELSE 2 END, id DESC
            LIMIT 1
            """
        )
        row = await cursor.fetchone()
        if not row:
            return False
        await db.execute("DELETE FROM robots WHERE id=?", (row["id"],))
        return True


async def set_total_robot_count(target_count: int) -> dict[str, int]:
    """Set exact total number of robots stored in the database.

    Increasing the value creates new active robots. Decreasing the value deletes
    robots, preferring maintenance robots first, then active robots.
    """
    target_count = max(0, int(target_count))
    async with get_db() as db:
        cursor = await db.execute("SELECT COUNT(*) FROM robots")
        total_count = int((await cursor.fetchone())[0])

        if target_count > total_count:
            for _ in range(target_count - total_count):
                cursor = await db.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM robots")
                next_num = int((await cursor.fetchone())[0])
                await db.execute(
                    "INSERT INTO robots(name, status) VALUES (?, 'active')",
                    (f"Робот #{next_num}",),
                )
        elif target_count < total_count:
            delete_count = total_count - target_count
            cursor = await db.execute(
                """
                SELECT id FROM robots
                ORDER BY CASE WHEN status='maintenance' THEN 0 WHEN status='inactive' THEN 1 ELSE 2 END, id DESC
                LIMIT ?
                """,
                (delete_count,),
            )
            rows = await cursor.fetchall()
            for row in rows:
                await db.execute("DELETE FROM robots WHERE id=?", (row["id"],))

    return await robot_summary()


async def send_one_robot_to_maintenance() -> bool:
    async with get_db() as db:
        cursor = await db.execute("SELECT id FROM robots WHERE status='active' ORDER BY id DESC LIMIT 1")
        row = await cursor.fetchone()
        if not row:
            return False
        await db.execute("UPDATE robots SET status='maintenance' WHERE id=?", (row["id"],))
        return True


async def return_one_robot_from_maintenance() -> bool:
    async with get_db() as db:
        cursor = await db.execute("SELECT id FROM robots WHERE status IN ('maintenance', 'inactive') ORDER BY id LIMIT 1")
        row = await cursor.fetchone()
        if not row:
            return False
        await db.execute("UPDATE robots SET status='active' WHERE id=?", (row["id"],))
        return True


# Backward-compatible aliases for old handlers or external scripts.
async def set_active_robot_count(target_count: int) -> dict[str, int]:
    return await set_total_robot_count(target_count)


async def remove_one_active_robot() -> bool:
    return await remove_one_robot()


async def create_booking(
    *,
    user_telegram_id: int,
    client_name: str,
    phone: str,
    address: str,
    delivery_required: str,
    comment: str | None,
    requested_dates_text: str,
) -> int:
    async with get_db() as db:
        cursor = await db.execute(
            """
            INSERT INTO bookings(
                user_telegram_id, client_name, phone, address, delivery_required,
                comment, requested_dates_text, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'new')
            """,
            (
                user_telegram_id,
                client_name,
                phone,
                address,
                delivery_required,
                comment,
                requested_dates_text,
            ),
        )
        return int(cursor.lastrowid)


async def get_booking(booking_id: int) -> aiosqlite.Row | None:
    async with get_db() as db:
        cursor = await db.execute("SELECT * FROM bookings WHERE id=?", (booking_id,))
        return await cursor.fetchone()


async def get_booking_dates(booking_id: int) -> list[str]:
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT date FROM booking_dates WHERE booking_id=? ORDER BY date",
            (booking_id,),
        )
        rows = await cursor.fetchall()
    return [row["date"] for row in rows]


async def list_bookings(status: str = "new", limit: int = 10) -> list[aiosqlite.Row]:
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM bookings WHERE status=? ORDER BY created_at DESC LIMIT ?",
            (status, limit),
        )
        return await cursor.fetchall()


async def day_usage(iso_date: str) -> DayAvailability:
    async with get_db() as db:
        cursor = await db.execute("SELECT COUNT(*) FROM robots WHERE status='active'")
        active = int((await cursor.fetchone())[0])

        cursor = await db.execute(
            """
            SELECT COUNT(*) FROM booking_dates bd
            JOIN bookings b ON b.id = bd.booking_id
            WHERE bd.date=? AND b.status='confirmed'
            """,
            (iso_date,),
        )
        booked = int((await cursor.fetchone())[0])

        cursor = await db.execute(
            "SELECT COALESCE(quantity, 0) FROM manual_blocks WHERE date=?",
            (iso_date,),
        )
        row = await cursor.fetchone()
        blocks = int(row[0]) if row else 0

    available = max(0, active - booked - blocks)
    return DayAvailability(
        iso_date=iso_date,
        active_robots=active,
        confirmed_bookings=booked,
        manual_blocks=blocks,
        available=available,
    )


async def availability_for_dates(iso_dates: Iterable[str]) -> dict[str, DayAvailability]:
    result: dict[str, DayAvailability] = {}
    for iso in iso_dates:
        result[iso] = await day_usage(iso)
    return result


async def confirm_booking(booking_id: int) -> tuple[bool, str, list[str]]:
    booking = await get_booking(booking_id)
    if not booking:
        return False, "Заявка не найдена.", []
    if booking["status"] == "confirmed":
        dates = await get_booking_dates(booking_id)
        return True, "Заявка уже подтверждена.", dates
    if booking["status"] not in {"new", "pending"}:
        return False, f"Нельзя подтвердить заявку со статусом {booking['status']}.", []

    try:
        iso_dates = parse_dates_to_iso(booking["requested_dates_text"])
    except ValueError as exc:
        return False, str(exc), []

    if not iso_dates:
        return False, "Не удалось распознать даты. Попросите клиента указать даты в формате ДД.ММ.ГГГГ.", []

    availability = await availability_for_dates(iso_dates)
    unavailable = [iso for iso, info in availability.items() if info.available <= 0]
    if unavailable:
        return False, "Нет свободных роботов на даты: " + ", ".join(unavailable), unavailable

    async with get_db() as db:
        await db.execute(
            "UPDATE bookings SET status='confirmed', confirmed_at=CURRENT_TIMESTAMP WHERE id=?",
            (booking_id,),
        )
        for iso in iso_dates:
            await db.execute(
                "INSERT OR IGNORE INTO booking_dates(booking_id, date) VALUES (?, ?)",
                (booking_id, iso),
            )
    return True, "Бронь подтверждена, даты заняты.", iso_dates


async def decline_booking(booking_id: int, reason: str | None = None) -> bool:
    async with get_db() as db:
        cursor = await db.execute("SELECT id FROM bookings WHERE id=?", (booking_id,))
        if not await cursor.fetchone():
            return False
        await db.execute(
            """
            UPDATE bookings
            SET status='declined', declined_at=CURRENT_TIMESTAMP, decline_reason=?
            WHERE id=?
            """,
            (reason, booking_id),
        )
        await db.execute("DELETE FROM booking_dates WHERE booking_id=?", (booking_id,))
        return True


async def set_manual_block(iso_date: str, quantity: int, note: str | None = None) -> None:
    quantity = max(0, int(quantity))
    async with get_db() as db:
        if quantity == 0:
            await db.execute("DELETE FROM manual_blocks WHERE date=?", (iso_date,))
            return
        await db.execute(
            """
            INSERT INTO manual_blocks(date, quantity, note)
            VALUES (?, ?, ?)
            ON CONFLICT(date) DO UPDATE SET quantity=excluded.quantity, note=excluded.note
            """,
            (iso_date, quantity, note),
        )


async def increment_manual_block(iso_date: str, delta: int = 1) -> int:
    info = await day_usage(iso_date)
    new_qty = max(0, min(info.active_robots, info.manual_blocks + delta))
    await set_manual_block(iso_date, new_qty, "Ручная блокировка администратором")
    return new_qty


async def block_remaining_robots(iso_date: str) -> int:
    info = await day_usage(iso_date)
    target_block = max(0, info.active_robots - info.confirmed_bookings)
    await set_manual_block(iso_date, target_block, "Дата занята администратором")
    return target_block


async def clear_manual_block(iso_date: str) -> None:
    await set_manual_block(iso_date, 0)


async def remember_ui_message(telegram_id: int, message_id: int, scope: str = "main") -> None:
    async with get_db() as db:
        await db.execute(
            """
            INSERT INTO ui_messages(telegram_id, scope, message_id, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(telegram_id, scope) DO UPDATE SET
                message_id=excluded.message_id,
                updated_at=CURRENT_TIMESTAMP
            """,
            (telegram_id, scope, message_id),
        )


async def get_ui_message(telegram_id: int, scope: str = "main") -> int | None:
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT message_id FROM ui_messages WHERE telegram_id=? AND scope=?",
            (telegram_id, scope),
        )
        row = await cursor.fetchone()
    if not row:
        return None
    return int(row["message_id"])


async def clear_ui_message(telegram_id: int, scope: str = "main") -> None:
    async with get_db() as db:
        await db.execute(
            "DELETE FROM ui_messages WHERE telegram_id=? AND scope=?",
            (telegram_id, scope),
        )
