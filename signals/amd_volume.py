"""
signals/amd_volume.py
AMD (Accumulation -> Manipulation -> Distribution) + MSS/FVG + Bybit/Binance hajm.
BARCHA taymfreymlar uchun YAGONA yadro: 15m (CFG) va 1h/4h/1d (signals/amd_swing.py
dagi PROFILES) shu moduldagi analyze/scan/backtest'dan foydalanadi.

Barcha funksiyalar sinxron. Async koddan: await asyncio.to_thread(scan, ...)
"""
from __future__ import annotations

import bisect
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import requests

import config as C
from engine import sim
from engine.evaluator import recently_signaled

logger = logging.getLogger("nozik.amd")

# candle = (ts_ms, open, high, low, close, volume)
Candle = Tuple[int, float, float, float, float, float]

# 15m profil. Boshqa taymfreymlar profillari — signals/amd_swing.py
CFG = {
    "label": "15m",
    "tf": "15",              # Bybit interval
    "htf": "60",             # trend filtri taymfreymi
    "htf_label": "1h",
    "bn_tf": "15m",          # Binance interval
    "tf_hours": 0.25,
    "min_turnover": C.MIN_24H_TURNOVER_USDT,
    "max_turnover": C.MAX_24H_TURNOVER_USDT,
    "max_symbols": C.MAX_CANDIDATES_PER_SCAN,
    "range_n": 32,           # accumulation oynasi (shamlar)
    "base_n": 64,            # diapazondan oldingi baza hajm oynasi
    "min_range_pct": 0.8,
    "max_range_pct": C._f("AMD_MAX_RANGE_PCT", "7.0"),
    "tight_pct": 3.0,        # shundan tor diapazon = qo'shimcha ball
    "acc_vol_max": C._f("AMD_ACC_VOL_MAX", "1.1"),
    "sweep_min_pct": C._f("AMD_SWEEP_MIN_PCT", "0.10"),
    "sweep_max_width_frac": 0.5,
    "sweep_wick_min": C._f("AMD_SWEEP_WICK_MIN", "0.3"),
    "sweep_vol_min": C._f("AMD_SWEEP_VOL_MIN", "1.4"),
    "confirm_vol_min": C._f("AMD_CONFIRM_VOL_MIN", "1.1"),
    "confirm_body_min": C._f("AMD_CONFIRM_BODY_MIN", "0.45"),
    "max_risk_pct": C.MAX_RISK_PCT,
    "min_rr1": 0.5,
    "min_rr2": C._f("AMD_MIN_RR2", "1.2"),
    "min_score": C.ALERT_THRESHOLD,
    "cooldown_sec": C.ALERT_COOLDOWN_SECONDS,
    "expire_candles": C.EXPIRE_CANDLES,
    "max_chase_r": C.MAX_CHASE_R,
    "require_structure": C.REQUIRE_STRUCTURE,
    "fee_pct": C.FEE_PCT,
    "slip_pct": C.SLIPPAGE_PCT,
    "req_sleep": 0.12,
}

MAJORS = {
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT",
    "ADAUSDT", "TRXUSDT", "LINKUSDT", "AVAXUSDT", "TONUSDT", "LTCUSDT",
    "DOTUSDT", "BCHUSDT", "SUIUSDT",
}
MAJORS.update(C.EXCLUDE_SYMBOLS)

EXTRA_SCORE_MAX = 17   # 1h/trend (+7) va Binance hajmi (+10) beradigan maksimal qo'shimcha ball


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
    candles: list = field(default_factory=list, repr=False)
    tf: str = "15m"


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


