"""
Nozik Bot v3 (AMD) - Asosiy Telegram interfeysi.
Strategiya: AMD (Accumulation -> Manipulation -> Distribution) + Bybit/Binance hajm.
Signal mantig'i signals/amd_volume.py da, bu fayl faqat Telegram bilan muloqot qatlami.

Dizayn v2 dagi kabi: admin-only, pastki menyu, rasmli signal, kunlik/haftalik hisobot.
"""
import asyncio
import datetime
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

from telegram import Update, ReplyKeyboardMarkup, BotCommand
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

from config import (
    TELEGRAM_BOT_TOKEN,
    ADMIN_CHAT_IDS,
    ALERT_THRESHOLD,
    ALERT_COOLDOWN_SECONDS,
    MAX_RISK_PCT,
    SCAN_INTERVAL_SECONDS,
    MIN_24H_TURNOVER_USDT,
    MAX_24H_TURNOVER_USDT,
    MAX_CANDIDATES_PER_SCAN,
    EXCLUDE_SYMBOLS,
    USE_BTC_FILTER,
    EXPIRE_CANDLES,
    EVAL_CHECK_INTERVAL_SECONDS,
    DAILY_REPORT_HOUR_UTC,
    WEEKLY_REPORT_WEEKDAY,
    SELF_PING_INTERVAL_SECONDS,
    PORT,
)
from engine.chart import generate_candle_chart
from engine.evaluator import init_db, record_signal, evaluate_pending, get_stats, get_stats_since
from engine.volatility import get_btc_regime, conflicts_with_btc_regime
from signals import amd_volume as amd
from signals.amd_volume import CFG, bybit_klines, check, scan
from keepalive import self_ping

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("nozik")

_scan_lock = asyncio.Lock()


def _apply_config():
    """config.py (Render env) qiymatlarini strategiya modullariga uzatadi."""
    CFG.update(
        min_score=ALERT_THRESHOLD,
        cooldown_sec=ALERT_COOLDOWN_SECONDS,
        max_risk_pct=MAX_RISK_PCT,
        min_turnover=MIN_24H_TURNOVER_USDT,
        max_turnover=MAX_24H_TURNOVER_USDT,
        max_symbols=MAX_CANDIDATES_PER_SCAN,
    )
    amd.MAJORS.update(EXCLUDE_SYMBOLS)


# Har bir AMD bosqichi uchun emoji - xabarlarni tez o'qish uchun
REASON_EMOJIS = {
    "Accumulation": "📦",
    "Manipulation": "🎣",
    "Distribution": "🚀",
    "Binance": "🟡",
    "1h": "📈",
}

MAIN_MENU = ReplyKeyboardMarkup(
    [
        ["🔍 Skanerlash", "📈 Statistika"],
        ["📊 Hisobot", "⚙️ Sozlamalar"],
    ],
    resize_keyboard=True,
)


def _is_admin(update: Update) -> bool:
    """Buyruqlar faqat ADMIN_CHAT_IDS ro'yxatidagi foydalanuvchilar uchun."""
    user = update.effective_user
    return user is not None and user.id in ADMIN_CHAT_IDS


def _p(x: float) -> str:
    return f"{x:.6g}"


def _reason_line(text: str) -> str:
    for key, emoji in REASON_EMOJIS.items():
        if text.startswith(key):
            return f"{emoji} {text}"
    return f"• {text}"


def _to_dicts(candles: list) -> list:
    return [{"open": c[1], "high": c[2], "low": c[3], "close": c[4]} for c in candles]


def _format_signal(s) -> str:
    emoji = "🟢🚀" if s.side == "LONG" else "🔴📉"
    tier = "💎 PREMIUM" if s.score >= 85 else "Standard"
    text = (
        f"{emoji} SIGNAL: {s.symbol}  [{tier}]\n\n"
        f"Yo'nalish: {s.side}\n"
        f"AMD score: {s.score}/100\n\n"
        f"Kirish: {_p(s.entry)}\n"
        f"SL: {_p(s.sl)} (risk {s.risk_pct:.2f}%)\n"
        f"TP1: {_p(s.tp1)} (RR {s.rr1:.2f}) — 50% yopish, SL breakeven'ga\n"
        f"TP2: {_p(s.tp2)} (RR {s.rr2:.2f})\n\n"
    )
    for r in s.reasons:
        text += _reason_line(r) + "\n"
    return text


