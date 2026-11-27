"""
engine/features.py  (v7.0)
Signal aniqligini HAQIQATAN oshirish uchun o'lchov vositasi.

Har yuborilgan signal bilan birga uning ko'rsatkichlari (hajm, taker, OI, funding, L/S, MSS/FVG ...)
bazaga yoziladi. Signal yopilgach /features buyrug'i har ko'rsatkichni ikkiga bo'ladi
(medianadan yuqori / past yoki ha / yo'q) va har guruhning win-rate hamda o'rtacha R sini
solishtiradi. Shunda qaysi filtr haqiqatan ishlayotgani, qaysi biri shunchaki shovqin ekani ko'rinadi
va chegaralarni (/params) taxmin bilan emas, ma'lumot bilan sozlaysiz.

Eslatma: kamida ~20 ta yopilgan signal kerak; 60 dan kam bo'lsa natijalar yo'nalish ko'rsatkichi, isbot emas.
"""
from __future__ import annotations

import json
import logging
import math
import statistics
import time
from typing import Dict, List, Optional

import config as C
from engine import db

logger = logging.getLogger("nozik.features")

_READY = False

PUMP_KEYS = ["score", "vol_x", "peak_x", "ch5", "ch15", "oi_chg", "ext", "retr", "pressure", "breakout",
             "btc_conflict", "corr", "resid", "funding", "spread", "ob_share", "taker", "crowd", "liq_with",
             "move_atr", "risk_pct", "has_tp3"]
AMD_KEYS = ["score", "sweep_x", "confirm_x", "acc_ratio", "range_pct", "risk_pct", "mss", "fvg",
            "bn_ok", "htf_ok", "ctx_adj"]

LABELS = {
    "score": "скор", "vol_x": "объём ×", "peak_x": "пик объёма ×", "ch5": "движение 5м %", "ch15": "движение 15м %",
    "oi_chg": "OI %", "ext": "уже ушла %", "retr": "откат", "pressure": "давление", "breakout": "пробой диапазона",
    "btc_conflict": "против BTC", "corr": "corr BTC", "resid": "своё движение %", "funding": "funding %",
    "spread": "спред %", "ob_share": "стакан", "taker": "тейкеры", "crowd": "L/S толпа", "liq_with": "ликвидации $",
    "move_atr": "движение/ATR", "risk_pct": "риск %", "has_tp3": "есть TP3", "sweep_x": "объём sweep ×",
    "confirm_x": "объём подтв. ×", "acc_ratio": "объём накопл.", "range_pct": "диапазон %", "mss": "MSS", "fvg": "FVG",
    "bn_ok": "Binance ✓", "htf_ok": "тренд HTF ✓", "ctx_adj": "контекст ±", "hour": "час (UTC)", "long": "LONG",
}


def _ensure() -> None:
    global _READY
    if _READY:
        return
    with db.tx() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS signal_feat ("
                     "symbol TEXT NOT NULL, tf TEXT NOT NULL, sent_ts BIGINT NOT NULL, feats TEXT NOT NULL)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_feat_sig ON signal_feat (symbol, tf, sent_ts)")
    _READY = True


