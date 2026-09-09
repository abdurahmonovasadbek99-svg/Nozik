"""
Nozik Bot v2 - Asosiy Telegram interfeysi.
Signal generatsiya mantig'i engine/ va signals/ papkalarida,
bu fayl faqat Telegram bilan muloqot qatlami.
"""
import datetime
import logging
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler

from telegram import Update, ReplyKeyboardMarkup, BotCommand
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

from config import (
    TELEGRAM_BOT_TOKEN,
    ADMIN_CHAT_IDS,
    WATCHLIST,
    ALERT_THRESHOLD,
    STRONG_COMBO_THRESHOLD,
    SCAN_INTERVAL_SECONDS,
    PORT,
    MIN_SIGNAL_AGREEMENT,
    EVAL_AFTER_SECONDS,
    EVAL_CHECK_INTERVAL_SECONDS,
    DAILY_REPORT_HOUR_UTC,
    WEEKLY_REPORT_WEEKDAY,
    SELF_PING_INTERVAL_SECONDS,
)
from engine.aggregator import analyze_symbol, scan_watchlist
from engine.evaluator import init_db, record_signal, evaluate_pending, get_stats, get_stats_since
from signals.universe import get_candidates, get_current_price
from keepalive import self_ping

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("nozik")

_last_alert_time = {}
ALERT_COOLDOWN_SECONDS = 3600

MAIN_MENU = ReplyKeyboardMarkup(
    [
        ["🔍 Skanerlash", "📈 Statistika"],
        ["📊 Hisobot", "👀 Watchlist"],
    ],
    resize_keyboard=True,
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 Nozik Bot v2 ishga tushdi.\n\n"
        "Endi faqat watchlist emas — Bybit'dagi BARCHA USDT juftliklari "
        "(kichik/alt tokenlar ham) muntazam skanerlanadi.\n\n"
        "Pastdagi menyudan foydalaning yoki buyruqlarni yozing:\n"
        "/scan - hozir butun bozorni tekshirish\n"
        "/check <SYMBOL> - bitta coinni tekshirish (masalan /check BTCUSDT)\n"
        "/pump_stats - umumiy signal aniqligi statistikasi\n"
        "/report - so'nggi 24 soat va 7 kunlik hisobot\n"
        "/watchlist - doim kuzatiladigan asosiy coinlar ro'yxati",
        reply_markup=MAIN_MENU,
    )


async def cmd_scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 Butun bozor (kichik tokenlar ham) tekshirilmoqda, biroz kuting...")
    candidates = get_candidates()
    results = scan_watchlist(candidates)
    lines = [f"📊 Skanerlash natijalari ({len(candidates)} juftlik tekshirildi):\n"]
    for r in results[:10]:
        emoji = "🟢" if r["direction"] == "long" else "🔴" if r["direction"] == "short" else "⚪"
        lines.append(
            f"{emoji} {r['symbol']}: {r['confluence_score']}/100 "
            f"({r['direction']}, {r['agreement_count']}/{r['signal_count']} modul rozi)"
        )
    await update.message.reply_text("\n".join(lines))


async def cmd_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Iltimos, coin belgisini kiriting. Masalan: /check BTCUSDT")
        return
    symbol = context.args[0].upper()
    await update.message.reply_text(f"🔍 {symbol} tekshirilmoqda...")
    result = analyze_symbol(symbol)

    lines = [f"📊 {symbol} tahlili:\n", f"Umumiy score: {result['confluence_score']}/100 ({result['direction']})\n"]
    for name, sig in result["signals"].items():
        lines.append(f"• {name}: {sig['score']}/100 ({sig['direction']})")
    await update.message.reply_text("\n".join(lines))


async def cmd_pump_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stats = get_stats()
    text = (
        "📈 Signal statistikasi:\n\n"
        f"Baholangan signallar: {stats['total_evaluated']}\n"
        f"Muvaffaqiyatli: {stats['successful']}\n"
        f"Aniqlik: {stats['accuracy_pct']}%\n"
        f"Kutilayotgan: {stats['pending']}\n"
        f"O'rtacha o'zgarish: {stats['avg_pct_change']}%"
    )
    await update.message.reply_text(text)


async def cmd_watchlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👀 Doim kuzatiladigan asosiy coinlar:\n" + ", ".join(WATCHLIST))


async def handle_menu_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if text == "🔍 Skanerlash":
        await cmd_scan(update, context)
    elif text == "📈 Statistika":
        await cmd_pump_stats(update, context)
    elif text == "📊 Hisobot":
        await cmd_report(update, context)
    elif text == "👀 Watchlist":
        await cmd_watchlist(update, context)
    else:
        await update.message.reply_text(
            "Tushunmadim. Pastdagi menyudan tanlang yoki /check SYMBOL kabi buyruq yozing."
        )