def _levels(s) -> dict:
    return {"range_high": s.range_high, "range_low": s.range_low,
            "entry": s.entry, "sl": s.sl, "tp1": s.tp1, "tp2": s.tp2}


async def _send_signal(bot, s):
    text = _format_signal(s)
    chart_buf = generate_candle_chart(s.symbol, _to_dicts(s.candles), s.side.lower(), _levels(s))
    for chat_id in ADMIN_CHAT_IDS:
        try:
            if chart_buf:
                chart_buf.seek(0)
                await bot.send_photo(chat_id=chat_id, photo=chart_buf, caption=text)
            else:
                await bot.send_message(chat_id=chat_id, text=text)
        except Exception as e:
            logger.error(f"Xabar yuborishda xato ({chat_id}): {e}")


async def _run_scan(bot):
    """Bozorni skanerlaydi, signallarni yozadi va yuboradi. (yuborildi, BTC filtri o'tkazdi, topildi)."""
    async with _scan_lock:
        sigs = await asyncio.to_thread(scan)

        regime = "neutral"
        if USE_BTC_FILTER and sigs:
            try:
                regime = await asyncio.to_thread(get_btc_regime)
            except Exception:
                regime = "neutral"

        sent = skipped = 0
        for s in sigs:
            # BTC kuchli oqimiga qarshi altcoin signali ishonchsiz
            if USE_BTC_FILTER and conflicts_with_btc_regime(s.symbol, s.side.lower(), regime):
                logger.info(f"{s.symbol}: signal ({s.side}) BTC rejimiga ({regime}) zid - o'tkazib yuborildi")
                skipped += 1
                continue
            await asyncio.to_thread(record_signal, s)
            await _send_signal(bot, s)
            sent += 1
        return sent, skipped, len(sigs)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update):
        await update.message.reply_text("Bu bot shaxsiy ishlatiladi. Kirish rad etildi.")
        return
    await update.message.reply_text(
        "🤖 Nozik Bot v3 ishga tushdi.\n\n"
        "Strategiya: AMD (Accumulation → Manipulation → Distribution) + "
        "Bybit/Binance hajm tahlili. Asosiy e'tibor — kichik tokenlar.\n\n"
        "Pastdagi menyudan foydalaning yoki buyruqlarni yozing:\n"
        "/scan - hozir bozorni tekshirish\n"
        "/check <SYMBOL> - bitta coinni tekshirish (masalan /check PEPEUSDT)\n"
        "/backtest <SYMBOL> - tarixiy sinov\n"
        "/pump_stats - umumiy signal statistikasi\n"
        "/report - so'nggi 24 soat va 7 kunlik hisobot\n"
        "/settings - joriy sozlamalar",
        reply_markup=MAIN_MENU,
    )


async def cmd_scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update):
        await update.message.reply_text("Ruxsat yo'q.")
        return
    if _scan_lock.locked():
        await update.message.reply_text("⏳ Skanerlash allaqachon ketmoqda, biroz kuting.")
        return
    await update.message.reply_text("🔍 Kichik tokenlar AMD bo'yicha tekshirilmoqda, 1-2 daqiqa kuting...")
    try:
        sent, skipped, found = await _run_scan(context.bot)
    except Exception as e:
        logger.error(f"Skanerlashda xato: {e}")
        await update.message.reply_text("❌ Skanerlashda xato yuz berdi. Loglarni tekshiring.")
        return
    text = f"📊 Skanerlash tugadi ({amd.LAST_SCAN['count']} juftlik tekshirildi).\n"
    if found == 0:
        text += "Hozircha AMD shartlariga mos signal yo'q."
    else:
        text += f"Yuborilgan signal: {sent}"
        if skipped:
            text += f"\nBTC oqimiga zid bo'lgani uchun o'tkazib yuborilgan: {skipped}"
    await update.message.reply_text(text)


