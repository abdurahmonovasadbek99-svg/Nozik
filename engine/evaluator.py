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

import config as C
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
                closed_ts BIGINT,
                mfe_r DOUBLE PRECISION,
                mae_r DOUBLE PRECISION
            )
        """)
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS signal_msgs (
                id {db.id_column()},
                symbol TEXT NOT NULL,
                tf TEXT NOT NULL,
                sent_ts BIGINT NOT NULL,
                chat_id BIGINT NOT NULL,
                message_id BIGINT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_msgs_sig ON signal_msgs (symbol, tf, sent_ts)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_signals_status ON signals (status, tf)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_signals_sym ON signals (symbol, tf, sent_ts)")
    # eski bazalar uchun migratsiya (har ustun alohida tranzaksiyada — xato bo'lsa keyingisiga ta'sir qilmasin)
    for col in ("tp3", "mfe_r", "mae_r"):
        try:
            with db.tx() as conn:
                conn.execute(f"ALTER TABLE signals ADD COLUMN IF NOT EXISTS {col} DOUBLE PRECISION"
                             if db.BACKEND == "postgres" else
                             f"ALTER TABLE signals ADD COLUMN {col} DOUBLE PRECISION")
        except Exception:
            pass        # ustun allaqachon bor


# ------------------------------------------------------------------ yozish
def record_signal(sig) -> int:
    """sig: signals.amd_volume.Signal (sig.tf = '15m' | '1h' | '4h' | '1d').
    Qaytaradi: sent_ts (soniya) — Mini App havolasi (symbol + sent_ts) shu bilan signalni topadi."""
    sent_ts = int(time.time())
    with db.tx() as conn:
        conn.execute(
            "INSERT INTO signals (symbol, tf, side, score, entry, sl, tp1, tp2, rr1, rr2, "
            "sent_ts, checked_ts, tp3) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (sig.symbol, sig.tf, sig.side, sig.score, sig.entry, sig.sl, sig.tp1, sig.tp2,
             sig.rr1, sig.rr2, sent_ts, sig.ts, getattr(sig, "tp3", None)),
        )
    return sent_ts


def save_msg(symbol: str, tf: str, sent_ts: int, chat_id: int, message_id: int) -> None:
    """Yuborilgan signal xabarining Telegram id si — keyingi TP/SL xabarlari shunga reply bo'ladi."""
    try:
        with db.tx() as conn:
            conn.execute(
                "INSERT INTO signal_msgs (symbol, tf, sent_ts, chat_id, message_id) VALUES (?,?,?,?,?)",
                (symbol, tf, int(sent_ts), int(chat_id), int(message_id)))
    except Exception as e:
        logger.warning(f"signal xabar id sini saqlashda xato: {e}")


def get_msgs(symbol: str, tf: str, sent_ts: int) -> list:
    """[(chat_id, message_id), ...] — shu signal yuborilgan xabarlar."""
    try:
        with db.tx() as conn:
            rows = conn.execute(
                "SELECT chat_id, message_id FROM signal_msgs WHERE symbol=? AND tf=? AND sent_ts=? "
                "ORDER BY id", (symbol, tf, int(sent_ts))).fetchall()
        return [(int(c), int(m)) for c, m in rows]
    except Exception as e:
        logger.warning(f"signal xabar id sini o'qishda xato: {e}")
        return []


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
                     events: Optional[list] = None, stale_candles: int = 0,
                     stale_min_mfe: float = 0.5) -> List[dict]:
    """Shu taymfreymdagi ochiq signallarni yangi YOPILGAN shamlar bilan tekshiradi.
    Yangi yopilganlar ro'yxatini qaytaradi. `events` berilsa — oraliq bosqichlar (TP1/TP2 olindi,
    pozitsiya hali ochiq) ham shu ro'yxatga qo'shiladi: {"symbol","side","stage","three","tp"...}."""
    with db.tx() as conn:
        rows = conn.execute(
            "SELECT id, symbol, side, entry, sl, tp1, tp2, rr1, rr2, checked_ts, candles_n, tp1_hit, tp3, "
            "sent_ts, mfe_r, mae_r FROM signals WHERE status='open' AND tf=?", (tf,)
        ).fetchall()

    closed = []
    for (row_id, symbol, side, entry, sl, tp1, tp2, rr1, rr2, checked, n, hit1, tp3,
         sent_ts, mfe, mae) in rows:
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
            risk = abs(entry - sl)
            long_ = side == "LONG"
            mfe = float(mfe or 0.0)
            mae = float(mae or 0.0)

            for x in c:
                if x[0] <= checked:
                    continue
                checked = x[0]
                n += 1
                if risk > 0:                            # MFE/MAE: eng ko'p foyda / eng ko'p qarshi harakat (R)
                    mfe = max(mfe, ((x[2] - entry) if long_ else (entry - x[3])) / risk)
                    mae = max(mae, ((entry - x[3]) if long_ else (x[2] - entry)) / risk)
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
                if stale_candles and n >= stale_candles and not hit1 and mfe < stale_min_mfe:
                    status = "stale"                    # impuls so'ndi: TP1 yo'q, narx kutilgan tomonga yurmadi
                    gross = sim.expire_gross(side, entry, sl, rr1, False, x[4])
                    break

            if status:
                net = gross - sim.cost_r(entry, sl, C.FEE_PCT, C.SLIPPAGE_PCT)
                upd = ("UPDATE signals SET checked_ts=?, candles_n=?, tp1_hit=?, status=?, "
                       "gross_r=?, result_r=?, closed_ts=?, mfe_r=?, mae_r=? WHERE id=? AND status='open'")
                args = (checked, n, int(hit1), status, gross, net, int(time.time()), mfe, mae, row_id)
                closed.append({"symbol": symbol, "tf": tf, "side": side, "status": status,
                               "gross_r": gross, "result_r": net, "sent_ts": sent_ts,
                               "mfe_r": mfe, "mae_r": mae})
            else:
                upd = ("UPDATE signals SET checked_ts=?, candles_n=?, tp1_hit=?, mfe_r=?, mae_r=? "
                       "WHERE id=? AND status='open'")
                args = (checked, n, int(hit1), mfe, mae, row_id)
                if events is not None and int(hit1) > stage0:       # yangi bosqich: TP1 yoki TP2 olindi
                    events.append({"symbol": symbol, "tf": tf, "side": side, "stage": int(hit1),
                                   "three": three, "tp1": tp1, "tp2": tp2, "tp3": tp3, "entry": entry,
                                   "sent_ts": sent_ts})
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