def _format_period_report(title: str, stats: dict) -> str:
    lines = [f"{title}\n", f"Yuborilgan signallar: {stats['total_sent']}"]
    if stats["total_evaluated"] > 0:
        lines.append(f"Baholangan: {stats['total_evaluated']}")
        lines.append(f"Aniqlik: {stats['accuracy_pct']}%")
        lines.append(f"O'rtacha o'zgarish: {stats['avg_pct_change']}%")
        if stats["best"]:
            lines.append(f"Eng yaxshi: {stats['best']['symbol']} ({stats['best']['pct_change']}%)")
        if stats["worst"]:
            lines.append(f"Eng yomon: {stats['worst']['symbol']} ({stats['worst']['pct_change']}%)")
    else:
        lines.append("Hali baholangan signal yo'q.")
    return "\n".join(lines)


async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
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


async def scheduled_evaluate(context: ContextTypes.DEFAULT_TYPE):
    try:
        evaluate_pending(get_current_price, eval_after_seconds=EVAL_AFTER_SECONDS)
    except Exception as e:
        logger.error(f"Signallarni baholashda xato: {e}")


async def background_scan(context: ContextTypes.DEFAULT_TYPE):
    candidates = get_candidates()
    results = scan_watchlist(candidates)
    now = time.time()

    for r in results:
        symbol = r["symbol"]
        score = r["confluence_score"]
        direction = r["direction"]
        agreement = r["agreement_count"]

        combo = r["signals"].get("volume_bos_combo", {})
        combo_score = combo.get("score", 0)
        combo_direction = combo.get("direction", "neutral")
        strong_combo = combo_score >= STRONG_COMBO_THRESHOLD and combo_direction in ("long", "short")

        normal_trigger = (
            score >= ALERT_THRESHOLD
            and direction != "neutral"
            and agreement >= MIN_SIGNAL_AGREEMENT
        )

        if not normal_trigger and not strong_combo:
            continue

        trigger_reason = None
        if not normal_trigger and strong_combo:
            direction = combo_direction
            score = combo_score
            trigger_reason = "🔥 Kuchli hajm+BOS tasdiqlash (alohida trigger)"

        last_sent = _last_alert_time.get(symbol, 0)
        if now - last_sent < ALERT_COOLDOWN_SECONDS:
            continue

        _last_alert_time[symbol] = now

        try:
            price_value = get_current_price(symbol)
        except Exception:
            price_value = 0

        record_signal(symbol, direction, score, price_value or 0)

        emoji = "🟢🚀" if direction == "long" else "🔴📉"
        text = (
            f"{emoji} SIGNAL: {symbol}\n\n"
            + (f"{trigger_reason}\n\n" if trigger_reason else "")
            + f"Yo'nalish: {direction.upper()}\n"
            f"Confluence score: {score}/100 ({agreement}/{r['signal_count']} modul rozi)\n"
            f"Narx: {price_value}\n\n"
        )
        for name, sig in r["signals"].items():
            text += f"• {name}: {sig['score']}/100 ({sig['direction']})\n"

        for chat_id in ADMIN_CHAT_IDS:
            try:
                await context.bot.send_message(chat_id=chat_id, text=text)
            except Exception as e:
                logger.error(f"Xabar yuborishda xato ({chat_id}): {e}")


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, format, *args):
        pass


def run_health_server():
    server = HTTPServer(("0.0.0.0", PORT), HealthHandler)
    server.serve_forever()


async def _post_init(app: Application):
    await app.bot.set_my_commands([
        BotCommand("start", "Botni ishga tushirish / menyu"),
        BotCommand("scan", "Butun bozorni hozir tekshirish"),
        BotCommand("check", "Bitta coinni tekshirish"),
        BotCommand("pump_stats", "Umumiy signal aniqligi"),
        BotCommand("report", "24 soat / 7 kunlik hisobot"),
        BotCommand("watchlist", "Asosiy kuzatiladigan coinlar"),
    ])


def main():
    init_db()

    threading.Thread(target=run_health_server, daemon=True).start()

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).post_init(_post_init).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("scan", cmd_scan))
    app.add_handler(CommandHandler("check", cmd_check))
    app.add_handler(CommandHandler("pump_stats", cmd_pump_stats))
    app.add_handler(CommandHandler("report", cmd_report))
    app.add_handler(CommandHandler("watchlist", cmd_watchlist))
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

    logger.info("Nozik Bot v2 ishga tushdi.")
    app.run_polling()


if __name__ == "__main__":
    main()
