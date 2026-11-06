"""
Signal Evaluator (AMD).
Har bir yuborilgan signalni SQLite bazasiga yozadi va keyingi shamlarni
kuzatib, natijasini R (risk birligi) da hisoblaydi:

  - SL urilsa                      -> -1R
  - TP1 urilsa: 50% pozitsiya yopiladi, SL breakeven'ga suriladi
      - keyin TP2 urilsa           -> 0.5*RR1 + 0.5*RR2
      - keyin kirish narxiga qaytsa -> 0.5*RR1
  - EXPIRE_CANDLES ichida hech biri bo'lmasa -> yopiladi (TP1 bo'lgan bo'lsa 0.5*RR1, aks holda 0R)

Bir sham ichida SL ham, TP ham urilsa — SL hisoblanadi (konservativ).
/pump_stats va hisobotlar shu yerdan ma'lumot oladi.
"""
import sqlite3
import time

from config import DB_PATH


def _conn():
    return sqlite3.connect(DB_PATH)


def init_db():
    conn = _conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS amd_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            score REAL NOT NULL,
            entry REAL NOT NULL,
            sl REAL NOT NULL,
            tp1 REAL NOT NULL,
            tp2 REAL NOT NULL,
            rr1 REAL NOT NULL,
            rr2 REAL NOT NULL,
            sent_ts INTEGER NOT NULL,
            checked_ts INTEGER NOT NULL,
            candles_n INTEGER DEFAULT 0,
            tp1_hit INTEGER DEFAULT 0,
            status TEXT DEFAULT 'open',
            result_r REAL,
            closed_ts INTEGER
        )
    """)
    conn.commit()
    conn.close()


def record_signal(sig):
    """sig: signals.amd_volume.Signal"""
    conn = _conn()
    conn.execute(
        "INSERT INTO amd_signals (symbol, side, score, entry, sl, tp1, tp2, rr1, rr2, "
        "sent_ts, checked_ts) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (sig.symbol, sig.side, sig.score, sig.entry, sig.sl, sig.tp1, sig.tp2,
         sig.rr1, sig.rr2, int(time.time()), sig.ts),
    )
    conn.commit()
    conn.close()


def evaluate_pending(get_klines_fn, interval: str = "15", expire_candles: int = 48) -> list:
    """Ochiq signallarni yangi shamlar bilan tekshiradi.
    Yangi yopilgan signallar ro'yxatini qaytaradi (bot ularni xabar qiladi)."""
    conn = _conn()
    rows = conn.execute(
        "SELECT id, symbol, side, entry, sl, tp1, tp2, rr1, rr2, checked_ts, candles_n, tp1_hit "
        "FROM amd_signals WHERE status='open'"
    ).fetchall()

    closed = []
    for (row_id, symbol, side, entry, sl, tp1, tp2, rr1, rr2,
         checked, n, hit1) in rows:
        try:
            c = get_klines_fn(symbol, interval, 200)
            if not c:
                continue
            c = c[:-1]  # faqat yopilgan shamlar
            long_ = side == "LONG"
            hit1 = bool(hit1)
            status, result = "open", None

            for x in c:
                if x[0] <= checked:
                    continue
                hi, lo = x[2], x[3]
                checked = x[0]
                n += 1
                stop = entry if hit1 else sl
                hit_sl = lo <= stop if long_ else hi >= stop
                hit_tp1 = hi >= tp1 if long_ else lo <= tp1
                hit_tp2 = hi >= tp2 if long_ else lo <= tp2

                if hit_sl:
                    status = "be" if hit1 else "sl"
                    result = 0.5 * rr1 if hit1 else -1.0
                    break
                if not hit1 and hit_tp1:
                    hit1 = True
                if hit1 and hit_tp2:
                    status, result = "tp2", 0.5 * rr1 + 0.5 * rr2
                    break
                if n >= expire_candles:
                    status = "expired"
                    result = 0.5 * rr1 if hit1 else 0.0
                    break

            closed_ts = int(time.time()) if status != "open" else None
            conn.execute(
                "UPDATE amd_signals SET checked_ts=?, candles_n=?, tp1_hit=?, status=?, "
                "result_r=?, closed_ts=? WHERE id=?",
                (checked, n, int(hit1), status, result, closed_ts, row_id),
            )
            if status != "open":
                closed.append({"symbol": symbol, "side": side,
                               "status": status, "result_r": result})
        except Exception:
            # Bitta signal xato bersa (API down va h.k.) qolganlari davom etadi
            continue

    conn.commit()
    conn.close()
    return closed


def _summary(rows) -> dict:
    n = len(rows)
    wins = sum(1 for _, r in rows if r > 0)
    total = sum(r for _, r in rows)
    return {
        "total_closed": n,
        "wins": wins,
        "winrate_pct": round(wins / n * 100, 1) if n else 0,
        "total_r": round(total, 2),
        "avg_r": round(total / n, 2) if n else 0,
        "best": max(rows, key=lambda x: x[1]) if rows else None,
        "worst": min(rows, key=lambda x: x[1]) if rows else None,
    }


def get_stats() -> dict:
    conn = _conn()
    rows = conn.execute(
        "SELECT symbol, result_r FROM amd_signals WHERE status!='open' AND result_r IS NOT NULL"
    ).fetchall()
    pending = conn.execute("SELECT COUNT(*) FROM amd_signals WHERE status='open'").fetchone()[0]
    by_status = dict(conn.execute(
        "SELECT status, COUNT(*) FROM amd_signals WHERE status!='open' GROUP BY status"
    ).fetchall())
    conn.close()
    out = _summary(rows)
    out["pending"] = pending
    out["by_status"] = by_status
    return out


def get_stats_since(seconds_ago: int) -> dict:
    conn = _conn()
    cutoff = int(time.time()) - seconds_ago
    total_sent = conn.execute(
        "SELECT COUNT(*) FROM amd_signals WHERE sent_ts >= ?", (cutoff,)
    ).fetchone()[0]
    rows = conn.execute(
        "SELECT symbol, result_r FROM amd_signals WHERE status!='open' "
        "AND result_r IS NOT NULL AND closed_ts >= ?", (cutoff,)
    ).fetchall()
    conn.close()
    out = _summary(rows)
    out["total_sent"] = total_sent
    return out
