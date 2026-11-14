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
import time
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
from signals import amd_swing

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
        ["🔍 Сканирование", "📈 Статистика"],
        ["📊 Отчёт", "⚙️ Настройки"],
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
    tier = "💎 PREMIUM" if s.score >= 85 else "Стандарт"
    text = (
        f"{emoji} СИГНАЛ: {s.symbol}  [{tier}]\n"
        f"⏱ Таймфрейм: 15m (тренд-фильтр 1h)\n\n"
        f"Направление: {s.side}\n"
        f"AMD-скор: {s.score}/100\n\n"
        f"Вход: {_p(s.entry)}\n"
        f"SL: {_p(s.sl)} (риск {s.risk_pct:.2f}%)\n"
        f"TP1: {_p(s.tp1)} (RR {s.rr1:.2f}) — закрыть 50%, SL в безубыток\n"
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
        uid = update.effective_user.id if update.effective_user else "?"
        await update.message.reply_text(
            "Этот бот приватный — доступ закрыт.\n"
            f"Ваш Telegram ID: {uid}\n"
            "Отправьте этот ID владельцу бота, чтобы он добавил вас."
        )
        return
    await update.message.reply_text(
        "🤖 Nozik Bot v3 запущен.\n\n"
        "Стратегия: AMD (Accumulation → Manipulation → Distribution) + "
        "анализ объёмов Bybit/Binance. Основной фокус — малокапитализированные токены.\n\n"
        "Сигналы по трём уровням:\n"
        "• 15m (тренд-фильтр 1h)\n"
        "• 1h (тренд-фильтр 4h)\n"
        "• 4h (тренд-фильтр 1d)\n\n"
        "Команды:\n"
        "/scan — проверить рынок (15m)\n"
        "/swing — проверить рынок (1h и 4h)\n"
        "/check <SYMBOL> — один токен, 15m (например /check PEPEUSDT)\n"
        "/swing_check <SYMBOL> 1h|4h — один токен, 1h/4h\n"
        "/backtest <SYMBOL> — бэктест 15m\n"
        "/swing_backtest <SYMBOL> 1h|4h — бэктест 1h/4h\n"
        "/pump_stats — статистика 15m\n"
        "/swing_stats — статистика 1h/4h\n"
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
        sent, skipped, found = await _run_scan(context.bot)
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
        levels = _levels(sig)
        ok = sig.score >= ALERT_THRESHOLD
        lines.append(f"Найден AMD-сетап: {sig.side}, скор {sig.score}/100")
        lines.append("✅ Проходит порог сигнала" if ok else
                     f"⚠️ Скор ниже порога ({ALERT_THRESHOLD}) — сигнал отправлен не будет")
        lines.append(f"Вход {_p(sig.entry)} | SL {_p(sig.sl)} | TP1 {_p(sig.tp1)} | TP2 {_p(sig.tp2)}")
        lines.append("")
        for r in sig.reasons:
            lines.append(_reason_line(r))
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

    chart_buf = generate_candle_chart(symbol, _to_dicts(res["candles"]), direction, levels)
    if chart_buf:
        await update.message.reply_photo(photo=chart_buf, caption=caption)
    else:
        await update.message.reply_text(caption)


async def cmd_backtest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update):
        return
    if not context.args:
        await update.message.reply_text("Укажите символ токена. Например: /backtest PEPEUSDT")
        return
    symbol = context.args[0].upper()
    await update.message.reply_text(f"🧪 {symbol}: идёт бэктест...")
    r = await asyncio.to_thread(amd.backtest, symbol)
    if not r:
        await update.message.reply_text("❌ Не удалось получить данные (проверьте символ).")
        return
    await update.message.reply_text(
        f"🧪 {r['symbol']} (последние ~10 дней, 15m)\n\n"
        f"Сделок: {r['trades']}\n"
        f"Прибыльных: {r['wins']} ({r['winrate']}%)\n"
        f"Среднее: {r['avg_R']}R\n"
        f"Итого: {r['total_R']}R\n\n"
        "Примечание: по одному токену сделок мало — проверьте на 10–15 токенах."
    )


async def cmd_pump_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update):
        return
    st = get_stats()
    bs = st["by_status"]
    text = (
        "📈 Статистика сигналов (15m):\n\n"
        f"Закрытых сигналов: {st['total_closed']}\n"
        f"Прибыльных: {st['wins']} ({st['winrate_pct']}%)\n"
        f"Итого: {st['total_r']:+.2f}R\n"
        f"Среднее: {st['avg_r']:+.2f}R\n"
        f"Открытых (в ожидании): {st['pending']}\n\n"
        f"TP2: {bs.get('tp2', 0)} | TP1+BE: {bs.get('be', 0)} | "
        f"SL: {bs.get('sl', 0)} | По истечении срока: {bs.get('expired', 0)}"
    )
    await update.message.reply_text(text)


