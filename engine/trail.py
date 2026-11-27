"""
engine/trail.py  (v6.8)
Ochiq pump/dump signallarida impuls KUCHINI o'lchaydi va SL / TP ni surish bo'yicha
MASLAHAT xabari tayyorlaydi (xabar asl signalga reply + zakrep bo'lib boradi).

Muhim: bu faqat ko'rsatma. Statistika (/pd_stats) avvalgidek qat'iy qoidalar bilan
(sim.py) hisoblanadi — shuning uchun natijalar solishtirma bo'lib qoladi.

Kuch (0-100) 3 ta narsadan:
  * hajm   — oxirgi 2 ta yopilgan 5m sham hajmi / signaldan oldingi me'yoriy hajm
  * bosim  — oxirgi 3 shamdan nechtasi harakat tomonida yopilgan
  * qaytish — signaldan keyingi cho'qqidan qancha qaytib tushgan (kam = kuchli)
"""
from __future__ import annotations

import logging
import statistics
import time
from typing import Dict, List, Optional, Tuple

import config as C
from engine import db

logger = logging.getLogger("nozik.trail")

FIVE_MIN_MS = 300_000
STRONG_AT = 65
WEAK_AT = 35

# (symbol, sent_ts) -> {"ts": oxirgi xabar vaqti, "label": str, "sl": oxirgi tavsiya SL, "n": xabarlar soni}
_STATE: Dict[Tuple[str, int], dict] = {}


def bar(score: float, width: int = 5) -> str:
    """0-100 -> ▰▰▰▱▱"""
    n = max(0, min(width, round(score / 100 * width)))
    return "▰" * n + "▱" * (width - n)


def _px(x: float) -> str:
    from engine.tg import p
    return p(x)


def measure(c: list, side: str, entry: float, risk: float, sent_ms: int) -> Optional[dict]:
    """c — YOPILGAN 5m shamlar (ts, o, h, l, c, v), eskidan yangiga.
    Signaldan keyin kamida 2 ta sham bo'lmasa None."""
    if risk <= 0:
        return None
    long_ = side == "LONG"
    post = [x for x in c if x[0] >= sent_ms]
    pre = [x for x in c if x[0] < sent_ms][-20:]
    if len(post) < 2 or len(pre) < 5:
        return None

    base = statistics.median(x[5] for x in pre) or 0.0
    last2 = post[-2:]
    vol_ratio = (sum(x[5] for x in last2) / 2 / base) if base > 0 else 1.0

    last3 = post[-3:]
    with_us = sum(1 for x in last3 if ((x[4] > x[1]) if long_ else (x[4] < x[1])))
    push = with_us / len(last3)

    price = post[-1][4]
    peak = max(x[2] for x in post) if long_ else min(x[3] for x in post)
    gain_peak = (peak - entry) if long_ else (entry - peak)
    giveback = 0.0
    if gain_peak > 0:
        cur = (price - entry) if long_ else (entry - price)
        giveback = max(0.0, min(1.0, (gain_peak - cur) / gain_peak))

    score = (40 * min(vol_ratio / 1.5, 1.0)
             + 30 * push
             + 30 * (1.0 - min(giveback / 0.5, 1.0)))
    score = int(round(max(0, min(100, score))))
    label = "strong" if score >= STRONG_AT else ("weak" if score <= WEAK_AT else "ok")
    r_now = ((price - entry) if long_ else (entry - price)) / risk
    return {"score": score, "label": label, "vol_ratio": vol_ratio, "push": push,
            "giveback": giveback, "price": price, "r_now": r_now, "post": post,
            "peak": peak}


