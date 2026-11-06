"""
signals/amd_volume.py
AMD (Accumulation -> Manipulation -> Distribution) + Bybit/Binance volume.
Focus: small-cap USDT perpetual futures. Only dependency: requests.

All functions are synchronous. From async bot code use:
    signals = await asyncio.to_thread(scan)
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import requests

# candle = (ts_ms, open, high, low, close, volume)
Candle = Tuple[int, float, float, float, float, float]

CFG = {
    "tf": "15",              # execution timeframe (Bybit), 15 min
    "htf": "60",             # trend filter timeframe, 1h
    "bn_tf": "15m",          # Binance timeframe
    "min_turnover": 3_000_000,    # 24h USDT turnover: lower bound
    "max_turnover": 120_000_000,  # upper bound (cuts large caps)
    "max_symbols": 150,
    "range_n": 32,           # accumulation window (candles)
    "base_n": 64,            # baseline volume window before the range
    "min_range_pct": 0.8,
    "max_range_pct": 5.0,
    "acc_vol_max": 0.9,      # range volume / baseline volume
    "sweep_min_pct": 0.15,   # min wick beyond range edge, %
    "sweep_max_width_frac": 0.5,
    "sweep_wick_min": 0.4,
    "sweep_vol_min": 1.8,
    "confirm_vol_min": 1.3,
    "confirm_body_min": 0.55,
    "max_risk_pct": 3.5,
    "min_rr1": 0.5,
    "min_rr2": 1.5,
    "min_score": 70,
    "cooldown_sec": 4 * 3600,
    "req_sleep": 0.12,
}

MAJORS = {
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT",
    "ADAUSDT", "TRXUSDT", "LINKUSDT", "AVAXUSDT", "TONUSDT", "LTCUSDT",
    "DOTUSDT", "BCHUSDT", "SUIUSDT",
}

EXTRA_SCORE_MAX = 17  # max bonus from 1h + Binance data


@dataclass
class Signal:
    symbol: str
    side: str            # "LONG" | "SHORT"
    entry: float
    sl: float
    tp1: float
    tp2: float
    rr1: float
    rr2: float
    risk_pct: float
    score: int
    range_high: float
    range_low: float
    ts: int
    reasons: List[str] = field(default_factory=list)
    candles: list = field(default_factory=list, repr=False)  # last ~60 candles (chart)


# ----------------------------------------------------------------- helpers
def _atr(c: List[Candle], n: int = 14) -> float:
    trs = []
    for i in range(1, len(c)):
        h, l, pc = c[i][2], c[i][3], c[i - 1][4]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    t = trs[-n:]
    return sum(t) / len(t) if t else 0.0


def _ema(vals: List[float], n: int) -> float:
    k = 2 / (n + 1)
    e = vals[0]
    for v in vals[1:]:
        e = v * k + e * (1 - k)
    return e


# ---------------------------------------------------------------- strategy
def analyze(symbol: str, c: List[Candle],
            h1: Optional[List[Candle]] = None,
            bn: Optional[List[Candle]] = None,
            min_score: Optional[int] = None) -> Optional[Signal]:
    """c, h1, bn: CLOSED candles only, oldest -> newest."""
    P = CFG
    if len(c) < P["range_n"] + P["base_n"] + 6:
        return None
    k = len(c) - 1
    thr = P["min_score"] if min_score is None else min_score
    for s in (k - 1, k - 2, k - 3):  # sweep happened 1-3 candles before confirm
        sig = _try(symbol, c, s, k, h1, bn)
        if sig and sig.score >= thr:
            return sig
    return None


def _try(symbol, c, s, k, h1, bn) -> Optional[Signal]:
    P = CFG
    w0 = s - P["range_n"]
    win = c[w0:s]
    base = c[w0 - P["base_n"]:w0]
    if len(win) < P["range_n"] or len(base) < P["base_n"]:
        return None

    # 1) ACCUMULATION: tight range + quiet volume
    rh = max(x[2] for x in win)
    rl = min(x[3] for x in win)
    mid = (rh + rl) / 2
    if mid <= 0:
        return None
    width = rh - rl
    wpct = width / mid * 100
    if not (P["min_range_pct"] <= wpct <= P["max_range_pct"]):
        return None
    base_vol = sum(x[5] for x in base) / len(base)
    if base_vol <= 0:
        return None
    acc_ratio = (sum(x[5] for x in win) / len(win)) / base_vol
    if acc_ratio > P["acc_vol_max"]:
        return None
    z = width * 0.2
    if sum(1 for x in win if x[2] >= rh - z) < 2:
        return None
    if sum(1 for x in win if x[3] <= rl + z) < 2:
        return None

    # 2) MANIPULATION: wick sweeps range edge, closes back inside, volume spike
    o, hh, ll, cl, v = c[s][1], c[s][2], c[s][3], c[s][4], c[s][5]
    rng = hh - ll
    if rng <= 0:
        return None
    sv = v / base_vol
    if sv < P["sweep_vol_min"]:
        return None
    side, wick = None, 0.0
    if (ll < rl * (1 - P["sweep_min_pct"] / 100) and cl >= rl
            and (rl - ll) <= width * P["sweep_max_width_frac"]):
        w = (min(o, cl) - ll) / rng
        if w >= P["sweep_wick_min"]:
            side, wick = "LONG", w
    if (side is None and hh > rh * (1 + P["sweep_min_pct"] / 100) and cl <= rh
            and (hh - rh) <= width * P["sweep_max_width_frac"]):
        w = (hh - max(o, cl)) / rng
        if w >= P["sweep_wick_min"]:
            side, wick = "SHORT", w
    if side is None:
        return None

    # 3) DISTRIBUTION: displacement candle through range midpoint, with volume
    ck = c[k]
    ko, kh, kl, kc, kv = ck[1], ck[2], ck[3], ck[4], ck[5]
    crng = kh - kl
    if crng <= 0:
        return None
    body = abs(kc - ko) / crng
    cvr = kv / base_vol
    if body < P["confirm_body_min"] or cvr < P["confirm_vol_min"]:
        return None
    atr = _atr(c[:k + 1])
    seg = c[s + 1:k + 1]
    if side == "LONG":
        if kc <= ko or kc <= mid:
            return None
        if any(x[4] < rl for x in seg):      # sweep invalidated
            return None
        ext = min(x[3] for x in c[s:k + 1])
        entry, sl = kc, ext - 0.2 * atr
        tp1, tp2 = rh, rh + width
        if entry >= tp1:
            return None
    else:
        if kc >= ko or kc >= mid:
            return None
        if any(x[4] > rh for x in seg):
            return None
        ext = max(x[2] for x in c[s:k + 1])
        entry, sl = kc, ext + 0.2 * atr
        tp1, tp2 = rl, rl - width
        if entry <= tp1:
            return None

    risk = abs(entry - sl)
    if risk <= 0:
        return None
    risk_pct = risk / entry * 100
    if risk_pct > P["max_risk_pct"]:
        return None
    rr1 = abs(tp1 - entry) / risk
    rr2 = abs(tp2 - entry) / risk
    if rr1 < P["min_rr1"] or rr2 < P["min_rr2"]:
        return None

    # ---- scoring
    score = 50
    why = [
        f"Accumulation: diapazon {wpct:.1f}%, hajm x{acc_ratio:.2f}",
        f"Manipulation: sweep hajmi x{sv:.1f}, fitil {wick * 100:.0f}%",
        f"Distribution: tasdiq hajmi x{cvr:.1f}",
    ]
    score += 10 if sv >= 3 else 6 if sv >= 2.2 else 0
    score += 8 if cvr >= 2 else 4 if cvr >= 1.6 else 0
    score += 5 if wick >= 0.6 else 0
    score += 5 if wpct <= 3 else 0
    score += 5 if acc_ratio <= 0.7 else 0
    score += 5 if rr2 >= 2.2 else 0

    if bn and len(bn) >= P["base_n"] + 4:
        bbase = sum(x[5] for x in bn[-(P["base_n"] + 4):-4]) / P["base_n"]
        if bbase > 0:
            bratio = max(x[5] for x in bn[-4:]) / bbase
            up = bn[-1][4] > bn[-4][4]
            aligned = up if side == "LONG" else (not up)
            if bratio >= 1.5 and aligned:
                score += 10
                why.append(f"Binance hajmi tasdiqladi x{bratio:.1f}")
            elif bratio < 1.0 or not aligned:
                score -= 8
                why.append("Binance hajmi tasdiqlamadi")

    if h1 and len(h1) >= 25:
        closes = [x[4] for x in h1]
        e = _ema(closes[-60:], 21)
        if (side == "LONG" and closes[-1] > e) or (side == "SHORT" and closes[-1] < e):
            score += 7
            why.append("1h trend yo'nalishga mos")

    return Signal(symbol=symbol, side=side, entry=entry, sl=sl, tp1=tp1, tp2=tp2,
                  rr1=rr1, rr2=rr2, risk_pct=risk_pct, score=min(score, 100),
                  range_high=rh, range_low=rl, ts=ck[0], reasons=why, candles=c[max(0, k - 59):k + 1])


# -------------------------------------------------------------- data fetch
_S = requests.Session()


def _get(url: str, params: dict):
    try:
        r = _S.get(url, params=params, timeout=10)
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None


def bybit_klines(symbol: str, interval: str, limit: int = 200) -> Optional[List[Candle]]:
    d = _get("https://api.bybit.com/v5/market/kline",
             {"category": "linear", "symbol": symbol,
              "interval": interval, "limit": limit})
    if not d or d.get("retCode") != 0:
        return None
    rows = d["result"]["list"]
    return [(int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5]))
            for r in reversed(rows)]


def binance_klines(symbol: str, interval: str, limit: int = 120) -> Optional[List[Candle]]:
    d = _get("https://fapi.binance.com/fapi/v1/klines",
             {"symbol": symbol, "interval": interval, "limit": limit})
    if not d or not isinstance(d, list):
        return None
    return [(int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5]))
            for r in d]


def universe() -> List[str]:
    d = _get("https://api.bybit.com/v5/market/tickers", {"category": "linear"})
    if not d or d.get("retCode") != 0:
        return []
    items = []
    for t in d["result"]["list"]:
        sym = t.get("symbol", "")
        if not sym.endswith("USDT") or sym in MAJORS:
            continue
        try:
            turn = float(t["turnover24h"])
        except (KeyError, ValueError):
            continue
        if CFG["min_turnover"] <= turn <= CFG["max_turnover"]:
            items.append((turn, sym))
    items.sort(reverse=True)
    return [s for _, s in items]


# -------------------------------------------------------------------- scan
_last: Dict[str, float] = {}
LAST_SCAN = {"count": 0, "ts": 0}


def scan(max_symbols: Optional[int] = None) -> List[Signal]:
    now = time.time()
    out: List[Signal] = []
    syms = universe()[:max_symbols or CFG["max_symbols"]]
    LAST_SCAN.update(count=len(syms), ts=int(now))
    for sym in syms:
        if now - _last.get(sym, 0) < CFG["cooldown_sec"]:
            continue
        c = bybit_klines(sym, CFG["tf"], 200)
        time.sleep(CFG["req_sleep"])
        if not c:
            continue
        c = c[:-1]  # drop the still-forming candle
        # stage 1: cheap pass, 2: confirm with 1h trend + Binance volume
        if not analyze(sym, c, min_score=CFG["min_score"] - EXTRA_SCORE_MAX):
            continue
        h1 = bybit_klines(sym, CFG["htf"], 80)
        h1 = h1[:-1] if h1 else None
        bn = binance_klines(sym, CFG["bn_tf"], 120)
        bn = bn[:-1] if bn else None
        sig = analyze(sym, c, h1, bn)
        if sig:
            _last[sym] = now
            out.append(sig)
    out.sort(key=lambda s: -s.score)
    return out


# ---------------------------------------------------------------- backtest
def backtest(symbol: str, bars: int = 1000, horizon: int = 48) -> Optional[dict]:
    """Quick history check on one symbol (50% TP1, 50% TP2; SL wins ties)."""
    c = bybit_klines(symbol, CFG["tf"], bars)
    if not c or len(c) < 200:
        return None
    c = c[:-1]
    res_list: List[float] = []
    i = 110
    while i < len(c) - 1:
        sig = analyze(symbol, c[:i + 1], min_score=CFG["min_score"] - EXTRA_SCORE_MAX)
        if not sig:
            i += 1
            continue
        # 50% closed at TP1, SL to breakeven, rest runs to TP2
        res, exit_j, tp1_hit = 0.0, min(i + horizon, len(c) - 1), False
        for j in range(i + 1, min(i + 1 + horizon, len(c))):
            hi, lo = c[j][2], c[j][3]
            long_ = sig.side == "LONG"
            stop = sig.entry if tp1_hit else sig.sl
            hit_sl = lo <= stop if long_ else hi >= stop
            hit_tp1 = hi >= sig.tp1 if long_ else lo <= sig.tp1
            hit_tp2 = hi >= sig.tp2 if long_ else lo <= sig.tp2
            if hit_sl:
                res = 0.5 * sig.rr1 if tp1_hit else -1.0
                exit_j = j
                break
            if not tp1_hit and hit_tp1:
                tp1_hit = True
                res = 0.5 * sig.rr1
            if tp1_hit and hit_tp2:
                res = 0.5 * sig.rr1 + 0.5 * sig.rr2
                exit_j = j
                break
        res_list.append(res)
        i = exit_j + 1
    n = len(res_list)
    wins = sum(1 for r in res_list if r > 0)
    return {
        "symbol": symbol, "trades": n, "wins": wins,
        "winrate": round(wins / n * 100, 1) if n else 0.0,
        "avg_R": round(sum(res_list) / n, 2) if n else 0.0,
        "total_R": round(sum(res_list), 2),
    }


# ------------------------------------------------------------ single check
def state(c: List[Candle]) -> Optional[dict]:
    """Current Accumulation status of the last closed candles (for /check)."""
    P = CFG
    if len(c) < P["range_n"] + P["base_n"] + 1:
        return None
    win = c[-P["range_n"]:]
    base = c[-(P["range_n"] + P["base_n"]):-P["range_n"]]
    rh = max(x[2] for x in win)
    rl = min(x[3] for x in win)
    mid = (rh + rl) / 2
    base_vol = sum(x[5] for x in base) / len(base)
    if mid <= 0 or base_vol <= 0:
        return None
    wpct = (rh - rl) / mid * 100
    acc = (sum(x[5] for x in win) / len(win)) / base_vol
    return {
        "range_high": rh, "range_low": rl, "range_pct": wpct,
        "acc_ratio": acc, "last_vol_x": c[-1][5] / base_vol, "price": c[-1][4],
        "tight": P["min_range_pct"] <= wpct <= P["max_range_pct"],
        "quiet": acc <= P["acc_vol_max"],
    }


def check(symbol: str) -> Optional[dict]:
    """One symbol: AMD signal (if any, score threshold ignored) + range state."""
    c = bybit_klines(symbol, CFG["tf"], 200)
    if not c:
        return None
    c = c[:-1]
    h1 = bybit_klines(symbol, CFG["htf"], 80)
    h1 = h1[:-1] if h1 else None
    bn = binance_klines(symbol, CFG["bn_tf"], 120)
    bn = bn[:-1] if bn else None
    return {
        "symbol": symbol,
        "signal": analyze(symbol, c, h1, bn, min_score=0),
        "state": state(c),
        "candles": c[-60:],
    }