async def cmd_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update):
        return
    if not context.args:
        await update.message.reply_text("Iltimos, coin belgisini kiriting. Masalan: /check PEPEUSDT")
        return
    symbol = context.args[0].upper()
    await update.message.reply_text(f"🔍 {symbol} tekshirilmoqda...")
    res = await asyncio.to_thread(check, symbol)
    if not res:
        await update.message.reply_text("❌ Ma'lumot olib bo'lmadi (symbolni tekshiring).")
        return

    sig, st = res["signal"], res["state"]
    lines = [f"📊 {symbol} tahlili:\n"]
    levels = None
    direction = "neutral"
    if sig:
        direction = sig.side.lower()
        levels = _levels(sig)
        ok = sig.score >= ALERT_THRESHOLD
        lines.append(f"AMD setup topildi: {sig.side}, score {sig.score}/100")
        lines.append("✅ Signal chegarasidan o'tadi" if ok else
                     f"⚠️ Score chegaradan ({ALERT_THRESHOLD}) past — signal yuborilmaydi")
        lines.append(f"Kirish {_p(sig.entry)} | SL {_p(sig.sl)} | TP1 {_p(sig.tp1)} | TP2 {_p(sig.tp2)}")
        lines.append("")
        for r in sig.reasons:
            lines.append(_reason_line(r))
    else:
        lines.append("AMD setup hozir yo'q.")
        if st:
            levels = {"range_high": st["range_high"], "range_low": st["range_low"]}
            lines.append("")
            lines.append(f"Diapazon: {st['range_pct']:.1f}% " +
                         ("✅" if st["tight"] else "❌ (shartga mos emas)"))
            lines.append(f"Diapazon hajmi: x{st['acc_ratio']:.2f} " +
                         ("✅ jim" if st["quiet"] else "❌ jim emas"))
            lines.append(f"Oxirgi sham hajmi: x{st['last_vol_x']:.1f}")
            if st["tight"] and st["quiet"]:
                lines.append("📦 Accumulation bosqichida — manipulyatsiyani kuzating.")
        else:
            lines.append("Tahlil uchun yetarli tarix yo'q.")
    caption = "\n".join(lines)

    chart_buf = generate_candle_chart(symbol, _to_dicts(res["candles"]), direction, levels)
    if chart_buf:
        await update.message.reply_photo(photo=chart_buf, caption=caption)
    else:
        await update.message.reply_text(caption)


async def cmd_backtest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update):
        return
    if not context.args:
        await update.message.reply_text("Iltimos, coin belgisini kiriting. Masalan: /backtest PEPEUSDT")
        return
    symbol = context.args[0].upper()
    await update.message.reply_text(f"🧪 {symbol} tarixiy sinov ketmoqda...")
    r = await asyncio.to_thread(amd.backtest, symbol)
    if not r:
        await update.message.reply_text("❌ Ma'lumot olib bo'lmadi (symbolni tekshiring).")
        return
    await update.message.reply_text(
        f"🧪 {r['symbol']} (so'nggi ~10 kun, 15m)\n\n"
        f"Bitimlar: {r['trades']}\n"
        f"Foydali: {r['wins']} ({r['winrate']}%)\n"
        f"O'rtacha: {r['avg_R']}R\n"
        f"Jami: {r['total_R']}R\n\n"
        "Eslatma: bitta coin uchun bitimlar kam bo'ladi — 10-15 ta coinda sinab ko'ring."
    )


