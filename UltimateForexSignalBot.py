#!/usr/bin/env python3
"""
UltimateForexSignalBot — Telegram Signal Bot
Trend + RSI + MACD + Bollinger Bands + News ogohlantirishlari

O'rnatish:
    pip install python-telegram-bot requests pandas ta

Ishga tushirish:
    python bot.py

Sozlash:
    1. BOT_TOKEN — @BotFather dan oling
    2. CHAT_ID   — @userinfobot dan oling
"""

import asyncio
import logging
from datetime import datetime, timezone
from telegram import Bot
from telegram.ext import Application, CommandHandler, ContextTypes
import requests
import pandas as pd
import ta

# ─────────────────────────────────────────────
#  SOZLAMALAR — BU YERNI TO'LDIRING
# ─────────────────────────────────────────────
BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"   # @BotFather dan oling
CHAT_ID   = "YOUR_CHAT_ID_HERE"     # @userinfobot dan oling

# Kuzatiladigan valyuta juftliklari
SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD"]

# Signal tekshirish oralig'i (daqiqa)
CHECK_INTERVAL = 15

# ─────────────────────────────────────────────
#  YANGILIKLAR JADVALI (UTC vaqtda)
# ─────────────────────────────────────────────
NEWS_CALENDAR = [
    {"date": "2025-07-04 12:30", "name": "🔴 NFP Non-Farm Payroll",       "impact": 3, "pairs": ["EURUSD","GBPUSD","XAUUSD"]},
    {"date": "2025-07-08 14:00", "name": "🔴 Fed Chairman Speech",         "impact": 3, "pairs": ["EURUSD","GBPUSD","XAUUSD"]},
    {"date": "2025-07-15 12:30", "name": "🔴 CPI Inflation Data",          "impact": 3, "pairs": ["EURUSD","GBPUSD"]},
    {"date": "2025-07-16 13:15", "name": "🟡 Retail Sales",                "impact": 2, "pairs": ["EURUSD"]},
    {"date": "2025-07-23 14:00", "name": "🔴 FOMC Meeting Minutes",        "impact": 3, "pairs": ["EURUSD","GBPUSD","XAUUSD"]},
    {"date": "2025-07-25 12:30", "name": "🔴 GDP Preliminary",             "impact": 3, "pairs": ["EURUSD","GBPUSD"]},
    {"date": "2025-08-01 12:30", "name": "🔴 NFP Non-Farm Payroll",       "impact": 3, "pairs": ["EURUSD","GBPUSD","XAUUSD"]},
    {"date": "2025-08-12 12:30", "name": "🔴 CPI Data",                    "impact": 3, "pairs": ["EURUSD","GBPUSD"]},
    {"date": "2025-08-21 14:00", "name": "🟡 Fed Minutes",                 "impact": 2, "pairs": ["EURUSD","XAUUSD"]},
    {"date": "2025-09-05 12:30", "name": "🔴 NFP Non-Farm Payroll",       "impact": 3, "pairs": ["EURUSD","GBPUSD","XAUUSD"]},
    {"date": "2025-09-17 18:00", "name": "🔴 FOMC Rate Decision",         "impact": 3, "pairs": ["EURUSD","GBPUSD","XAUUSD"]},
]

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)

# ─────────────────────────────────────────────
#  NARX MA'LUMOTI OLISH (Yahoo Finance bepul API)
# ─────────────────────────────────────────────
SYMBOL_MAP = {
    "EURUSD": "EURUSD=X",
    "GBPUSD": "GBPUSD=X",
    "USDJPY": "JPY=X",
    "XAUUSD": "GC=F",
}

def get_price_data(symbol: str, period: str = "5d", interval: str = "1h") -> pd.DataFrame | None:
    """Yahoo Finance dan narx ma'lumotlarini olish"""
    try:
        ticker = SYMBOL_MAP.get(symbol, symbol)
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
        params = {
            "range": period,
            "interval": interval,
            "includePrePost": False,
        }
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        data = resp.json()

        result = data["chart"]["result"][0]
        timestamps = result["timestamp"]
        ohlcv = result["indicators"]["quote"][0]

        df = pd.DataFrame({
            "time":   pd.to_datetime(timestamps, unit="s"),
            "open":   ohlcv["open"],
            "high":   ohlcv["high"],
            "low":    ohlcv["low"],
            "close":  ohlcv["close"],
            "volume": ohlcv.get("volume", [0]*len(timestamps)),
        }).dropna()

        return df
    except Exception as e:
        log.error(f"Narx olishda xato ({symbol}): {e}")
        return None

