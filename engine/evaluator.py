"""
Signal Evaluator (AMD) — barcha taymfreymlar (15m, 1h, 4h, 1d) uchun BITTA jadval.

Har yuborilgan signal bazaga yoziladi, keyingi YOPILGAN shamlar kuzatiladi va natija
R (risk birligi) da hisoblanadi. Qoidalar — engine/sim.py (backtest bilan bir xil).

  gross_r  = komissiyasiz natija
  result_r = sof natija (komissiya + slippage ayrilgan) — statistika shundan hisoblanadi

Cooldown ham shu bazadan olinadi (recently_signaled) — redeploy'dan keyin yo'qolmaydi
(agar PostgreSQL ishlatilsa).
"""
from __future__ import annotations

import logging
import time
from typing import List, Optional

from config import FEE_PCT, SLIPPAGE_PCT
from engine import db, sim

logger = logging.getLogger("nozik.evaluator")


def init_db():
    try:
        _init()
    except Exception as e:
        if db.BACKEND == "postgres":
            db.fallback_to_sqlite(str(e))
            _init()
        else:
            raise


def _init():
    with db.tx() as conn:
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS signals (
                id {db.id_column()},
                symbol TEXT NOT NULL,
                tf TEXT NOT NULL,
                side TEXT NOT NULL,
                score DOUBLE PRECISION NOT NULL,
                entry DOUBLE PRECISION NOT NULL,
                sl DOUBLE PRECISION NOT NULL,
                tp1 DOUBLE PRECISION NOT NULL,
                tp2 DOUBLE PRECISION NOT NULL,
                tp3 DOUBLE PRECISION,
                rr1 DOUBLE PRECISION NOT NULL,
                rr2 DOUBLE PRECISION NOT NULL,
                sent_ts BIGINT NOT NULL,
                checked_ts BIGINT NOT NULL,
                candles_n INTEGER DEFAULT 0,
                tp1_hit INTEGER DEFAULT 0,
                status TEXT DEFAULT 'open',
                gross_r DOUBLE PRECISION,
                result_r DOUBLE PRECISION,
                closed_ts BIGINT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_signals_status ON signals (status, tf)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_signals_sym ON signals (symbol, tf, sent_ts)")
    # eski bazalar uchun migratsiya: tp3 ustuni (alohida tranzaksiya — xato bo'lsa keyingisiga ta'sir qilmasin)
    try:
        with db.tx() as conn:
            conn.execute("ALTER TABLE signals ADD COLUMN IF NOT EXISTS tp3 DOUBLE PRECISION"
                         if db.BACKEND == "postgres" else
                         "ALTER TABLE signals ADD COLUMN tp3 DOUBLE PRECISION")
    except Exception:
        pass            # ustun allaqachon bor


# ------------------------------------------------------------------ yozish
def record_signal(sig):
    """sig: signals.amd_volume.Signal (sig.tf = '15m' | '1h' | '4h' | '1d')"""
    with db.tx() as conn:
        conn.execute(
            "INSERT INTO signals (symbol, tf, side, score, entry, sl, tp1, tp2, rr1, rr2, "
            "sent_ts, checked_ts, tp3) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (sig.symbol, sig.tf, sig.side, sig.score, sig.entry, sig.sl, sig.tp1, sig.tp2,
             sig.rr1, sig.rr2, int(time.time()), sig.ts, getattr(sig, "tp3", None)),
        )


def recently_signaled(symbol: str, tf: str, cooldown_sec: int) -> bool:
    """Shu coin shu taymfreymda cooldown ichida signal olganmi? (DB xato bersa — False)"""
    try:
        with db.tx() as conn:
            row = conn.execute(
                "SELECT 1 FROM signals WHERE symbol=? AND tf=? AND sent_ts>=? LIMIT 1",
                (symbol, tf, int(time.time()) - cooldown_sec),
            ).fetchone()
        return row is not None
    except Exception as e:
        logger.warning(f"cooldown tekshiruvi xatosi: {e}")
        return False


