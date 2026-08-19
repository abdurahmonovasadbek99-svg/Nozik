"""
aiosqlite orqali: cooldown (bir xil signalni qayta yubormaslik) va obunachilar ro'yxati.
Nozik botning asosiy bazasidan alohida, kichik fayl (pump.db) sifatida ishlaydi.
"""

import time
import aiosqlite

DB_PATH = "pump.db"


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS alerts (
                symbol TEXT PRIMARY KEY,
                alerted_at INTEGER NOT NULL
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS subscribers (
                user_id INTEGER PRIMARY KEY
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS signal_outcomes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                direction TEXT NOT NULL,
                price_at_signal REAL NOT NULL,
                signaled_at INTEGER NOT NULL,
                checked INTEGER NOT NULL DEFAULT 0,
                price_after REAL,
                result TEXT
            )
            """
        )
        await db.commit()


# --- Signal natijalarini kuzatish (o'z-o'zini baholash) ---

async def record_signal(symbol: str, direction: str, price: float):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO signal_outcomes (symbol, direction, price_at_signal, signaled_at, checked) "
            "VALUES (?, ?, ?, ?, 0)",
            (symbol, direction, price, int(time.time())),
        )
        await db.commit()


async def get_pending_outcomes(older_than_minutes: int) -> list[dict]:
    """Belgilangan vaqtdan o'tgan, hali tekshirilmagan signallar."""
    cutoff = int(time.time()) - older_than_minutes * 60
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT id, symbol, direction, price_at_signal FROM signal_outcomes "
            "WHERE checked = 0 AND signaled_at <= ?",
            (cutoff,),
        )
        rows = await cursor.fetchall()
        return [
            {"id": r[0], "symbol": r[1], "direction": r[2], "price_at_signal": r[3]}
            for r in rows
        ]


async def update_outcome(outcome_id: int, price_after: float, result: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE signal_outcomes SET checked = 1, price_after = ?, result = ? WHERE id = ?",
            (price_after, result, outcome_id),
        )
        await db.commit()


async def get_stats() -> dict:
    """Umumiy va oxirgi 7 kunlik statistikani qaytaradi."""
    async with aiosqlite.connect(DB_PATH) as db:
        async def _counts(since_ts: int | None):
            query = "SELECT result, COUNT(*) FROM signal_outcomes WHERE checked = 1"
            params: tuple = ()
            if since_ts is not None:
                query += " AND signaled_at >= ?"
                params = (since_ts,)
            query += " GROUP BY result"
            cursor = await db.execute(query, params)
            rows = await cursor.fetchall()
            return {r[0]: r[1] for r in rows}

        all_time = await _counts(None)
        last_7d = await _counts(int(time.time()) - 7 * 86400)
        return {"all_time": all_time, "last_7d": last_7d}


async def is_on_cooldown(symbol: str, cooldown_minutes: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT alerted_at FROM alerts WHERE symbol = ?", (symbol,)
        )
        row = await cursor.fetchone()
        if not row:
            return False
        elapsed = time.time() - row[0]
        return elapsed < cooldown_minutes * 60


async def record_alert(symbol: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO alerts (symbol, alerted_at) VALUES (?, ?) "
            "ON CONFLICT(symbol) DO UPDATE SET alerted_at = excluded.alerted_at",
            (symbol, int(time.time())),
        )
        await db.commit()


async def add_subscriber(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO subscribers (user_id) VALUES (?)", (user_id,)
        )
        await db.commit()


async def remove_subscriber(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM subscribers WHERE user_id = ?", (user_id,))
        await db.commit()


async def get_subscribers() -> list[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT user_id FROM subscribers")
        rows = await cursor.fetchall()
        return [r[0] for r in rows]


async def is_subscribed(user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT 1 FROM subscribers WHERE user_id = ?", (user_id,)
        )
        return (await cursor.fetchone()) is not None
