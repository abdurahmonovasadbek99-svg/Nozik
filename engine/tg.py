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
    """Текст сигнала (Telegram HTML) — подпись к картинке, parse_mode="HTML"."""
    from engine.chart import grade_of

    is_long = s.side == "LONG"
    dot = "🟢" if is_long else "🔴"
    premium = "  💎 PREMIUM" if s.score >= 85 else ""
    grade, _ = grade_of(s.score)
    risk = abs(s.entry - s.sl)
    limit_px = s.entry + P["max_chase_r"] * risk * (1 if is_long else -1)
    hours = P["expire_candles"] * P["tf_hours"]
    dur = f"~{hours:.0f} ч" if hours < 48 else f"~{hours / 24:.1f} дн."
    cost = sim.cost_r(s.entry, s.sl, P["fee_pct"], P["slip_pct"])

    def pct(v: float) -> str:
        return f"{(v - s.entry) / s.entry * 100:+.2f}%"

    conf = [f"объём sweep x{s.sweep_x:.1f}"] if s.sweep_x else ["sweep"]
    if s.mss:
        conf.append("MSS")
    if s.fvg:
        conf.append("FVG")
    if s.bn_ok is True:
        conf.append("объём Binance ✓")
    if s.htf_ok is True:
        conf.append(f"тренд {P['htf_label']} ✓")

    line = "━━━━━━━━━━━━━━━━"
    return (
        f"{dot} <b>{s.side} · {s.symbol} · {s.tf}</b>{premium}\n"
        f"{line}\n"
        f"🎯 Вход: <code>{p(s.entry)}</code>\n"
        f"🛑 SL: <code>{p(s.sl)}</code>  <i>({pct(s.sl)})</i>\n"
        f"✅ TP1: <code>{p(s.tp1)}</code>  <i>({pct(s.tp1)})</i>\n"
        f"✅ TP2: <code>{p(s.tp2)}</code>  <i>({pct(s.tp2)})</i>\n"
        f"{line}\n"
        f"⭐ Качество: <b>{grade}</b> ({s.score}/100)\n"
        f"🧩 Конфлюэнс: {' · '.join(conf)}\n"
        f"🧭 AMD: Accumulation → Manipulation → Distribution\n"
        f"📦 Диапазон {s.range_pct:.1f}% · объём x{s.acc_ratio:.2f}\n"
        f"⚖️ R:R 1:{s.rr1:.1f} – 1:{s.rr2:.1f} · издержки ≈ {cost:.2f}R\n"
        f"⏱ Срок: {dur} · не догонять: до <code>{p(limit_px)}</code>\n"
        f"💡 На TP1 закрыть 50%, SL — в безубыток"
    )


def levels_of(s) -> dict:
    return {"range_high": s.range_high, "range_low": s.range_low,
            "entry": s.entry, "sl": s.sl, "tp1": s.tp1, "tp2": s.tp2}


def meta_of(s, P: dict) -> dict:
    """Chart kartasi uchun qo'shimcha ma'lumot (sifat, MSS/FVG, indekslar...)."""
    return {"score": s.score, "ts": s.ts, "rr1": s.rr1, "rr2": s.rr2, "risk_pct": s.risk_pct,
            "sweep_i": s.sweep_i, "range_i": s.range_i, "mss": s.mss, "fvg": s.fvg,
            "bn_ok": s.bn_ok, "htf_ok": s.htf_ok, "htf": P.get("htf_label", "")}


def to_dicts(candles: list) -> list:
    return [{"ts": c[0], "open": c[1], "high": c[2], "low": c[3], "close": c[4]} for c in candles]


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


async def send_with_chart(bot, chat_id, text: str, buf, parse_mode=None) -> None:
    """Admin chat'ga rasm + matn. Matn sig'masa — alohida xabar."""
    if buf is not None:
        buf.seek(0)
        if len(text) <= CAPTION_LIMIT:
            await bot.send_photo(chat_id=chat_id, photo=buf, caption=text, parse_mode=parse_mode)
            return
        await bot.send_photo(chat_id=chat_id, photo=buf)
    await bot.send_message(chat_id=chat_id, text=text[:MESSAGE_LIMIT], parse_mode=parse_mode)


async def broadcast(bot, chat_ids: Iterable[int], text: str, buf=None, parse_mode=None) -> None:
    for chat_id in chat_ids:
        try:
            await send_with_chart(bot, chat_id, text, buf, parse_mode)
        except Exception as e:
            logger.error(f"Xabar yuborishda xato ({chat_id}): {e}")


async def reply_with_chart(message, text: str, buf, parse_mode=None) -> None:
    if buf is not None:
        buf.seek(0)
        if len(text) <= CAPTION_LIMIT:
            await message.reply_photo(photo=buf, caption=text, parse_mode=parse_mode)
            return
        await message.reply_photo(photo=buf)
    await message.reply_text(text[:MESSAGE_LIMIT], parse_mode=parse_mode)


async def make_chart(symbol, candles, direction, levels, tf_label, meta=None):
    """matplotlib og'ir — event loop'ni bloklamaslik uchun threadda."""
    from engine.chart import generate_candle_chart
    return await asyncio.to_thread(generate_candle_chart, symbol, candles, direction,
                                   levels, tf_label, meta)
