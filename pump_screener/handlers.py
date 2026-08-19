"""
Nozik botga ulanadigan Router. main.py da:

    from pump_screener.handlers import pump_router, pump_watcher
    dp.include_router(pump_router)
    asyncio.create_task(pump_watcher(bot))

qo'shish kifoya.
"""

import asyncio
import logging

import aiohttp
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message

from . import db, config
from .bybit_client import BybitClient
from .detector import scan_market

logger = logging.getLogger("pump.handlers")

pump_router = Router(name="pump_screener")


@pump_router.message(Command("pump"))
async def cmd_pump(message: Message):
    await message.answer("🔍 Bybit bozori skanerlanmoqda, biroz kuting...")
    async with BybitClient() as client:
        try:
            signals = await scan_market(client)
        except Exception as e:
            logger.exception("Skanerlashda xato")
            await message.answer(f"❌ Xatolik: {e}")
            return

    if not signals:
        await message.answer("Hozircha pump/dump signali topilmadi.")
        return

    top = signals[: config.SCREENER_TOP_N]
    text = "📊 <b>Pump Screener — Bybit USDT Perp</b>\n\n"
    text += "\n\n".join(s.format() for s in top)
    await message.answer(text, parse_mode="HTML")


@pump_router.message(Command("pump_on"))
async def cmd_pump_on(message: Message):
    await db.add_subscriber(message.from_user.id)
    await message.answer(
        f"✅ Avtomatik pump alertlar yoqildi.\n"
        f"Har {config.SCAN_INTERVAL_SECONDS // 60} daqiqada bozor tekshiriladi."
    )


@pump_router.message(Command("pump_off"))
async def cmd_pump_off(message: Message):
    await db.remove_subscriber(message.from_user.id)
    await message.answer("🔕 Avtomatik pump alertlar o'chirildi.")


@pump_router.message(Command("pump_stats"))
async def cmd_pump_stats(message: Message):
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
    await message.answer(text, parse_mode="HTML")


async def pump_watcher(bot):
    """Fon vazifasi: doimiy skanerlab, obunachilarga yangi signallarni yuboradi."""
    await db.init_db()
    logger.info("Pump watcher ishga tushdi")

    while True:
        try:
            async with BybitClient() as client:
                signals = await scan_market(client)

            # Avtomatik alertlarga faqat TASDIQLANGAN (5m+15m mos kelgan) signallar boradi —
            # "ERTA" signallar shovqinni ko'paytirmasligi uchun faqat /pump buyrug'ida ko'rinadi
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
            logger.exception(f"pump_watcher xatosi: {e}")

        await asyncio.sleep(config.SCAN_INTERVAL_SECONDS)


async def outcome_evaluator(bot=None):
    """
    Fon vazifasi: har bir yuborilgan signaldan OUTCOME_CHECK_MINUTES daqiqa o'tgach,
    narx haqiqatan davom etganmi yoki qaytganmi tekshiradi va bazaga yozadi.
    Shu orqali /pump_stats real aniqlik foizini ko'rsata oladi.
    """
    logger.info("Outcome evaluator ishga tushdi")
    while True:
        try:
            pending = await db.get_pending_outcomes(config.OUTCOME_CHECK_MINUTES)
            if pending:
                async with BybitClient() as client:
                    tickers = await client.get_tickers()
                for item in pending:
                    ticker = tickers.get(item["symbol"])
                    if not ticker:
                        continue
                    price_after = float(ticker["lastPrice"])
                    price_before = item["price_at_signal"]
                    change_pct = (price_after - price_before) / price_before * 100
                    if item["direction"] == "up":
                        signed_change = change_pct
                    else:
                        signed_change = -change_pct

                    if signed_change >= config.OUTCOME_CONTINUE_THRESHOLD:
                        result = "continued"
                    elif signed_change <= config.OUTCOME_REVERSE_THRESHOLD:
                        result = "reversed"
                    else:
                        result = "flat"

                    await db.update_outcome(item["id"], price_after, result)

        except Exception as e:
            logger.exception(f"outcome_evaluator xatosi: {e}")

        await asyncio.sleep(120)  # har 2 daqiqada tekshirib turadi (kutayotganlar bormi)