async def cmd_pump_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update):
        return
    st = get_stats()
    bs = st["by_status"]
    text = (
        "📈 Signal statistikasi:\n\n"
        f"Yopilgan signallar: {st['total_closed']}\n"
        f"Foydali: {st['wins']} ({st['winrate_pct']}%)\n"
        f"Jami natija: {st['total_r']:+.2f}R\n"
        f"O'rtacha: {st['avg_r']:+.2f}R\n"
        f"Kutilayotgan (ochiq): {st['pending']}\n\n"
        f"TP2: {bs.get('tp2', 0)} | TP1+BE: {bs.get('be', 0)} | "
        f"SL: {bs.get('sl', 0)} | Muddati tugagan: {bs.get('expired', 0)}"
    )
    await update.message.reply_text(text)


async def cmd_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update):
        return
    text = (
        "⚙️ Joriy sozlamalar:\n\n"
        f"Strategiya: AMD + Bybit/Binance hajm\n"
        f"Timeframe: {CFG['tf']}m (trend filtri: 1h)\n"
        f"Minimal score: {ALERT_THRESHOLD}/100\n"
        f"Maks. risk: {MAX_RISK_PCT}%\n"
        f"Universe: 24s hajm {MIN_24H_TURNOVER_USDT/1e6:g}M — {MAX_24H_TURNOVER_USDT/1e6:g}M USDT "
        f"(maks. {MAX_CANDIDATES_PER_SCAN} juftlik)\n"
        f"Skanerlash: har {SCAN_INTERVAL_SECONDS // 60} daqiqada\n"
        f"Cooldown: {ALERT_COOLDOWN_SECONDS // 3600} soat\n"
        f"BTC filtri: {'yoqilgan' if USE_BTC_FILTER else 'o‘chirilgan'}\n"
        f"Signal muddati: {EXPIRE_CANDLES * 15 // 60} soat\n\n"
        "O'zgartirish: Render → Environment Variables."
    )
    await update.message.reply_text(text)


async def handle_menu_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update):
        return
    text = update.message.text

    if text == "🔍 Skanerlash":
        await cmd_scan(update, context)
    elif text == "📈 Statistika":
        await cmd_pump_stats(update, context)
    elif text == "📊 Hisobot":
        await cmd_report(update, context)
    elif text == "⚙️ Sozlamalar":
        await cmd_settings(update, context)
    else:
        await update.message.reply_text(
            "Tushunmadim. Pastdagi menyudan tanlang yoki /check SYMBOL kabi buyruq yozing."
        )


def _format_period_report(title: str, stats: dict) -> str:
    lines = [f"{title}\n", f"Yuborilgan signallar: {stats['total_sent']}"]
    if stats["total_closed"] > 0:
        lines.append(f"Yopilgan: {stats['total_closed']}")
        lines.append(f"Foydali: {stats['wins']} ({stats['winrate_pct']}%)")
        lines.append(f"Jami natija: {stats['total_r']:+.2f}R")
        lines.append(f"O'rtacha: {stats['avg_r']:+.2f}R")
        if stats["best"]:
            lines.append(f"Eng yaxshi: {stats['best'][0]} ({stats['best'][1]:+.2f}R)")
        if stats["worst"]:
            lines.append(f"Eng yomon: {stats['worst'][0]} ({stats['worst'][1]:+.2f}R)")
    else:
        lines.append("Hali yopilgan signal yo'q.")
    return "\n".join(lines)


async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update):
        return
    daily = get_stats_since(86400)
    weekly = get_stats_since(604800)
    text = (
        _format_period_report("📅 So'nggi 24 soat", daily)
        + "\n\n"
        + _format_period_report("🗓 So'nggi 7 kun", weekly)
    )
    await update.message.reply_text(text)


async def scheduled_daily_report(context: ContextTypes.DEFAULT_TYPE):
    stats = get_stats_since(86400)
    text = _format_period_report("📅 Kunlik hisobot", stats)
    for chat_id in ADMIN_CHAT_IDS:
        try:
            await context.bot.send_message(chat_id=chat_id, text=text)
        except Exception as e:
            logger.error(f"Kunlik hisobot yuborishda xato ({chat_id}): {e}")