def _structure(side: str, c: List[Candle], s: int, k: int) -> Tuple[bool, bool]:
    """Sweep (s) dan tasdiq (k) gacha: (MSS, FVG).
    MSS — tasdiq sham sweepdan keyingi oxirgi tuzilma chegarasini yopilish bilan buzdi.
    FVG — 3 ta sham orasida imbalance (gap) qoldi, tasdiq yo'nalishida."""
    kc = c[k][4]
    if side == "LONG":
        mss = kc > max(x[2] for x in c[s:k])
        fvg = any(c[i + 1][3] > c[i - 1][2] for i in range(max(s, 1), k))
    else:
        mss = kc < min(x[3] for x in c[s:k])
        fvg = any(c[i + 1][2] < c[i - 1][3] for i in range(max(s, 1), k))
    return mss, fvg


# ---------------------------------------------------------------- strategy
def analyze(symbol: str, c: List[Candle],
            h1: Optional[List[Candle]] = None,
            bn: Optional[List[Candle]] = None,
            min_score: Optional[int] = None,
            P: Optional[dict] = None) -> Optional[Signal]:
    """c, h1, bn: faqat YOPILGAN shamlar, eskidan yangiga. P — profil (default 15m)."""
    P = P or CFG
    if len(c) < P["range_n"] + P["base_n"] + 6:
        return None
    k = len(c) - 1
    thr = P["min_score"] if min_score is None else min_score
    best = None
    for s in (k - 1, k - 2, k - 3):  # sweep tasdiqdan 1-3 sham oldin bo'lgan
        sig = _try(symbol, c, s, k, h1, bn, P)
        if sig and sig.score >= thr and (best is None or sig.score > best.score):
            best = sig
    return best


def _try(symbol, c, s, k, h1, bn, P) -> Optional[Signal]:
    w0 = s - P["range_n"]
    win = c[w0:s]
    base = c[w0 - P["base_n"]:w0]
    if w0 < P["base_n"] or len(win) < P["range_n"] or len(base) < P["base_n"]:
        return None

    # 1) ACCUMULATION: tor diapazon + past hajm
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

    # 2) MANIPULATION: fitil diapazon chetini oladi, ichkariga yopiladi, hajm portlaydi
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

    # 3) DISTRIBUTION: diapazon o'rtasidan o'tuvchi kuchli sham + hajm
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
        if any(x[4] < rl for x in seg):      # sweep bekor bo'lgan
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

    # MSS / FVG
    mss, fvg = _structure(side, c, s, k)
    if P.get("require_structure") and not (mss or fvg):
        return None

    # ---- ball
    score = 50
    why = [
        f"Accumulation: диапазон {wpct:.1f}%, объём x{acc_ratio:.2f}",
        f"Manipulation: объём sweep x{sv:.1f}, тень {wick * 100:.0f}%",
        f"Distribution: объём подтверждения x{cvr:.1f}",
    ]
    score += 10 if sv >= 3 else 6 if sv >= 2.2 else 0
    score += 8 if cvr >= 2 else 4 if cvr >= 1.6 else 0
    score += 5 if wick >= 0.6 else 0
    score += 5 if wpct <= P["tight_pct"] else 0
    score += 5 if acc_ratio <= 0.7 else 0
    score += 5 if rr2 >= 2.2 else 0

    if mss or fvg:
        parts = [n for n, ok in (("MSS (слом структуры)", mss), ("FVG (имбаланс)", fvg)) if ok]
        score += 6 * (int(mss) + int(fvg))
        why.append("Structure: " + " + ".join(parts))
    else:
        score -= 6
        why.append("Structure: нет MSS/FVG")

    n_b = P["base_n"]
    if bn is None:
        why.append("Binance: данных нет — проверка пропущена")
    elif len(bn) >= n_b + 4:
        bbase = sum(x[5] for x in bn[-(n_b + 4):-4]) / n_b
        if bbase > 0:
            bratio = max(x[5] for x in bn[-4:]) / bbase
            up = bn[-1][4] > bn[-4][4]
            aligned = up if side == "LONG" else (not up)
            if bratio >= 1.5 and aligned:
                score += 10
                why.append(f"Binance: объём подтвердил x{bratio:.1f}")
            elif bratio < 1.0 or not aligned:
                score -= 8
                why.append("Binance: объём не подтвердил")

    if h1 and len(h1) >= 25:
        closes = [x[4] for x in h1]
        e = _ema(closes[-60:], 21)
        if (side == "LONG" and closes[-1] > e) or (side == "SHORT" and closes[-1] < e):
            score += 7
            why.append(f"{P['htf_label']}: тренд совпадает с направлением")

    return Signal(symbol=symbol, side=side, entry=entry, sl=sl, tp1=tp1, tp2=tp2,
                  rr1=rr1, rr2=rr2, risk_pct=risk_pct, score=max(0, min(score, 100)),
                  range_high=rh, range_low=rl, ts=ck[0], reasons=why,
                  candles=c[max(0, k - 59):k + 1], tf=P["label"])


