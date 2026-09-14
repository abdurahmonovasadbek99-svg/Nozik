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
- YANGI: "muvaffaqiyat" chegarasi endi qattiq 1% emas, balki signal
  yuborilgan paytdagi ATR%ga NISBATAN hisoblanadi (qarang:
  engine/volatility.py). Sabab: 1% harakat past-volatillik coin uchun
  katta yutuq, yuqori-volatillik coin uchun oddiy shovqin bo'lishi
  mumkin - shuning uchun barcha coinlarni bir xil qattiq % bilan
  o'lchash aniqlik statistikasini buzardi.
"""
import sqlite3
import time
from config import DB_PATH

# Muvaffaqiyat chegarasi = ATR% * bu koeffitsient (masalan ATR%=0.4
# bo'lsa, muvaffaqiyat uchun kamida 0.4*0.6=0.24% harakat kerak)
ATR_SUCCESS_MULTIPLIER = 0.6
# ATR ma'lumoti yo'q eski yozuvlar uchun zaxira chegara
FALLBACK_SUCCESS_THRESHOLD_PCT = 1.0
# Har qanday holatda ham talab qilinadigan eng kichik harakat
# (juda past ATR'li coinlarda chegara deyarli 0 bo'lib qolmasligi uchun)
MIN_SUCCESS_THRESHOLD_PCT = 0.3


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
            pct_change REAL,
            atr_pct REAL
        )
    """)
    # TUZATISH: eski nozik.db fayllarida atr_pct ustuni yo'q bo'lishi
    # mumkin (v2.1'dan oldin yaratilgan). ALTER TABLE bilan qo'shamiz,
    # ustun allaqachon bo'lsa xatoni e'tiborsiz qoldiramiz.
    try:
        conn.execute("ALTER TABLE signals ADD COLUMN atr_pct REAL")
    except sqlite3.OperationalError:
        pass
    conn.commit()
    conn.close()


def record_signal(symbol: str, direction: str, confluence_score: float, price: float, atr_pct: float = 0.0):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO signals (symbol, direction, confluence_score, price_at_signal, timestamp, atr_pct) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (symbol, direction, confluence_score, price, int(time.time()), atr_pct),
    )
    conn.commit()
    conn.close()


def evaluate_pending(get_current_price_fn, eval_after_seconds: int = 3600):
    conn = sqlite3.connect(DB_PATH)
    cutoff = int(time.time()) - eval_after_seconds
    rows = conn.execute(
        "SELECT id, symbol, direction, price_at_signal, atr_pct FROM signals "
        "WHERE evaluated = 0 AND timestamp <= ?",
        (cutoff,),
    ).fetchall()

    for row_id, symbol, direction, price_at_signal, atr_pct in rows:
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

            if atr_pct and atr_pct > 0:
                success_threshold_pct = max(
                    atr_pct * ATR_SUCCESS_MULTIPLIER, MIN_SUCCESS_THRESHOLD_PCT
                )
            else:
                success_threshold_pct = FALLBACK_SUCCESS_THRESHOLD_PCT

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
    # TUZATISH: 'invalid' (narx=0 bo'lgani uchun baholab bo'lmagan)
    # signallar avval "total" ga kiritilib, aniqlik foizini sun'iy
    # pasaytirar edi (ular hech qachon 'success' bo'la olmasdi).
    # Endi aniqlik faqat HAQIQATDA baholangan (success/fail) signallar
    # ustida hisoblanadi.
    total = conn.execute(
        "SELECT COUNT(*) FROM signals WHERE evaluated=1 AND outcome IN ('success','fail')"
    ).fetchone()[0]
    success = conn.execute(
        "SELECT COUNT(*) FROM signals WHERE evaluated=1 AND outcome='success'"
    ).fetchone()[0]
    invalid = conn.execute(
        "SELECT COUNT(*) FROM signals WHERE evaluated=1 AND outcome='invalid'"
    ).fetchone()[0]
    pending = conn.execute("SELECT COUNT(*) FROM signals WHERE evaluated=0").fetchone()[0]
    avg_pct = conn.execute(
        "SELECT AVG(pct_change) FROM signals WHERE evaluated=1 AND outcome IN ('success','fail')"
    ).fetchone()[0]
    conn.close()

    accuracy = (success / total * 100) if total > 0 else 0
    return {
        "total_evaluated": total,
        "successful": success,
        "accuracy_pct": round(accuracy, 1),
        "pending": pending,
        "invalid": invalid,
        "avg_pct_change": round(avg_pct, 2) if avg_pct else 0,
    }


def get_stats_since(seconds_ago: int) -> dict:
    conn = sqlite3.connect(DB_PATH)
    cutoff = int(time.time()) - seconds_ago

    total_sent = conn.execute(
        "SELECT COUNT(*) FROM signals WHERE timestamp >= ?", (cutoff,)
    ).fetchone()[0]
    # TUZATISH: 'invalid' signallar (narx=0) endi na total_evaluated'ga,
    # na eng yaxshi/yomon tanloviga kiritilmaydi - ular pct_change=NULL
    # bo'lgani uchun SQLite'da ORDER BY ASC/DESC paytida NULL "eng kichik"
    # deb hisoblanib, 'worst' sifatida noto'g'ri tanlanib qolishi mumkin edi.
    total_evaluated = conn.execute(
        "SELECT COUNT(*) FROM signals WHERE timestamp >= ? AND evaluated=1 "
        "AND outcome IN ('success','fail')",
        (cutoff,),
    ).fetchone()[0]
    success = conn.execute(
        "SELECT COUNT(*) FROM signals WHERE timestamp >= ? AND evaluated=1 AND outcome='success'",
        (cutoff,),
    ).fetchone()[0]
    avg_pct = conn.execute(
        "SELECT AVG(pct_change) FROM signals WHERE timestamp >= ? AND evaluated=1 "
        "AND outcome IN ('success','fail')",
        (cutoff,),
    ).fetchone()[0]
    best = conn.execute(
        "SELECT symbol, pct_change FROM signals WHERE timestamp >= ? AND evaluated=1 "
        "AND outcome IN ('success','fail') ORDER BY pct_change DESC LIMIT 1",
        (cutoff,),
    ).fetchone()
    worst = conn.execute(
        "SELECT symbol, pct_change FROM signals WHERE timestamp >= ? AND evaluated=1 "
        "AND outcome IN ('success','fail') ORDER BY pct_change ASC LIMIT 1",
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