def _clean(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return float(v) if math.isfinite(float(v)) else None
    return None


def extract(sig) -> Dict[str, object]:
    """Alert (pump) yoki Signal (AMD) dan ko'rsatkichlar lug'ati."""
    is_pump = hasattr(sig, "kind")
    keys = PUMP_KEYS if is_pump else AMD_KEYS
    f: Dict[str, object] = {}
    for k in keys:
        if k == "has_tp3":
            f[k] = getattr(sig, "tp3", None) is not None
        elif k == "breakout":
            v = getattr(sig, "breakout", None)
            f[k] = None if v is None else bool(v)
        else:
            v = getattr(sig, k, None)
            f[k] = (None if v is None else (bool(v) if isinstance(v, bool) else _clean(v)))
    f["long"] = getattr(sig, "side", "") == "LONG"
    f["hour"] = time.gmtime().tm_hour
    return {k: v for k, v in f.items() if v is not None}


def record(sig) -> None:
    """Signal yuborilgach chaqiriladi (sig.sent_ts bo'lishi kerak). Xato signalni to'xtatmaydi."""
    try:
        ts = getattr(sig, "sent_ts", None)
        if not ts:
            return
        _ensure()
        with db.tx() as conn:
            conn.execute("INSERT INTO signal_feat (symbol, tf, sent_ts, feats) VALUES (?,?,?,?)",
                         (sig.symbol, sig.tf, int(ts), json.dumps(extract(sig))))
    except Exception as e:
        logger.warning(f"Ko'rsatkichlarni yozib bo'lmadi: {e}")


def _rows(tf: str) -> List[tuple]:
    _ensure()
    with db.tx() as conn:
        return conn.execute(
            "SELECT s.result_r, f.feats FROM signals s JOIN signal_feat f "
            "ON f.symbol = s.symbol AND f.tf = s.tf AND f.sent_ts = s.sent_ts "
            "WHERE s.tf = ? AND s.status != 'open' AND s.result_r IS NOT NULL", (tf,)
        ).fetchall()


def _grp(rs: List[float]) -> str:
    n = len(rs)
    wr = sum(1 for r in rs if r > 0) / n * 100
    return f"WR {wr:.0f}% · {sum(rs) / n:+.2f}R ({n})"


def analyze(rows: List[tuple], min_n: int = 8, top: int = 6) -> dict:
    """rows: [(result_r, feats_json)]. Qaytaradi: {"n", "wr", "avg", "items": [(delta, matn)]}."""
    data = []
    for r, fj in rows:
        try:
            data.append((float(r), json.loads(fj)))
        except Exception:
            continue
    n = len(data)
    if n == 0:
        return {"n": 0, "wr": 0.0, "avg": 0.0, "items": []}
    rs_all = [r for r, _ in data]
    out = {"n": n, "wr": sum(1 for r in rs_all if r > 0) / n * 100, "avg": sum(rs_all) / n, "items": []}
    keys = sorted({k for _, f in data for k in f})
    for k in keys:
        vals = [(r, f[k]) for r, f in data if k in f]
        if len(vals) < 2 * min_n:
            continue
        if all(isinstance(v, bool) for _, v in vals):
            a = [r for r, v in vals if v]
            b = [r for r, v in vals if not v]
            name_a, name_b = f"{LABELS.get(k, k)} — да", "нет"
        else:
            nums = [float(v) for _, v in vals if not isinstance(v, bool)]
            if len(nums) < 2 * min_n:
                continue
            med = statistics.median(nums)
            a = [r for r, v in vals if float(v) >= med]
            b = [r for r, v in vals if float(v) < med]
            name_a, name_b = f"{LABELS.get(k, k)} ≥{med:.3g}", "ниже"
        if len(a) < min_n or len(b) < min_n:
            continue
        ma, mb = sum(a) / len(a), sum(b) / len(b)
        out["items"].append((abs(ma - mb), f"{name_a}: {_grp(a)}\n   {name_b}: {_grp(b)}", ma - mb))
    out["items"].sort(key=lambda x: -x[0])
    out["items"] = out["items"][:top]
    return out


def report_text(tf: str) -> str:
    try:
        res = analyze(_rows(tf))
    except Exception as e:
        return f"❌ Не удалось прочитать данные: {e}"
    n = res["n"]
    if n < 20:
        return (f"🔬 [{tf}] Пока мало данных: {n} закрытых сигналов с записанными показателями (нужно ≥20).\n"
                "Показатели записываются с версии v7.0 — подождите несколько дней.")
    lines = [f"🔬 <b>Что работает · {tf}</b>",
             f"{n} закрытых · WR {res['wr']:.0f}% · {res['avg']:+.2f}R в среднем", ""]
    if not res["items"]:
        lines.append("Явных различий между группами пока нет.")
    for _, txt, delta in res["items"]:
        mark = "🟢" if delta > 0 else "🔴"
        lines.append(f"{mark} {txt}")
    lines.append("")
    lines.append("🟢 группа выше лучше (порог можно поднять), 🔴 хуже (фильтр, возможно, не помогает).")
    if n < 60:
        lines.append(f"⚠️ Выборка {n} < 60: это ориентир, а не доказательство. Меняйте пороги осторожно.")
    return "\n".join(lines)


async def cmd_features(update, context):
    from config import ADMIN_CHAT_IDS
    import asyncio
    user = update.effective_user
    if user is None or user.id not in ADMIN_CHAT_IDS:
        return
    tf = (context.args[0].lower() if context.args else "pump")
    if tf not in ("pump", "15m", "1h", "4h", "1d"):
        await update.message.reply_text("Использование: /features [pump|15m|1h|4h|1d]")
        return
    text = await asyncio.to_thread(report_text, tf)
    await update.message.reply_text(text, parse_mode="HTML")


def register(app) -> None:
    from telegram.ext import CommandHandler
    app.add_handler(CommandHandler("features", cmd_features))
