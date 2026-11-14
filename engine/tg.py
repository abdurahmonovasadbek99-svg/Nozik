"""
Telegram yordamchilari: signal matni, backtest matni, rasm + matn yuborish.

MUAMMO: Telegram rasm izohi (caption) 1024 belgigacha. Uzun matn yuborilmay qolardi.
YECHIM: matn sig'sa — rasm izohida, sig'masa — rasm alohida, matn keyingi xabarda.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Iterable, Optional

from engine import sim

logger = logging.getLogger("nozik.tg")

CAPTION_LIMIT = 1024
MESSAGE_LIMIT = 4096

REASON_EMOJIS = {
    "Accumulation": "📦",
    "Manipulation": "🎣",
    "Distribution": "🚀",
    "Structure": "🧱",
    "Binance": "🟡",
}

RESULT_TEXT = {
    "tp2": "✅✅ TP2 достигнут",
    "be": "✅ TP1 взят, остаток закрыт в безубытке",
    "sl": "❌ Сработал SL",
    "expired": "⏱ Срок сигнала истёк (позиция закрыта по рынку)",
}


def p(x: float) -> str:
    return f"{x:.6g}"


def reason_line(text: str) -> str:
    for key, emoji in REASON_EMOJIS.items():
        if text.startswith(key):
            return f"{emoji} {text}"
    if "тренд" in text:
        return f"📈 {text}"
    return f"• {text}"


def format_signal(s, P: dict) -> str:
    emoji = "🟢🚀" if s.side == "LONG" else "🔴📉"
    tier = "💎 PREMIUM" if s.score >= 85 else "Стандарт"
    risk = abs(s.entry - s.sl)
    limit_px = s.entry + P["max_chase_r"] * risk * (1 if s.side == "LONG" else -1)
    hours = P["expire_candles"] * P["tf_hours"]
    dur = f"~{hours:.0f} ч" if hours < 48 else f"~{hours / 24:.1f} дн."
    cost = sim.cost_r(s.entry, s.sl, P["fee_pct"], P["slip_pct"])
    text = (
        f"{emoji} СИГНАЛ {s.tf}: {s.symbol}  [{tier}]\n"
        f"⏱ Таймфрейм: {s.tf} (тренд-фильтр {P['htf_label']})\n\n"
        f"Направление: {s.side}\n"
        f"AMD-скор: {s.score}/100\n\n"
        f"Вход: {p(s.entry)}  (не догонять: допустимо до {p(limit_px)})\n"
        f"SL: {p(s.sl)} (риск {s.risk_pct:.2f}%)\n"
        f"TP1: {p(s.tp1)} (RR {s.rr1:.2f}) — закрыть 50%, SL в безубыток\n"
        f"TP2: {p(s.tp2)} (RR {s.rr2:.2f})\n"
        f"Издержки (комиссия+проскальзывание) ≈ {cost:.2f}R\n"
        f"Срок сигнала: {dur}\n\n"
    )
    for r in s.reasons:
        text += reason_line(r) + "\n"
    return text


def levels_of(s) -> dict:
    return {"range_high": s.range_high, "range_low": s.range_low,
            "entry": s.entry, "sl": s.sl, "tp1": s.tp1, "tp2": s.tp2}


def to_dicts(candles: list) -> list:
    return [{"open": c[1], "high": c[2], "low": c[3], "close": c[4]} for c in candles]


def format_backtest(r: dict, P: dict, days: Optional[float] = None) -> str:
    n = r["trades"]
    title = f"🧪 {r['symbol']} [{r['tf']}]"
    if days is not None:
        title += f", ~{days:.0f} дн."
    pf = f"{r['pf']}" if r.get("pf") is not None else "—"
    lines = [
        title, "",
        f"Сделок: {n}",
        f"Прибыльных: {r['wins']} ({r['winrate']}%)",
        f"Итого (после издержек): {r['total_R']:+.2f}R",
        f"До издержек: {r['gross_total_R']:+.2f}R",
        f"Издержки: -{r['cost_total_R']:.2f}R "
        f"(комиссия {P['fee_pct']}% + проскальзывание {P['slip_pct']}% за сторону)",
        f"Среднее: {r['avg_R']:+.2f}R | Profit factor: {pf}",
    ]
    if "symbols_ok" in r:
        lines.append(f"Токенов в плюсе: {r['symbols_profitable']}/{r['symbols_ok']}")
        top = r.get("per_symbol", [])
        if top:
            lines.append("")
            lines.append("Лучшие: " + ", ".join(f"{s} {t:+.1f}R" for s, _, t in top[:3]))
            lines.append("Худшие: " + ", ".join(f"{s} {t:+.1f}R" for s, _, t in top[-3:][::-1]))
    if n < 30:
        lines.append("\n⚠️ Меньше 30 сделок — статистически ненадёжно. "
                     "Используйте backtest_top (много токенов).")
    return "\n".join(lines)


async def send_with_chart(bot, chat_id, text: str, buf) -> None:
    """Admin chat'ga rasm + matn. Matn sig'masa — alohida xabar."""
    if buf is not None:
        buf.seek(0)
        if len(text) <= CAPTION_LIMIT:
            await bot.send_photo(chat_id=chat_id, photo=buf, caption=text)
            return
        await bot.send_photo(chat_id=chat_id, photo=buf)
    await bot.send_message(chat_id=chat_id, text=text[:MESSAGE_LIMIT])


async def broadcast(bot, chat_ids: Iterable[int], text: str, buf=None) -> None:
    for chat_id in chat_ids:
        try:
            await send_with_chart(bot, chat_id, text, buf)
        except Exception as e:
            logger.error(f"Xabar yuborishda xato ({chat_id}): {e}")


async def reply_with_chart(message, text: str, buf) -> None:
    if buf is not None:
        buf.seek(0)
        if len(text) <= CAPTION_LIMIT:
            await message.reply_photo(photo=buf, caption=text)
            return
        await message.reply_photo(photo=buf)
    await message.reply_text(text[:MESSAGE_LIMIT])


async def make_chart(symbol, candles, direction, levels, tf_label):
    """matplotlib og'ir — event loop'ni bloklamaslik uchun threadda."""
    from engine.chart import generate_candle_chart
    return await asyncio.to_thread(generate_candle_chart, symbol, candles, direction,
                                   levels, tf_label)