# -------------------------------------------------------------- data fetch
_S = requests.Session()


_WARNED: Dict[str, float] = {}


def _warn_once(key: str, msg: str, every: int = 900):
    """Bir xil ogohlantirishni har 15 daqiqada ko'pi bilan bir marta yozadi."""
    now = time.time()
    if now - _WARNED.get(key, 0) > every:
        _WARNED[key] = now
        logger.warning(msg)


def _get(url: str, params: dict, timeout: int = 10, retries: int = 2):
    """GET + JSON. 429/5xx va tarmoq xatolarida qisqa kutib qayta urinadi."""
    host = url.split("/")[2]
    for attempt in range(retries + 1):
        try:
            r = _S.get(url, params=params, timeout=timeout)
            if r.status_code == 200:
                return r.json()
            if r.status_code not in (418, 429, 500, 502, 503, 504):
                # 403/451 — region bloki: qayta urinib bo'lmaydi, lekin LOGDA ko'rinsin
                _warn_once(f"{host}:{r.status_code}",
                           f"{host} HTTP {r.status_code} qaytardi (region bloki bo'lishi mumkin — "
                           "Render region'ini Singapore/Frankfurt qiling)")
                return None
        except Exception as e:
            _warn_once(f"{host}:exc", f"{host} so'rovi xato: {e}")
        if attempt < retries:
            time.sleep(0.6 * (attempt + 1))
    return None


def _row(r) -> Candle:
    return (int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5]))


def bybit_klines(symbol: str, interval: str, limit: int = 200) -> Optional[List[Candle]]:
    d = _get("https://api.bybit.com/v5/market/kline",
             {"category": "linear", "symbol": symbol, "interval": interval, "limit": limit})
    if not d or d.get("retCode") != 0:
        return None
    return [_row(r) for r in reversed(d["result"]["list"])]


def bybit_klines_history(symbol: str, interval: str, bars: int,
                         sleep: float = 0.12) -> List[Candle]:
    """Bybit tarixini sahifalab oladi (har so'rov <=1000 sham). Eskidan yangiga."""
    out: Dict[int, Candle] = {}
    end = None
    while len(out) < bars:
        params = {"category": "linear", "symbol": symbol, "interval": interval, "limit": 1000}
        if end:
            params["end"] = end
        d = _get("https://api.bybit.com/v5/market/kline", params)
        if not d or d.get("retCode") != 0:
            break
        rows = d["result"]["list"]
        if not rows:
            break
        for r in rows:
            out[int(r[0])] = _row(r)
        if len(rows) < 1000:
            break
        end = min(int(r[0]) for r in rows) - 1
        time.sleep(sleep)
    res = [out[t] for t in sorted(out)]
    return res[-bars:]


def binance_klines(symbol: str, interval: str, limit: int = 120) -> Optional[List[Candle]]:
    d = _get("https://fapi.binance.com/fapi/v1/klines",
             {"symbol": symbol, "interval": interval, "limit": limit})
    if not d or not isinstance(d, list):
        return None
    return [_row(r) for r in d]


