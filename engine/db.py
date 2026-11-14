"""
engine/db.py
Ma'lumotlar bazasi qatlami: PostgreSQL (DATABASE_URL berilsa) yoki SQLite.

MUAMMO: Render bepul tarifida SQLite fayli har redeploy'da o'chadi — statistika va
cooldown yo'qoladi.
YECHIM: Doimiy PostgreSQL (Neon / Supabase / Render Postgres) ga ulanish.
`DATABASE_URL` env o'rnatilsa — Postgres, aks holda SQLite (WAL rejimida).
Postgres ishlamasa bot to'xtamaydi: SQLite'ga o'tadi va logda aniq ogohlantiradi.
"""
from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager

from config import DATABASE_URL, DB_PATH

logger = logging.getLogger("nozik.db")

BACKEND = "postgres" if DATABASE_URL.startswith(("postgres://", "postgresql://")) else "sqlite"
_psycopg2 = None

if BACKEND == "postgres":
    try:
        import psycopg2 as _psycopg2  # type: ignore
    except ImportError:
        logger.error("DATABASE_URL berilgan, lekin psycopg2 o'rnatilmagan -> SQLite'ga o'tildi.")
        BACKEND = "sqlite"


class _Conn:
    """sqlite3 va psycopg2 uchun bir xil interfeys ('?' placeholder)."""

    def __init__(self, raw, pg: bool):
        self.raw, self.pg = raw, pg

    def execute(self, sql: str, params=()):
        if self.pg:
            cur = self.raw.cursor()
            cur.execute(sql.replace("?", "%s"), tuple(params))
            return cur
        return self.raw.execute(sql, tuple(params))

    def commit(self):
        self.raw.commit()

    def rollback(self):
        try:
            self.raw.rollback()
        except Exception:
            pass

    def close(self):
        try:
            self.raw.close()
        except Exception:
            pass


def connect() -> _Conn:
    if BACKEND == "postgres":
        return _Conn(_psycopg2.connect(DATABASE_URL, connect_timeout=10), True)
    raw = sqlite3.connect(DB_PATH, timeout=30)
    try:
        raw.execute("PRAGMA journal_mode=WAL")
        raw.execute("PRAGMA busy_timeout=30000")
    except Exception:
        pass
    return _Conn(raw, False)


@contextmanager
def tx():
    """with tx() as conn: ...  — muvaffaqiyatda commit, xatoda rollback, doim close."""
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def fallback_to_sqlite(reason: str):
    """Postgres ishga tushmasa — bot ishlashda davom etadi (signal muhimroq)."""
    global BACKEND
    logger.error(f"PostgreSQL ishlamadi ({reason}) -> SQLite'ga o'tildi. "
                 "DIQQAT: statistika redeploy'da yo'qoladi!")
    BACKEND = "sqlite"


def id_column() -> str:
    return "SERIAL PRIMARY KEY" if BACKEND == "postgres" else "INTEGER PRIMARY KEY AUTOINCREMENT"
