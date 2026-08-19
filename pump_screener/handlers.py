"""
UltimateForexSignalBot.py ga ulanadigan modul — python-telegram-bot (PTB) kutubxonasi
uchun yozilgan (Application / CommandHandler / job_queue asosida, aiogram EMAS).

Integratsiya uchun UltimateForexSignalBot.py fayliga qo'shish kerak bo'lgan qismlar
README.md da batafsil yozilgan.
"""

import logging

from telegram import Update
from telegram.ext import ContextTypes

from . import db, config
from .bybit_client import BybitClient
from .detector import scan_market

logger = logging.getLogger("pump.handlers")


# ============ Buyruqlar (CommandHandler bilan ro'yxatdan o'tkaziladi) ============

async def cmd_pump(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 Bybit bozori skanerlanmoqda, biroz kuting...")
    async with BybitClient() as client:
        try:
            signals = await scan_market(client)
        except Exception as e:
            logger.exception("Skanerlashda xato")
            await update.message.reply_text(f"❌ Xatolik: {e}")
            return

    if not signals:
        await update.message.reply_text("Hozircha pump/dump signali topilmadi.")
        return

    top = signals[: config.SCREENER_TOP_N]
    text = "📊 <b>Pump Screener — Bybit USDT Perp</b>\n\n"
    text += "\n\n".join(s.format() for s in top)
    await update.message.reply_text(text, parse_mode="HTML")


async def cmd_pump_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await db.add_subscriber(update.effective_user.id)
    await update.message.reply_text(
        f"✅ Avtomatik pump alertlar yoqildi.\n"
        f"Har {config.SCAN_INTERVAL_SECONDS // 60} daqiqada bozor tekshiriladi."
    )


async def cmd_pump_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await db.remove_subscriber(update.effective_user.id)
    await update.message.reply_text("🔕 Avtomatik pump alertlar o'chirildi.")


async def cmd_pump_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stats = await db.get_stats()

    def _fmt(counts: dict) -> str:
        continued = counts.get("continued", 0)
        reversed_ = counts.get("reversed", 0)
        flat = counts.get("flat", 0)
        total = continued + reversed_ + flat
        if total == 0:
            return "Hali yetarli ma'lumot yo'q."
        win_rate = continued / total * 100
        return (
            f"Jami: {total} ta signal\n"
            f"   ✅ Davom etdi: {continued} ({continued/total*100:.0f}%)\n"
            f"   ❌ Qaytdi: {reversed_} ({reversed_/total*100:.0f}%)\n"
            f"   ➖ O'zgarmadi: {flat} ({flat/total*100:.0f}%)\n"
            f"   <b>Aniqlik: {win_rate:.1f}%</b>"
        )

    text = (
        "📈 <b>Pump Screener — real aniqlik statistikasi</b>\n\n"
        f"<b>Oxirgi 7 kun:</b>\n{_fmt(stats['last_7d'])}\n\n"
        f"<b>Barcha vaqt:</b>\n{_fmt(stats['all_time'])}\n\n"
        f"<i>\"Davom etdi\" — signaldan {config.OUTCOME_CHECK_MINUTES} daq keyin narx "
        f"o'sha yo'nalishda {config.OUTCOME_CONTINUE_THRESHOLD}%+ harakatlangan.</i>"
    )
    await update.message.reply_text(text, parse_mode="HTML")


# ============ Fon vazifalari (app.job_queue.run_repeating bilan ulanadi) ============

async def pump_watcher_job(context: ContextTypes.DEFAULT_TYPE):
    """
    job_queue orqali har SCAN_INTERVAL_SECONDS da chaqiriladi.
    Bozorni skanerlaydi va TASDIQLANGAN signallarni obunachilarga yuboradi.
    """
    bot = context.bot
    try:
        async with BybitClient() as client:
            signals = await scan_market(client)

        # Faqat TASDIQLANGAN (5m+15m mos kelgan) signallar avtomatik yuboriladi —
        # "ERTA" signallar shovqin qilmasligi uchun faqat /pump buyrug'ida ko'rinadi
        new_signals = []
        for s in signals:
            if not s.confirmed:
                continue
            if not await db.is_on_cooldown(s.symbol, config.ALERT_COOLDOWN_MINUTES):
                new_signals.append(s)
                await db.record_alert(s.symbol)
                direction = "up" if s.price_change_pct > 0 else "down"
                await db.record_signal(s.symbol, direction, s.last_price)

        if new_signals:
            subscribers = await db.get_subscribers()
            for sig in new_signals[: config.SCREENER_TOP_N]:
                text = "🚨 <b>Yangi signal!</b>\n\n" + sig.format()
                for user_id in subscribers:
                    try:
                        await bot.send_message(user_id, text, parse_mode="HTML")
                    except Exception as e:
                        logger.warning(f"{user_id} ga yuborilmadi: {e}")

    except Exception as e:
        logger.exception(f"pump_watcher_job xatosi: {e}")


async def outcome_evaluator_job(context: ContextTypes.DEFAULT_TYPE):
    """
    job_queue orqali har 2 daqiqada chaqiriladi.
    Yuborilgan signallardan OUTCOME_CHECK_MINUTES o'tganlarini tekshiradi:
    narx davom etdimi, qaytdimi — /pump_stats shu ma'lumotdan foydalanadi.
    """
    try:
        pending = await db.get_pending_outcomes(config.OUTCOME_CHECK_MINUTES)
        if not pending:
            return

        async with BybitClient() as client:
            tickers = await client.get_tickers()

        for item in pending:
            ticker = tickers.get(item["symbol"])
            if not ticker:
                continue
            price_after = float(ticker["lastPrice"])
            price_before = item["price_at_signal"]
            change_pct = (price_after - price_before) / price_before * 100
            signed_change = change_pct if item["direction"] == "up" else -change_pct

            if signed_change >= config.OUTCOME_CONTINUE_THRESHOLD:
                result = "continued"
            elif signed_change <= config.OUTCOME_REVERSE_THRESHOLD:
                result = "reversed"
            else:
                result = "flat"

            await db.update_outcome(item["id"], price_after, result)

    except Exception as e:
        logger.exception(f"outcome_evaluator_job xatosi: {e}")


async def pump_db_init(context: ContextTypes.DEFAULT_TYPE = None):
    """Bazani (pump.db) tayyorlaydi. post_init callback sifatida chaqiriladi."""
    await db.init_db()
    logger.info("Pump screener bazasi tayyor")