def binance_klines_range(symbol: str, interval: str, start_ms: int, end_ms: int,
                         sleep: float = 0.12) -> List[Candle]:
    out: List[Candle] = []
    cur = start_ms
    while cur < end_ms:
        d = _get("https://fapi.binance.com/fapi/v1/klines",
                 {"symbol": symbol, "interval": interval, "startTime": cur,
                  "endTime": end_ms, "limit": 1500})
        if not d or not isinstance(d, list):
            break
        out.extend(_row(r) for r in d)
        if len(d) < 1500:
            break
        cur = int(d[-1][0]) + 1
        time.sleep(sleep)
    return out


# --- Binance symbol moslash: Bybit 'SHIB1000USDT' <-> Binance '1000SHIBUSDT' va h.k.
_BN = {"set": set(), "ts": 0.0}
_MULTS = ("", "1000", "10000", "100000", "1000000")
_MULT_RE = re.compile(r"(1(?:0{1,6}))?([A-Z]+?)(1(?:0{1,6}))?USDT")


def _bn_symbols() -> set:
    now = time.time()
    if now - _BN["ts"] < (6 * 3600 if _BN["set"] else 600):
        return _BN["set"]
    _BN["ts"] = now
    d = _get("https://fapi.binance.com/fapi/v1/exchangeInfo", {}, timeout=20)
    if isinstance(d, dict) and d.get("symbols"):
        _BN["set"] = {s["symbol"] for s in d["symbols"]
                      if s.get("contractType") == "PERPETUAL" and s.get("status") == "TRADING"}
    return _BN["set"]


def binance_symbol(sym: str) -> Optional[str]:
    """Bybit symbolning Binance Futures'dagi nomi. Topilmasa None.
    Binance ro'yxatini olib bo'lmasa (region bloki) — symbol o'zgarishsiz qaytadi."""
    syms = _bn_symbols()
    if not syms or sym in syms:
        return sym
    m = _MULT_RE.fullmatch(sym)
    if not m:
        return None
    core = m.group(2)
    for mult in _MULTS:
        for cand in (mult + core + "USDT", core + mult + "USDT"):
            if cand in syms:
                return cand
    return None


def _bn_closed(sym: str, P: dict, limit: int = 120) -> Optional[List[Candle]]:
    bs = binance_symbol(sym)
    if not bs:
        return None
    bn = binance_klines(bs, P["bn_tf"], limit)
    return bn[:-1] if bn else None


def last_price(symbol: str) -> Optional[float]:
    d = _get("https://api.bybit.com/v5/market/tickers", {"category": "linear", "symbol": symbol})
    try:
        return float(d["result"]["list"][0]["lastPrice"])
    except Exception:
        return None


def universe() -> List[str]:
    d = _get("https://api.bybit.com/v5/market/tickers", {"category": "linear"})
    if not d or d.get("retCode") != 0:
        _warn_once("universe", "Bybit tickers olinmadi — skaner bo'sh ro'yxat bilan ishlayapti")
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
LAST_SCAN = {"count": 0, "ts": 0, "skipped_stale": 0}
_DONE: Dict[str, int] = {}     # taymfreym -> tahlil qilingan oxirgi YOPILGAN sham ochilish vaqti


def _fresh(sig: Signal, P: dict) -> bool:
    """Signal kelgan paytdagi narx kirishdan ko'p ketib qolgan bo'lsa — o'tkazib yuboriladi."""
    px = last_price(sig.symbol)
    if px is None:
        return True                      # tekshirib bo'lmadi — signalni yo'qotmaymiz
    risk = abs(sig.entry - sig.sl)
    prog = (px - sig.entry) / risk if sig.side == "LONG" else (sig.entry - px) / risk
    if prog > P["max_chase_r"]:
        logger.info(f"{sig.symbol} [{sig.tf}]: narx kirishdan {prog:.2f}R ketib qolgan — o'tkazildi")
        return False
    if prog <= -1:
        logger.info(f"{sig.symbol} [{sig.tf}]: narx SL'dan o'tib ketgan — o'tkazildi")
        return False
    return True


