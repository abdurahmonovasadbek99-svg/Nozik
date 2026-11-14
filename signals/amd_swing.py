"""
signals/amd_swing.py
AMD (Accumulation -> Manipulation -> Distribution) — YUQORI TAYMFREYM (4h / 1d)
uzoq muddatli (swing) signallar uchun. signals/amd_volume.py (15m) ga TEGMAYDI.

Strategiya mantig'i bir xil, faqat parametrlar katta shamlarga moslangan:
  - "1h": 1 soatlik shamlar, trend filtri 4h. Signal muddati ~2 kun.
  - "4h": 4 soatlik shamlar, trend filtri 1d. Signal muddati ~7 kun.
  - "1d": (ixtiyoriy, SWING_TIMEFRAMES=1h,4h,1d) trend filtri 1w, ~30 kun.
15m (trend filtri 1h) — asosiy signals/amd_volume.py modulida.

Ulash (bot.py ichida, 2 qator):
    from signals import amd_swing
    ...
    amd_swing.register(app)      # main() ichida, app.run_polling() dan oldin

Yangi buyruqlar: /swing, /swing_check, /swing_backtest, /swing_stats
"""
from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

from config import ADMIN_CHAT_IDS, DB_PATH
from signals.amd_volume import (
    Candle, Signal, _atr, _ema, binance_klines, bybit_klines, universe,
)

logger = logging.getLogger("nozik.swing")

# --------------------------------------------------------------- sozlamalar
_COMMON = {
    "acc_vol_max": 0.9,         # diapazon hajmi / oldingi o'rtacha hajm
    "sweep_max_width_frac": 0.5,
    "sweep_wick_min": 0.4,
    "sweep_vol_min": 1.8,
    "confirm_vol_min": 1.3,
    "confirm_body_min": 0.55,
    "min_rr1": 0.5,
    "min_rr2": 1.5,
}

PROFILES: Dict[str, dict] = {
    "1h": {
        **_COMMON,
        "label": "1h", "tf": "60", "htf": "240", "htf_label": "4h", "bn_tf": "1h",
        "tf_hours": 1,
        "range_n": 32,            # ~1.3 kun
        "base_n": 64,             # ~2.7 kun
        "min_range_pct": 1.2, "max_range_pct": 8.0,
        "sweep_min_pct": 0.25,
        "max_risk_pct": 5.0,
        "cooldown_sec": 12 * 3600,
        "expire_candles": 48,     # 48 x 1h = 2 kun
        "btc_candles": 6, "btc_move_pct": 2.5,   # BTC ~6 soatda
    },
    "4h": {
        **_COMMON,
        "label": "4h", "tf": "240", "htf": "D", "htf_label": "1d", "bn_tf": "4h",
        "tf_hours": 4,
        "range_n": 30,            # ~5 kun
        "base_n": 60,             # ~10 kun
        "min_range_pct": 2.0, "max_range_pct": 15.0,
        "sweep_min_pct": 0.5,
        "max_risk_pct": 8.0,
        "cooldown_sec": 2 * 86400,
        "expire_candles": 42,     # 42 x 4h = 7 kun
        "btc_candles": 6, "btc_move_pct": 4.0,   # BTC ~24 soatda
    },
    "1d": {
        **_COMMON,
        "label": "1d", "tf": "D", "htf": "W", "htf_label": "1w", "bn_tf": "1d",
        "tf_hours": 24,
        "range_n": 20,            # ~3 hafta
        "base_n": 40,
        "min_range_pct": 5.0, "max_range_pct": 30.0,
        "sweep_min_pct": 1.0,
        "max_risk_pct": 12.0,
        "cooldown_sec": 7 * 86400,
        "expire_candles": 30,     # 30 kun
        "btc_candles": 8, "btc_move_pct": 10.0,  # BTC ~7 kunda
    },
}

