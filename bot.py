"""
Nozik Bot v4 (AMD) - Asosiy Telegram interfeysi.
Strategiya: AMD (Accumulation -> Manipulation -> Distribution) + MSS/FVG + Bybit/Binance hajm.
Signal mantig'i signals/amd_volume.py da, bu fayl faqat Telegram bilan muloqot qatlami.
"""
import asyncio
import datetime
import logging
import os
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler

from telegram import Update, ReplyKeyboardMarkup, BotCommand
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

import config as C
from config import (
    TELEGRAM_BOT_TOKEN,
    ADMIN_CHAT_IDS,
    EVAL_CHECK_INTERVAL_SECONDS,
    DAILY_REPORT_HOUR_UTC,
    WEEKLY_REPORT_WEEKDAY,
    SELF_PING_INTERVAL_SECONDS,
    PORT,
)
from engine import db, tg, runtime_settings
from engine.evaluator import init_db, record_signal, evaluate_pending, get_stats, get_stats_since
from engine.volatility import get_btc_regime, conflicts_with_btc_regime
from signals import amd_volume as amd
from signals.amd_volume import CFG, bybit_klines, check
from engine.market_ctx import enrich_signal
from engine import features
from keepalive import start_self_ping
from signals import amd_swing, pump_detector

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)  # token URL'da chiqmasin
logger = logging.getLogger("nozik")

_scan_lock = asyncio.Lock()

MAIN_MENU = ReplyKeyboardMarkup(
    [
        ["🔍 Сканирование", "📈 Статистика"],
        ["📊 Отчёт", "⚙️ Настройки"],
    ],
    resize_keyboard=True,
)


def _is_admin(update: Update) -> bool:
    """Buyruqlar faqat ADMIN_CHAT_IDS ro'yxatidagi foydalanuvchilar uchun."""
    user = update.effective_user
    return user is not None and user.id in ADMIN_CHAT_IDS


def _all_tfs() -> list:
    return ["15m"] + list(amd_swing.ENABLED)


async def _send_signal(bot, s) -> int:
    """Qaytaradi: nechta chatga yetib bordi."""
    buf = await tg.make_chart(s.symbol, tg.to_dicts(s.candles), s.side.lower(),
                              tg.levels_of(s), s.tf, tg.meta_of(s, CFG))
    text = tg.format_signal(s, CFG)
    try:
        note = pump_detector.pre_note(s.symbol, s.side)    # shu coin bo'yicha yaqindagi "накопление"
    except Exception:
        note = ""
    if note:
        text += "\n" + note
    return await tg.broadcast(bot, ADMIN_CHAT_IDS, text, buf, parse_mode="HTML",
                              reply_markup=tg.live_markup(s.symbol, getattr(s, "sent_ts", None)),
                              track=(s.symbol, s.tf, getattr(s, "sent_ts", None)))


async def _run_scan(bot, force: bool = False):
    """Bozorni skanerlaydi, signallarni yozadi va yuboradi. (yuborildi, BTC filtri o'tkazdi, topildi)."""
    async with _scan_lock:
        sigs = await asyncio.to_thread(lambda: amd.scan(force=force))

        regime = "neutral"
        if C.USE_BTC_FILTER and sigs:
            try:
                regime = await asyncio.to_thread(get_btc_regime)
            except Exception:
                regime = "neutral"

        sent = skipped = 0
        for s in sigs:
            # BTC kuchli oqimiga qarshi altcoin signali ishonchsiz
            if C.USE_BTC_FILTER and conflicts_with_btc_regime(s.symbol, s.side, regime):
                logger.info(f"{s.symbol}: signal ({s.side}) BTC rejimiga ({regime}) zid - o'tkazib yuborildi")
                skipped += 1
                continue
            if not await asyncio.to_thread(enrich_signal, s, CFG["min_score"]):   # v6.9: OI/funding/L-S/taker
                skipped += 1
                continue
            s.sent_ts = int(time.time())     # avval yuboramiz; cooldown faqat YUBORILGAN signaldan boshlanadi
            if not await _send_signal(bot, s):
                logger.warning(f"{s.symbol}: signal yuborilmadi — bazaga yozilmadi")
                skipped += 1
                continue
            try:
                await asyncio.to_thread(record_signal, s, s.sent_ts)
            except Exception as e:
                logger.error(f"{s.symbol}: signalni bazaga yozishda xato: {e}")
            await asyncio.to_thread(features.record, s)               # v7.0
            sent += 1
        return sent, skipped, len(sigs)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update):
        uid = update.effective_user.id if update.effective_user else "?"
        await update.message.reply_text(
            "Этот бот приватный — доступ закрыт.\n"
            f"Ваш Telegram ID: {uid}\n"
            "Отправьте этот ID владельцу бота, чтобы он добавил вас."
        )
        return
    await update.message.reply_text(
        "🤖 <b>Nozik</b> · v7.0\n"
        "AMD 15m/1h/4h + Pump/Dump детектор\n\n"
        "🔍 /scan · /swing · /pd_scan — проверить рынок\n"
        "🎯 /check SYMBOL — разбор монеты\n"
        "📊 /report · /pd_stats — статистика\n"
        "⚙️ /params — параметры кнопками\n\n"
        "Сигнал приходит с графиком; подсказки по SL/TP и итог — ответом на него (сигнал закреплён).",
        reply_markup=MAIN_MENU, parse_mode="HTML",
    )