async def cmd_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update):
        return
    text = (
        "⚙️ Текущие настройки:\n\n"
        "Стратегия: AMD + объёмы Bybit/Binance\n"
        f"Таймфрейм 15m: тренд-фильтр 1h\n"
        f"Таймфреймы {', '.join(amd_swing.ENABLED)}: тренд-фильтр "
        f"{', '.join(amd_swing.PROFILES[t]['htf_label'] for t in amd_swing.ENABLED)}\n"
        f"Минимальный скор: {ALERT_THRESHOLD}/100\n"
        f"Макс. риск: {MAX_RISK_PCT}%\n"
        f"Фильтр рынка: оборот за 24ч {MIN_24H_TURNOVER_USDT/1e6:g}M — {MAX_24H_TURNOVER_USDT/1e6:g}M USDT "
        f"(макс. {MAX_CANDIDATES_PER_SCAN} пар)\n"
        f"Сканирование 15m: каждые {SCAN_INTERVAL_SECONDS // 60} мин\n"
        f"Cooldown: {ALERT_COOLDOWN_SECONDS // 3600} ч\n"
        f"BTC-фильтр: {'включён' if USE_BTC_FILTER else 'выключен'}\n"
        f"Срок сигнала 15m: {EXPIRE_CANDLES * 15 // 60} ч\n"
        f"Пользователей с доступом: {len(ADMIN_CHAT_IDS)}\n\n"
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


def _format_period_report(title: str, stats: dict) -> str:
    lines = [f"{title}\n", f"Отправлено сигналов: {stats['total_sent']}"]
    if stats["total_closed"] > 0:
        lines.append(f"Закрыто: {stats['total_closed']}")
        lines.append(f"Прибыльных: {stats['wins']} ({stats['winrate_pct']}%)")
        lines.append(f"Итого: {stats['total_r']:+.2f}R")
        lines.append(f"Среднее: {stats['avg_r']:+.2f}R")
        if stats["best"]:
            lines.append(f"Лучший: {stats['best'][0]} ({stats['best'][1]:+.2f}R)")
        if stats["worst"]:
            lines.append(f"Худший: {stats['worst'][0]} ({stats['worst'][1]:+.2f}R)")
    else:
        lines.append("Закрытых сигналов пока нет.")
    return "\n".join(lines)


async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update):
        return
    daily = get_stats_since(86400)
    weekly = get_stats_since(604800)
    text = (
        _format_period_report("📅 Последние 24 часа", daily)
        + "\n\n"
        + _format_period_report("🗓 Последние 7 дней", weekly)
    )
    await update.message.reply_text(text)


async def scheduled_daily_report(context: ContextTypes.DEFAULT_TYPE):
    stats = get_stats_since(86400)
    text = _format_period_report("📅 Дневной отчёт", stats)
    for chat_id in ADMIN_CHAT_IDS:
        try:
            await context.bot.send_message(chat_id=chat_id, text=text)
        except Exception as e:
            logger.error(f"Kunlik hisobot yuborishda xato ({chat_id}): {e}")


async def scheduled_weekly_report(context: ContextTypes.DEFAULT_TYPE):
    stats = get_stats_since(604800)
    text = _format_period_report("🗓 Недельный отчёт", stats)
    for chat_id in ADMIN_CHAT_IDS:
        try:
            await context.bot.send_message(chat_id=chat_id, text=text)
        except Exception as e:
            logger.error(f"Haftalik hisobot yuborishda xato ({chat_id}): {e}")


RESULT_TEXT = {
    "tp2": "✅✅ TP2 достигнут",
    "be": "✅ TP1 взят, остаток закрыт в безубытке",
    "sl": "❌ Сработал SL",
    "expired": "⏱ Срок сигнала истёк",
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
        BotCommand("start", "Запуск / меню"),
        BotCommand("scan", "Проверить рынок (15m)"),
        BotCommand("check", "Проверить один токен"),
        BotCommand("backtest", "Бэктест (15m)"),
        BotCommand("pump_stats", "Статистика сигналов 15m"),
        BotCommand("report", "Отчёт за 24ч / 7 дней"),
        BotCommand("settings", "Текущие настройки"),
        BotCommand("swing", "Проверить рынок (1h и 4h)"),
        BotCommand("swing_check", "1h/4h: один токен"),
        BotCommand("swing_backtest", "1h/4h: бэктест"),
        BotCommand("swing_stats", "Статистика 1h/4h")
        ,BotCommand("myid", "Ваш Telegram ID"),
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
    app.add_handler(CommandHandler("myid", cmd_myid))
    app.add_handler(CommandHandler("scan", cmd_scan))
    app.add_handler(CommandHandler("check", cmd_check))
    app.add_handler(CommandHandler("backtest", cmd_backtest))
    app.add_handler(CommandHandler("pump_stats", cmd_pump_stats))
    app.add_handler(CommandHandler("report", cmd_report))
    app.add_handler(CommandHandler("settings", cmd_settings))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_menu_text))

    amd_swing.register(app)  # 1h (trend 4h) va 4h (trend 1d) AMD moduli

    # Скан выравнивается по часам: :00, :05, :10 ... (+15 с после закрытия свечи)
    first_scan = SCAN_INTERVAL_SECONDS - (time.time() % SCAN_INTERVAL_SECONDS) + 15
    app.job_queue.run_repeating(background_scan, interval=SCAN_INTERVAL_SECONDS, first=first_scan)
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