def advise(m: dict, side: str, entry: float, sl: float, tp1: float, tp2: float,
           tp3: Optional[float], stage: int, key: Tuple[str, int], now: float) -> Optional[str]:
    """Xabar matni yoki None (hozir gapiradigan narsa yo'q / spam bo'lmasin)."""
    long_ = side == "LONG"
    risk = abs(entry - sl)
    d = 1 if long_ else -1
    price, r_now, label, score = m["price"], m["r_now"], m["label"], m["score"]
    post = m["post"]

    three = tp3 is not None
    stop_now = sl if stage == 0 else (entry if stage == 1 else tp1)
    next_tp = tp1 if stage == 0 else (tp2 if stage == 1 else (tp3 if three else None))

    st = _STATE.get(key, {"ts": 0.0, "label": None, "sl": None, "n": 0})
    if st["n"] >= C.PUMP_TRAIL_MAX_MSGS:
        return None
    if now - st["ts"] < C.PUMP_TRAIL_MIN_GAP_SEC:
        return None

    def better(a: float, b: float) -> float:     # a, b dan necha R yaxshiroq (yo'nalish hisobida)
        return (a - b) * d / risk

    new_sl: Optional[float] = None
    new_tp: Optional[float] = None
    head = ""
    tip = ""

    if label == "strong" and r_now >= max(C.PUMP_TRAIL_MIN_R, 0.8):
        # Impuls kuchli: SL ni oxirgi 3 sham orqasiga suramiz (cho'qqiga yopishtirmaymiz)
        last3 = post[-3:]
        if long_:
            cand = min(x[3] for x in last3) - 0.1 * risk
        else:
            cand = max(x[2] for x in last3) + 0.1 * risk
        safe = (price - cand) * d >= 0.3 * risk          # narxga juda yaqin emas
        if safe and better(cand, stop_now) >= 0.25:
            new_sl = cand
        if next_tp is not None and abs(next_tp - price) <= 0.35 * risk and (price - next_tp) * d < 0:
            new_tp = next_tp + d * 1.0 * risk
        if new_sl is None and new_tp is None:
            return None
        head = f"🔥 Импульс усиливается  {bar(score)} {score}"
        tip = "Держим позицию, SL подтягиваем"
    elif label == "weak" and r_now >= C.PUMP_TRAIL_MIN_R:
        # Импульс слабеет: прибыль защищаем
        lock = entry + d * (0.5 * risk if r_now >= 1.0 else 0.05 * risk)
        cand = lock if better(lock, stop_now) >= 0.2 else None
        if cand is not None and (price - cand) * d >= 0.2 * risk:
            new_sl = cand
        if next_tp is not None:
            near = price + d * max(0.3 * risk, 0.0)
            if (near - price) * d > 0 and (next_tp - near) * d > 0:
                new_tp = near
        if new_sl is None and new_tp is None:
            return None
        head = f"⚠️ Импульс слабеет  {bar(score)} {score}"
        tip = "Зафиксируйте часть прибыли"
    else:
        return None

    # takror: bir xil holat va deyarli bir xil SL bo'lsa — jim
    if (st["label"] == label and new_sl is not None and st["sl"] is not None
            and abs(better(new_sl, st["sl"])) < 0.25 and new_tp is None):
        return None

    lines = [head, f"{side} · {r_now:+.1f}R · цена {_px(price)}"]
    if new_sl is not None:
        sl_r = ((new_sl - entry) * d) / risk
        where = "вход" if abs(sl_r) < 0.06 else f"{sl_r:+.1f}R"
        lines.append(f"🛑 SL → <code>{_px(new_sl)}</code> ({where})")
    if new_tp is not None:
        lines.append(f"🎯 TP → <code>{_px(new_tp)}</code>")
    lines.append(f"💡 {tip}")

    st = {"ts": now, "label": label, "sl": new_sl if new_sl is not None else st["sl"], "n": st["n"] + 1}
    _STATE[key] = st
    return "\n".join(lines)


def check_open(get_klines_fn, tf: str, interval: str = "5") -> List[dict]:
    """Ochiq signallar bo'yicha maslahatlar: [{symbol, tf, sent_ts, text}]. Sinxron (to_thread bilan chaqiring)."""
    if not C.PUMP_TRAIL:
        return []
    with db.tx() as conn:
        rows = conn.execute(
            "SELECT symbol, side, entry, sl, tp1, tp2, tp3, tp1_hit, sent_ts FROM signals "
            "WHERE status='open' AND tf=?", (tf,)
        ).fetchall()

    live = {(r[0], int(r[8] or 0)) for r in rows}
    for k in [k for k in _STATE if k not in live]:       # yopilganlarni xotiradan tozalash
        _STATE.pop(k, None)

    out: List[dict] = []
    now = time.time()
    for symbol, side, entry, sl, tp1, tp2, tp3, hit1, sent_ts in rows:
        try:
            if not sent_ts:
                continue
            c = get_klines_fn(symbol, interval, 60)
            if not c:
                continue
            c = c[:-1]                                    # faqat yopilgan shamlar
            risk = abs(entry - sl)
            m = measure(c, side, entry, risk, int(sent_ts) * 1000)
            if not m:
                continue
            text = advise(m, side, entry, sl, tp1, tp2, tp3, int(hit1 or 0),
                          (symbol, int(sent_ts)), now)
            if text:
                out.append({"symbol": symbol, "tf": tf, "sent_ts": int(sent_ts), "text": text})
        except Exception as e:
            logger.warning(f"{symbol} trail xatosi: {e}")
    return out