MIN_SCORE = int(os.environ.get("SWING_ALERT_THRESHOLD", "70"))
SCAN_INTERVAL = int(os.environ.get("SWING_SCAN_INTERVAL_SECONDS", "1800"))
EVAL_INTERVAL = int(os.environ.get("SWING_EVAL_INTERVAL_SECONDS", "3600"))
ENABLED = [p.strip() for p in os.environ.get("SWING_TIMEFRAMES", "1h,4h").split(",")
           if p.strip() in PROFILES]
USE_BTC_FILTER = os.environ.get("USE_BTC_FILTER", "1") == "1"
REQ_SLEEP = 0.12
EXTRA_SCORE_MAX = 17  # 1d/1w trend + Binance hajmi beradigan maksimal qo'shimcha ball


@dataclass
class SwingSignal(Signal):
    tf: str = "4h"


# ----------------------------------------------------------------- strategiya
def analyze(P: dict, symbol: str, c: List[Candle],
            h1: Optional[List[Candle]] = None,
            bn: Optional[List[Candle]] = None,
            min_score: Optional[int] = None) -> Optional[SwingSignal]:
    """c, h1, bn: faqat YOPILGAN shamlar, eskidan yangiga."""
    if len(c) < P["range_n"] + P["base_n"] + 6:
        return None
    k = len(c) - 1
    thr = MIN_SCORE if min_score is None else min_score
    for s in (k - 1, k - 2, k - 3):  # sweep tasdiqdan 1-3 sham oldin bo'lgan
        sig = _try(P, symbol, c, s, k, h1, bn)
        if sig and sig.score >= thr:
            return sig
    return None