# ------------------------------------------------------- batafsil tahlil (v6.5)
def _grp(rows) -> str:
    n = len(rows)
    vals = [r[4] for r in rows]
    wins = sum(1 for v in vals if v > 0)
    return f"{n} сд · {wins / n * 100:.0f}% · {sum(vals):+.1f}R (ср. {sum(vals) / n:+.2f}R)"


def breakdown_text(tf: str) -> str:
    """Yopilgan signallar bo'yicha: soat, ball, yo'nalish, MFE/MAE. Matn (Russian — bot tili)."""
    with db.tx() as conn:
        rows = conn.execute(
            "SELECT sent_ts, score, side, status, result_r, mfe_r, mae_r FROM signals "
            "WHERE tf=? AND status!='open' AND result_r IS NOT NULL", (tf,)).fetchall()
    n = len(rows)
    if n < 5:
        return f"Пока мало закрытых сделок ({n}) — подробный разбор появится после 5+."

    out = [f"🔬 Разбор {n} закрытых сделок (после издержек)", ""]

    def block(title, keyf, order):
        groups = {}
        for r in rows:
            groups.setdefault(keyf(r), []).append(r)
        lines = [title]
        for k in order:
            if k in groups:
                lines.append(f"• {k}: {_grp(groups[k])}")
        out.extend(lines + [""])

    tz = C.STATS_TZ_OFFSET

    def hour_block(r):
        h = (int(r[0]) // 3600 + tz) % 24
        a = h // 6 * 6
        return f"{a:02d}–{a + 6:02d}ч"
    block(f"🕒 По времени (UTC{tz:+d})", hour_block, ["00–06ч", "06–12ч", "12–18ч", "18–24ч"])

    def score_block(r):
        s = r[1]
        return "90+" if s >= 90 else ("80–89" if s >= 80 else ("70–79" if s >= 70 else "<70"))
    block("⭐ По баллу", score_block, ["<70", "70–79", "80–89", "90+"])
    block("↕️ По стороне", lambda r: r[2], ["LONG", "SHORT"])

    with_mfe = [r for r in rows if r[5] is not None]
    if with_mfe:
        def avg(xs):
            return sum(xs) / len(xs) if xs else 0.0
        lines = [f"📏 MFE/MAE ({len(with_mfe)} сд.)"]
        exp = [r for r in with_mfe if r[3] in ("expired", "stale")]
        if exp:
            weak = sum(1 for r in exp if r[5] < 0.5)
            lines.append(f"• Истёк/затух: {len(exp)} · ср. MFE {avg([r[5] for r in exp]):.2f}R · "
                         f"не дошли до +0.5R: {weak}/{len(exp)} · ср. итог {avg([r[4] for r in exp]):+.2f}R")
        win = [r for r in with_mfe if r[3] in ("tp2", "tp3", "lock", "be")]
        if win:
            lines.append(f"• Прибыльные: {len(win)} · ср. MFE {avg([r[5] for r in win]):.2f}R "
                         f"vs взято {avg([r[4] for r in win]):+.2f}R")
        sl = [r for r in with_mfe if r[3] == "sl"]
        if sl:
            up = sum(1 for r in sl if r[5] >= 0.5)
            lines.append(f"• SL: {len(sl)} · из них сначала шли в плюс ≥0.5R: {up}/{len(sl)} · "
                         f"ср. MFE {avg([r[5] for r in sl]):.2f}R")
        out.extend(lines + [""])
    else:
        out.append("📏 MFE/MAE: данные начнут копиться с новых сделок.\n")

    if n < 30:
        out.append("⚠️ Выборка мала — это ориентир, не вывод.")
    return "\n".join(out)