# --------------------------------------------------------------- baholash
def evaluate_pending(get_klines_fn, tf: str, interval: str, expire_candles: int,
                     events: Optional[list] = None) -> List[dict]:
    """Shu taymfreymdagi ochiq signallarni yangi YOPILGAN shamlar bilan tekshiradi.
    Yangi yopilganlar ro'yxatini qaytaradi. `events` berilsa — oraliq bosqichlar (TP1/TP2 olindi,
    pozitsiya hali ochiq) ham shu ro'yxatga qo'shiladi: {"symbol","side","stage","three","tp"...}."""
    with db.tx() as conn:
        rows = conn.execute(
            "SELECT id, symbol, side, entry, sl, tp1, tp2, rr1, rr2, checked_ts, candles_n, tp1_hit, tp3 "
            "FROM signals WHERE status='open' AND tf=?", (tf,)
        ).fetchall()

    closed = []
    for (row_id, symbol, side, entry, sl, tp1, tp2, rr1, rr2, checked, n, hit1, tp3) in rows:
        try:
            c = get_klines_fn(symbol, interval, 200)   # tarmoq — tranzaksiyadan TASHQARIDA
            if not c:
                continue
            c = c[:-1]                                  # faqat yopilgan shamlar
            three = tp3 is not None
            stage0 = int(hit1 or 0)                     # tp1_hit ustuni: 0/1 (2 ta TP) yoki 0..2 (3 ta TP)
            hit1 = stage0 if three else bool(hit1)
            status: Optional[str] = None
            gross: Optional[float] = None

            for x in c:
                if x[0] <= checked:
                    continue
                checked = x[0]
                n += 1
                if three:
                    rr3 = abs(tp3 - entry) / abs(entry - sl) if entry != sl else 3.0
                    hit1, status, gross = sim.step3(side, entry, sl, tp1, tp2, tp3, rr1, rr2, rr3,
                                                    hit1, x[2], x[3])
                else:
                    hit1, status, gross = sim.step(side, entry, sl, tp1, tp2, rr1, rr2,
                                                   hit1, x[2], x[3])
                if status:
                    break
                if n >= expire_candles:
                    status = "expired"
                    gross = (sim.expire_gross3(side, entry, sl, rr1, rr2, hit1, x[4]) if three
                             else sim.expire_gross(side, entry, sl, rr1, hit1, x[4]))
                    break

            if status:
                net = gross - sim.cost_r(entry, sl, FEE_PCT, SLIPPAGE_PCT)
                upd = ("UPDATE signals SET checked_ts=?, candles_n=?, tp1_hit=?, status=?, "
                       "gross_r=?, result_r=?, closed_ts=? WHERE id=? AND status='open'")
                args = (checked, n, int(hit1), status, gross, net, int(time.time()), row_id)
                closed.append({"symbol": symbol, "tf": tf, "side": side, "status": status,
                               "gross_r": gross, "result_r": net})
            else:
                upd = "UPDATE signals SET checked_ts=?, candles_n=?, tp1_hit=? WHERE id=? AND status='open'"
                args = (checked, n, int(hit1), row_id)
                if events is not None and int(hit1) > stage0:       # yangi bosqich: TP1 yoki TP2 olindi
                    events.append({"symbol": symbol, "side": side, "stage": int(hit1), "three": three,
                                   "tp1": tp1, "tp2": tp2, "tp3": tp3, "entry": entry})
            with db.tx() as conn:
                conn.execute(upd, args)
        except Exception as e:
            logger.warning(f"{symbol} [{tf}] baholashda xato: {e}")
            continue
    return closed


# ------------------------------------------------------------- statistika
def _summary(rows) -> dict:
    n = len(rows)
    vals = [r for _, r in rows]
    wins = sum(1 for r in vals if r > 0)
    gains = sum(r for r in vals if r > 0)
    losses = -sum(r for r in vals if r < 0)
    return {
        "total_closed": n,
        "wins": wins,
        "winrate_pct": round(wins / n * 100, 1) if n else 0,
        "total_r": round(sum(vals), 2),
        "avg_r": round(sum(vals) / n, 2) if n else 0,
        "profit_factor": round(gains / losses, 2) if losses > 0 else None,
        "best": max(rows, key=lambda x: x[1]) if rows else None,
        "worst": min(rows, key=lambda x: x[1]) if rows else None,
    }


def get_stats(tf: str) -> dict:
    with db.tx() as conn:
        rows = conn.execute(
            "SELECT symbol, result_r FROM signals WHERE tf=? AND status!='open' "
            "AND result_r IS NOT NULL", (tf,)).fetchall()
        pending = conn.execute(
            "SELECT COUNT(*) FROM signals WHERE tf=? AND status='open'", (tf,)).fetchone()[0]
        by_status = dict(conn.execute(
            "SELECT status, COUNT(*) FROM signals WHERE tf=? AND status!='open' GROUP BY status",
            (tf,)).fetchall())
        gross = conn.execute(
            "SELECT COALESCE(SUM(gross_r),0) FROM signals WHERE tf=? AND status!='open' "
            "AND gross_r IS NOT NULL", (tf,)).fetchone()[0]
    out = _summary(rows)
    out.update(pending=pending, by_status=by_status, gross_total_r=round(float(gross), 2))
    return out


def get_stats_since(seconds_ago: int, tf: Optional[str] = None,
                    exclude_tf: Optional[str] = None) -> dict:
    """tf — faqat shu taymfreym; exclude_tf — shu taymfreymni hisobdan chiqarish
    (AMD statistikasi pump/dump detektori bilan aralashmasligi uchun)."""
    cutoff = int(time.time()) - seconds_ago
    if tf:
        tf_sql, tf_args = "AND tf=?", (tf,)
    elif exclude_tf:
        tf_sql, tf_args = "AND tf<>?", (exclude_tf,)
    else:
        tf_sql, tf_args = "", ()
    with db.tx() as conn:
        total_sent = conn.execute(
            f"SELECT COUNT(*) FROM signals WHERE sent_ts >= ? {tf_sql}", (cutoff, *tf_args)
        ).fetchone()[0]
        rows = conn.execute(
            f"SELECT symbol, result_r FROM signals WHERE status!='open' "
            f"AND result_r IS NOT NULL AND closed_ts >= ? {tf_sql}", (cutoff, *tf_args)
        ).fetchall()
    out = _summary(rows)
    out["total_sent"] = total_sent
    return out
