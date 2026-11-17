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
    SCAN_INTERVAL_SECONDS,
    USE_BTC_FILTER,
    EVAL_CHECK_INTERVAL_SECONDS,
    DAILY_REPORT_HOUR_UTC,
    WEEKLY_REPORT_WEEKDAY,
    SELF_PING_INTERVAL_SECONDS,
    PORT,
)
from engine import db, tg
from engine.evaluator import init_db, record_signal, evaluate_pending, get_stats, get_stats_since
from engine.volatility import get_btc_regime, conflicts_with_btc_regime
from signals import amd_volume as amd
from signals.amd_volume import CFG, bybit_klines, check
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


async def _send_signal(bot, s):
    buf = await tg.make_chart(s.symbol, tg.to_dicts(s.candles), s.side.lower(),
                              tg.levels_of(s), s.tf, tg.meta_of(s, CFG))
    await tg.broadcast(bot, ADMIN_CHAT_IDS, tg.format_signal(s, CFG), buf, parse_mode="HTML")


async def _run_scan(bot, force: bool = False):
    """Bozorni skanerlaydi, signallarni yozadi va yuboradi. (yuborildi, BTC filtri o'tkazdi, topildi)."""
    async with _scan_lock:
        sigs = await asyncio.to_thread(lambda: amd.scan(force=force))

        regime = "neutral"
        if USE_BTC_FILTER and sigs:
            try:
                regime = await asyncio.to_thread(get_btc_regime)
            except Exception:
                regime = "neutral"

        sent = skipped = 0
        for s in sigs:
            # BTC kuchli oqimiga qarshi altcoin signali ishonchsiz
            if USE_BTC_FILTER and conflicts_with_btc_regime(s.symbol, s.side, regime):
                logger.info(f"{s.symbol}: signal ({s.side}) BTC rejimiga ({regime}) zid - o'tkazib yuborildi")
                skipped += 1
                continue
            await asyncio.to_thread(record_signal, s)   # cooldown faqat YUBORILGAN signaldan boshlanadi
            await _send_signal(bot, s)
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
        "🤖 Nozik Bot v4 запущен.\n\n"
        "Стратегия: AMD (Accumulation → Manipulation → Distribution) + MSS/FVG + "
        "объёмы Bybit/Binance. Основной фокус — малокапитализированные токены.\n\n"
        "Сигналы по трём уровням:\n"
        "• 15m (тренд-фильтр 1h)\n"
        "• 1h (тренд-фильтр 4h)\n"
        "• 4h (тренд-фильтр 1d)\n\n"
        "Команды:\n"
        "/scan — проверить рынок (15m)\n"
        "/swing — проверить рынок (1h и 4h)\n"
        "/check <SYMBOL> — один токен, 15m (например /check PEPEUSDT)\n"
        "/swing_check <SYMBOL> 1h|4h — один токен, 1h/4h\n"
        "/backtest <SYMBOL> — бэктест 15m (с комиссиями)\n"
        "/backtest_top — бэктест 15m по топ-токенам (надёжнее)\n"
        "/swing_backtest <SYMBOL> 1h|4h — бэктест 1h/4h\n"
        "/swing_backtest_top 1h|4h — бэктест 1h/4h по топ-токенам\n"
        "/pump_stats — статистика 15m\n"
        "/swing_stats — статистика 1h/4h\n"
        "/pd_scan — проверить резкие движения (pump/dump)\n"
        "/pd_check <SYMBOL> — pump/dump-статус одной монеты\n"
        "/pd_stats — статистика детектора pump/dump\n"
        "/pd_backtest [SYMBOL] — бэктест pump/dump\n"
        "/report — отчёт за 24 часа и 7 дней\n"
        "/settings — текущие настройки\n"
        "/myid — ваш Telegram ID",
        reply_markup=MAIN_MENU,
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


