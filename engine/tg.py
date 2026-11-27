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
    "tp3": "🏆 TP3 достигнут (сильный импульс)",
    "lock": "✅✅ TP1+TP2 взяты, остаток закрыт по TP1",
    "tp2": "✅✅ TP2 достигнут",
    "be": "✅ TP1 взят, остаток закрыт в безубытке",
    "sl": "❌ Сработал SL",
    "expired": "⏱ Срок сигнала истёк (позиция закрыта по рынку)",
    "stale": "⏸ Импульс затух — закрыто досрочно по рынку",
}


def p(x: float) -> str:
    """Narx matni. Juda kichik narxlar (PEPE...) ilmiy yozuvsiz: 0.0000123."""
    if x and abs(x) < 1e-4:
        import math
        dec = int(-math.floor(math.log10(abs(x)))) + 3
        return f"{x:.{dec}f}"
    return f"{x:.6g}"


def reason_line(text: str) -> str:
    for key, emoji in REASON_EMOJIS.items():
        if text.startswith(key):
            return f"{emoji} {text}"
    if "тренд" in text:
        return f"📈 {text}"
    return f"• {text}"


def format_signal(s, P: dict) -> str:
    """Ixcham AMD signal kartasi (Telegram HTML) — rasm izohi, parse_mode="HTML"."""
    from engine.chart import grade_of
    from engine.trail import bar

    is_long = s.side == "LONG"
    dot = "🟢" if is_long else "🔴"
    premium = " 💎" if s.score >= 85 else ""
    grade, _ = grade_of(s.score)
    risk = abs(s.entry - s.sl)
    limit_px = s.entry + P["max_chase_r"] * risk * (1 if is_long else -1)
    hours = P["expire_candles"] * P["tf_hours"]
    dur = f"~{hours:.0f} ч" if hours < 48 else f"~{hours / 24:.1f} дн."
    cost = sim.cost_r(s.entry, s.sl, P["fee_pct"], P["slip_pct"])

    def pct(v: float) -> str:
        return f"{(v - s.entry) / s.entry * 100:+.1f}%"

    conf = [f"sweep ×{s.sweep_x:.1f}"] if s.sweep_x else ["sweep"]
    if s.mss:
        conf.append("MSS")
    if s.fvg:
        conf.append("FVG")
    if s.bn_ok is True:
        conf.append("Binance ✓")
    if s.htf_ok is True:
        conf.append(f"тренд {P['htf_label']} ✓")

    chase = "выше" if is_long else "ниже"
    ctx = getattr(s, "ctx_line", "")
    ctx_row = f"🧭 {ctx}\n" if ctx else ""
    return (
        f"{dot} <b>{s.side} · {s.symbol}</b> · {s.tf}{premium}\n"
        f"{bar(s.score)} <b>{grade}</b> · {s.score}/100\n"
        f"\n"
        f"🎯 Вход <code>{p(s.entry)}</code>\n"
        f"🛑 SL <code>{p(s.sl)}</code> ({pct(s.sl)})\n"
        f"✅ TP1 <code>{p(s.tp1)}</code> ({pct(s.tp1)}) · TP2 <code>{p(s.tp2)}</code> ({pct(s.tp2)})\n"
        f"\n"
        f"🧩 {' · '.join(conf)}\n"
        f"{ctx_row}"
        f"⚖️ R:R 1:{s.rr1:.1f}–1:{s.rr2:.1f} · издержки ≈{cost:.2f}R · ⏱ {dur}\n"
        f"💡 TP1: закрыть 50%, SL → вход · не догонять {chase} <code>{p(limit_px)}</code>"
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


def live_markup(symbol: str, sent_ts: Optional[int]):
    """Rasm ostidagi "📊 Jonli grafik" tugmasi (Telegram Mini App). Sozlanmagan bo'lsa — None."""
    import config as C
    if not (C.USE_WEBAPP and sent_ts and symbol):
        return None
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
    url = f"{C.WEBAPP_URL}/app?s={symbol}&t={int(sent_ts)}"
    return InlineKeyboardMarkup([[InlineKeyboardButton("📊 Живой график", web_app=WebAppInfo(url=url))]])


async def send_with_chart(bot, chat_id, text: str, buf, parse_mode=None, reply_markup=None):
    """Admin chat'ga rasm + matn. Matn sig'masa — alohida xabar. reply_markup — tugma (rasm/matn ostida).
    Tugma xato bersa (masalan guruh chat) — xabar tugmasiz qayta yuboriladi, signal yo'qolmaydi."""
    try:
        return await _send(bot, chat_id, text, buf, parse_mode, reply_markup)
    except Exception as e:
        if reply_markup is None:
            raise
        logger.warning(f"Tugma bilan yuborib bo'lmadi ({chat_id}): {e} — tugmasiz qayta urinaman")
        return await _send(bot, chat_id, text, buf, parse_mode, None)


async def _send(bot, chat_id, text: str, buf, parse_mode, reply_markup):
    """Yuborilgan OXIRGI xabarni qaytaradi (signal matni/tugmasi shu xabarda)."""
    if buf is not None:
        buf.seek(0)
        if len(text) <= CAPTION_LIMIT:
            return await bot.send_photo(chat_id=chat_id, photo=buf, caption=text, parse_mode=parse_mode,
                                        reply_markup=reply_markup)
        await bot.send_photo(chat_id=chat_id, photo=buf)
    return await bot.send_message(chat_id=chat_id, text=text[:MESSAGE_LIMIT], parse_mode=parse_mode,
                                  reply_markup=reply_markup)


async def _track(bot, chat_id, msg, track) -> None:
    """Signal xabari id sini saqlaydi (keyingi TP/SL xabarlari shunga reply bo'ladi); ixtiyoriy zakrepit."""
    import config as C
    from engine import evaluator
    symbol, tf, sent_ts = track
    await asyncio.to_thread(evaluator.save_msg, symbol, tf, sent_ts, chat_id, msg.message_id)
    if C.PIN_ACTIVE_SIGNALS:
        try:
            await bot.pin_chat_message(chat_id=chat_id, message_id=msg.message_id,
                                       disable_notification=True)
        except Exception as e:
            logger.warning(f"Signalni zakrepit qilib bo'lmadi ({chat_id}): {e}")


async def broadcast(bot, chat_ids: Iterable[int], text: str, buf=None, parse_mode=None,
                    reply_markup=None, track=None) -> None:
    """track=(symbol, tf, sent_ts) berilsa — xabar id si saqlanadi va notify() shunga reply qiladi."""
    for chat_id in chat_ids:
        try:
            msg = await send_with_chart(bot, chat_id, text, buf, parse_mode, reply_markup)
        except Exception as e:
            logger.error(f"Xabar yuborishda xato ({chat_id}): {e}")
            continue
        if track and track[2] and msg is not None:
            try:
                await _track(bot, chat_id, msg, track)
            except Exception as e:
                logger.warning(f"Signal xabarini kuzatishda xato ({chat_id}): {e}")


async def notify(bot, chat_ids: Iterable[int], text: str, symbol: str, tf: str, sent_ts,
                 parse_mode=None, unpin: bool = False) -> None:
    """Signal bo'yicha yangilik (TP1/TP2/SL/muddat...) — ASL signal xabariga REPLY qilib yuboradi.
    Asl xabar topilmasa yoki o'chirilgan bo'lsa — oddiy xabar sifatida boradi."""
    import config as C
    from engine import evaluator
    ids = {}
    if C.REPLY_TO_SIGNAL and sent_ts:
        for chat, mid in await asyncio.to_thread(evaluator.get_msgs, symbol, tf, sent_ts):
            ids[chat] = mid
    for chat_id in chat_ids:
        mid = ids.get(chat_id)
        try:
            if mid:
                await bot.send_message(chat_id=chat_id, text=text[:MESSAGE_LIMIT], parse_mode=parse_mode,
                                       reply_to_message_id=mid, allow_sending_without_reply=True)
            else:
                await bot.send_message(chat_id=chat_id, text=text[:MESSAGE_LIMIT], parse_mode=parse_mode)
        except Exception as e:
            logger.error(f"Yangilik yuborishda xato ({chat_id}): {e}")
        if unpin and mid and C.PIN_ACTIVE_SIGNALS:
            try:
                await bot.unpin_chat_message(chat_id=chat_id, message_id=mid)
            except Exception as e:
                logger.warning(f"Zakrepni olib bo'lmadi ({chat_id}): {e}")


def progress_text(ev: dict, label: str) -> str:
    """TP1/TP2 olinganda: pozitsiyani qo'lda boshqarish uchun qisqa ko'rsatma."""
    sym, side, st, three = ev["symbol"], ev["side"], ev["stage"], ev["three"]
    if st == 1:
        part = "40%" if three else "50%"
        return f"🎯 TP1 · {sym} {side}\nЗакройте ~{part}, SL → вход ({ev['entry']:.6g})"
    if not three:
        return f"🎯🎯 TP2 · {sym} {side}\nПозиция закрыта полностью"
    return (f"🎯🎯 TP2 · {sym} {side}\nЗакройте ~30%, SL → TP1 ({ev['tp1']:.6g}), "
            f"остаток к TP3 ({ev['tp3']:.6g})")


def result_text(r: dict, label: str) -> str:
    """Signal yopilganda yakuniy xabar (qisqa)."""
    extra = ""
    if r.get("mfe_r") is not None:
        extra = f" · MFE {r['mfe_r']:.1f}R / MAE {r['mae_r']:.1f}R"
    return (f"{RESULT_TEXT.get(r['status'], r['status'])}\n"
            f"{r['symbol']} {r['side']}: {r['result_r']:+.2f}R{extra}")


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