# ─────────────────────────────────────────────
#  INDIKATORLAR HISOBLASH
# ─────────────────────────────────────────────
def calc_indicators(df: pd.DataFrame) -> dict:
    close = df["close"]
    high  = df["high"]
    low   = df["low"]

    # Moving Averages
    ema10  = ta.trend.EMAIndicator(close, window=10).ema_indicator()
    ema50  = ta.trend.EMAIndicator(close, window=50).ema_indicator()

    # RSI
    rsi = ta.momentum.RSIIndicator(close, window=14).rsi()

    # MACD
    macd_obj = ta.trend.MACD(close, window_slow=26, window_fast=12, window_sign=9)
    macd     = macd_obj.macd()
    macd_sig = macd_obj.macd_signal()

    # Bollinger Bands
    bb      = ta.volatility.BollingerBands(close, window=20, window_dev=2)
    bb_up   = bb.bollinger_hband()
    bb_mid  = bb.bollinger_mavg()
    bb_low  = bb.bollinger_lband()

    # ATR (volatillik)
    atr = ta.volatility.AverageTrueRange(high, low, close, window=14).average_true_range()

    return {
        "price":    round(close.iloc[-1], 5),
        "ema10":    ema10.iloc[-1],
        "ema10_1":  ema10.iloc[-2],
        "ema50":    ema50.iloc[-1],
        "ema50_1":  ema50.iloc[-2],
        "rsi":      round(rsi.iloc[-1], 2),
        "macd":     macd.iloc[-1],
        "macd_sig": macd_sig.iloc[-1],
        "macd_1":   macd.iloc[-2],
        "macd_sig1":macd_sig.iloc[-2],
        "bb_up":    round(bb_up.iloc[-1], 5),
        "bb_mid":   round(bb_mid.iloc[-1], 5),
        "bb_low":   round(bb_low.iloc[-1], 5),
        "atr":      round(atr.iloc[-1], 5),
    }

# ─────────────────────────────────────────────
#  SIGNAL YARATISH
# ─────────────────────────────────────────────
def generate_signal(symbol: str, ind: dict) -> dict | None:
    """
    Signal kuchi quyidagicha hisoblanadi:
    - EMA kesishishi  → +1/-1
    - RSI             → +1/-1
    - MACD kesishishi → +1/-1
    - Bollinger Band  → +1/-1
    
    Kuch 3+ bo'lsa KUCHLI, 2 bo'lsa O'RTA signal
    """
    buy_score  = 0
    sell_score = 0
    reasons    = []

    price  = ind["price"]
    atr    = ind["atr"]

    # 1. EMA kesishishi
    ema_cross_up   = ind["ema10_1"] < ind["ema50_1"] and ind["ema10"] > ind["ema50"]
    ema_cross_down = ind["ema10_1"] > ind["ema50_1"] and ind["ema10"] < ind["ema50"]
    ema_trend_up   = ind["ema10"] > ind["ema50"]
    ema_trend_down = ind["ema10"] < ind["ema50"]

    if ema_cross_up:
        buy_score += 2; reasons.append("📈 EMA kesishdi (yuqoriga)")
    elif ema_trend_up:
        buy_score += 1; reasons.append("📈 Trend: yuqoriga")

    if ema_cross_down:
        sell_score += 2; reasons.append("📉 EMA kesishdi (pastga)")
    elif ema_trend_down:
        sell_score += 1; reasons.append("📉 Trend: pastga")

    # 2. RSI
    if ind["rsi"] < 30:
        buy_score += 2; reasons.append(f"🟢 RSI oversold: {ind['rsi']}")
    elif ind["rsi"] < 45:
        buy_score += 1; reasons.append(f"🟡 RSI past: {ind['rsi']}")

    if ind["rsi"] > 70:
        sell_score += 2; reasons.append(f"🔴 RSI overbought: {ind['rsi']}")
    elif ind["rsi"] > 55:
        sell_score += 1; reasons.append(f"🟡 RSI yuqori: {ind['rsi']}")

    # 3. MACD kesishishi
    macd_cross_up   = ind["macd_1"] < ind["macd_sig1"] and ind["macd"] > ind["macd_sig"]
    macd_cross_down = ind["macd_1"] > ind["macd_sig1"] and ind["macd"] < ind["macd_sig"]

    if macd_cross_up:
        buy_score += 2; reasons.append("⚡ MACD kesishdi (yuqoriga)")
    elif ind["macd"] > ind["macd_sig"]:
        buy_score += 1; reasons.append("⚡ MACD musbat")

    if macd_cross_down:
        sell_score += 2; reasons.append("⚡ MACD kesishdi (pastga)")
    elif ind["macd"] < ind["macd_sig"]:
        sell_score += 1; reasons.append("⚡ MACD manfiy")

    # 4. Bollinger Bands
    if price < ind["bb_low"]:
        buy_score += 2; reasons.append(f"🎯 BB quyi chegarada: {ind['bb_low']}")
    elif price < ind["bb_mid"]:
        buy_score += 1

    if price > ind["bb_up"]:
        sell_score += 2; reasons.append(f"🎯 BB yuqori chegarada: {ind['bb_up']}")
    elif price > ind["bb_mid"]:
        sell_score += 1

    # Minimum ball tekshirish
    min_score = 3
    direction = None
    score = 0

    if buy_score >= min_score and buy_score > sell_score:
        direction = "BUY"
        score = buy_score
    elif sell_score >= min_score and sell_score > buy_score:
        direction = "SELL"
        score = sell_score

    if direction is None:
        return None

    # SL va TP hisoblash (ATR asosida)
    sl_dist = round(atr * 1.5, 5)
    tp_dist = round(atr * 3.0, 5)

    if direction == "BUY":
        sl = round(price - sl_dist, 5)
        tp = round(price + tp_dist, 5)
    else:
        sl = round(price + sl_dist, 5)
        tp = round(price - tp_dist, 5)

    strength = "🔥 KUCHLI" if score >= 5 else "✅ O'RTA"

    return {
        "direction": direction,
        "strength":  strength,
        "score":     score,
        "price":     price,
        "sl":        sl,
        "tp":        tp,
        "rsi":       ind["rsi"],
        "reasons":   reasons,
    }

