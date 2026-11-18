"""
signals/pump_detector.py
PUMP / DUMP DETEKTORI — AMD strategiyasidan ALOHIDA modul.

AMD "sweep'dan keyingi qaytish"ni qidiradi, shuning uchun to'g'ri yo'nalishda uchib ketgan
coinlarni ko'rmaydi. Bu modul aynan shularni ushlaydi: qisqa vaqtda keskin narx harakati
+ hajm sakrashi (+ OI o'sishi, bo'lsa).

Ikki bosqich (API yukini kam ushlash uchun):
  1) Har skanda BITTA so'rov: Bybit tickers (barcha coinlar). Xotirada ~25 daqiqalik narx/OI
     "snapshot"lari saqlanadi. Narxi 5/15 daqiqada chegaraning ~60% idan ko'p o'zgargan
     coinlar nomzod bo'ladi (eng ko'pi PUMP_MAX_CANDIDATES ta).
  2) Nomzodlar uchun 1m shamlar: hajm sakrashi, qaytish (retrace), "kech qolganlik" va
     ball (0-100) hisoblanadi. Ball PUMP_MIN_SCORE dan past bo'lsa — xabar yuborilmaydi.

Natijalar `signals` jadvaliga tf="pump" bilan yoziladi (AMD statistikasi bilan ARALASHMAYDI)
va 5m shamlar bilan kuzatiladi (engine/evaluator.py, engine/sim.py qoidalari).

Muhim: bu "AMD signal" emas, impuls ogohlantirishi. Taxminiy SL = impuls yarmi, TP1 = 1R, TP2 = 2R.

Barcha funksiyalar sinxron. Async koddan: await asyncio.to_thread(...)
"""
from __future__ import annotations

import gc
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional, Tuple

import config as C
from engine import db, sim
from engine.volatility import conflicts_with_btc_regime, get_btc_regime
from signals import amd_volume as A

logger = logging.getLogger("nozik.pump")

TF = "pump"                  # signals jadvalidagi tf yorlig'i
EVAL_INTERVAL = "5"          # kuzatuv shamlari (Bybit interval)
HIST_SECONDS = 25 * 60       # snapshot saqlash muddati
PRE_RATIO = 0.6              # nomzod bo'lish uchun chegaraning shuncha ulushi
IMPULSE_SL_FRAC = 0.5        # SL = impuls uzunligining yarmi
MAX_RETRACE = 0.40           # impulsning 40% idan ko'p qaytgan bo'lsa — endi aylanib ketgan

# sym -> deque[(ts, price, oi_value)]   (oi_value 0 = ma'lumot yo'q)
_HIST: Dict[str, Deque[Tuple[float, float, float]]] = {}
_MEM_SENT: Dict[Tuple[str, str], float] = {}     # DB ishlamasa zaxira cooldown
STATE = {"scans": 0, "first_ts": 0.0, "last_ts": 0.0, "universe": 0,
         "candidates": 0, "alerts": 0, "last_error": ""}


@dataclass
class Alert:
    symbol: str
    kind: str                 # "PUMP" | "DUMP"
    side: str                 # "LONG" | "SHORT" (impuls davomi g'oyasi)
    score: int
    entry: float
    sl: float
    tp1: float
    tp2: float
    rr1: float
    rr2: float
    risk_pct: float
    ts: int                   # 5m sham ochilish vaqti (ms) — evaluator uchun
    ch5: float = 0.0
    ch15: float = 0.0
    vol_x: float = 0.0
    peak_x: float = 0.0
    oi_chg: Optional[float] = None
    ext: float = 0.0
    retr: float = 0.0
    turn24: float = 0.0
    btc_conflict: bool = False
    breakout: Optional[bool] = None
    tp3: Optional[float] = None          # faqat kuchli impulsda
    rr3: Optional[float] = None
    trend: Optional[str] = None          # 1h trend: "up" | "down" | "flat" | None (ma'lumot yo'q)
    line_broken: Optional[bool] = None   # 1h trend chizig'i buzilganmi (None — chiziq yo'q/ma'lumot yo'q)
    reasons: List[str] = field(default_factory=list)
    candles: list = field(default_factory=list)      # grafik uchun oxirgi 1m shamlar (DB ga yozilmaydi)
    tf: str = TF


