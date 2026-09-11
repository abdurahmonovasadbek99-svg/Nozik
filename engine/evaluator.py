"""
Signal Evaluator.
Har bir yuborilgan signalni SQLite bazasiga yozadi va keyinchalik
narx qanday harakatlanganini tekshirib, aniqlik statistikasini yuritadi.
/pump_stats buyrug'i shu yerdan ma'lumot oladi.

TUZATISHLAR:
- price_at_signal = 0 bo'lgan signallar 0 ga bo'lish (ZeroDivisionError)
  keltirib chiqarardi va baholashni har doim sindirib yuborardi.
  Endi bunday signallar 'invalid' deb belgilanadi.
- Bitta signal xato bersa qolganlarining baholanishi to'xtab
  qolmasligi uchun har bir qator alohida try/except ichida.
"""
import sqlite3
import time
from config import DB_PATH


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            direction TEXT NOT NULL,
            confluence_score REAL NOT NULL,
            price_at_signal REAL NOT NULL,
            timestamp INTEGER NOT NULL,
            evaluated INTEGER DEFAULT 0,
            outcome TEXT,
            price_after REAL,
            pct_change REAL
        )
    """)
    conn.commit()
    conn.close()


def record_signal(symbol: str, direction: str, confluence_score: float, price: float):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO signals (symbol, direction, confluence_score, price_at_signal, timestamp) "
        "VALUES (?, ?, ?, ?, ?)",
        (symbol, direction, confluence_score, price, int(time.time())),
    )
    conn.commit()
    conn.close()


def evaluate_pending(get_current_price_fn, eval_after_seconds: int = 3600, success_threshold_pct: float = 1.0):
    conn = sqlite3.connect(DB_PATH)
    cutoff = int(time.time()) - eval_after_seconds
    rows = conn.execute(
        "SELECT id, symbol, direction, price_at_signal FROM signals "
        "WHERE evaluated = 0 AND timestamp <= ?",
        (cutoff,),
    ).fetchall()

    for row_id, symbol, direction, price_at_signal in rows:
        try:
            # TUZATISH: narx 0 (yoki manfiy) yozilgan signallar 0 ga
            # bo'lishga olib kelardi. Ularni belgilab o'tkazib yuboramiz.
            if not price_at_signal or price_at_signal <= 0:
                conn.execute(
                    "UPDATE signals SET evaluated=1, outcome='invalid' WHERE id=?",
                    (row_id,),
                )
                continue

            current_price = get_current_price_fn(symbol)

            pct_change = ((current_price - price_at_signal) / price_at_signal) * 100

            if direction == "long":
                outcome = "success" if pct_change >= success_threshold_pct else "fail"
            elif direction == "short":
                outcome = "success" if pct_change <= -success_threshold_pct else "fail"
            else:
                outcome = "neutral"

            conn.execute(
                "UPDATE signals SET evaluated=1, outcome=?, price_after=?, pct_change=? WHERE id=?",
                (outcome, current_price, pct_change, row_id),
            )
        except Exception:
            # TUZATISH: bitta signal xato bersa (API down, narx yo'q va h.k.)
            # qolgan signallar baholanishda davom etadi
            continue

    conn.commit()
    conn.close()


def get_stats() -> dict:
    conn = sqlite3.connect(DB_PATH)
    total = conn.execute("SELECT COUNT(*) FROM signals WHERE evaluated=1").fetchone()[0]
    success = conn.execute(
        "SELECT COUNT(*) FROM signals WHERE evaluated=1 AND outcome='success'"
    ).fetchone()[0]
    pending = conn.execute("SELECT COUNT(*) FROM signals WHERE evaluated=0").fetchone()[0]
    avg_pct = conn.execute(
        "SELECT AVG(pct_change) FROM signals WHERE evaluated=1 AND outcome != 'invalid'"
    ).fetchone()[0]
    conn.close()

    accuracy = (success / total * 100) if total > 0 else 0
    return {
        "total_evaluated": total,
        "successful": success,
        "accuracy_pct": round(accuracy, 1),
        "pending": pending,
        "avg_pct_change": round(avg_pct, 2) if avg_pct else 0,
    }


def get_stats_since(seconds_ago: int) -> dict:
    conn = sqlite3.connect(DB_PATH)
    cutoff = int(time.time()) - seconds_ago

    total_sent = conn.execute(
        "SELECT COUNT(*) FROM signals WHERE timestamp >= ?", (cutoff,)
    ).fetchone()[0]
    total_evaluated = conn.execute(
        "SELECT COUNT(*) FROM signals WHERE timestamp >= ? AND evaluated=1", (cutoff,)
    ).fetchone()[0]
    success = conn.execute(
        "SELECT COUNT(*) FROM signals WHERE timestamp >= ? AND evaluated=1 AND outcome='success'",
        (cutoff,),
    ).fetchone()[0]
    avg_pct = conn.execute(
        "SELECT AVG(pct_change) FROM signals WHERE timestamp >= ? AND evaluated=1 AND outcome != 'invalid'",
        (cutoff,),
    ).fetchone()[0]
    best = conn.execute(
        "SELECT symbol, pct_change FROM signals WHERE timestamp >= ? AND evaluated=1 "
        "ORDER BY pct_change DESC LIMIT 1",
        (cutoff,),
    ).fetchone()
    worst = conn.execute(
        "SELECT symbol, pct_change FROM signals WHERE timestamp >= ? AND evaluated=1 "
        "ORDER BY pct_change ASC LIMIT 1",
        (cutoff,),
    ).fetchone()
    conn.close()

    accuracy = (success / total_evaluated * 100) if total_evaluated > 0 else 0
    return {
        "total_sent": total_sent,
        "total_evaluated": total_evaluated,
        "successful": success,
        "accuracy_pct": round(accuracy, 1),
        "avg_pct_change": round(avg_pct, 2) if avg_pct else 0,
        "best": {"symbol": best[0], "pct_change": round(best[1], 2)} if best else None,
        "worst": {"symbol": worst[0], "pct_change": round(worst[1], 2)} if worst else None,
    }