# ─────────────────────────────────────────────
#  YANGILIK TEKSHIRISH
# ─────────────────────────────────────────────
def check_news(symbol: str) -> list[dict]:
    """Yaqin soatlardagi yangiliklar ro'yxati"""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    upcoming = []

    for news in NEWS_CALENDAR:
        if symbol not in news["pairs"]:
            continue
        news_time = datetime.strptime(news["date"], "%Y-%m-%d %H:%M")
        diff_min  = (news_time - now).total_seconds() / 60

        if -30 <= diff_min <= 120:  # 30 daqiqa oldin va 2 soat keyin
            upcoming.append({
                "name":     news["name"],
                "time":     news["date"],
                "impact":   news["impact"],
                "diff_min": int(diff_min),
            })

    return upcoming

# ─────────────────────────────────────────────
#  XABAR FORMATLASH
# ─────────────────────────────────────────────
def format_signal_message(symbol: str, signal: dict, news_list: list) -> str:
    direction = signal["direction"]
    emoji     = "🟢" if direction == "BUY" else "🔴"
    now_str   = datetime.now(timezone.utc).strftime("%H:%M UTC")

    msg = f"""
{emoji} *{symbol} — {direction}* {signal["strength"]}
━━━━━━━━━━━━━━━━━━
💰 Narx:  `{signal["price"]}`
🎯 TP:    `{signal["tp"]}`
🛡️ SL:    `{signal["sl"]}`
📊 RSI:   `{signal["rsi"]}`
⭐ Ball:  `{signal["score"]}/8`
⏰ Vaqt:  `{now_str}`
━━━━━━━━━━━━━━━━━━
*Sabablar:*
"""
    for r in signal["reasons"]:
        msg += f"  {r}\n"

    if news_list:
        msg += "\n━━━━━━━━━━━━━━━━━━\n"
        msg += "⚠️ *YANGILIKLAR DIQQAT:*\n"
        for n in news_list:
            if n["diff_min"] > 0:
                msg += f"  {n['name']}\n"
                msg += f"  ⏳ {n['diff_min']} daqiqadan keyin\n"
            else:
                msg += f"  {n['name']}\n"
                msg += f"  🔴 HOZIR FAOL ({abs(n['diff_min'])} daqiqa oldin)\n"

        msg += "\n💡 _Yangilik vaqtida ehtiyot bo'ling!\nStraddle yoki savdoga kirmaslik tavsiya etiladi._"

    return msg.strip()

def format_news_alert(news: dict, symbol: str) -> str:
    impact_emoji = {3: "🔴", 2: "🟡", 1: "⚪"}.get(news["impact"], "⚪")
    return f"""
⚠️ *YANGILIK OGOHLANTIRISHИ* ⚠️
━━━━━━━━━━━━━━━━━━
{impact_emoji} *{news['name']}*
📌 Juftlik: `{symbol}`
⏰ Vaqt: `{news['time']} UTC`
⏳ {news['diff_min']} daqiqadan keyin!
━━━━━━━━━━━━━━━━━━
💡 *Tavsiya:*
  • Ochiq pozitsiyalarni yoping
  • Yangi savdoga kirmang
  • Yangilik o'tgach kuting
""".strip()

# ─────────────────────────────────────────────
#  ASOSIY TEKSHIRISH TSIKLI
# ─────────────────────────────────────────────
sent_news_alerts = set()