def scan(P: Optional[dict] = None, max_symbols: Optional[int] = None,
         force: bool = False) -> List[Signal]:
    """P — profil (default 15m). force=False bo'lsa, bir xil yopilgan sham qayta
    skanerlanmaydi (5 daqiqalik skanerlar 15m shamni 3 marta bekorga tekshirmasin)."""
    P = P or CFG
    now = time.time()
    L = sim.tf_ms(P["tf"])
    expected = int(now * 1000) // L * L - L
    if not force and _DONE.get(P["label"]) == expected:
        return []

    syms = universe()[:max_symbols or P["max_symbols"]]
    LAST_SCAN.update(count=len(syms), ts=int(now), skipped_stale=0)
    out: List[Signal] = []
    ok = 0
    for sym in syms:
        if recently_signaled(sym, P["label"], P["cooldown_sec"]):
            ok += 1
            continue
        c = bybit_klines(sym, P["tf"], 200)
        time.sleep(P["req_sleep"])
        if not c:
            continue
        ok += 1
        c = c[:-1]  # hali shakllanayotgan shamni olib tashlaymiz
        # 1-bosqich: arzon filtr; 2-bosqich: trend + Binance hajmi bilan tasdiq
        if not analyze(sym, c, min_score=P["min_score"] - EXTRA_SCORE_MAX, P=P):
            continue
        h1 = bybit_klines(sym, P["htf"], 80)
        h1 = h1[:-1] if h1 else None
        bn = _bn_closed(sym, P)
        sig = analyze(sym, c, h1, bn, P=P)
        if not sig:
            continue
        if not _fresh(sig, P):
            LAST_SCAN["skipped_stale"] += 1
            continue
        out.append(sig)
    if syms and ok >= 0.9 * len(syms):
        _DONE[P["label"]] = expected      # katta xato bo'lsa — keyingi skanerda qayta uriniladi
    out.sort(key=lambda s: -s.score)
    return out


