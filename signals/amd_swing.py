"""
signals/amd_swing.py
AMD — yuqori taymfreymlar (1h / 4h / 1d). Strategiya yadrosi BITTA: signals/amd_volume.py
(analyze / scan / backtest). Bu modulda faqat profillar (parametrlar) va Telegram buyruqlari.

15m (trend filtri 1h) — signals/amd_volume.py dagi CFG.

bot.py main() ichida: amd_swing.register(app)
Buyruqlar: /swing, /swing_check, /swing_backtest, /swing_backtest_top, /swing_stats
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Dict, Optional

import config as C
from config import ADMIN_CHAT_IDS
from engine import tg
from engine.evaluator import evaluate_pending, get_stats, record_signal
from engine.volatility import btc_regime, conflicts_with_btc_regime
from signals import amd_volume as A

logger = logging.getLogger("nozik.swing")

MIN_SCORE = int(os.environ.get("SWING_ALERT_THRESHOLD", "70"))
SCAN_INTERVAL = int(os.environ.get("SWING_SCAN_INTERVAL_SECONDS", "1800"))
EVAL_INTERVAL = int(os.environ.get("SWING_EVAL_INTERVAL_SECONDS", "3600"))

_COMMON = {
    "min_turnover": C.MIN_24H_TURNOVER_USDT,
    "max_turnover": C.MAX_24H_TURNOVER_USDT,
    "max_symbols": C.MAX_CANDIDATES_PER_SCAN,
    "acc_vol_max": 0.9,
    "sweep_max_width_frac": 0.5,
    "sweep_wick_min": 0.4,
    "sweep_vol_min": 1.8,
    "confirm_vol_min": 1.3,
    "confirm_body_min": 0.55,
    "min_rr1": 0.5,
    "min_rr2": 1.5,
    "min_score": MIN_SCORE,
    "max_chase_r": C.MAX_CHASE_R,
    "require_structure": C.REQUIRE_STRUCTURE,
    "fee_pct": C.FEE_PCT,
    "slip_pct": C.SLIPPAGE_PCT,
    "req_sleep": 0.12,
}

PROFILES: Dict[str, dict] = {
    "1h": {
        **_COMMON,
        "label": "1h", "tf": "60", "htf": "240", "htf_label": "4h", "bn_tf": "1h",
        "tf_hours": 1,
        "range_n": 32,            # ~1.3 kun
        "base_n": 64,             # ~2.7 kun
        "min_range_pct": 1.2, "max_range_pct": 8.0, "tight_pct": 1.92,
        "sweep_min_pct": 0.25,
        "max_risk_pct": 5.0,
        "cooldown_sec": 12 * 3600,
        "expire_candles": 48,     # 48 x 1h = 2 kun
        "btc_candles": 6, "btc_move_pct": 2.5,
    },
    "4h": {
        **_COMMON,
        "label": "4h", "tf": "240", "htf": "D", "htf_label": "1d", "bn_tf": "4h",
        "tf_hours": 4,
        "range_n": 30,            # ~5 kun
        "base_n": 60,             # ~10 kun
        "min_range_pct": 2.0, "max_range_pct": 15.0, "tight_pct": 3.2,
        "sweep_min_pct": 0.5,
        "max_risk_pct": 8.0,
        "cooldown_sec": 2 * 86400,
        "expire_candles": 42,     # 42 x 4h = 7 kun
        "btc_candles": 6, "btc_move_pct": 4.0,
    },
    "1d": {
        **_COMMON,
        "label": "1d", "tf": "D", "htf": "W", "htf_label": "1w", "bn_tf": "1d",
        "tf_hours": 24,
        "range_n": 20,            # ~3 hafta
        "base_n": 40,
        "min_range_pct": 5.0, "max_range_pct": 30.0, "tight_pct": 8.0,
        "sweep_min_pct": 1.0,
        "max_risk_pct": 12.0,
        "cooldown_sec": 7 * 86400,
        "expire_candles": 30,     # 30 kun
        "btc_candles": 8, "btc_move_pct": 10.0,
    },
}

ENABLED = [p.strip() for p in os.environ.get("SWING_TIMEFRAMES", "1h,4h").split(",")
           if p.strip() in PROFILES]

# Eski kod bilan moslik
SwingSignal = A.Signal

_lock = asyncio.Lock()


def _is_admin(update) -> bool:
    u = update.effective_user
    return u is not None and u.id in ADMIN_CHAT_IDS


def _parse_tf(args, idx: int) -> str:
    if len(args) > idx and args[idx].lower() in PROFILES:
        return args[idx].lower()
    return "1h"


# ----------------------------------------------------------------- skaner
async def _run(bot, force: bool = False):
    sent = found = 0
    async with _lock:
        for prof in ENABLED:
            P = PROFILES[prof]
            sigs = await asyncio.to_thread(lambda: A.scan(P, force=force))
            found += len(sigs)
            regime = "neutral"
            if C.USE_BTC_FILTER and sigs:
                regime = await asyncio.to_thread(
                    btc_regime, P["tf"], P["btc_candles"], P["btc_move_pct"])
            for s in sigs:
                if conflicts_with_btc_regime(s.symbol, s.side, regime):
                    logger.info(f"{s.symbol} [{prof}]: BTC rejimiga zid, o'tkazildi")
                    continue
                s.sent_ts = await asyncio.to_thread(record_signal, s)
                buf = await tg.make_chart(s.symbol, tg.to_dicts(s.candles), s.side.lower(),
                                          tg.levels_of(s), s.tf, tg.meta_of(s, P))
                await tg.broadcast(bot, ADMIN_CHAT_IDS, tg.format_signal(s, P), buf, parse_mode="HTML",
                                   reply_markup=tg.live_markup(s.symbol, getattr(s, "sent_ts", None)),
                                   track=(s.symbol, s.tf, getattr(s, "sent_ts", None)))
                sent += 1
    return sent, found


# --------------------------------------------------------------- buyruqlar
async def cmd_swing(update, context):
    if not _is_admin(update):
        return
    if _lock.locked():
        await update.message.reply_text("⏳ Сканирование уже идёт, подождите немного.")
        return
    await update.message.reply_text(
        f"🔍 Проверяю рынок ({', '.join(ENABLED)}), подождите 2–4 минуты...")
    try:
        sent, found = await _run(context.bot, force=True)
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
    symbol, prof = context.args[0].upper(), _parse_tf(context.args, 1)
    P = PROFILES[prof]
    res = await asyncio.to_thread(A.check, symbol, P)
    if not res:
        await update.message.reply_text("❌ Не удалось получить данные (проверьте символ).")
        return
    sig = res["signal"]
    if not sig:
        await update.message.reply_text(f"{symbol} [{prof}]: AMD-сетапа сейчас нет.")
        return
    ok = ("✅ Проходит порог сигнала" if sig.score >= MIN_SCORE
          else f"⚠️ Скор ниже порога ({MIN_SCORE}) — сигнал отправлен не будет")
    caption = tg.format_signal(sig, P) + "\n" + ok
    buf = await tg.make_chart(symbol, tg.to_dicts(sig.candles), sig.side.lower(),
                              tg.levels_of(sig), prof, tg.meta_of(sig, P))
    await tg.reply_with_chart(update.message, caption, buf, parse_mode="HTML")


async def cmd_swing_backtest(update, context):
    if not _is_admin(update):
        return
    if not context.args:
        await update.message.reply_text("Пример: /swing_backtest PEPEUSDT 1h (или 4h, 1d)")
        return
    symbol, prof = context.args[0].upper(), _parse_tf(context.args, 1)
    P = PROFILES[prof]
    await update.message.reply_text(f"🧪 {symbol} [{prof}]: идёт бэктест (до 1–2 минут)...")
    r = await asyncio.to_thread(A.backtest, symbol, P)
    if not r:
        await update.message.reply_text("❌ Недостаточно данных (возможно, токен новый).")
        return
    days = r["bars"] * A.sim.tf_ms(P["tf"]) / 86_400_000
    await update.message.reply_text(tg.format_backtest(r, P, days))


async def cmd_swing_backtest_top(update, context):
    if not _is_admin(update):
        return
    prof = _parse_tf(context.args, 0)
    P = PROFILES[prof]
    n = C.BACKTEST_TOP_N
    await update.message.reply_text(
        f"🧪 [{prof}] бэктест по {n} самым ликвидным малым токенам. Это займёт несколько минут...")
    r = await asyncio.to_thread(lambda: A.backtest_many(A.universe()[:n], P))
    if not r:
        await update.message.reply_text("❌ Не удалось получить данные.")
        return
    days = r["bars"] / max(r["symbols_ok"], 1) * A.sim.tf_ms(P["tf"]) / 86_400_000
    await update.message.reply_text(tg.format_backtest(r, P, days))


async def cmd_swing_stats(update, context):
    if not _is_admin(update):
        return
    lines = [f"📈 Статистика {'/'.join(ENABLED)} (после издержек):\n"]
    for tf in ENABLED:
        s = await asyncio.to_thread(get_stats, tf)
        lines.append(
            f"[{tf}] закрыто {s['total_closed']} | прибыльных {s['wins']} ({s['winrate_pct']}%) | "
            f"итого {s['total_r']:+.2f}R | среднее {s['avg_r']:+.2f}R | открыто {s['pending']}")
    await update.message.reply_text("\n".join(lines))


# ----------------------------------------------------------------- joblar
async def _job_scan(context):
    if _lock.locked():
        return
    try:
        await _run(context.bot)
    except Exception as e:
        logger.error(f"Swing background skanerlashda xato: {e}")


async def _job_eval(context):
    for tf in ENABLED:
        P = PROFILES[tf]
        events: list = []
        try:
            closed = await asyncio.to_thread(
                evaluate_pending, A.bybit_klines, tf, P["tf"], P["expire_candles"], events)
        except Exception as e:
            logger.error(f"Swing baholashda xato ({tf}): {e}")
            continue
        for ev in events:
            await tg.notify(context.bot, ADMIN_CHAT_IDS, tg.progress_text(ev, ev["tf"]),
                            ev["symbol"], ev["tf"], ev.get("sent_ts"))
        for r in closed:
            await tg.notify(context.bot, ADMIN_CHAT_IDS, tg.result_text(r, r["tf"]),
                            r["symbol"], r["tf"], r.get("sent_ts"), unpin=True)


def register(app):
    """bot.py main() ichida chaqiriladi: handlerlar va background joblarni qo'shadi."""
    from telegram.ext import CommandHandler
    app.add_handler(CommandHandler("swing", cmd_swing))
    app.add_handler(CommandHandler("swing_check", cmd_swing_check))
    app.add_handler(CommandHandler("swing_backtest", cmd_swing_backtest))
    app.add_handler(CommandHandler("swing_backtest_top", cmd_swing_backtest_top))
    app.add_handler(CommandHandler("swing_stats", cmd_swing_stats))
    # Skaner soat/yarim soat chegarasiga tekislanadi (+20 s): yangi 1h/4h sham yopilgach darrov
    first = SCAN_INTERVAL - (time.time() % SCAN_INTERVAL) + 20
    app.job_queue.run_repeating(_job_scan, interval=SCAN_INTERVAL, first=first)
    app.job_queue.run_repeating(_job_eval, interval=EVAL_INTERVAL, first=120)
    logger.info(f"Swing AMD moduli yoqildi: {', '.join(ENABLED)}")