async def check_and_send(context: ContextTypes.DEFAULT_TYPE):
    bot = context.bot

    for symbol in SYMBOLS:
        try:
            # Yangilik ogohlantirishlari (5 daqiqa qolganda)
            news_list = check_news(symbol)
            for news in news_list:
                if 3 <= news["diff_min"] <= 7:
                    key = f"{symbol}_{news['time']}"
                    if key not in sent_news_alerts:
                        sent_news_alerts.add(key)
                        alert_msg = format_news_alert(news, symbol)
                        await bot.send_message(
                            chat_id=CHAT_ID,
                            text=alert_msg,
                            parse_mode="Markdown"
                        )
                        log.info(f"Yangilik ogohlantirishi yuborildi: {symbol} {news['name']}")

            # Signal tekshirish
            df = get_price_data(symbol)
            if df is None or len(df) < 60:
                continue

            ind    = calc_indicators(df)
            signal = generate_signal(symbol, ind)

            if signal:
                msg = format_signal_message(symbol, signal, news_list)
                await bot.send_message(
                    chat_id=CHAT_ID,
                    text=msg,
                    parse_mode="Markdown"
                )
                log.info(f"Signal yuborildi: {symbol} {signal['direction']} (ball: {signal['score']})")

        except Exception as e:
            log.error(f"Xato ({symbol}): {e}")

# ─────────────────────────────────────────────
#  TELEGRAM KOMANDALAR
# ─────────────────────────────────────────────
async def cmd_start(update, context):
    await update.message.reply_text(
        "👋 *UltimateForexSignalBot* ga xush kelibsiz!\n\n"
        "📋 *Komandalar:*\n"
        "/start — Botni ishga tushirish\n"
        "/status — Joriy narxlar\n"
        "/news — Bugungi yangiliklar\n"
        "/signal — Hozirgi signallar\n",
        parse_mode="Markdown"
    )

async def cmd_status(update, context):
    msg = "📊 *Joriy Narxlar:*\n━━━━━━━━━━━━━━━━\n"
    for symbol in SYMBOLS:
        df = get_price_data(symbol, period="1d", interval="5m")
        if df is not None and len(df) > 0:
            price = round(df["close"].iloc[-1], 5)
            change = round(df["close"].iloc[-1] - df["close"].iloc[0], 5)
            emoji = "🟢" if change >= 0 else "🔴"
            msg += f"{emoji} *{symbol}*: `{price}` ({'+' if change>=0 else ''}{change})\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def cmd_news(update, context):
    msg = "📰 *Yaqin yangiliklar (UTC):*\n━━━━━━━━━━━━━━━━\n"
    found = False
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    for news in NEWS_CALENDAR:
        news_time = datetime.strptime(news["date"], "%Y-%m-%d %H:%M")
        diff_min  = (news_time - now).total_seconds() / 60
        if 0 <= diff_min <= 1440:  # Keyingi 24 soat
            impact_e = {3:"🔴",2:"🟡",1:"⚪"}.get(news["impact"],"⚪")
            msg += f"{impact_e} {news['name']}\n"
            msg += f"   ⏰ {news['date']} | {int(diff_min//60)}s {int(diff_min%60)}d keyin\n\n"
            found = True

    if not found:
        msg += "Keyingi 24 soatda muhim yangilik yo'q ✅"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def cmd_signal(update, context):
    await update.message.reply_text("⏳ Signal tahlil qilinmoqda...")
    for symbol in SYMBOLS:
        df = get_price_data(symbol)
        if df is None or len(df) < 60:
            continue
        ind    = calc_indicators(df)
        signal = generate_signal(symbol, ind)
        news_list = check_news(symbol)
        if signal:
            msg = format_signal_message(symbol, signal, news_list)
            await update.message.reply_text(msg, parse_mode="Markdown")
        else:
            await update.message.reply_text(
                f"⏸ *{symbol}* — Hozircha aniq signal yo'q. Kutilmoqda...",
                parse_mode="Markdown"
            )

# ─────────────────────────────────────────────
#  ISHGA TUSHIRISH
# ─────────────────────────────────────────────
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start",  cmd_start))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("news",   cmd_news))
    app.add_handler(CommandHandler("signal", cmd_signal))

    # Avtomatik tekshirish (har CHECK_INTERVAL daqiqada)
    app.job_queue.run_repeating(
        check_and_send,
        interval=CHECK_INTERVAL * 60,
        first=10
    )

    log.info(f"Bot ishga tushdi! Tekshirish oralig'i: {CHECK_INTERVAL} daqiqa")
    app.run_polling()

if __name__ == "__main__":
    main()