# ---------------------------------------------------------------- backtest
def backtest(symbol: str, P: Optional[dict] = None, bars: Optional[int] = None) -> Optional[dict]:
    """JONLI logika bilan bir xil: trend (htf) va Binance hajmi tarixiy ma'lumotdan
    vaqt bo'yicha to'g'ri joylashtiriladi (kelajakka qarash yo'q), to'liq ball
    chegarasi qo'llanadi, komissiya + slippage ayriladi."""
    P = P or CFG
    bars = bars or C.BACKTEST_BARS
    L, Lh, Lb = sim.tf_ms(P["tf"]), sim.tf_ms(P["htf"]), sim.bn_ms(P["bn_tf"])
    c = bybit_klines_history(symbol, P["tf"], bars + 1, P["req_sleep"])
    need = P["range_n"] + P["base_n"] + 20
    if len(c) < need + 30:
        return None
    c = c[:-1]
    n_h = min(int(len(c) * L / Lh) + 100, 3000)
    h_all = bybit_klines_history(symbol, P["htf"], n_h, P["req_sleep"])
    bs = binance_symbol(symbol)
    b_all = (binance_klines_range(bs, P["bn_tf"], c[0][0] - Lb * (P["base_n"] + 10),
                                  c[-1][0] + L, P["req_sleep"]) if bs else [])
    h_close = [x[0] + Lh for x in h_all]     # har htf shamning YOPILISH vaqti
    b_close = [x[0] + Lb for x in b_all]

    cd_candles = max(1, -(-P["cooldown_sec"] // (L // 1000)))
    expire = P["expire_candles"]
    gross_l: List[float] = []
    net_l: List[float] = []
    i = need
    while i < len(c) - 1:
        t_close = c[i][0] + L
        hj = bisect.bisect_right(h_close, t_close)
        bj = bisect.bisect_right(b_close, t_close)
        sig = analyze(symbol, c[max(0, i + 1 - 300):i + 1],
                      h_all[max(0, hj - 80):hj] or None,
                      b_all[max(0, bj - 120):bj] if b_all else None, P=P)
        if not sig:
            i += 1
            continue
        hit1, status, gross, exit_j = False, None, None, None
        for j in range(i + 1, min(i + 1 + expire, len(c))):
            hit1, status, gross = sim.step(sig.side, sig.entry, sig.sl, sig.tp1, sig.tp2,
                                           sig.rr1, sig.rr2, hit1, c[j][2], c[j][3])
            if status:
                exit_j = j
                break
            if j - i >= expire:
                status, exit_j = "expired", j
                gross = sim.expire_gross(sig.side, sig.entry, sig.sl, sig.rr1, hit1, c[j][4])
                break
        if status is None:
            break                       # ma'lumot tugadi, savdo yakunlanmagan — hisobga olinmaydi
        gross_l.append(gross)
        net_l.append(gross - sim.cost_r(sig.entry, sig.sl, P["fee_pct"], P["slip_pct"]))
        i = max(exit_j + 1, i + cd_candles)
    return _bt_summary(symbol, P["label"], len(c), gross_l, net_l)


def _bt_summary(symbol: str, tf: str, nbars: int, gross: List[float], net: List[float]) -> dict:
    n = len(net)
    wins = sum(1 for r in net if r > 0)
    gains = sum(r for r in net if r > 0)
    losses = -sum(r for r in net if r < 0)
    return {
        "symbol": symbol, "tf": tf, "bars": nbars, "trades": n, "wins": wins,
        "winrate": round(wins / n * 100, 1) if n else 0.0,
        "avg_R": round(sum(net) / n, 2) if n else 0.0,
        "total_R": round(sum(net), 2),
        "gross_total_R": round(sum(gross), 2),
        "cost_total_R": round(sum(gross) - sum(net), 2),
        "pf": round(gains / losses, 2) if losses > 0 else None,
        "_net": net, "_gross": gross,
    }


def backtest_many(symbols: List[str], P: Optional[dict] = None,
                  bars: Optional[int] = None) -> Optional[dict]:
    """Bir nechta token bo'yicha jamlangan backtest (bitta tokenda savdo juda kam)."""
    P = P or CFG
    net_all: List[float] = []
    gross_all: List[float] = []
    per = []
    for sym in symbols:
        r = backtest(sym, P, bars)
        if not r:
            continue
        per.append(r)
        net_all += r["_net"]
        gross_all += r["_gross"]
    if not per:
        return None
    out = _bt_summary(f"{len(per)} токенов", P["label"], sum(r["bars"] for r in per),
                      gross_all, net_all)
    out["symbols_ok"] = len(per)
    out["symbols_profitable"] = sum(1 for r in per if r["total_R"] > 0)
    out["per_symbol"] = sorted(((r["symbol"], r["trades"], r["total_R"]) for r in per),
                               key=lambda x: -x[2])
    return out


# ------------------------------------------------------------ single check
def state(c: List[Candle], P: Optional[dict] = None) -> Optional[dict]:
    """Oxirgi yopilgan shamlar bo'yicha Accumulation holati (/check uchun)."""
    P = P or CFG
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


def check(symbol: str, P: Optional[dict] = None) -> Optional[dict]:
    """Bitta token: AMD signal (ball chegarasi e'tiborsiz) + diapazon holati."""
    P = P or CFG
    c = bybit_klines(symbol, P["tf"], 200)
    if not c:
        return None
    c = c[:-1]
    h1 = bybit_klines(symbol, P["htf"], 80)
    h1 = h1[:-1] if h1 else None
    bn = _bn_closed(symbol, P)
    return {
        "symbol": symbol,
        "signal": analyze(symbol, c, h1, bn, min_score=0, P=P),
        "state": state(c, P),
        "candles": c[-60:],
    }