async def cmd_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update):
        return
    text = (
        "⚙️ Текущие настройки:\n\n"
        "Стратегия: AMD + MSS/FVG + объёмы Bybit/Binance\n"
        "Таймфрейм 15m: тренд-фильтр 1h\n"
        f"Таймфреймы {', '.join(amd_swing.ENABLED)}: тренд-фильтр "
        f"{', '.join(amd_swing.PROFILES[t]['htf_label'] for t in amd_swing.ENABLED)}\n"
        f"Минимальный скор: {CFG['min_score']}/100\n"
        f"MSS/FVG обязательны: {'да' if CFG['require_structure'] else 'нет (только скор)'}\n"
        f"Макс. риск: {CFG['max_risk_pct']}%\n"
        f"Фильтр рынка: оборот за 24ч {CFG['min_turnover']/1e6:g}M — {CFG['max_turnover']/1e6:g}M USDT "
        f"(макс. {CFG['max_symbols']} пар)\n"
        f"Сканирование 15m: каждые {SCAN_INTERVAL_SECONDS // 60} мин (по новой свече)\n"
        f"Cooldown: {CFG['cooldown_sec'] // 3600} ч\n"
        f"BTC-фильтр: {'включён' if USE_BTC_FILTER else 'выключен'}\n"
        f"Не догонять цену: макс. {CFG['max_chase_r']}R от входа\n"
        f"Издержки: комиссия {CFG['fee_pct']}% + проскальзывание {CFG['slip_pct']}% за сторону\n"
        f"Срок сигнала 15m: {CFG['expire_candles'] * 15 // 60} ч\n"
        f"База данных: {db.BACKEND}\n"
        f"Пользователей с доступом: {len(ADMIN_CHAT_IDS)}\n\n"
        + pump_detector.settings_text() + "\n"
        "Изменить: Render → Environment Variables."
    )
    await update.message.reply_text(text)


async def handle_menu_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update):
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
    try:
        closed = await asyncio.to_thread(
            evaluate_pending, bybit_klines, "15m", CFG["tf"], CFG["expire_candles"]
        )
    except Exception as e:
        logger.error(f"Signallarni baholashda xato: {e}")
        return
    for r in closed:
        text = (f"{tg.RESULT_TEXT.get(r['status'], r['status'])}\n"
                f"{r['symbol']} {r['side']}: {r['result_r']:+.2f}R")
        await tg.broadcast(context.bot, ADMIN_CHAT_IDS, text)


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
    server = HTTPServer(("0.0.0.0", PORT), HealthHandler)
    server.serve_forever()


async def _post_init(app: Application):
    await app.bot.set_my_commands([
        BotCommand("start", "Запуск / меню"),
        BotCommand("scan", "Проверить рынок (15m)"),
        BotCommand("check", "Проверить один токен"),
        BotCommand("backtest", "Бэктест (15m)"),
        BotCommand("backtest_top", "Бэктест 15m по топ-токенам"),
        BotCommand("pump_stats", "Статистика сигналов 15m"),
        BotCommand("report", "Отчёт за 24ч / 7 дней"),
        BotCommand("settings", "Текущие настройки"),
        BotCommand("swing", "Проверить рынок (1h и 4h)"),
        BotCommand("swing_check", "1h/4h: один токен"),
        BotCommand("swing_backtest", "1h/4h: бэктест"),
        BotCommand("swing_backtest_top", "1h/4h: бэктест по топ-токенам"),
        BotCommand("swing_stats", "Статистика 1h/4h"),
        BotCommand("pd_scan", "Pump/Dump: проверить сейчас"),
        BotCommand("pd_check", "Pump/Dump: одна монета"),
        BotCommand("pd_stats", "Статистика pump/dump"),
        BotCommand("pd_backtest", "Бэктест pump/dump"),
        BotCommand("myid", "Ваш Telegram ID"),
    ])


CARD_VERSION = "v6.1-RU"


def main():
    logger.info("Карточка сигнала: %s (русский интерфейс)", CARD_VERSION)
    if not TELEGRAM_BOT_TOKEN:
        raise SystemExit(
            "XATO: TELEGRAM_BOT_TOKEN topilmadi! "
            "Render'da Environment Variables bo'limini tekshiring."
        )

    init_db()
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

    amd_swing.register(app)  # 1h (trend 4h) va 4h (trend 1d) AMD moduli
    pump_detector.register(app)  # pump/dump detektori (AMD'dan alohida)

    # Скан выравнивается по часам: :00, :05, :10 ... (+15 с после закрытия свечи).
    # Bir xil yopilgan sham qayta tahlil qilinmaydi (amd.scan ichida).
    first_scan = SCAN_INTERVAL_SECONDS - (time.time() % SCAN_INTERVAL_SECONDS) + 15
    app.job_queue.run_repeating(background_scan, interval=SCAN_INTERVAL_SECONDS, first=first_scan)
    app.job_queue.run_repeating(scheduled_evaluate, interval=EVAL_CHECK_INTERVAL_SECONDS, first=60)
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