async def scheduled_weekly_report(context: ContextTypes.DEFAULT_TYPE):
    stats = get_stats_since(604800)
    text = _format_period_report("🗓 Haftalik hisobot", stats)
    for chat_id in ADMIN_CHAT_IDS:
        try:
            await context.bot.send_message(chat_id=chat_id, text=text)
        except Exception as e:
            logger.error(f"Haftalik hisobot yuborishda xato ({chat_id}): {e}")


RESULT_TEXT = {
    "tp2": "✅✅ TP2 urildi",
    "be": "✅ TP1 olindi, qolgani breakeven'da yopildi",
    "sl": "❌ SL urildi",
    "expired": "⏱ Muddati tugadi",
}


async def scheduled_evaluate(context: ContextTypes.DEFAULT_TYPE):
    """Ochiq signallarni tekshiradi va natijasini xabar qiladi."""
    try:
        closed = await asyncio.to_thread(
            evaluate_pending, bybit_klines, CFG["tf"], EXPIRE_CANDLES
        )
    except Exception as e:
        logger.error(f"Signallarni baholashda xato: {e}")
        return
    for r in closed:
        text = f"{RESULT_TEXT.get(r['status'], r['status'])}\n{r['symbol']} {r['side']}: {r['result_r']:+.2f}R"
        for chat_id in ADMIN_CHAT_IDS:
            try:
                await context.bot.send_message(chat_id=chat_id, text=text)
            except Exception as e:
                logger.error(f"Natija yuborishda xato ({chat_id}): {e}")


async def background_scan(context: ContextTypes.DEFAULT_TYPE):
    if _scan_lock.locked():
        return
    try:
        await _run_scan(context.bot)
    except Exception as e:
        logger.error(f"Skanerlashda xato: {e}")


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def do_HEAD(self):  # UptimeRobot HEAD so'rovi yuborishi mumkin
        self.send_response(200)
        self.end_headers()

    def log_message(self, format, *args):
        pass


def run_health_server():
    server = HTTPServer(("0.0.0.0", PORT), HealthHandler)
    server.serve_forever()


async def _post_init(app: Application):
    await app.bot.set_my_commands([
        BotCommand("start", "Botni ishga tushirish / menyu"),
        BotCommand("scan", "Bozorni hozir tekshirish"),
        BotCommand("check", "Bitta coinni tekshirish"),
        BotCommand("backtest", "Tarixiy sinov"),
        BotCommand("pump_stats", "Umumiy signal statistikasi"),
        BotCommand("report", "24 soat / 7 kunlik hisobot"),
        BotCommand("settings", "Joriy sozlamalar"),
    ])


def main():
    if not TELEGRAM_BOT_TOKEN:
        raise SystemExit(
            "XATO: TELEGRAM_BOT_TOKEN topilmadi! "
            "Render'da Environment Variables bo'limini tekshiring."
        )

    _apply_config()
    init_db()

    threading.Thread(target=run_health_server, daemon=True).start()

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).post_init(_post_init).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("scan", cmd_scan))
    app.add_handler(CommandHandler("check", cmd_check))
    app.add_handler(CommandHandler("backtest", cmd_backtest))
    app.add_handler(CommandHandler("pump_stats", cmd_pump_stats))
    app.add_handler(CommandHandler("report", cmd_report))
    app.add_handler(CommandHandler("settings", cmd_settings))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_menu_text))

    app.job_queue.run_repeating(background_scan, interval=SCAN_INTERVAL_SECONDS, first=10)
    app.job_queue.run_repeating(scheduled_evaluate, interval=EVAL_CHECK_INTERVAL_SECONDS, first=60)
    app.job_queue.run_repeating(self_ping, interval=SELF_PING_INTERVAL_SECONDS, first=300)
    app.job_queue.run_daily(
        scheduled_daily_report,
        time=datetime.time(hour=DAILY_REPORT_HOUR_UTC, minute=0),
    )
    app.job_queue.run_daily(
        scheduled_weekly_report,
        time=datetime.time(hour=DAILY_REPORT_HOUR_UTC, minute=0),
        days=(WEEKLY_REPORT_WEEKDAY,),
    )

    logger.info("Nozik Bot v3 (AMD) ishga tushdi.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