# ------------------------------------------------------------------ yuklash
def _f(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def fetch_tickers() -> Optional[List[dict]]:
    d = A._get("https://api.bybit.com/v5/market/tickers", {"category": "linear"})
    if not d or d.get("retCode") != 0:
        return None
    return d["result"]["list"]


def _update_history(items: List[dict], now: float) -> List[Tuple[str, float, float]]:
    """Snapshotlarni yangilaydi. Qaytaradi: universe [(symbol, price, turnover24h)]."""
    uni: List[Tuple[str, float, float]] = []
    seen = set()
    for t in items:
        sym = t.get("symbol", "")
        if not sym.endswith("USDT") or sym in A.MAJORS:
            continue
        price, turn = _f(t.get("lastPrice")), _f(t.get("turnover24h"))
        if price <= 0 or not (C.PUMP_MIN_TURNOVER_USDT <= turn <= C.PUMP_MAX_TURNOVER_USDT):
            continue
        oi = _f(t.get("openInterestValue"))
        h = _HIST.setdefault(sym, deque())
        h.append((now, price, oi))
        while h and h[0][0] < now - HIST_SECONDS:
            h.popleft()
        seen.add(sym)
        uni.append((sym, price, turn))
    for sym in list(_HIST):          # universe'dan chiqib ketganlarni tozalaymiz
        if sym not in seen:
            del _HIST[sym]
    return uni


def _at(sym: str, secs_ago: float, now: float, tol: float):
    """secs_ago soniya oldingi snapshot (tol ichida eng yaqini) yoki None."""
    best, bd = None, tol + 1
    for snap in _HIST.get(sym, ()):
        d = abs(snap[0] - (now - secs_ago))
        if d < bd:
            best, bd = snap, d
    return best if bd <= tol else None


def _prefilter(now: float, uni: List[Tuple[str, float, float]]) -> List[Tuple[float, str, float]]:
    out = []
    for sym, price, turn in uni:
        r = 0.0
        h5, h15 = _at(sym, 300, now, 100), _at(sym, 900, now, 150)
        if h5 and h5[1] > 0:
            r = max(r, abs(price / h5[1] - 1) * 100 / C.PUMP_MOVE_5M_PCT)
        if h15 and h15[1] > 0:
            r = max(r, abs(price / h15[1] - 1) * 100 / C.PUMP_MOVE_15M_PCT)
        if r >= PRE_RATIO:
            out.append((r, sym, turn))
    out.sort(reverse=True)
    return out[:C.PUMP_MAX_CANDIDATES]


def _oi_change(sym: str, now: float) -> Optional[float]:
    """OI o'zgarishi (%) ~15 daqiqa (yo'q bo'lsa ~5 daqiqa) uchun. Ma'lumot yo'q bo'lsa None."""
    cur = _HIST.get(sym)
    if not cur or cur[-1][2] <= 0:
        return None
    old = _at(sym, 900, now, 150) or _at(sym, 300, now, 100)
    if not old or old[2] <= 0:
        return None
    return (cur[-1][2] / old[2] - 1) * 100


def _base_volume(base: list) -> float:
    """Bazaviy 1m hajm: eng baland ~10% shamlar chiqarib tashlangan o'rtacha. Shunda oldingi
    pump/spike shamlari bazani "shishirib", keyingi haqiqiy sakrashni yashirib qo'ymaydi."""
    vs = sorted(x[5] for x in base)
    if not vs:
        return 0.0
    k = max(1, len(vs) // 10)
    trimmed = vs[:-k]
    m = sum(trimmed) / len(trimmed) if trimmed else 0.0
    return m if m > 0 else sum(vs) / len(vs)


# ------------------------------------------------------------------- tahlil
def _is_breakout(c5: list, price: float, up: bool) -> Optional[bool]:
    """Narx oxirgi N soatlik 5m diapazon chegarasini (oxirgi 30 daqiqa impulsisiz) buzganmi?
    Ma'lumot yetarli bo'lmasa None (noma'lum)."""
    n = C.PUMP_BREAKOUT_HOURS * 12
    prior = c5[-(n + 6):-6] if c5 else []
    if len(prior) < 24:
        return None
    return price > max(x[2] for x in prior) if up else price < min(x[3] for x in prior)


def _ema(vals: list, n: int) -> float:
    k = 2.0 / (n + 1)
    e = vals[0]
    for v in vals[1:]:
        e = v * k + e * (1 - k)
    return e


def _swings(c: list, high: bool, k: int = 2) -> List[Tuple[int, float]]:
    """Tasdiqlangan swing nuqtalar (k ta sham chap/o'ngda). [(index, narx)]"""
    out = []
    for i in range(k, len(c) - k):
        v = c[i][2] if high else c[i][3]
        ok = True
        for j in range(i - k, i + k + 1):
            if j == i:
                continue
            if j < i:      # chapda qat'iy katta/kichik bo'lsa — swing emas; o'ngda teng bo'lsa ham emas (dublikat oldini olish)
                bad = (c[j][2] > v) if high else (c[j][3] < v)
            else:
                bad = (c[j][2] >= v) if high else (c[j][3] <= v)
            if bad:
                ok = False
                break
        if ok:
            out.append((i, v))
    return out


def trend_ctx(c1h: Optional[list], price: float, up: bool) -> Optional[dict]:
    """1h kontekst: EMA20/EMA50 yo'nalishi va trend chizig'i (oxirgi 2 ta swing).
    LONG uchun — pasayuvchi qarshilik chizig'i (lower highs); SHORT uchun — o'suvchi qo'llab-quvvatlash
    chizig'i (higher lows). `c1h` — faqat YOPILGAN 1h shamlar (eskidan yangiga).
    Ma'lumot yetarli bo'lmasa None."""
    if not c1h or len(c1h) < 55:
        return None
    c = c1h[-120:]
    closes = [x[4] for x in c]
    e20, e50 = _ema(closes, 20), _ema(closes, 50)
    gap = (e20 / e50 - 1) * 100 if e50 > 0 else 0.0
    trend = "up" if gap > 0.3 else "down" if gap < -0.3 else "flat"
    against = (trend == "down" and up) or (trend == "up" and not up)

    line, broken = None, None
    sw = _swings(c, high=up)
    prev = [q for q in sw[:-1] if sw and q[0] <= sw[-1][0] - 3]
    if sw and prev:
        (i1, v1), (i2, v2) = prev[-1], sw[-1]
        descending_ok = (v2 < v1) if up else (v2 > v1)     # lower highs / higher lows
        if descending_ok:
            n_now = len(c)                                   # hozirgi (shakllanayotgan) shamning indeksi
            line = v2 + (v2 - v1) / (i2 - i1) * (n_now - i2)
            buf = 0.003                                      # 0.3% bufer
            broken = price > line * (1 + buf) if up else price < line * (1 - buf)
    return {"trend": trend, "gap": gap, "against": against, "line": line, "broken": broken}


def evaluate(symbol: str, c: list, oi_chg: Optional[float] = None, regime: str = "neutral",
             turn24: float = 0.0, now_ms: Optional[int] = None,
             c5: Optional[list] = None, c1h: Optional[list] = None) -> dict:
    """1m shamlar (eskidan yangiga, oxirgisi — shakllanayotgan) bo'yicha tekshiradi.
    Qaytaradi: {"alert": Alert|None, "reject": sabab|None, "m": ko'rsatkichlar}.
    Sof funksiya (tarmoqsiz) — test va /pd_check uchun ham ishlatiladi."""
    T5, T15, VX = C.PUMP_MOVE_5M_PCT, C.PUMP_MOVE_15M_PCT, C.PUMP_VOL_X
    m: dict = {"symbol": symbol}
    if not c or len(c) < 50:
        return {"alert": None, "reject": "недостаточно истории 1m", "m": m}

    price = c[-1][4]
    last5, last15, last30 = c[-5:], c[-15:], c[-30:]
    base = c[-45:-5]
    ch5 = (price / last5[0][1] - 1) * 100
    ch15 = (price / last15[0][1] - 1) * 100
    r5, r15 = abs(ch5) / T5, abs(ch15) / T15
    m.update(price=price, ch5=ch5, ch15=ch15)
    if max(r5, r15) < 1:
        return {"alert": None, "reject": f"движение ниже порога ({ch5:+.1f}% / 5м, {ch15:+.1f}% / 15м)", "m": m}

    up = (ch5 if r5 >= r15 else ch15) > 0
    side, kind = ("LONG", "PUMP") if up else ("SHORT", "DUMP")

    # --- hajm
    base_v = _base_volume(base)
    if base_v <= 0:
        return {"alert": None, "reject": "нет базового объёма", "m": m}
    vol_x = (sum(x[5] for x in last5) / 5) / base_v
    peak_x = max(x[5] for x in last5) / base_v
    win_turn = sum(x[5] * x[4] for x in last5)
    m.update(vol_x=vol_x, peak_x=peak_x, win_turn=win_turn)
    if vol_x < VX:
        return {"alert": None, "reject": f"объём x{vol_x:.1f} < x{VX:g}", "m": m}
    if win_turn < C.PUMP_MIN_WINDOW_TURNOVER_USDT:
        return {"alert": None, "reject": f"оборот за 5 мин мал ({win_turn:,.0f} USDT) — неликвид", "m": m}

    # --- kech qolganlik (30 daqiqadagi umumiy yurish)
    lo30, hi30 = min(x[3] for x in last30), max(x[2] for x in last30)
    ext = (price / lo30 - 1) * 100 if up else (hi30 / price - 1) * 100
    m["ext"] = ext
    if ext > C.PUMP_MAX_EXT_PCT:
        return {"alert": None, "reject": f"уже ушла на {ext:.0f}% за 30 мин — поздно", "m": m}

    # --- impuls va qaytish
    i_lo = min(range(len(last15)), key=lambda i: last15[i][3])
    i_hi = max(range(len(last15)), key=lambda i: last15[i][2])
    start, peak = last15[i_lo][3], last15[i_hi][2]
    if up:
        if i_lo > i_hi:
            return {"alert": None, "reject": "нет чистого импульса вверх", "m": m}
        imp = peak - start
        retr = (peak - price) / imp if imp > 0 else 1.0
    else:
        start, peak = last15[i_hi][2], last15[i_lo][3]
        if i_hi > i_lo:
            return {"alert": None, "reject": "нет чистого импульса вниз", "m": m}
        imp = start - peak
        retr = (price - peak) / imp if imp > 0 else 1.0
    m["retr"] = retr
    if imp <= 0:
        return {"alert": None, "reject": "нет импульса", "m": m}
    if retr > MAX_RETRACE:
        return {"alert": None, "reject": f"откат {retr * 100:.0f}% импульса — уже разворачивается", "m": m}

    # --- vertikal "blow-off" cho'qqiga kirmaslik: impuls zinapoya (kamida bir oz orqaga qaytish) bo'lishi kerak.
    # Yo'l bo'yicha eng chuqur orqaga qaytish (running extreme'dan) impulsning PUMP_MIN_PULLBACK ulushidan kam bo'lsa —
    # bu bitta vertikal chiziq: odatda darhol 40-60% qaytadi va SL uriladi.
    if up:
        run, dd = last15[i_lo][2], 0.0
        for x in last15[i_lo + 1:]:
            dd = max(dd, run - x[3])
            run = max(run, x[2])
    else:
        run, dd = last15[i_hi][3], 0.0
        for x in last15[i_hi + 1:]:
            dd = max(dd, x[2] - run)
            run = min(run, x[3])
    pb = dd / imp
    m["pullback"] = pb
    if C.PUMP_STRICT and C.PUMP_MIN_PULLBACK > 0 and pb < C.PUMP_MIN_PULLBACK:
        return {"alert": None, "reject": f"вертикальный всплеск без отката ({pb * 100:.0f}% < "
                                         f"{C.PUMP_MIN_PULLBACK * 100:.0f}%) — вход на пике", "m": m}

    # --- daraja: SL = impulsning yarmi + ATR bufer (stop-hunt shovqini), TP1 = 1R, TP2 = 2R
    atr = sum(max(x[2] - x[3], abs(x[2] - c[k - 1][4]), abs(x[3] - c[k - 1][4]))
              for k, x in enumerate(c[-14:], start=len(c) - 14)) / 14
    struct = abs(price - (min(x[3] for x in c[-10:]) if up else max(x[2] for x in c[-10:])))
    risk = max(IMPULSE_SL_FRAC * imp, struct) + C.PUMP_SL_ATR * atr
    risk_pct = risk / price * 100
    m["risk_pct"] = risk_pct
    if risk_pct > C.PUMP_MAX_RISK_PCT:
        return {"alert": None, "reject": f"риск {risk_pct:.1f}% > {C.PUMP_MAX_RISK_PCT:g}% — слишком растянуто", "m": m}
    if risk_pct < 0.5:
        return {"alert": None, "reject": f"риск {risk_pct:.2f}% слишком мал", "m": m}
    sgn = 1 if up else -1
    sl, tp1, tp2 = price - sgn * risk, price + sgn * risk, price + sgn * 2 * risk
    cost_r = sim.cost_r(price, sl, C.FEE_PCT, C.SLIPPAGE_PCT)
    m["cost_r"] = cost_r
    if cost_r > C.PUMP_MAX_COST_R:
        return {"alert": None, "reject": f"издержки {cost_r:.2f}R > {C.PUMP_MAX_COST_R:.2f}R — "
                                         f"стоп слишком близко, комиссия съедает прибыль", "m": m}

    # --- qat'iy rejim: faqat aniq, davom etayotgan harakat
    n_dir = sum(1 for x in c[-4:] if (x[4] > x[1]) == up)
    breakout = _is_breakout(c5, price, up) if c5 else None
    m["breakout"] = breakout
    if C.PUMP_STRICT:
        if n_dir < 3 or (c[-2][4] > c[-2][1]) != up:
            return {"alert": None, "reject": "нет продолжения: свечи не в сторону движения", "m": m}
        if oi_chg is not None and oi_chg <= -2.0:
            return {"alert": None, "reject": f"OI {oi_chg:+.1f}% — это закрытие позиций, а не новый спрос", "m": m}
        if breakout is False:
            return {"alert": None, "reject": f"нет пробоя диапазона за {C.PUMP_BREAKOUT_HOURS} ч (локальный всплеск)", "m": m}

    # --- 1h trend / trend chizig'i: trendga qarshi pump/dump — ko'pincha "dead cat bounce" (SL shundan)
    tc = trend_ctx(c1h, price, up) if (C.PUMP_TREND_FILTER and c1h) else None
    if tc:
        m.update(trend=tc["trend"], line_broken=tc["broken"])
        line_txt = "нисходящей" if up else "восходящей"
        if tc["line"] is not None and tc["broken"] is False:
            return {"alert": None, "reject": f"против 1ч тренда: цена не пробила {line_txt} линию тренда", "m": m}
        if tc["against"] and tc["line"] is None:
            return {"alert": None, "reject": f"против 1ч тренда (EMA20/50 {tc['gap']:+.1f}%), линии тренда для пробоя нет", "m": m}

    # --- ball
    reasons: List[str] = []
    score = 35.0
    mr = max(r5, r15)
    score += min(20.0, 10 + (mr - 1) * 10)
    reasons.append(f"Движение {ch5:+.1f}% / 5м, {ch15:+.1f}% / 15м")
    vr = vol_x / VX
    score += min(20.0, 10 + (vr - 1) * 10)
    reasons.append(f"Объём x{vol_x:.1f} (пик x{peak_x:.1f})")
    if oi_chg is not None:
        if oi_chg >= 1.0:
            score += 10
            reasons.append(f"OI {oi_chg:+.1f}% — новые позиции")
        elif oi_chg <= -1.0:
            score -= 5
            reasons.append(f"OI {oi_chg:+.1f}% — закрытие позиций (движение слабее)")
        else:
            reasons.append(f"OI {oi_chg:+.1f}%")
    if 0.05 <= retr <= 0.30:
        score += 5
        reasons.append(f"Откат {retr * 100:.0f}% и продолжение")
    if n_dir >= 3:
        score += 5
    if breakout:
        score += 10
        reasons.append(f"Пробой диапазона {C.PUMP_BREAKOUT_HOURS} ч")
    if ext > 0.6 * C.PUMP_MAX_EXT_PCT:
        score -= 10
        reasons.append(f"Уже ушла {ext:.0f}% за 30 мин")
    if tc:
        if not tc["against"]:
            if tc["trend"] != "flat":
                score += 8
                reasons.append("По 1ч тренду")
            if tc["broken"]:
                score += 4
                reasons.append("Пробой линии тренда 1ч")
        else:
            score -= 5
            reasons.append("Разворот: против 1ч EMA, но линия тренда пробита")
    conflict = conflicts_with_btc_regime(symbol, side, regime)
    if conflict:
        score -= C.PUMP_BTC_PENALTY
        reasons.append("Против тренда BTC")
    score_i = max(0, min(100, int(round(score))))
    m["score"] = score_i
    if score_i < C.PUMP_MIN_SCORE:
        return {"alert": None, "reject": f"скор {score_i} < {C.PUMP_MIN_SCORE}", "m": m}

    # --- kuchli impuls -> TP3: yuqori ball + katta hajm + diapazon sinishi + trendga qarshi emas + OI o'sishi/noma'lum
    tp3 = rr3 = None
    strong = (C.PUMP_TP3_ENABLED and score_i >= C.PUMP_TP3_MIN_SCORE and vol_x >= C.PUMP_TP3_VOL_X
              and breakout is True and not conflict and mr >= 1.2
              and (oi_chg is None or oi_chg >= 0.0) and not (tc and tc["against"]))
    if strong:
        rr3 = float(C.PUMP_TP3_RR)
        tp3 = price + sgn * rr3 * risk
        reasons.append(f"Сильный импульс → добавлен TP3 ({rr3:g}R)")

    tfms = sim.tf_ms(EVAL_INTERVAL)
    ts = int((now_ms or time.time() * 1000) // tfms * tfms)
    alert = Alert(
        symbol=symbol, kind=kind, side=side, score=score_i, entry=price, sl=sl, tp1=tp1, tp2=tp2,
        rr1=1.0, rr2=2.0, risk_pct=risk_pct, ts=ts, ch5=ch5, ch15=ch15, vol_x=vol_x,
        peak_x=peak_x, oi_chg=oi_chg, ext=ext, retr=retr, turn24=turn24,
        btc_conflict=conflict, breakout=breakout, reasons=reasons, tp3=tp3, rr3=rr3,
        trend=(tc["trend"] if tc else None), line_broken=(tc["broken"] if tc else None),
        candles=c[-60:])
    return {"alert": alert, "reject": None, "m": m}


# ---------------------------------------------------------- cooldown / limit
def _recent(symbol: str, side: str, sec: int) -> bool:
    try:
        with db.tx() as conn:
            row = conn.execute(
                "SELECT 1 FROM signals WHERE symbol=? AND tf=? AND side=? AND sent_ts>=? LIMIT 1",
                (symbol, TF, side, int(time.time()) - sec)).fetchone()
        return row is not None
    except Exception as e:
        logger.warning(f"pump cooldown tekshiruvi xatosi: {e}")
        return _MEM_SENT.get((symbol, side), 0) >= time.time() - sec


def _recent_sl(symbol: str, side: str, sec: int) -> bool:
    """Shu coin+yo'nalish yaqinda SL urganmi? (qayta kirmaslik uchun uzoqroq cooldown)"""
    if sec <= 0:
        return False
    try:
        with db.tx() as conn:
            row = conn.execute(
                "SELECT 1 FROM signals WHERE symbol=? AND tf=? AND side=? AND status='sl' "
                "AND closed_ts>=? LIMIT 1",
                (symbol, TF, side, int(time.time()) - sec)).fetchone()
        return row is not None
    except Exception as e:
        logger.warning(f"pump SL cooldown xatosi: {e}")
        return False


def _fetch_1h_closed(sym: str) -> Optional[list]:
    c = A.bybit_klines(sym, "60", 120)
    time.sleep(0.1)
    return c[:-1] if c else None            # shakllanayotgan shamni tashlaymiz


def _sent_last_hour() -> int:
    try:
        with db.tx() as conn:
            return int(conn.execute(
                "SELECT COUNT(*) FROM signals WHERE tf=? AND sent_ts>=?",
                (TF, int(time.time()) - 3600)).fetchone()[0])
    except Exception as e:
        logger.warning(f"pump soatlik limit xatosi: {e}")
        return 0


def mark_sent(a: Alert):
    _MEM_SENT[(a.symbol, a.side)] = time.time()


# --------------------------------------------------------------------- skan
def scan() -> List[Alert]:
    """Bitta skan: tickers -> nomzodlar -> 1m tahlil. Yuboriladigan Alert'lar (ball bo'yicha)."""
    now = time.time()
    STATE["scans"] += 1
    STATE["first_ts"] = STATE["first_ts"] or now
    STATE["last_ts"] = now
    items = fetch_tickers()
    if items is None:
        STATE["last_error"] = "Bybit tickers olinmadi"
        logger.warning("Pump: Bybit tickers olinmadi")
        return []
    STATE["last_error"] = ""
    uni = _update_history(items, now)
    cands = _prefilter(now, uni)
    STATE["universe"], STATE["candidates"] = len(uni), len(cands)
    if not cands:
        return []

    room = C.PUMP_MAX_ALERTS_PER_HOUR - _sent_last_hour()
    if room <= 0:
        logger.info("Pump: soatlik limitga yetildi")
        return []

    regime = "neutral"
    if C.USE_BTC_FILTER:
        try:
            regime = get_btc_regime()
        except Exception:
            regime = "neutral"

    out: List[Alert] = []
    for _, sym, turn in cands:
        c = A.bybit_klines(sym, "1", 60)
        time.sleep(0.1)
        if not c:
            continue
        oi = _oi_change(sym, now)
        res = evaluate(sym, c, oi, regime, turn)
        if res["alert"]:                      # 2-bosqich: 5m kontekst (diapazon sinishi) + 1h trend
            c5 = A.bybit_klines(sym, "5", 130)
            time.sleep(0.1)
            c1h = _fetch_1h_closed(sym) if C.PUMP_TREND_FILTER else None
            res = evaluate(sym, c, oi, regime, turn, c5=c5, c1h=c1h)
        a = res["alert"]
        if not a:
            logger.debug(f"Pump {sym}: {res['reject']}")
            continue
        if _recent(sym, a.side, C.PUMP_COOLDOWN_SECONDS):
            continue
        if _recent_sl(sym, a.side, C.PUMP_SL_COOLDOWN_SECONDS):
            logger.info(f"Pump {sym}: yaqinda SL urgan, qayta kirilmaydi")
            continue
        out.append(a)
    out.sort(key=lambda x: -x.score)
    out = out[:min(C.PUMP_MAX_ALERTS_PER_SCAN, room)]
    STATE["alerts"] += len(out)
    return out


def check(symbol: str) -> Optional[dict]:
    """/pd_check: bitta coin uchun hozirgi holat (nomzod filtrisiz) va rad etish sababi."""
    c = A.bybit_klines(symbol, "1", 60)
    if not c:
        return None
    now = time.time()
    regime = "neutral"
    if C.USE_BTC_FILTER:
        try:
            regime = get_btc_regime()
        except Exception:
            pass
    oi = _oi_change(symbol, now)
    res = evaluate(symbol, c, oi, regime)
    if res["alert"]:
        c1h = _fetch_1h_closed(symbol) if C.PUMP_TREND_FILTER else None
        res = evaluate(symbol, c, oi, regime, c5=A.bybit_klines(symbol, "5", 130), c1h=c1h)
    return res


# ------------------------------------------------------------------- matn
def _pct(a: Alert, v: float) -> str:
    return f"{(v - a.entry) / a.entry * 100:+.2f}%"


def format_alert(a: Alert) -> str:
    """Telegram HTML matni."""
    from engine.tg import p
    up = a.kind == "PUMP"
    head = "🚀 PUMP" if up else "🩸 DUMP"
    strong = "  🔥 СИЛЬНЫЙ" if a.score >= 80 else ""
    oi = f"{a.oi_chg:+.1f}%" if a.oi_chg is not None else "нет данных"
    hours = C.PUMP_EXPIRE_CANDLES * 5 / 60
    line = "━━━━━━━━━━━━━━━━"
    brk = f"🧱 Пробой диапазона {C.PUMP_BREAKOUT_HOURS} ч\n" if a.breakout else ""
    tr = {"up": "↑ вверх", "down": "↓ вниз", "flat": "→ боковик"}.get(a.trend or "", "")
    if tr:
        brk += f"📐 Тренд 1ч: {tr}" + (" · линия тренда пробита" if a.line_broken else "") + "\n"
    tp3_line = ""
    if a.tp3:
        tp3_line = (f"🏆 TP3: <code>{p(a.tp3)}</code> ({_pct(a, a.tp3)}) — сильный импульс\n"
                    f"📌 Закрытие 40% / 30% / 30%: после TP1 SL → вход, после TP2 SL → TP1\n")
    return (
        f"{head} · <b>{a.symbol}</b>{strong}\n"
        f"{line}\n"
        f"📈 {a.ch5:+.1f}% за 5 мин · {a.ch15:+.1f}% за 15 мин\n"
        f"📊 Объём: x{a.vol_x:.1f} от нормы (пик x{a.peak_x:.1f})\n"
        f"🧭 OI: {oi} · оборот 24ч: {a.turn24 / 1e6:.1f}M USDT\n"
        f"{brk}"
        f"⭐ Скор: {a.score}/100"
        f"{'  ⚠️ против BTC' if a.btc_conflict else ''}\n"
        f"{line}\n"
        f"💡 Идея по импульсу: <b>{a.side}</b> (риск {a.risk_pct:.1f}%)\n"
        f"🎯 Вход ≈ <code>{p(a.entry)}</code>\n"
        f"🛑 SL: <code>{p(a.sl)}</code> ({_pct(a, a.sl)})\n"
        f"✅ TP1: <code>{p(a.tp1)}</code> ({_pct(a, a.tp1)}) · TP2: <code>{p(a.tp2)}</code> ({_pct(a, a.tp2)})\n"
        f"{tp3_line}"
        f"⏱ Срок: ~{hours:.0f} ч\n"
        f"{line}\n"
        f"⚠️ Это детектор импульса, не AMD-сигнал. Вход по движению — повышенный риск; "
        f"если цена уже ушла дальше, не догоняйте."
    )


def format_check(symbol: str, res: dict) -> str:
    m, a = res["m"], res["alert"]
    lines = [f"🔎 {symbol} — детектор pump/dump (1m)\n"]
    if "ch5" in m:
        lines.append(f"Движение: {m['ch5']:+.2f}% / 5м, {m['ch15']:+.2f}% / 15м "
                     f"(порог {C.PUMP_MOVE_5M_PCT:g}% / {C.PUMP_MOVE_15M_PCT:g}%)")
    if "vol_x" in m:
        lines.append(f"Объём: x{m['vol_x']:.1f} (нужно x{C.PUMP_VOL_X:g}), пик x{m['peak_x']:.1f}")
    if "ext" in m:
        lines.append(f"Ушла за 30 мин: {m['ext']:.1f}% (макс. {C.PUMP_MAX_EXT_PCT:g}%)")
    if "retr" in m:
        lines.append(f"Откат от экстремума: {m['retr'] * 100:.0f}% (макс. {MAX_RETRACE * 100:.0f}%)")
    if m.get("breakout") is not None:
        lines.append("Пробой диапазона: " + ("да ✅" if m["breakout"] else "нет ❌"))
    if "pullback" in m:
        lines.append(f"Откат внутри импульса: {m['pullback'] * 100:.0f}% (нужно от {C.PUMP_MIN_PULLBACK * 100:.0f}%)")
    if "cost_r" in m:
        lines.append(f"Риск {m['risk_pct']:.1f}% · издержки {m['cost_r']:.2f}R (макс. {C.PUMP_MAX_COST_R:.2f}R)")
    if m.get("trend"):
        lines.append(f"Тренд 1ч: {m['trend']}" + (", линия пробита ✅" if m.get("line_broken") else ""))
    if "score" in m:
        lines.append(f"Скор: {m['score']}/100 (порог {C.PUMP_MIN_SCORE})")
    lines.append("")
    if a:
        lines.append(f"✅ Условия выполнены: {a.kind} ({a.side}). Сигнал отправился бы, если нет cooldown.")
    else:
        lines.append(f"❌ Не проходит: {res['reject']}")
    return "\n".join(lines)


# ------------------------------------------------------------------ backtest
def _aggregate_5m(c1: list) -> list:
    """1m -> 5m (faqat to'liq 5 ta shamdan iborat bucketlar)."""
    out, cur, key = [], [], None
    for x in c1:
        k = x[0] // 300000
        if k != key:
            if len(cur) == 5:
                out.append((cur[0][0] // 300000 * 300000, cur[0][1], max(y[2] for y in cur),
                            min(y[3] for y in cur), cur[-1][4], sum(y[5] for y in cur)))
            cur, key = [], k
        cur.append(x)
    if len(cur) == 5:
        out.append((cur[0][0] // 300000 * 300000, cur[0][1], max(y[2] for y in cur),
                    min(y[3] for y in cur), cur[-1][4], sum(y[5] for y in cur)))
    return out


def backtest(symbol: str, bars: Optional[int] = None) -> Optional[dict]:
    """Detektorni tarixiy 1m ma'lumotda sinaydi (jonli bilan bir xil evaluate()).
    Kirish = signal shamining yopilish narxi; SL/TP 1m shamlar bilan (bir shamda ikkalasi
    urilsa SL hisoblanadi); xarajatlar R da ayriladi. OI va BTC rejimi tarixda yo'q — hisobga olinmaydi."""
    bars = bars or C.PUMP_BACKTEST_BARS
    c1 = A.bybit_klines_history(symbol, "1", bars)
    if len(c1) < 400:
        return None
    b5 = _aggregate_5m(c1)
    h1: list = []
    if C.PUMP_TREND_FILTER:                    # 1h tarix: signal paytida faqat YOPILGAN 1h shamlar (kelajakka qarash yo'q)
        h1 = A.bybit_klines_history(symbol, "60", len(c1) // 60 + 130)
    exp = C.PUMP_EXPIRE_CANDLES * 5            # 1m shamlarda
    cool = max(1, C.PUMP_COOLDOWN_SECONDS // 60)
    trades: List[dict] = []
    k, i, kh = 0, 59, 0
    while i < len(c1) - 1:
        w = c1[i - 59:i + 1]
        res = evaluate(symbol, w, None, "neutral", 0.0, now_ms=w[-1][0])
        if res["alert"]:
            while k < len(b5) and b5[k][0] + 300000 <= w[-1][0] + 60000:
                k += 1
            while kh < len(h1) and h1[kh][0] + 3600000 <= w[-1][0] + 60000:
                kh += 1
            res = evaluate(symbol, w, None, "neutral", 0.0, now_ms=w[-1][0],
                           c5=b5[max(0, k - 130):k], c1h=(h1[max(0, kh - 120):kh] if h1 else None))
        a = res["alert"]
        if not a:
            i += 1
            continue
        end = min(len(c1), i + 1 + exp)
        hit1, status, gross = False, None, None
        for j in range(i + 1, end):
            if a.tp3:
                hit1, status, gross = sim.step3(a.side, a.entry, a.sl, a.tp1, a.tp2, a.tp3, 1.0, 2.0,
                                                a.rr3, int(hit1), c1[j][2], c1[j][3])
            else:
                hit1, status, gross = sim.step(a.side, a.entry, a.sl, a.tp1, a.tp2, 1.0, 2.0,
                                               hit1, c1[j][2], c1[j][3])
            if status:
                break
        if not status:
            if end - i - 1 < exp:              # ma'lumot tugadi — natija noma'lum
                break
            status = "expired"
            gross = (sim.expire_gross3(a.side, a.entry, a.sl, 1.0, 2.0, int(hit1), c1[end - 1][4]) if a.tp3
                     else sim.expire_gross(a.side, a.entry, a.sl, 1.0, hit1, c1[end - 1][4]))
        cost = sim.cost_r(a.entry, a.sl, C.FEE_PCT, C.SLIPPAGE_PCT)
        trades.append({"side": a.side, "score": a.score, "status": status, "tp3": bool(a.tp3),
                       "gross": gross, "net": gross - cost, "cost": cost})
        i += cool                               # cooldown
    return {"symbol": symbol, "bars": len(c1), "trades": trades}


def backtest_many(symbols: List[str]) -> Optional[dict]:
    allt, per, ok = [], [], 0
    bars = 0
    for sym in symbols:
        r = backtest(sym)
        if not r:
            continue
        ok += 1
        bars += r["bars"]
        allt.extend(r["trades"])
        per.append((sym, len(r["trades"]), sum(t["net"] for t in r["trades"])))
    if not ok:
        return None
    return summarize(allt, per, ok, bars)


def summarize(trades: List[dict], per: list, ok: int, bars: int) -> dict:
    n = len(trades)
    nets = [t["net"] for t in trades]
    gains, losses = sum(x for x in nets if x > 0), -sum(x for x in nets if x < 0)
    by_status: Dict[str, int] = {}
    for t in trades:
        by_status[t["status"]] = by_status.get(t["status"], 0) + 1
    return {
        "symbols_ok": ok, "bars": bars, "trades": n,
        "wins": sum(1 for x in nets if x > 0),
        "winrate": round(sum(1 for x in nets if x > 0) / n * 100, 1) if n else 0,
        "total_R": round(sum(nets), 2),
        "gross_R": round(sum(t["gross"] for t in trades), 2),
        "cost_R": round(sum(t["cost"] for t in trades), 2),
        "avg_R": round(sum(nets) / n, 2) if n else 0,
        "pf": round(gains / losses, 2) if losses > 0 else None,
        "by_status": by_status, "strong": sum(1 for t in trades if t.get("tp3")),
        "per_symbol": sorted(per, key=lambda x: -x[2]),
        "profitable_symbols": sum(1 for _, nn, r in per if nn and r > 0),
        "active_symbols": sum(1 for _, nn, _ in per if nn),
    }


def format_backtest(r: dict) -> str:
    days = r["bars"] / max(r["symbols_ok"], 1) / 60 / 24
    n = r["trades"]
    pf = r["pf"] if r["pf"] is not None else "—"
    bs = r["by_status"]
    lines = [
        f"🧪 Pump/Dump бэктест, ~{days:.1f} дн., токенов: {r['symbols_ok']}", "",
        f"Сделок: {n}",
        f"Прибыльных: {r['wins']} ({r['winrate']}%)",
        f"Итого (после издержек): {r['total_R']:+.2f}R",
        f"До издержек: {r['gross_R']:+.2f}R | издержки: -{r['cost_R']:.2f}R",
        f"Среднее: {r['avg_R']:+.2f}R | Profit factor: {pf}",
        f"TP3: {bs.get('tp3', 0)} | TP2: {bs.get('tp2', 0)} | TP1+TP2: {bs.get('lock', 0)} | "
        f"TP1+BE: {bs.get('be', 0)} | SL: {bs.get('sl', 0)} | по сроку: {bs.get('expired', 0)}",
        f"Сильных (с TP3): {r.get('strong', 0)}",
    ]
    if r["active_symbols"]:
        lines.append(f"Токенов в плюсе: {r['profitable_symbols']}/{r['active_symbols']}")
        top = r["per_symbol"]
        lines.append("Лучшие: " + ", ".join(f"{s} {t:+.1f}R" for s, nn, t in top[:3] if nn))
        lines.append("Худшие: " + ", ".join(f"{s} {t:+.1f}R" for s, nn, t in top[-3:][::-1] if nn))
    if n < 30:
        lines.append("\n⚠️ Меньше 30 сделок — статистически ненадёжно. Увеличьте PUMP_BACKTEST_BARS "
                     "или проверьте больше токенов.")
    lines.append("\nℹ️ OI и режим BTC в истории недоступны, поэтому в бэктесте они не участвуют "
                 "(в боте они дополнительно фильтруют).")
    return "\n".join(lines)


# =================================================================== Telegram
import asyncio  # noqa: E402

from config import ADMIN_CHAT_IDS  # noqa: E402
from engine import tg  # noqa: E402
from engine.evaluator import evaluate_pending, get_stats, record_signal  # noqa: E402

_lock = asyncio.Lock()


def _is_admin(update) -> bool:
    user = update.effective_user
    return user is not None and user.id in ADMIN_CHAT_IDS


async def _run(bot) -> int:
    """Bitta skan + yuborish. Yuborilgan alertlar soni."""
    async with _lock:
        alerts = await asyncio.to_thread(scan)
        sent = 0
        for a in alerts:
            try:
                await asyncio.to_thread(record_signal, a)
            except Exception as e:
                logger.error(f"Pump signalni yozishda xato ({a.symbol}): {e}")
            mark_sent(a)
            buf = None
            if C.PUMP_SEND_CHART:             # grafik xatosi xabarni to'xtatmaydi
                try:
                    from engine.pump_chart import generate_pump_chart
                    buf = await asyncio.to_thread(generate_pump_chart, a)
                except Exception as e:
                    logger.warning(f"Pump grafigi chizilmadi ({a.symbol}): {e}")
            a.candles = []                    # xotirani bo'shatish
            await tg.broadcast(bot, ADMIN_CHAT_IDS, format_alert(a), buf, parse_mode="HTML")
            buf = None
            sent += 1
            logger.info(f"Pump alert: {a.symbol} {a.kind} skor={a.score} "
                        f"5m={a.ch5:+.1f}% x{a.vol_x:.1f}")
        if sent:
            gc.collect()                      # grafik ishlatgan xotirani qaytarish (Render bepul tarifi)
        return sent


async def _job_scan(context):
    if _lock.locked():
        return
    try:
        await _run(context.bot)
    except Exception as e:
        STATE["last_error"] = str(e)[:120]
        logger.error(f"Pump skanerlashda xato: {e}")


def _progress_text(ev: dict) -> str:
    sym, side, st, three = ev["symbol"], ev["side"], ev["stage"], ev["three"]
    if st == 1:
        part = "40%" if three else "50%"
        return (f"🎯 TP1 взят [pump]\n{sym} {side}: закройте ~{part}, SL перенесите на вход "
                f"({ev['entry']:.6g})")
    if not three:
        return f"🎯🎯 TP2 взят [pump]\n{sym} {side}: позиция закрыта полностью."
    return (f"🎯🎯 TP2 взят [pump]\n{sym} {side}: закройте ещё ~30%, SL перенесите на TP1 "
            f"({ev['tp1']:.6g}), остаток — к TP3 ({ev['tp3']:.6g})")


async def _job_eval(context):
    events: list = []
    try:
        closed = await asyncio.to_thread(
            evaluate_pending, A.bybit_klines, TF, EVAL_INTERVAL, C.PUMP_EXPIRE_CANDLES, events)
    except Exception as e:
        logger.error(f"Pump baholashda xato: {e}")
        return
    for ev in events:                 # oraliq bosqichlar: pozitsiyani qo'lda boshqarish uchun ko'rsatma
        await tg.broadcast(context.bot, ADMIN_CHAT_IDS, _progress_text(ev))
    for r in closed:
        text = (f"{tg.RESULT_TEXT.get(r['status'], r['status'])} [pump]\n"
                f"{r['symbol']} {r['side']}: {r['result_r']:+.2f}R")
        await tg.broadcast(context.bot, ADMIN_CHAT_IDS, text)


async def cmd_pd_scan(update, context):
    if not _is_admin(update):
        return
    if _lock.locked():
        await update.message.reply_text("⏳ Скан уже идёт, подождите.")
        return
    warm = (time.time() - STATE["first_ts"]) / 60 if STATE["first_ts"] else 0
    await update.message.reply_text("🔍 Проверяю резкие движения (pump/dump)...")
    try:
        sent = await _run(context.bot)
    except Exception as e:
        logger.error(f"Pump /pd_scan xatosi: {e}")
        await update.message.reply_text("❌ Ошибка при сканировании. Проверьте логи.")
        return
    text = (f"📊 Pump/Dump скан: монет в наблюдении {STATE['universe']}, "
            f"кандидатов {STATE['candidates']}, отправлено {sent}.")
    if warm < 5:
        text += ("\n⏳ История цен ещё копится (нужно ~5 мин после запуска; для порога 15м — ~15 мин), "
                 "поэтому часть движений пока не видна.")
    if STATE["last_error"]:
        text += f"\n⚠️ {STATE['last_error']}"
    await update.message.reply_text(text)


async def cmd_pd_check(update, context):
    if not _is_admin(update):
        return
    if not context.args:
        await update.message.reply_text("Пример: /pd_check PEPEUSDT")
        return
    symbol = context.args[0].upper()
    res = await asyncio.to_thread(check, symbol)
    if not res:
        await update.message.reply_text("❌ Не удалось получить данные (проверьте символ).")
        return
    await update.message.reply_text(format_check(symbol, res))


async def cmd_pd_stats(update, context):
    if not _is_admin(update):
        return
    st = await asyncio.to_thread(get_stats, TF)
    bs = st["by_status"]
    pf = st["profit_factor"] if st["profit_factor"] is not None else "—"
    text = (
        "📈 Статистика pump/dump (после издержек, отдельно от AMD):\n\n"
        f"Закрытых: {st['total_closed']}\n"
        f"Прибыльных: {st['wins']} ({st['winrate_pct']}%)\n"
        f"Итого: {st['total_r']:+.2f}R (до издержек {st['gross_total_r']:+.2f}R)\n"
        f"Среднее: {st['avg_r']:+.2f}R | Profit factor: {pf}\n"
        f"Открытых: {st['pending']}\n\n"
        f"TP3: {bs.get('tp3', 0)} | TP2: {bs.get('tp2', 0)} | TP1+TP2: {bs.get('lock', 0)} | "
        f"TP1+BE: {bs.get('be', 0)} | SL: {bs.get('sl', 0)} | Истёк срок: {bs.get('expired', 0)}"
    )
    if st["total_closed"] < 30:
        text += "\n\n⚠️ Меньше 30 сделок — выводы делать рано."
    await update.message.reply_text(text)


_bt_lock = asyncio.Lock()


async def cmd_pd_backtest(update, context):
    if not _is_admin(update):
        return
    if _bt_lock.locked():
        await update.message.reply_text("⏳ Бэктест уже идёт, подождите.")
        return
    async with _bt_lock:
        if context.args:
            syms = [context.args[0].upper()]
            await update.message.reply_text(f"🧪 {syms[0]}: бэктест pump/dump (до 1 мин)...")
        else:
            n = C.BACKTEST_TOP_N
            syms = await asyncio.to_thread(lambda: A.universe()[:n])
            await update.message.reply_text(
                f"🧪 Бэктест pump/dump по {len(syms)} токенам (~{C.PUMP_BACKTEST_BARS / 1440:.0f} дн.). "
                "Это займёт 1–3 минуты...")
        r = await asyncio.to_thread(backtest_many, syms)
    if not r:
        await update.message.reply_text("❌ Не удалось получить данные.")
        return
    await update.message.reply_text(format_backtest(r))


def settings_text() -> str:
    return (
        "🚀 Детектор pump/dump (отдельно от AMD): "
        f"{'включён' if C.USE_PUMP_DETECTOR else 'выключен'}\n"
        f"Порог движения: {C.PUMP_MOVE_5M_PCT:g}% / 5м или {C.PUMP_MOVE_15M_PCT:g}% / 15м\n"
        f"Объём: от x{C.PUMP_VOL_X:g} | мин. скор {C.PUMP_MIN_SCORE} | "
        f"строгий режим: {'да' if C.PUMP_STRICT else 'нет'} | график: {'да' if C.PUMP_SEND_CHART else 'нет'}\n"
        f"Оборот 24ч: {C.PUMP_MIN_TURNOVER_USDT / 1e6:g}M — {C.PUMP_MAX_TURNOVER_USDT / 1e6:g}M USDT\n"
        f"Фильтры v6.2: тренд 1ч {'да' if C.PUMP_TREND_FILTER else 'нет'} | мин. откат {C.PUMP_MIN_PULLBACK * 100:.0f}% | "
        f"SL +{C.PUMP_SL_ATR:g}×ATR | макс. издержки {C.PUMP_MAX_COST_R:.2f}R | SL-cooldown {C.PUMP_SL_COOLDOWN_SECONDS // 60} мин\n"
        f"Скан: каждые {C.PUMP_SCAN_INTERVAL_SECONDS} с | cooldown {C.PUMP_COOLDOWN_SECONDS // 60} мин | "
        f"макс. {C.PUMP_MAX_ALERTS_PER_HOUR}/час\n"
    )


def register(app):
    """bot.py main() ichida chaqiriladi."""
    from telegram.ext import CommandHandler
    app.add_handler(CommandHandler("pd_scan", cmd_pd_scan))
    app.add_handler(CommandHandler("pd_check", cmd_pd_check))
    app.add_handler(CommandHandler("pd_stats", cmd_pd_stats))
    app.add_handler(CommandHandler("pd_backtest", cmd_pd_backtest))
    if not C.USE_PUMP_DETECTOR:
        logger.info("Pump detektori o'chirilgan (USE_PUMP_DETECTOR=0)")
        return
    interval = max(30, C.PUMP_SCAN_INTERVAL_SECONDS)
    first = interval - (time.time() % interval) + 5
    app.job_queue.run_repeating(_job_scan, interval=interval, first=first)
    app.job_queue.run_repeating(_job_eval, interval=300, first=90)
    logger.info(f"Pump detektori ishga tushdi: har {interval} s")