def _try(P, symbol, c, s, k, h1, bn) -> Optional[SwingSignal]:
    w0 = s - P["range_n"]
    win = c[w0:s]
    base = c[w0 - P["base_n"]:w0]
    if len(win) < P["range_n"] or len(base) < P["base_n"]:
        return None

    # 1) ACCUMULATION: tor diapazon + past hajm
    rh = max(x[2] for x in win)
    rl = min(x[3] for x in win)
    mid = (rh + rl) / 2
    if mid <= 0:
        return None
    width = rh - rl
    wpct = width / mid * 100
    if not (P["min_range_pct"] <= wpct <= P["max_range_pct"]):
        return None
    base_vol = sum(x[5] for x in base) / len(base)
    if base_vol <= 0:
        return None
    acc_ratio = (sum(x[5] for x in win) / len(win)) / base_vol
    if acc_ratio > P["acc_vol_max"]:
        return None
    z = width * 0.2
    if sum(1 for x in win if x[2] >= rh - z) < 2:
        return None
    if sum(1 for x in win if x[3] <= rl + z) < 2:
        return None

    # 2) MANIPULATION: fitil diapazon chetini olib, ichkariga qaytadi + hajm
    o, hh, ll, cl, v = c[s][1], c[s][2], c[s][3], c[s][4], c[s][5]
    rng = hh - ll
    if rng <= 0:
        return None
    sv = v / base_vol
    if sv < P["sweep_vol_min"]:
        return None
    side, wick = None, 0.0
    if (ll < rl * (1 - P["sweep_min_pct"] / 100) and cl >= rl
            and (rl - ll) <= width * P["sweep_max_width_frac"]):
        w = (min(o, cl) - ll) / rng
        if w >= P["sweep_wick_min"]:
            side, wick = "LONG", w
    if (side is None and hh > rh * (1 + P["sweep_min_pct"] / 100) and cl <= rh
            and (hh - rh) <= width * P["sweep_max_width_frac"]):
        w = (hh - max(o, cl)) / rng
        if w >= P["sweep_wick_min"]:
            side, wick = "SHORT", w
    if side is None:
        return None

    # 3) DISTRIBUTION: diapazon o'rtasidan o'tuvchi kuchli sham + hajm
    ck = c[k]
    ko, kh, kl, kc, kv = ck[1], ck[2], ck[3], ck[4], ck[5]
    crng = kh - kl
    if crng <= 0:
        return None
    body = abs(kc - ko) / crng
    cvr = kv / base_vol
    if body < P["confirm_body_min"] or cvr < P["confirm_vol_min"]:
        return None
    atr = _atr(c[:k + 1])
    seg = c[s + 1:k + 1]
    if side == "LONG":
        if kc <= ko or kc <= mid:
            return None
        if any(x[4] < rl for x in seg):
            return None
        ext = min(x[3] for x in c[s:k + 1])
        entry, sl = kc, ext - 0.2 * atr
        tp1, tp2 = rh, rh + width
        if entry >= tp1:
            return None
    else:
        if kc >= ko or kc >= mid:
            return None
        if any(x[4] > rh for x in seg):
            return None
        ext = max(x[2] for x in c[s:k + 1])
        entry, sl = kc, ext + 0.2 * atr
        tp1, tp2 = rl, rl - width
        if entry <= tp1:
            return None

    risk = abs(entry - sl)
    if risk <= 0:
        return None
    risk_pct = risk / entry * 100
    if risk_pct > P["max_risk_pct"]:
        return None
    rr1 = abs(tp1 - entry) / risk
    rr2 = abs(tp2 - entry) / risk
    if rr1 < P["min_rr1"] or rr2 < P["min_rr2"]:
        return None

    # ---- ball
    score = 50
    why = [
        f"Accumulation: диапазон {wpct:.1f}%, объём x{acc_ratio:.2f}",
        f"Manipulation: объём sweep x{sv:.1f}, тень {wick * 100:.0f}%",
        f"Distribution: объём подтверждения x{cvr:.1f}",
    ]
    score += 10 if sv >= 3 else 6 if sv >= 2.2 else 0
    score += 8 if cvr >= 2 else 4 if cvr >= 1.6 else 0
    score += 5 if wick >= 0.6 else 0
    score += 5 if wpct <= P["min_range_pct"] * 1.6 else 0
    score += 5 if acc_ratio <= 0.7 else 0
    score += 5 if rr2 >= 2.2 else 0

    n_b = P["base_n"]
    if bn and len(bn) >= n_b + 4:
        bbase = sum(x[5] for x in bn[-(n_b + 4):-4]) / n_b
        if bbase > 0:
            bratio = max(x[5] for x in bn[-4:]) / bbase
            up = bn[-1][4] > bn[-4][4]
            aligned = up if side == "LONG" else (not up)
            if bratio >= 1.5 and aligned:
                score += 10
                why.append(f"Binance: объём подтвердил x{bratio:.1f}")
            elif bratio < 1.0 or not aligned:
                score -= 8
                why.append("Binance: объём не подтвердил")

    if h1 and len(h1) >= 25:
        closes = [x[4] for x in h1]
        e = _ema(closes[-60:], 21)
        if (side == "LONG" and closes[-1] > e) or (side == "SHORT" and closes[-1] < e):
            score += 7
            why.append(f"{P['htf_label']}: тренд совпадает с направлением")

    return SwingSignal(
        symbol=symbol, side=side, entry=entry, sl=sl, tp1=tp1, tp2=tp2,
        rr1=rr1, rr2=rr2, risk_pct=risk_pct, score=min(score, 100),
        range_high=rh, range_low=rl, ts=ck[0], reasons=why,
        candles=c[max(0, k - 59):k + 1], tf=P["label"],
    )


# ----------------------------------------------------------------- baza
def _conn():
    return sqlite3.connect(DB_PATH)