async def cmd_myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Доступна ВСЕМ: показывает Telegram ID, чтобы владелец мог добавить человека."""
    user = update.effective_user
    if user is None:
        return
    await update.message.reply_text(
        f"Ваш Telegram ID: {user.id}\n"
        "Отправьте его владельцу бота, чтобы получать сигналы."
    )


async def cmd_scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update):
        await update.message.reply_text("Нет доступа.")
        return
    if _scan_lock.locked():
        await update.message.reply_text("⏳ Сканирование уже идёт, подождите немного.")
        return
    await update.message.reply_text("🔍 Проверяю малые токены по AMD, подождите 1–2 минуты...")
    try:
        sent, skipped, found = await _run_scan(context.bot, force=True)
    except Exception as e:
        logger.error(f"Skanerlashda xato: {e}")
        await update.message.reply_text("❌ Ошибка при сканировании. Проверьте логи.")
        return
    text = f"📊 Сканирование завершено (проверено пар: {amd.LAST_SCAN['count']}).\n"
    if found == 0:
        text += "Сигналов, подходящих под условия AMD, пока нет."
    else:
        text += f"Отправлено сигналов: {sent}"
        if skipped:
            text += f"\nПропущено из-за противоположного тренда BTC: {skipped}"
    if amd.LAST_SCAN.get("skipped_stale"):
        text += f"\nПропущено (цена уже ушла от входа): {amd.LAST_SCAN['skipped_stale']}"
    await update.message.reply_text(text)


async def cmd_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update):
        return
    if not context.args:
        await update.message.reply_text("Укажите символ токена. Например: /check PEPEUSDT")
        return
    symbol = context.args[0].upper()
    await update.message.reply_text(f"🔍 Проверяю {symbol}...")
    res = await asyncio.to_thread(check, symbol)
    if not res:
        await update.message.reply_text("❌ Не удалось получить данные (проверьте символ).")
        return

    sig, st = res["signal"], res["state"]
    lines = [f"📊 Анализ {symbol}:\n"]
    levels = None
    direction = "neutral"
    if sig:
        direction = sig.side.lower()
        levels = tg.levels_of(sig)
        ok = sig.score >= CFG["min_score"]
        lines.append(f"Найден AMD-сетап: {sig.side}, скор {sig.score}/100")
        lines.append("✅ Проходит порог сигнала" if ok else
                     f"⚠️ Скор ниже порога ({CFG['min_score']}) — сигнал отправлен не будет")
        lines.append(f"Вход {tg.p(sig.entry)} | SL {tg.p(sig.sl)} | "
                     f"TP1 {tg.p(sig.tp1)} | TP2 {tg.p(sig.tp2)}")
        lines.append("")
        for r in sig.reasons:
            lines.append(tg.reason_line(r))
    else:
        lines.append("AMD-сетапа сейчас нет.")
        if st:
            levels = {"range_high": st["range_high"], "range_low": st["range_low"]}
            lines.append("")
            lines.append(f"Диапазон: {st['range_pct']:.1f}% " +
                         ("✅" if st["tight"] else "❌ (не подходит)"))
            lines.append(f"Объём диапазона: x{st['acc_ratio']:.2f} " +
                         ("✅ тихий" if st["quiet"] else "❌ не тихий"))
            lines.append(f"Объём последней свечи: x{st['last_vol_x']:.1f}")
            if st["tight"] and st["quiet"]:
                lines.append("📦 Идёт фаза Accumulation — следите за манипуляцией.")
        else:
            lines.append("Недостаточно истории для анализа.")
    caption = "\n".join(lines)

    buf = await tg.make_chart(symbol, tg.to_dicts(res["candles"]), direction, levels, "15m")
    await tg.reply_with_chart(update.message, caption, buf)


async def cmd_backtest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update):
        return
    if not context.args:
        await update.message.reply_text("Укажите символ токена. Например: /backtest PEPEUSDT")
        return
    symbol = context.args[0].upper()
    await update.message.reply_text(f"🧪 {symbol}: идёт бэктест (до 1–2 минут)...")
    r = await asyncio.to_thread(amd.backtest, symbol)
    if not r:
        await update.message.reply_text("❌ Не удалось получить данные (проверьте символ).")
        return
    days = r["bars"] * 15 / 60 / 24
    await update.message.reply_text(tg.format_backtest(r, CFG, days))


async def cmd_backtest_top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update):
        return
    n = C.BACKTEST_TOP_N
    await update.message.reply_text(
        f"🧪 Бэктест 15m по {n} самым ликвидным малым токенам. Это займёт несколько минут...")
    r = await asyncio.to_thread(lambda: amd.backtest_many(amd.universe()[:n]))
    if not r:
        await update.message.reply_text("❌ Не удалось получить данные.")
        return
    days = r["bars"] / max(r["symbols_ok"], 1) * 15 / 60 / 24
    await update.message.reply_text(tg.format_backtest(r, CFG, days))


async def cmd_pump_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update):
        return
    st = await asyncio.to_thread(get_stats, "15m")
    bs = st["by_status"]
    pf = st["profit_factor"] if st["profit_factor"] is not None else "—"
    text = (
        "📈 Статистика сигналов (15m, после издержек):\n\n"
        f"Закрытых сигналов: {st['total_closed']}\n"
        f"Прибыльных: {st['wins']} ({st['winrate_pct']}%)\n"
        f"Итого: {st['total_r']:+.2f}R (до издержек {st['gross_total_r']:+.2f}R)\n"
        f"Среднее: {st['avg_r']:+.2f}R | Profit factor: {pf}\n"
        f"Открытых (в ожидании): {st['pending']}\n\n"
        f"TP2: {bs.get('tp2', 0)} | TP1+BE: {bs.get('be', 0)} | "
        f"SL: {bs.get('sl', 0)} | По истечении срока: {bs.get('expired', 0)}"
    )
    if db.BACKEND != "postgres":
        text += "\n\n⚠️ База SQLite: на Render статистика стирается при каждом деплое. Задайте DATABASE_URL."
    await update.message.reply_text(text)


def amd_volume_last() -> str:
    from signals.amd_volume import LAST_SCAN
    d = LAST_SCAN.get('dur')
    return f"{d} с ({LAST_SCAN.get('count', 0)} монет, {LAST_SCAN.get('tf', '15m')})" if d else "—"


async def cmd_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update):
        return
    text = (
        "⚙️ <b>Настройки</b>\n\n"
        f"📈 AMD: скор ≥{CFG['min_score']} · риск ≤{CFG['max_risk_pct']}% · "
        f"оборот {CFG['min_turnover']/1e6:g}–{CFG['max_turnover']/1e6:g}M · "
        f"скан {C.SCAN_INTERVAL_SECONDS // 60} мин\n"
        f"🕐 Тренд: 15m→1h · "
        + " · ".join(f"{t}→{amd_swing.PROFILES[t]['htf_label']}" for t in amd_swing.ENABLED) + "\n"
        f"⏱ Скорость: AMD-скан {amd_volume_last()}; pump-скан {pump_detector.STATE.get('last_dur', '—')} с · потоков {C.SCAN_WORKERS}/{C.PUMP_WORKERS}\n"
        f"🛡 BTC-фильтр: {'да' if C.USE_BTC_FILTER else 'нет'} · cooldown {CFG['cooldown_sec'] // 3600} ч\n"
        f"💸 Издержки: {CFG['fee_pct']}% + {CFG['slip_pct']}% за сторону\n\n"
        + pump_detector.settings_text() + "\n"
        f"🗄 {db.BACKEND} · доступ: {len(ADMIN_CHAT_IDS)}\n"
        "Изменить: /params или /set ИМЯ ЗНАЧЕНИЕ"
    )
    await update.message.reply_text(text, parse_mode="HTML")


async def handle_menu_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update):
        return
    if await runtime_settings.handle_text(update, context):
        return
    text = update.message.text

    if text == "🔍 Сканирование":
        await cmd_scan(update, context)
    elif text == "📈 Статистика":
        await cmd_pump_stats(update, context)
    elif text == "📊 Отчёт":
        await cmd_report(update, context)
    elif text == "⚙️ Настройки":
        await cmd_settings(update, context)
    else:
        await update.message.reply_text(
            "Не понял. Выберите пункт в меню внизу или введите команду, например /check SYMBOL."
        )


def _format_period_report(title: str, seconds: int) -> str:
    total = get_stats_since(seconds, exclude_tf=pump_detector.TF)   # AMD — pump'siz
    lines = [f"{title}\n", f"Отправлено сигналов: {total['total_sent']}"]
    if total["total_closed"] > 0:
        pf = f" | PF {total['profit_factor']}" if total["profit_factor"] is not None else ""
        lines.append(f"Закрыто: {total['total_closed']} (после издержек)")
        lines.append(f"Прибыльных: {total['wins']} ({total['winrate_pct']}%)")
        lines.append(f"Итого: {total['total_r']:+.2f}R{pf}")
        lines.append(f"Среднее: {total['avg_r']:+.2f}R")
        if total["best"]:
            lines.append(f"Лучший: {total['best'][0]} ({total['best'][1]:+.2f}R)")
        if total["worst"]:
            lines.append(f"Худший: {total['worst'][0]} ({total['worst'][1]:+.2f}R)")
        parts = []
        for tf in _all_tfs():
            s = get_stats_since(seconds, tf)
            if s["total_closed"]:
                parts.append(f"{tf}: {s['total_closed']} сд., {s['total_r']:+.2f}R")
        if parts:
            lines.append("По таймфреймам: " + " | ".join(parts))
    else:
        lines.append("Закрытых сигналов пока нет.")
    pd = get_stats_since(seconds, pump_detector.TF)
    if pd["total_sent"]:
        lines.append("")
        lines.append(f"🚀 Pump/Dump (отдельно): отправлено {pd['total_sent']}"
                     + (f", закрыто {pd['total_closed']}, {pd['total_r']:+.2f}R"
                        if pd["total_closed"] else ""))
    return "\n".join(lines)


async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update):
        return
    text = await asyncio.to_thread(
        lambda: _format_period_report("📅 Последние 24 часа", 86400)
        + "\n\n" + _format_period_report("🗓 Последние 7 дней", 604800))
    await update.message.reply_text(text)


async def scheduled_daily_report(context: ContextTypes.DEFAULT_TYPE):
    text = await asyncio.to_thread(_format_period_report, "📅 Дневной отчёт", 86400)
    await tg.broadcast(context.bot, ADMIN_CHAT_IDS, text)


async def scheduled_weekly_report(context: ContextTypes.DEFAULT_TYPE):
    text = await asyncio.to_thread(_format_period_report, "🗓 Недельный отчёт", 604800)
    await tg.broadcast(context.bot, ADMIN_CHAT_IDS, text)


async def scheduled_evaluate(context: ContextTypes.DEFAULT_TYPE):
    """Ochiq 15m signallarni tekshiradi va natijasini xabar qiladi."""
    events: list = []
    try:
        closed = await asyncio.to_thread(
            evaluate_pending, bybit_klines, "15m", CFG["tf"], CFG["expire_candles"], events
        )
    except Exception as e:
        logger.error(f"Signallarni baholashda xato: {e}")
        return
    for ev in events:                 # TP1 olindi: SL ni breakeven'ga surish ko'rsatmasi (asl signalga reply)
        await tg.notify(context.bot, ADMIN_CHAT_IDS, tg.progress_text(ev, ev["tf"]),
                        ev["symbol"], ev["tf"], ev.get("sent_ts"))
    for r in closed:
        await tg.notify(context.bot, ADMIN_CHAT_IDS, tg.result_text(r, r["tf"]),
                        r["symbol"], r["tf"], r.get("sent_ts"), unpin=True)


async def background_scan(context: ContextTypes.DEFAULT_TYPE):
    if _scan_lock.locked():
        return
    try:
        sent, skipped, found = await _run_scan(context.bot)
        logger.info(f"Skan: topildi={found}, yuborildi={sent}, o'tkazildi={skipped}")
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
    """Health-check + Telegram Mini App (jonli grafik) — BIR portda (webapp/server.py)."""
    from webapp.server import run_server
    run_server(PORT)


async def _post_init(app: Application):
    if C.USE_LIQ_STREAM:                       # v6.9: likvidatsiya oqimi (fon vazifa)
        try:
            from engine import liq
            task = asyncio.create_task(liq.run())

            def _liq_done(t):
                if not t.cancelled() and t.exception():
                    logger.error(f"Likvidatsiya oqimi to'xtadi: {t.exception()}")
            task.add_done_callback(_liq_done)
            app.bot_data["liq_task"] = task
        except Exception as e:                  # bot baribir ishga tushsin
            logger.error(f"Likvidatsiya oqimi ishga tushmadi: {e}")
    await app.bot.set_my_commands([
        BotCommand("scan", "Скан рынка (AMD 15m)"),
        BotCommand("swing", "Скан 1h/4h"),
        BotCommand("pd_scan", "Скан Pump/Dump"),
        BotCommand("check", "Разбор одной монеты"),
        BotCommand("report", "Отчёт 24ч / 7 дней"),
        BotCommand("pd_stats", "Статистика Pump/Dump"),
        BotCommand("features", "Что реально работает (по сделкам)"),
        BotCommand("params", "Параметры кнопками"),
        BotCommand("settings", "Текущие настройки"),
    ])


CARD_VERSION = "v7.0-RU"


def main():
    logger.info("Карточка сигнала: %s (русский интерфейс)", CARD_VERSION)
    if not TELEGRAM_BOT_TOKEN:
        raise SystemExit(
            "XATO: TELEGRAM_BOT_TOKEN topilmadi! "
            "Render'da Environment Variables bo'limini tekshiring."
        )

    init_db()
    runtime_settings.init()   # v6.7: Telegram'dan saqlangan parametrlarni qo'llash (job'lardan OLDIN)
    if db.BACKEND != "postgres" and os.environ.get("RENDER"):
        logger.warning("SQLite + Render: statistika va cooldown har deploy'da o'chadi. "
                       "DATABASE_URL (PostgreSQL) o'rnating.")

    threading.Thread(target=run_health_server, daemon=True).start()

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).post_init(_post_init).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("myid", cmd_myid))
    app.add_handler(CommandHandler("scan", cmd_scan))
    app.add_handler(CommandHandler("check", cmd_check))
    app.add_handler(CommandHandler("backtest", cmd_backtest))
    app.add_handler(CommandHandler("backtest_top", cmd_backtest_top))
    app.add_handler(CommandHandler("pump_stats", cmd_pump_stats))
    app.add_handler(CommandHandler("report", cmd_report))
    app.add_handler(CommandHandler("settings", cmd_settings))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_menu_text))

    runtime_settings.register(app)  # /params, /set, /reset_param
    features.register(app)          # v7.0: /features
    amd_swing.register(app)  # 1h (trend 4h) va 4h (trend 1d) AMD moduli
    pump_detector.register(app)  # pump/dump detektori (AMD'dan alohida)

    # Скан выравнивается по часам: :00, :05, :10 ... (+15 с после закрытия свечи).
    # Bir xil yopilgan sham qayta tahlil qilinmaydi (amd.scan ichida).
    first_scan = C.SCAN_INTERVAL_SECONDS - (time.time() % C.SCAN_INTERVAL_SECONDS) + 15
    app.job_queue.run_repeating(background_scan, interval=C.SCAN_INTERVAL_SECONDS, first=first_scan,
                                  name="background_scan")
    app.job_queue.run_repeating(scheduled_evaluate, interval=EVAL_CHECK_INTERVAL_SECONDS, first=60,
                                  name="evaluate")
    start_self_ping()
    app.job_queue.run_daily(
        scheduled_daily_report,
        time=datetime.time(hour=DAILY_REPORT_HOUR_UTC, minute=0),
    )
    app.job_queue.run_daily(
        scheduled_weekly_report,
        time=datetime.time(hour=DAILY_REPORT_HOUR_UTC, minute=0),
        days=(WEEKLY_REPORT_WEEKDAY,),
    )

    logger.info("Nozik Bot v4 (AMD) ishga tushdi.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
