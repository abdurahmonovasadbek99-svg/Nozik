"""
Nozik Bot v2 - Asosiy Telegram interfeysi.
Signal generatsiya mantig'i engine/ va signals/ papkalarida,
bu fayl faqat Telegram bilan muloqot qatlami.
"""
import logging
import threading
import time
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from config import TELEGRAM_BOT_TOKEN, ADMIN_CHAT_IDS, WATCHLIST, ALERT_THRESHOLD, SCAN_INTERVAL_SECONDS, PORT, SELF_URL
from engine.aggregator import analyze_symbol, scan_watchlist
from engine.evaluator import init_db, record_signal, evaluate_pending, get_stats

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("nozik")

_last_alert_time = {}
ALERT_COOLDOWN_SECONDS = 3600


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 Nozik Bot v2 ishga tushdi.\n\n"
        "Buyruqlar:\n"
        "/scan - watchlistni hoziroq tekshirish\n"
        "/check <SYMBOL> - bitta coinni tekshirish (masalan /check BTCUSDT)\n"
        "/pump_stats - signal aniqligi statistikasi\n"
        "/watchlist - kuzatilayotgan coinlar ro'yxati"
    )


async def cmd_scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 Watchlist tekshirilmoqda, biroz kuting...")
    results = scan_watchlist(WATCHLIST)
    lines = ["📊 Skanerlash natijalari:\n"]
    for r in results[:10]:
        emoji = "🟢" if r["direction"] == "long" else "🔴" if r["direction"] == "short" else "⚪"
        lines.append(f"{emoji} {r['symbol']}: {r['confluence_score']}/100 ({r['direction']})")
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
    await update.message.reply_text("👀 Kuzatilayotgan coinlar:\n" + ", ".join(WATCHLIST))


async def background_scan(context: ContextTypes.DEFAULT_TYPE):
    """JobQueue orqali muntazam ishga tushadi."""
    results = scan_watchlist(WATCHLIST)
    now = time.time()

    for r in results:
        symbol = r["symbol"]
        score = r["confluence_score"]
        direction = r["direction"]

        if score < ALERT_THRESHOLD or direction == "neutral":
            continue

        last_sent = _last_alert_time.get(symbol, 0)
        if now - last_sent < ALERT_COOLDOWN_SECONDS:
            continue

        _last_alert_time[symbol] = now

        price = r["signals"]["ict_smc"]["details"].get("order_block", {})
        price_value = price.get("high") if isinstance(price, dict) and price else 0

        record_signal(symbol, direction, score, price_value or 0)

        emoji = "🟢🚀" if direction == "long" else "🔴📉"
        text = (
            f"{emoji} SIGNAL: {symbol}\n\n"
            f"Yo'nalish: {direction.upper()}\n"
            f"Confluence score: {score}/100\n\n"
        )
        for name, sig in r["signals"].items():
            text += f"• {name}: {sig['score']}/100\n"

        for chat_id in ADMIN_CHAT_IDS:
            try:
                await context.bot.send_message(chat_id=chat_id, text=text)
            except Exception as e:
                logger.error(f"Xabar yuborishda xato ({chat_id}): {e}")


async def self_ping(context: ContextTypes.DEFAULT_TYPE):
    """Render'ni uxlab qolishdan saqlash uchun o'z-o'ziga so'rov yuboradi."""
    if not SELF_URL:
        return
    try:
        requests.get(SELF_URL, timeout=10)
        logger.info("Self-ping muvaffaqiyatli")
    except Exception as e:
        logger.error(f"Self-ping xatosi: {e}")


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


def main():
    init_db()

    threading.Thread(target=run_health_server, daemon=True).start()

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("scan", cmd_scan))
    app.add_handler(CommandHandler("check", cmd_check))
    app.add_handler(CommandHandler("pump_stats", cmd_pump_stats))
    app.add_handler(CommandHandler("watchlist", cmd_watchlist))

    app.job_queue.run_repeating(background_scan, interval=SCAN_INTERVAL_SECONDS, first=10)
    app.job_queue.run_repeating(self_ping, interval=600, first=60)

    logger.info("Nozik Bot v2 ishga tushdi.")
    app.run_polling()


if __name__ == "__main__":
    main()