def init_db():
    conn = _conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS swing_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL, tf TEXT NOT NULL, side TEXT NOT NULL,
            score REAL NOT NULL,
            entry REAL NOT NULL, sl REAL NOT NULL, tp1 REAL NOT NULL, tp2 REAL NOT NULL,
            rr1 REAL NOT NULL, rr2 REAL NOT NULL,
            sent_ts INTEGER NOT NULL, checked_ts INTEGER NOT NULL,
            candles_n INTEGER DEFAULT 0, tp1_hit INTEGER DEFAULT 0,
            status TEXT DEFAULT 'open', result_r REAL, closed_ts INTEGER
        )
    """)
    conn.commit()
    conn.close()


def _recent(symbol: str, tf: str, cooldown: int) -> bool:
    conn = _conn()
    row = conn.execute(
        "SELECT 1 FROM swing_signals WHERE symbol=? AND tf=? AND sent_ts>=? LIMIT 1",
        (symbol, tf, int(time.time()) - cooldown),
    ).fetchone()
    conn.close()
    return row is not None


def record(sig: SwingSignal):
    conn = _conn()
    conn.execute(
        "INSERT INTO swing_signals (symbol, tf, side, score, entry, sl, tp1, tp2, rr1, rr2, "
        "sent_ts, checked_ts) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (sig.symbol, sig.tf, sig.side, sig.score, sig.entry, sig.sl, sig.tp1, sig.tp2,
         sig.rr1, sig.rr2, int(time.time()), sig.ts),
    )
    conn.commit()
    conn.close()


def evaluate_pending() -> list:
    """Ochiq swing signallarni yangi yopilgan shamlar bilan tekshiradi."""
    conn = _conn()
    rows = conn.execute(
        "SELECT id, symbol, tf, side, entry, sl, tp1, tp2, rr1, rr2, checked_ts, candles_n, tp1_hit "
        "FROM swing_signals WHERE status='open'"
    ).fetchall()
    closed = []
    for (row_id, symbol, tf, side, entry, sl, tp1, tp2, rr1, rr2, checked, n, hit1) in rows:
        P = PROFILES.get(tf)
        if not P:
            continue
        try:
            c = bybit_klines(symbol, P["tf"], 200)
            if not c:
                continue
            c = c[:-1]
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
                if n >= P["expire_candles"]:
                    status = "expired"
                    result = 0.5 * rr1 if hit1 else 0.0
                    break
            conn.execute(
                "UPDATE swing_signals SET checked_ts=?, candles_n=?, tp1_hit=?, status=?, "
                "result_r=?, closed_ts=? WHERE id=?",
                (checked, n, int(hit1), status, result,
                 int(time.time()) if status != "open" else None, row_id),
            )
            if status != "open":
                closed.append({"symbol": symbol, "tf": tf, "side": side,
                               "status": status, "result_r": result})
        except Exception:
            continue
    conn.commit()
    conn.close()
    return closed


def get_stats() -> dict:
    conn = _conn()
    out = {}
    for tf in PROFILES:
        rows = conn.execute(
            "SELECT result_r FROM swing_signals WHERE tf=? AND status!='open' "
            "AND result_r IS NOT NULL", (tf,)).fetchall()
        pend = conn.execute(
            "SELECT COUNT(*) FROM swing_signals WHERE tf=? AND status='open'", (tf,)
        ).fetchone()[0]
        vals = [r[0] for r in rows]
        n = len(vals)
        wins = sum(1 for r in vals if r > 0)
        out[tf] = {
            "closed": n, "wins": wins, "pending": pend,
            "winrate": round(wins / n * 100, 1) if n else 0,
            "total_r": round(sum(vals), 2),
            "avg_r": round(sum(vals) / n, 2) if n else 0,
        }
    conn.close()
    return out


# ----------------------------------------------------------------- skaner
def _btc_regime(P: dict) -> str:
    c = bybit_klines("BTCUSDT", P["tf"], P["btc_candles"] + 1)
    if not c or len(c) < 3:
        return "neutral"
    c = c[:-1][-P["btc_candles"]:]
    if not c or not c[0][1]:
        return "neutral"
    chg = (c[-1][4] - c[0][1]) / c[0][1] * 100
    if chg >= P["btc_move_pct"]:
        return "strong_up"
    if chg <= -P["btc_move_pct"]:
        return "strong_down"
    return "neutral"


def scan(profile: str, max_symbols: int = 150) -> List[SwingSignal]:
    P = PROFILES[profile]
    out: List[SwingSignal] = []
    for sym in universe()[:max_symbols]:
        if _recent(sym, P["label"], P["cooldown_sec"]):
            continue
        c = bybit_klines(sym, P["tf"], 200)
        time.sleep(REQ_SLEEP)
        if not c:
            continue
        c = c[:-1]  # hali shakllanayotgan shamni olib tashlaymiz
        if not analyze(P, sym, c, min_score=MIN_SCORE - EXTRA_SCORE_MAX):
            continue
        h1 = bybit_klines(sym, P["htf"], 80)
        h1 = h1[:-1] if h1 else None
        bn = binance_klines(sym, P["bn_tf"], 120)
        bn = bn[:-1] if bn else None
        sig = analyze(P, sym, c, h1, bn)
        if sig:
            out.append(sig)
    out.sort(key=lambda s: -s.score)
    return out


def check(symbol: str, profile: str) -> Optional[dict]:
    P = PROFILES[profile]
    c = bybit_klines(symbol, P["tf"], 200)
    if not c:
        return None
    c = c[:-1]
    h1 = bybit_klines(symbol, P["htf"], 80)
    h1 = h1[:-1] if h1 else None
    bn = binance_klines(symbol, P["bn_tf"], 120)
    bn = bn[:-1] if bn else None
    return {"signal": analyze(P, symbol, c, h1, bn, min_score=0), "candles": c[-60:]}


def backtest(symbol: str, profile: str) -> Optional[dict]:
    P = PROFILES[profile]
    c = bybit_klines(symbol, P["tf"], 1000)
    need = P["range_n"] + P["base_n"] + 20
    if not c or len(c) < need + 30:
        return None
    c = c[:-1]
    res_list: List[float] = []
    i = need
    while i < len(c) - 1:
        sig = analyze(P, symbol, c[:i + 1], min_score=MIN_SCORE - EXTRA_SCORE_MAX)
        if not sig:
            i += 1
            continue
        res, exit_j, tp1_hit = 0.0, min(i + P["expire_candles"], len(c) - 1), False
        long_ = sig.side == "LONG"
        for j in range(i + 1, min(i + 1 + P["expire_candles"], len(c))):
            hi, lo = c[j][2], c[j][3]
            stop = sig.entry if tp1_hit else sig.sl
            hit_sl = lo <= stop if long_ else hi >= stop
            hit_tp1 = hi >= sig.tp1 if long_ else lo <= sig.tp1
            hit_tp2 = hi >= sig.tp2 if long_ else lo <= sig.tp2
            if hit_sl:
                res = 0.5 * sig.rr1 if tp1_hit else -1.0
                exit_j = j
                break
            if not tp1_hit and hit_tp1:
                tp1_hit = True
                res = 0.5 * sig.rr1
            if tp1_hit and hit_tp2:
                res = 0.5 * sig.rr1 + 0.5 * sig.rr2
                exit_j = j
                break
        res_list.append(res)
        i = exit_j + 1
    n = len(res_list)
    wins = sum(1 for r in res_list if r > 0)
    return {
        "symbol": symbol, "tf": profile, "bars": len(c), "trades": n, "wins": wins,
        "winrate": round(wins / n * 100, 1) if n else 0.0,
        "avg_R": round(sum(res_list) / n, 2) if n else 0.0,
        "total_R": round(sum(res_list), 2),
    }


# ----------------------------------------------------------------- Telegram
def _p(x: float) -> str:
    return f"{x:.6g}"


def _format(s: SwingSignal) -> str:
    emoji = "🟢🚀" if s.side == "LONG" else "🔴📉"
    tier = "💎 PREMIUM" if s.score >= 85 else "Стандарт"
    P = PROFILES[s.tf]
    hours = P["expire_candles"] * P["tf_hours"]
    text = (
        f"{emoji} СИГНАЛ {s.tf}: {s.symbol}  [{tier}]\n"
        f"⏱ Таймфрейм: {s.tf} (тренд-фильтр {P['htf_label']})\n\n"
        f"Направление: {s.side}\n"
        f"AMD-скор: {s.score}/100\n\n"
        f"Вход: {_p(s.entry)}\n"
        f"SL: {_p(s.sl)} (риск {s.risk_pct:.2f}%)\n"
        f"TP1: {_p(s.tp1)} (RR {s.rr1:.2f}) — закрыть 50%, SL в безубыток\n"
        f"TP2: {_p(s.tp2)} (RR {s.rr2:.2f})\n"
        f"Ожидаемая длительность: ~{hours / 24:.1f} дн.\n\n"
    )
    emojis = {"Accumulation": "📦", "Manipulation": "🎣", "Distribution": "🚀", "Binance": "🟡"}
    for r in s.reasons:
        e = next((v for k, v in emojis.items() if r.startswith(k)), "📈" if "тренд" in r else "•")
        text += f"{e} {r}\n"
    return text


def _is_admin(update) -> bool:
    u = update.effective_user
    return u is not None and u.id in ADMIN_CHAT_IDS


async def _send(bot, s: SwingSignal):
    from engine.chart import generate_candle_chart
    candles = [{"open": c[1], "high": c[2], "low": c[3], "close": c[4]} for c in s.candles]
    levels = {"range_high": s.range_high, "range_low": s.range_low,
              "entry": s.entry, "sl": s.sl, "tp1": s.tp1, "tp2": s.tp2}
    text = _format(s)
    buf = generate_candle_chart(s.symbol, candles, s.side.lower(), levels, tf_label=s.tf)
    for chat_id in ADMIN_CHAT_IDS:
        try:
            if buf:
                buf.seek(0)
                await bot.send_photo(chat_id=chat_id, photo=buf, caption=text)
            else:
                await bot.send_message(chat_id=chat_id, text=text)
        except Exception as e:
            logger.error(f"Swing xabar xatosi ({chat_id}): {e}")


_lock = asyncio.Lock()


async def _run(bot):
    sent = found = 0
    async with _lock:
        for prof in ENABLED:
            P = PROFILES[prof]
            sigs = await asyncio.to_thread(scan, prof)
            found += len(sigs)
            regime = "neutral"
            if USE_BTC_FILTER and sigs:
                try:
                    regime = await asyncio.to_thread(_btc_regime, P)
                except Exception:
                    regime = "neutral"
            for s in sigs:
                if (regime == "strong_down" and s.side == "LONG"
                        or regime == "strong_up" and s.side == "SHORT") \
                        and s.symbol not in ("BTCUSDT", "ETHUSDT"):
                    logger.info(f"{s.symbol} [{prof}]: BTC rejimiga zid, o'tkazildi")
                    continue
                await asyncio.to_thread(record, s)
                await _send(bot, s)
                sent += 1
    return sent, found


def _parse_tf(args, idx: int) -> str:
    if len(args) > idx and args[idx].lower() in PROFILES:
        return args[idx].lower()
    return "1h"


async def cmd_swing(update, context):
    if not _is_admin(update):
        return
    if _lock.locked():
        await update.message.reply_text("⏳ Сканирование уже идёт, подождите немного.")
        return
    await update.message.reply_text(
        f"🔍 Проверяю рынок ({', '.join(ENABLED)}), подождите 2–4 минуты...")
    try:
        sent, found = await _run(context.bot)
    except Exception as e:
        logger.error(f"Swing skanerlashda xato: {e}")
        await update.message.reply_text("❌ Произошла ошибка. Проверьте логи.")
        return
    await update.message.reply_text(
        f"📊 Сканирование завершено. Отправлено сигналов: {sent}" if found
        else "Сигналов, подходящих под условия AMD, пока нет.")


async def cmd_swing_check(update, context):
    if not _is_admin(update):
        return
    if not context.args:
        await update.message.reply_text("Пример: /swing_check PEPEUSDT 1h (или 4h, 1d)")
        return
    from engine.chart import generate_candle_chart
    symbol, prof = context.args[0].upper(), _parse_tf(context.args, 1)
    res = await asyncio.to_thread(check, symbol, prof)
    if not res:
        await update.message.reply_text("❌ Не удалось получить данные (проверьте символ).")
        return
    sig = res["signal"]
    if not sig:
        await update.message.reply_text(f"{symbol} [{prof}]: AMD-сетапа сейчас нет.")
        return
    ok = "✅ Проходит порог сигнала" if sig.score >= MIN_SCORE else \
        f"⚠️ Скор ниже порога ({MIN_SCORE}) — сигнал отправлен не будет"
    caption = _format(sig) + "\n" + ok
    candles = [{"open": c[1], "high": c[2], "low": c[3], "close": c[4]} for c in sig.candles]
    levels = {"range_high": sig.range_high, "range_low": sig.range_low, "entry": sig.entry,
              "sl": sig.sl, "tp1": sig.tp1, "tp2": sig.tp2}
    buf = generate_candle_chart(symbol, candles, sig.side.lower(), levels, tf_label=prof)
    if buf:
        await update.message.reply_photo(photo=buf, caption=caption)
    else:
        await update.message.reply_text(caption)


async def cmd_swing_backtest(update, context):
    if not _is_admin(update):
        return
    if not context.args:
        await update.message.reply_text("Пример: /swing_backtest PEPEUSDT 1h (или 4h, 1d)")
        return
    symbol, prof = context.args[0].upper(), _parse_tf(context.args, 1)
    await update.message.reply_text(f"🧪 {symbol} [{prof}]: идёт бэктест...")
    r = await asyncio.to_thread(backtest, symbol, prof)
    if not r:
        await update.message.reply_text("❌ Недостаточно данных (возможно, токен новый).")
        return
    await update.message.reply_text(
        f"🧪 {r['symbol']} [{r['tf']}], свечей: {r['bars']}\n\n"
        f"Сделок: {r['trades']}\nПрибыльных: {r['wins']} ({r['winrate']}%)\n"
        f"Среднее: {r['avg_R']}R\nИтого: {r['total_R']}R\n\n"
        "Примечание: на старших таймфреймах сделок мало — проверьте на 10–15 токенах."
    )


async def cmd_swing_stats(update, context):
    if not _is_admin(update):
        return
    st = await asyncio.to_thread(get_stats)
    lines = ["📈 Статистика 1h/4h:\n"]
    for tf, s in st.items():
        lines.append(
            f"[{tf}] закрыто {s['closed']} | прибыльных {s['wins']} ({s['winrate']}%) | "
            f"итого {s['total_r']:+.2f}R | среднее {s['avg_r']:+.2f}R | открыто {s['pending']}")
    await update.message.reply_text("\n".join(lines))


async def _job_scan(context):
    if _lock.locked():
        return
    try:
        await _run(context.bot)
    except Exception as e:
        logger.error(f"Swing background skanerlashda xato: {e}")


RESULT_TEXT = {
    "tp2": "✅✅ TP2 достигнут",
    "be": "✅ TP1 взят, остаток закрыт в безубытке",
    "sl": "❌ Сработал SL",
    "expired": "⏱ Срок сигнала истёк",
}


async def _job_eval(context):
    try:
        closed = await asyncio.to_thread(evaluate_pending)
    except Exception as e:
        logger.error(f"Swing baholashda xato: {e}")
        return
    for r in closed:
        text = (f"{RESULT_TEXT.get(r['status'], r['status'])} [{r['tf']}]\n"
                f"{r['symbol']} {r['side']}: {r['result_r']:+.2f}R")
        for chat_id in ADMIN_CHAT_IDS:
            try:
                await context.bot.send_message(chat_id=chat_id, text=text)
            except Exception as e:
                logger.error(f"Swing natija xatosi ({chat_id}): {e}")


def register(app):
    """bot.py main() ichida chaqiriladi: handlerlar va background joblarni qo'shadi."""
    from telegram.ext import CommandHandler
    init_db()
    app.add_handler(CommandHandler("swing", cmd_swing))
    app.add_handler(CommandHandler("swing_check", cmd_swing_check))
    app.add_handler(CommandHandler("swing_backtest", cmd_swing_backtest))
    app.add_handler(CommandHandler("swing_stats", cmd_swing_stats))
    app.job_queue.run_repeating(_job_scan, interval=SCAN_INTERVAL, first=60)
    app.job_queue.run_repeating(_job_eval, interval=EVAL_INTERVAL, first=120)
    logger.info(f"Swing AMD moduli yoqildi: {', '.join(ENABLED)}")
