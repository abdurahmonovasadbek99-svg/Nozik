#!/usr/bin/env python3
"""
UltimateForexSignalBot v4.0 — Telegram Signal Bot
═══════════════════════════════════════════════════
Juftliklar: XAUUSD, XAGUSD, BTC-USD, EURUSD, GBPUSD

Signal manbalari (12 ta):
  1.  EMA trend (10/50)
  2.  RSI (14)
  3.  MACD kesishishi
  4.  Bollinger Bands
  5.  Stochastic Oscillator
  6.  ADX (trend kuchi)
  7.  Klassik patternlar (Pin Bar, Engulfing, Double Top/Bottom, Doji)
  8.  Fibonacci darajalari (0.382, 0.5, 0.618)
  9.  Support / Resistance darajalari
 10.  Volume tahlili
 11.  Sentiment (Fear & Greed Index)
 12.  Multi-timeframe tasdiqlash (15m + 4h)

Intraday:
  Forex/Metal: 07:00–21:00 UTC (London + NY sessiyasi)
  Bitcoin:     00:00–24:00 UTC (24/7)
"""

import os, logging, threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timezone
import requests, pandas as pd, ta
from telegram.ext import Application, CommandHandler, ContextTypes

# MUHIM: python-telegram-bot[job-queue] o'rnatilishi kerak, aks holda
# job_queue = None bo'lib qoladi va run_repeating xato beradi.

# ══════════════════════════════════════════════
#  SOZLAMALAR
# ══════════════════════════════════════════════
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
CHAT_ID   = os.environ.get("CHAT_ID",   "YOUR_CHAT_ID_HERE")

# Juftliklar va Yahoo Finance tickerlari
SYMBOL_MAP = {
    "XAUUSD":  "GC=F",      # Oltin
    "XAGUSD":  "SI=F",      # Kumush
    "BTCUSD":  "BTC-USD",   # Bitcoin
    "EURUSD":  "EURUSD=X",  # Euro/Dollar
    "GBPUSD":  "GBPUSD=X",  # Funt/Dollar
}
SYMBOLS = list(SYMBOL_MAP.keys())

# Bitcoin 24/7 ishlaydi — alohida belgi
CRYPTO_SYMBOLS = {"BTCUSD"}

# Intraday sozlamalar
CHECK_INTERVAL        = 5    # daqiqa
MAX_DAILY_SIGNALS     = 6    # har juftlik uchun
TRADING_START         = 7    # UTC (forex/metal uchun)
TRADING_END           = 21   # UTC (forex/metal uchun)
EOD_REMINDER_HOUR     = 20   # UTC
MIN_SCORE             = 6    # Minimal ball
REQUIRE_CONFIRMATION  = True # Signal chiqqach 1 bar tasdiqlashini kutish

# ══════════════════════════════════════════════
#  YANGILIKLAR JADVALI (2026, UTC)
# ══════════════════════════════════════════════
NEWS_CALENDAR = [
    # IYUL 2026
    {"date":"2026-07-03 12:30","name":"🔴 NFP Non-Farm Payroll",    "impact":3,"pairs":["EURUSD","GBPUSD","XAUUSD","XAGUSD","BTCUSD"]},
    {"date":"2026-07-09 12:30","name":"🔴 CPI Inflation Data",      "impact":3,"pairs":["EURUSD","GBPUSD","XAUUSD","BTCUSD"]},
    {"date":"2026-07-15 13:15","name":"🟡 Retail Sales",            "impact":2,"pairs":["EURUSD","GBPUSD"]},
    {"date":"2026-07-28 18:00","name":"🔴 FOMC Rate Decision",      "impact":3,"pairs":["EURUSD","GBPUSD","XAUUSD","XAGUSD","BTCUSD"]},
    {"date":"2026-07-28 18:30","name":"🔴 Fed Press Conference",    "impact":3,"pairs":["EURUSD","GBPUSD","XAUUSD","BTCUSD"]},
    {"date":"2026-07-30 12:30","name":"🔴 GDP Advance Q2",          "impact":3,"pairs":["EURUSD","GBPUSD","XAUUSD"]},
    # AVGUST 2026
    {"date":"2026-08-07 12:30","name":"🔴 NFP Non-Farm Payroll",    "impact":3,"pairs":["EURUSD","GBPUSD","XAUUSD","XAGUSD","BTCUSD"]},
    {"date":"2026-08-12 12:30","name":"🔴 CPI Inflation Data",      "impact":3,"pairs":["EURUSD","GBPUSD","XAUUSD","BTCUSD"]},
    {"date":"2026-08-22 14:00","name":"🔴 Fed Chair Jackson Hole",  "impact":3,"pairs":["EURUSD","GBPUSD","XAUUSD","XAGUSD","BTCUSD"]},
    # SENTABR 2026
    {"date":"2026-09-04 12:30","name":"🔴 NFP Non-Farm Payroll",    "impact":3,"pairs":["EURUSD","GBPUSD","XAUUSD","XAGUSD","BTCUSD"]},
    {"date":"2026-09-16 18:00","name":"🔴 FOMC Rate Decision",      "impact":3,"pairs":["EURUSD","GBPUSD","XAUUSD","XAGUSD","BTCUSD"]},
    # OKTABR 2026
    {"date":"2026-10-02 12:30","name":"🔴 NFP Non-Farm Payroll",    "impact":3,"pairs":["EURUSD","GBPUSD","XAUUSD","XAGUSD","BTCUSD"]},
    {"date":"2026-10-29 18:00","name":"🔴 FOMC Rate Decision",      "impact":3,"pairs":["EURUSD","GBPUSD","XAUUSD","XAGUSD","BTCUSD"]},
    # NOYABR 2026
    {"date":"2026-11-06 12:30","name":"🔴 NFP Non-Farm Payroll",    "impact":3,"pairs":["EURUSD","GBPUSD","XAUUSD","XAGUSD","BTCUSD"]},
    {"date":"2026-11-12 12:30","name":"🔴 CPI Inflation Data",      "impact":3,"pairs":["EURUSD","GBPUSD","XAUUSD","BTCUSD"]},
    # DEKABR 2026
    {"date":"2026-12-04 12:30","name":"🔴 NFP Non-Farm Payroll",    "impact":3,"pairs":["EURUSD","GBPUSD","XAUUSD","XAGUSD","BTCUSD"]},
    {"date":"2026-12-16 18:00","name":"🔴 FOMC Rate Decision",      "impact":3,"pairs":["EURUSD","GBPUSD","XAUUSD","XAGUSD","BTCUSD"]},
]

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)

# ══════════════════════════════════════════════
#  NARX MA'LUMOTI
# ══════════════════════════════════════════════
def get_price_data(symbol: str, period: str = "5d", interval: str = "15m") -> pd.DataFrame | None:
    try:
        ticker = SYMBOL_MAP.get(symbol, symbol)
        r = requests.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}",
            params={"range": period, "interval": interval, "includePrePost": False},
            headers={"User-Agent": "Mozilla/5.0"}, timeout=10
        )
        d = r.json()["chart"]["result"][0]
        q = d["indicators"]["quote"][0]
        df = pd.DataFrame({
            "time":   pd.to_datetime(d["timestamp"], unit="s"),
            "open":   q["open"], "high": q["high"],
            "low":    q["low"],  "close": q["close"],
            "volume": q.get("volume", [0]*len(d["timestamp"])),
        }).dropna()
        return df
    except Exception as e:
        log.error(f"Narx xato ({symbol}): {e}")
        return None

# ══════════════════════════════════════════════
#  SUPPORT / RESISTANCE
# ══════════════════════════════════════════════
def calc_sr(df: pd.DataFrame) -> dict:
    lookback = min(50, len(df))
    rec = df.tail(lookback)
    h, l = rec["high"].values, rec["low"].values
    res, sup = [], []
    for i in range(2, len(h)-2):
        if h[i] > h[i-1] and h[i] > h[i-2] and h[i] > h[i+1] and h[i] > h[i+2]:
            res.append(h[i])
        if l[i] < l[i-1] and l[i] < l[i-2] and l[i] < l[i+1] and l[i] < l[i+2]:
            sup.append(l[i])
    price = df["close"].iloc[-1]
    atr   = ta.volatility.AverageTrueRange(df["high"],df["low"],df["close"],14).average_true_range().iloc[-1]
    zone  = atr * 0.5
    nr = min([r for r in res if r > price], default=None)
    ns = max([s for s in sup if s < price], default=None)
    return {
        "support":       round(ns, 5) if ns else None,
        "resistance":    round(nr, 5) if nr else None,
        "at_support":    bool(ns and abs(price-ns) < zone),
        "at_resistance": bool(nr and abs(price-nr) < zone),
    }

# ══════════════════════════════════════════════
#  FIBONACCI
# ══════════════════════════════════════════════
def calc_fib(df: pd.DataFrame) -> dict:
    lookback = min(100, len(df))
    rec = df.tail(lookback)
    hi, lo = rec["high"].max(), rec["low"].min()
    diff   = hi - lo
    price  = df["close"].iloc[-1]
    atr    = ta.volatility.AverageTrueRange(df["high"],df["low"],df["close"],14).average_true_range().iloc[-1]
    zone   = atr * 0.3
    levels = {
        "0.236": round(hi - diff*0.236, 5),
        "0.382": round(hi - diff*0.382, 5),
        "0.500": round(hi - diff*0.500, 5),
        "0.618": round(hi - diff*0.618, 5),
        "0.786": round(hi - diff*0.786, 5),
    }
    near, near_type = None, None
    for name, lv in levels.items():
        if abs(price - lv) < zone:
            near, near_type = lv, name
            break
    return {"levels": levels, "near": near, "near_type": near_type,
            "swing_hi": round(hi,5), "swing_lo": round(lo,5)}

# ══════════════════════════════════════════════
#  VOLUME
# ══════════════════════════════════════════════
def calc_volume(df: pd.DataFrame) -> dict:
    if df["volume"].sum() == 0:
        return {"ratio": 1.0, "high": False, "low": False}
    avg = df["volume"].tail(20).mean()
    cur = df["volume"].iloc[-1]
    r   = cur / avg if avg > 0 else 1.0
    return {"ratio": round(r,2), "high": r > 1.5, "low": r < 0.5}

# ══════════════════════════════════════════════
#  SENTIMENT (Fear & Greed)
# ══════════════════════════════════════════════
_sentiment_cache = {"data": None, "ts": None}

def get_sentiment() -> dict:
    now = datetime.now(timezone.utc)
    if _sentiment_cache["data"] and _sentiment_cache["ts"]:
        if (now - _sentiment_cache["ts"]).seconds < 3600:
            return _sentiment_cache["data"]
    try:
        r = requests.get(
            "https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
            headers={"User-Agent":"Mozilla/5.0"}, timeout=8
        )
        fg   = r.json()["fear_and_greed"]
        sc   = float(fg["score"])
        data = {
            "score": round(sc,1), "rating": fg["rating"],
            "extreme_fear":  sc <= 25,
            "fear":          25 < sc <= 45,
            "neutral":       45 < sc <= 55,
            "greed":         55 < sc <= 75,
            "extreme_greed": sc > 75,
        }
    except Exception:
        data = {"score":50.0,"rating":"Neutral","extreme_fear":False,
                "fear":False,"neutral":True,"greed":False,"extreme_greed":False}
    _sentiment_cache["data"] = data
    _sentiment_cache["ts"]   = now
    return data

# ══════════════════════════════════════════════
#  PATTERN ANIQLASH
# ══════════════════════════════════════════════
def detect_patterns(df: pd.DataFrame) -> dict:
    o,h,l,c = df["open"].values, df["high"].values, df["low"].values, df["close"].values
    n = len(c)
    p = {k:False for k in ["bullish_pin","bearish_pin","bull_engulf",
                             "bear_engulf","doji","double_top","double_bottom"]}
    if n < 3: return p
    body = abs(c[-1]-o[-1]); rng = h[-1]-l[-1]
    uw = h[-1]-max(c[-1],o[-1]); lw = min(c[-1],o[-1])-l[-1]
    if rng > 0:
        if lw > body*2 and uw < body*0.5: p["bullish_pin"]  = True
        if uw > body*2 and lw < body*0.5: p["bearish_pin"]  = True
        if body < rng*0.1:                p["doji"]         = True
    pt=max(o[-2],c[-2]); pb=min(o[-2],c[-2])
    ct=max(o[-1],c[-1]); cb=min(o[-1],c[-1])
    if c[-2]<o[-2] and c[-1]>o[-1] and ct>=pt and cb<=pb: p["bull_engulf"] = True
    if c[-2]>o[-2] and c[-1]<o[-1] and ct>=pt and cb<=pb: p["bear_engulf"] = True
    if n >= 20:
        rh=h[-20:]; rl=l[-20:]
        peaks=[i for i in range(1,19) if rh[i]>rh[i-1] and rh[i]>rh[i+1]]
        if len(peaks)>=2:
            p2=[rh[pk] for pk in peaks[-2:]]
            if rh.max()>0 and abs(p2[0]-p2[1])/rh.max()<0.002: p["double_top"] = True
        trfs=[i for i in range(1,19) if rl[i]<rl[i-1] and rl[i]<rl[i+1]]
        if len(trfs)>=2:
            t2=[rl[t] for t in trfs[-2:]]
            if rl.min()>0 and abs(t2[0]-t2[1])/rl.min()<0.002: p["double_bottom"] = True
    return p

# ══════════════════════════════════════════════
#  TRENDLINE ANIQLASH (klassik texnik tahlil)
# ══════════════════════════════════════════════
def calc_trendline(df: pd.DataFrame, lookback: int = 40) -> dict:
    """
    Oxirgi N barda eng muhim ikkita pastki (support) yoki yuqori (resistance)
    nuqta orqali trend chizig'ini chizadi va narx uni yaqinda buzganmi
    (breakout) tekshiradi.
    """
    if len(df) < lookback:
        lookback = len(df)
    rec = df.tail(lookback).reset_index(drop=True)
    h, l, c = rec["high"].values, rec["low"].values, rec["close"].values
    n = len(c)

    troughs = [i for i in range(2, n-2) if l[i]<l[i-1] and l[i]<l[i-2] and l[i]<l[i+1] and l[i]<l[i+2]]
    peaks   = [i for i in range(2, n-2) if h[i]>h[i-1] and h[i]>h[i-2] and h[i]>h[i+1] and h[i]>h[i+2]]

    result = {"uptrend_break": False, "downtrend_break": False,
              "trendline_support": None, "trendline_resistance": None}

    # Yuqoriga ko'tarilgan trend chizig'i (2 ta pastki nuqta orqali)
    if len(troughs) >= 2:
        i1, i2 = troughs[-2], troughs[-1]
        if i2 > i1:
            slope = (l[i2] - l[i1]) / (i2 - i1)
            proj  = l[i2] + slope * (n-1 - i2)
            result["trendline_support"] = round(proj, 5)
            # Narx trend chizig'idan pastga tushib ketganmi (buzilish)
            if slope > 0 and c[-1] < proj:
                result["uptrend_break"] = True

    # Pastga tushgan trend chizig'i (2 ta yuqori nuqta orqali)
    if len(peaks) >= 2:
        i1, i2 = peaks[-2], peaks[-1]
        if i2 > i1:
            slope = (h[i2] - h[i1]) / (i2 - i1)
            proj  = h[i2] + slope * (n-1 - i2)
            result["trendline_resistance"] = round(proj, 5)
            # Narx trend chizig'idan yuqoriga chiqib ketganmi (buzilish)
            if slope < 0 and c[-1] > proj:
                result["downtrend_break"] = True

    return result

# ══════════════════════════════════════════════
#  SMART MONEY CONCEPTS (SMC)
# ══════════════════════════════════════════════
def calc_smc(df: pd.DataFrame, lookback: int = 50) -> dict:
    """
    Smart Money Concepts tahlili:
      - Market Structure: BOS (Break of Structure) / CHoCH (Change of Character)
      - Liquidity: teng yuqori/past nuqtalar (stop-loss ov qilinadigan zonalar)
      - Order Block: oxirgi kuchli qarama-qarshi sham (institutsional order zonasi)
      - Fair Value Gap (FVG): 3 ta sham orasidagi narx bo'shlig'i
    """
    if len(df) < lookback:
        lookback = len(df)
    rec = df.tail(lookback).reset_index(drop=True)
    o, h, l, c = rec["open"].values, rec["high"].values, rec["low"].values, rec["close"].values
    n = len(c)

    result = {
        "bos_bullish": False, "bos_bearish": False,
        "choch_bullish": False, "choch_bearish": False,
        "liquidity_high": None, "liquidity_low": None,
        "bullish_ob": None, "bearish_ob": None,
        "fvg_bullish": None, "fvg_bearish": None,
    }

    # ── Market Structure (swing high/low) ──
    swing_hi_idx = [i for i in range(2, n-2) if h[i]>h[i-1] and h[i]>h[i-2] and h[i]>h[i+1] and h[i]>h[i+2]]
    swing_lo_idx = [i for i in range(2, n-2) if l[i]<l[i-1] and l[i]<l[i-2] and l[i]<l[i+1] and l[i]<l[i+2]]

    price = c[-1]

    # BOS (Break of Structure) — trend davom etayotganini tasdiqlaydi
    if len(swing_hi_idx) >= 1:
        last_high = h[swing_hi_idx[-1]]
        if price > last_high:
            result["bos_bullish"] = True
    if len(swing_lo_idx) >= 1:
        last_low = l[swing_lo_idx[-1]]
        if price < last_low:
            result["bos_bearish"] = True

    # CHoCH (Change of Character) — trend YO'NALISHI o'zgarganini bildiradi
    # (oldingi ikkita swing solishtiriladi: pastga ketayotgan trendda birinchi
    #  yuqoriga sinish CHoCH hisoblanadi va aksincha)
    if len(swing_lo_idx) >= 2:
        prev_lo, cur_lo = l[swing_lo_idx[-2]], l[swing_lo_idx[-1]]
        if cur_lo > prev_lo and len(swing_hi_idx) >= 1 and price > h[swing_hi_idx[-1]]:
            result["choch_bullish"] = True
    if len(swing_hi_idx) >= 2:
        prev_hi, cur_hi = h[swing_hi_idx[-2]], h[swing_hi_idx[-1]]
        if cur_hi < prev_hi and len(swing_lo_idx) >= 1 and price < l[swing_lo_idx[-1]]:
            result["choch_bearish"] = True

    # ── Liquidity zones (deyarli teng yuqori/past nuqtalar) ──
    if len(swing_hi_idx) >= 2:
        h1, h2 = h[swing_hi_idx[-2]], h[swing_hi_idx[-1]]
        if abs(h1-h2)/max(h1,h2) < 0.0015:
            result["liquidity_high"] = round(max(h1,h2), 5)
    if len(swing_lo_idx) >= 2:
        l1, l2 = l[swing_lo_idx[-2]], l[swing_lo_idx[-1]]
        if abs(l1-l2)/max(l1,l2) < 0.0015:
            result["liquidity_low"] = round(min(l1,l2), 5)

    # ── Order Block: kuchli harakatdan oldingi oxirgi qarama-qarshi sham ──
    # Bullish OB: kuchli yuqoriga harakatdan oldingi oxirgi qizil sham
    for i in range(n-3, max(n-15,1), -1):
        if c[i] < o[i] and c[i+1] > o[i+1] and (c[i+1]-o[i+1]) > (h[i]-l[i])*0.8:
            result["bullish_ob"] = {"top": round(h[i],5), "bottom": round(l[i],5)}
            break
    # Bearish OB: kuchli pastga harakatdan oldingi oxirgi yashil sham
    for i in range(n-3, max(n-15,1), -1):
        if c[i] > o[i] and c[i+1] < o[i+1] and (o[i+1]-c[i+1]) > (h[i]-l[i])*0.8:
            result["bearish_ob"] = {"top": round(h[i],5), "bottom": round(l[i],5)}
            break

    # ── Fair Value Gap (FVG) — 3 sham orasidagi bo'shliq ──
    if n >= 3:
        # Bullish FVG: 1-sham high < 3-sham low (orada bo'shliq qoladi)
        if h[-3] < l[-1]:
            result["fvg_bullish"] = {"top": round(l[-1],5), "bottom": round(h[-3],5)}
        # Bearish FVG: 1-sham low > 3-sham high
        if l[-3] > h[-1]:
            result["fvg_bearish"] = {"top": round(l[-3],5), "bottom": round(h[-1],5)}

    return result

# ══════════════════════════════════════════════
#  INDIKATORLAR
# ══════════════════════════════════════════════
def calc_ind(df: pd.DataFrame) -> dict:
    c,h,l = df["close"],df["high"],df["low"]
    e10=ta.trend.EMAIndicator(c,10).ema_indicator()
    e50=ta.trend.EMAIndicator(c,50).ema_indicator()
    rsi=ta.momentum.RSIIndicator(c,14).rsi()
    mc=ta.trend.MACD(c,26,12,9)
    bb=ta.volatility.BollingerBands(c,20,2)
    st=ta.momentum.StochasticOscillator(h,l,c,14,3)
    adx=ta.trend.ADXIndicator(h,l,c,14)
    atr=ta.volatility.AverageTrueRange(h,l,c,14).average_true_range()
    return {
        "price":   round(c.iloc[-1],5),
        "e10":     e10.iloc[-1], "e10_1": e10.iloc[-2],
        "e50":     e50.iloc[-1], "e50_1": e50.iloc[-2],
        "rsi":     round(rsi.iloc[-1],2),
        "macd":    mc.macd().iloc[-1],    "macd_s": mc.macd_signal().iloc[-1],
        "macd_1":  mc.macd().iloc[-2],    "macd_s1":mc.macd_signal().iloc[-2],
        "bb_up":   round(bb.bollinger_hband().iloc[-1],5),
        "bb_mid":  round(bb.bollinger_mavg().iloc[-1],5),
        "bb_low":  round(bb.bollinger_lband().iloc[-1],5),
        "stk":     round(st.stoch().iloc[-1],2),
        "std":     round(st.stoch_signal().iloc[-1],2),
        "adx":     round(adx.adx().iloc[-1],2),
        "atr":     round(atr.iloc[-1],5),
    }

# ══════════════════════════════════════════════
#  HTF TREND (4 soatlik)
# ══════════════════════════════════════════════
def get_htf(symbol: str) -> str | None:
    try:
        df=get_price_data(symbol,"1mo","4h")
        if df is None or len(df)<55: return None
        c=df["close"]
        e20=ta.trend.EMAIndicator(c,20).ema_indicator()
        e50=ta.trend.EMAIndicator(c,50).ema_indicator()
        if e20.iloc[-1]>e50.iloc[-1]: return "UP"
        if e20.iloc[-1]<e50.iloc[-1]: return "DOWN"
    except: pass
    return None

# ══════════════════════════════════════════════
#  SIGNAL GENERATSIYA
# ══════════════════════════════════════════════
def generate_signal(symbol,ind,pat,sr,fib,vol,sentiment,htf,trend=None,smc=None) -> dict | None:
    B=0; S=0; R=[]
    p=ind["price"]; atr=ind["atr"]; adx=ind["adx"]
    trend = trend or {}
    smc   = smc or {}

    # 1. EMA
    if ind["e10_1"]<ind["e50_1"] and ind["e10"]>ind["e50"]: B+=2; R.append("📈 EMA kesishdi (yuqori)")
    elif ind["e10"]>ind["e50"]: B+=1; R.append("📈 Trend: yuqori")
    if ind["e10_1"]>ind["e50_1"] and ind["e10"]<ind["e50"]: S+=2; R.append("📉 EMA kesishdi (pastga)")
    elif ind["e10"]<ind["e50"]: S+=1; R.append("📉 Trend: pastga")

    # 2. RSI
    if ind["rsi"]<30:   B+=2; R.append(f"🟢 RSI oversold: {ind['rsi']}")
    elif ind["rsi"]<45: B+=1
    if ind["rsi"]>70:   S+=2; R.append(f"🔴 RSI overbought: {ind['rsi']}")
    elif ind["rsi"]>55: S+=1

    # 3. MACD
    if ind["macd_1"]<ind["macd_s1"] and ind["macd"]>ind["macd_s"]: B+=2; R.append("⚡ MACD yuqoriga")
    elif ind["macd"]>ind["macd_s"]: B+=1
    if ind["macd_1"]>ind["macd_s1"] and ind["macd"]<ind["macd_s"]: S+=2; R.append("⚡ MACD pastga")
    elif ind["macd"]<ind["macd_s"]: S+=1

    # 4. Bollinger
    if p<ind["bb_low"]:  B+=2; R.append(f"🎯 BB quyi: {ind['bb_low']}")
    elif p<ind["bb_mid"]: B+=1
    if p>ind["bb_up"]:   S+=2; R.append(f"🎯 BB yuqori: {ind['bb_up']}")
    elif p>ind["bb_mid"]: S+=1

    # 5. Stochastic
    if ind["stk"]<20 and ind["stk"]>ind["std"]: B+=1; R.append(f"🔵 Stoch oversold: {ind['stk']}")
    if ind["stk"]>80 and ind["stk"]<ind["std"]: S+=1; R.append(f"🔵 Stoch overbought: {ind['stk']}")

    # 6. ADX
    if adx<20:
        B=int(B*0.6); S=int(S*0.6)
        R.append(f"⚠️ ADX kuchsiz ({adx})")
    else:
        R.append(f"💪 ADX kuchli ({adx})")

    # 7. Patternlar
    if pat["bullish_pin"]:   B+=2; R.append("🕯️ Bullish Pin Bar")
    if pat["bull_engulf"]:   B+=2; R.append("🕯️ Bullish Engulfing")
    if pat["double_bottom"]: B+=2; R.append("📐 Double Bottom")
    if pat["bearish_pin"]:   S+=2; R.append("🕯️ Bearish Pin Bar")
    if pat["bear_engulf"]:   S+=2; R.append("🕯️ Bearish Engulfing")
    if pat["double_top"]:    S+=2; R.append("📐 Double Top")
    if pat["doji"]:
        B=max(0,B-1); S=max(0,S-1)
        R.append("➖ Doji — bozor ikkilanmoqda")

    # 8. Fibonacci
    if fib["near"] and fib["near_type"] in ("0.382","0.500","0.618"):
        if B>S: B+=2; R.append(f"📐 Fib {fib['near_type']}: {fib['near']}")
        else:   S+=2; R.append(f"📐 Fib {fib['near_type']}: {fib['near']}")

    # 9. S/R
    if sr["at_support"]:    B+=2; R.append(f"🧱 Support: {sr['support']}")
    if sr["at_resistance"]: S+=2; R.append(f"🧱 Resistance: {sr['resistance']}")

    # 10. Volume
    if vol["high"]:
        if B>S: B+=1; R.append(f"📊 Yuqori volume: {vol['ratio']}x ✅")
        else:   S+=1; R.append(f"📊 Yuqori volume: {vol['ratio']}x ✅")
    elif vol["low"]:
        B=max(0,B-1); S=max(0,S-1)
        R.append(f"📊 Past volume: {vol['ratio']}x ⚠️")

    # 11. Sentiment
    fg=sentiment["score"]
    if sentiment["extreme_fear"]:  B+=2; R.append(f"😱 Extreme Fear ({fg}) — BUY imkoniyati")
    elif sentiment["fear"]:        B+=1; R.append(f"😨 Fear ({fg})")
    elif sentiment["extreme_greed"]: S+=2; R.append(f"🤑 Extreme Greed ({fg}) — SELL imkoniyati")
    elif sentiment["greed"]:       S+=1; R.append(f"😏 Greed ({fg})")
    else:                          R.append(f"😐 Neytral ({fg})")

    # 12. HTF
    if htf=="UP":
        S=int(S*0.5)
        if B>0: R.append("✅ 4H trend: yuqori (BUY mos)")
    elif htf=="DOWN":
        B=int(B*0.5)
        if S>0: R.append("✅ 4H trend: pastga (SELL mos)")

    # 13. Trendline breakout (klassik texnik tahlil)
    if trend.get("uptrend_break"):
        S+=2; R.append(f"📏 Ko'tarilgan trendline buzildi: {trend.get('trendline_support')}")
    if trend.get("downtrend_break"):
        B+=2; R.append(f"📏 Tushgan trendline buzildi: {trend.get('trendline_resistance')}")

    # 14. Smart Money Concepts (SMC)
    if smc.get("choch_bullish"):
        B+=3; R.append("🧠 SMC: CHoCH — trend BUY'ga o'zgardi")
    elif smc.get("bos_bullish"):
        B+=2; R.append("🧠 SMC: BOS — yuqoriga trend davom etmoqda")
    if smc.get("choch_bearish"):
        S+=3; R.append("🧠 SMC: CHoCH — trend SELL'ga o'zgardi")
    elif smc.get("bos_bearish"):
        S+=2; R.append("🧠 SMC: BOS — pastga trend davom etmoqda")

    bull_ob = smc.get("bullish_ob")
    bear_ob = smc.get("bearish_ob")
    if bull_ob and bull_ob["bottom"] <= p <= bull_ob["top"]*1.001:
        B+=2; R.append(f"🟦 Bullish Order Block zonasida: {bull_ob['bottom']}-{bull_ob['top']}")
    if bear_ob and bear_ob["bottom"]*0.999 <= p <= bear_ob["top"]:
        S+=2; R.append(f"🟥 Bearish Order Block zonasida: {bear_ob['bottom']}-{bear_ob['top']}")

    fvg_b = smc.get("fvg_bullish")
    fvg_s = smc.get("fvg_bearish")
    if fvg_b and fvg_b["bottom"] <= p <= fvg_b["top"]:
        B+=1; R.append(f"⚡ Bullish FVG ichida: {fvg_b['bottom']}-{fvg_b['top']}")
    if fvg_s and fvg_s["bottom"] <= p <= fvg_s["top"]:
        S+=1; R.append(f"⚡ Bearish FVG ichida: {fvg_s['bottom']}-{fvg_s['top']}")

    if smc.get("liquidity_high") and p < smc["liquidity_high"] < p + atr*2:
        R.append(f"💧 Yuqori likvidlik zonasi yaqinda: {smc['liquidity_high']} (stop-hunt xavfi)")
    if smc.get("liquidity_low") and p - atr*2 < smc["liquidity_low"] < p:
        R.append(f"💧 Past likvidlik zonasi yaqinda: {smc['liquidity_low']} (stop-hunt xavfi)")

    # Natija
    direction=None; score=0
    if B>=MIN_SCORE and B>S: direction,score = "BUY",B
    elif S>=MIN_SCORE and S>B: direction,score = "SELL",S
    if not direction: return None

    sl = round(p - atr*1.3, 5) if direction=="BUY" else round(p + atr*1.3, 5)
    tp1= round(p + atr*2.0, 5) if direction=="BUY" else round(p - atr*2.0, 5)
    tp2= round(p + atr*3.5, 5) if direction=="BUY" else round(p - atr*3.5, 5)

    strength=("🔥🔥 ULTRA" if score>=14 else "🔥 JUDA KUCHLI" if score>=10
              else "✅ KUCHLI" if score>=7 else "🟡 O'RTA")

    return {"direction":direction,"strength":strength,"score":score,
            "price":p,"sl":sl,"tp1":tp1,"tp2":tp2,
            "rsi":ind["rsi"],"adx":adx,"atr":atr,
            "reasons":R,"sr":sr,"fib":fib,"sentiment":sentiment}

# ══════════════════════════════════════════════
#  YANGILIK TEKSHIRISH
# ══════════════════════════════════════════════
def check_news(symbol: str) -> list:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    out = []
    for n in NEWS_CALENDAR:
        if symbol not in n["pairs"]: continue
        nt   = datetime.strptime(n["date"],"%Y-%m-%d %H:%M")
        diff = (nt-now).total_seconds()/60
        if -30<=diff<=120: out.append({**n,"diff_min":int(diff)})
    return out

# ══════════════════════════════════════════════
#  XABAR FORMATLASH
# ══════════════════════════════════════════════
SYMBOL_EMOJI = {
    "XAUUSD":"🥇","XAGUSD":"🥈","BTCUSD":"₿",
    "EURUSD":"💶","GBPUSD":"💷"
}

def fmt_signal(symbol,sig,news,remaining) -> str:
    se = SYMBOL_EMOJI.get(symbol,"💱")
    de = "🟢" if sig["direction"]=="BUY" else "🔴"
    now= datetime.now(timezone.utc).strftime("%H:%M UTC")
    sr = sig["sr"]; fib=sig["fib"]; fg=sig["sentiment"]

    msg=(f"{se} {de} *{symbol} — {sig['direction']}* {sig['strength']}\n"
         f"━━━━━━━━━━━━━━━━━━\n"
         f"💰 Narx:  `{sig['price']}`\n"
         f"🎯 TP1:   `{sig['tp1']}`\n"
         f"🎯 TP2:   `{sig['tp2']}`\n"
         f"🛡️ SL:    `{sig['sl']}`\n"
         f"📊 RSI:   `{sig['rsi']}`\n"
         f"📈 ADX:   `{sig['adx']}`\n"
         f"⭐ Ball:  `{sig['score']}/30`\n"
         f"⏰ Vaqt:  `{now}`\n"
         f"📅 Qoldi: `{remaining}/{MAX_DAILY_SIGNALS}`\n"
         f"━━━━━━━━━━━━━━━━━━\n")

    if sr["support"] or sr["resistance"]:
        msg += "🧱 *S/R:*\n"
        if sr["support"]:
            msg += f"  🟢 Support: `{sr['support']}`"
            if sr["at_support"]: msg += " ⬅️ HOZIR"
            msg += "\n"
        if sr["resistance"]:
            msg += f"  🔴 Resist:  `{sr['resistance']}`"
            if sr["at_resistance"]: msg += " ⬅️ HOZIR"
            msg += "\n"

    if fib["near"]:
        msg += f"📐 *Fib {fib['near_type']}:* `{fib['near']}`\n"

    msg += f"🧠 *Sentiment:* `{fg['rating']}` ({fg['score']})\n"
    msg += "━━━━━━━━━━━━━━━━━━\n*Sabablar:*\n"
    for r in sig["reasons"]: msg += f"  {r}\n"

    if news:
        msg += "\n⚠️ *YANGILIKLAR:*\n"
        for n in news:
            t = f"{n['diff_min']} daqiqa" if n["diff_min"]>0 else "HOZIR FAOL"
            msg += f"  {n['name']} — {t}\n"
        msg += "💡 _Ehtiyot bo'ling!_"
    return msg.strip()

def fmt_news_alert(news,symbol) -> str:
    e={3:"🔴",2:"🟡",1:"⚪"}.get(news["impact"],"⚪")
    return (f"⚠️ *YANGILIK OGOHLANTIRISHИ*\n━━━━━━━━━━━━━━━━━━\n"
            f"{e} *{news['name']}*\n📌 `{symbol}`\n"
            f"⏰ `{news['date']} UTC`\n⏳ {news['diff_min']} daqiqadan keyin!\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💡 Ochiq pozitsiyalarni yoping!\nYangi savdoga kirmang!")

# ══════════════════════════════════════════════
#  ASOSIY TSIKL
# ══════════════════════════════════════════════
_sent_news   = set()
_daily       = {}
_eod_sent    = set()
_pending     = {}   # {symbol: {"direction": "BUY", "score": 8, "price": ...}} — tasdiq kutayotgan signal

def is_session(symbol: str, now: datetime) -> bool:
    """Bitcoin 24/7, qolganlar sessiya vaqtida"""
    if symbol in CRYPTO_SYMBOLS:
        return True
    return TRADING_START <= now.hour < TRADING_END

def can_signal(symbol,now) -> bool:
    today=now.strftime("%Y-%m-%d")
    if symbol not in _daily or _daily[symbol]["date"]!=today:
        _daily[symbol]={"date":today,"count":0}
    return _daily[symbol]["count"]<MAX_DAILY_SIGNALS

def reg_signal(symbol,now):
    today=now.strftime("%Y-%m-%d")
    if symbol not in _daily or _daily[symbol]["date"]!=today:
        _daily[symbol]={"date":today,"count":0}
    _daily[symbol]["count"]+=1

async def check_and_send(context: ContextTypes.DEFAULT_TYPE):
    bot=context.bot
    now=datetime.now(timezone.utc)
    today=now.strftime("%Y-%m-%d")

    # EOD eslatmasi
    if now.hour==EOD_REMINDER_HOUR and now.minute<CHECK_INTERVAL and today not in _eod_sent:
        _eod_sent.add(today)
        await bot.send_message(chat_id=CHAT_ID,parse_mode="Markdown",
            text=("🌙 *KUN OXIRI ESLATMASI*\n━━━━━━━━━━━━━━━━━━\n"
                  "Ochiq pozitsiyalarni ko'rib chiqing.\n"
                  "Tunda spread kengayadi — yopish tavsiya etiladi.\n\n"
                  "₿ _Bitcoin savdosi davom etadi (24/7)_"))

    sentiment=get_sentiment()

    for symbol in SYMBOLS:
        try:
            # Savdo sessiyasi
            if not is_session(symbol,now): continue

            # Yangilik ogohlantirishi
            nl=check_news(symbol)
            for n in nl:
                if 3<=n["diff_min"]<=7:
                    key=f"{symbol}_{n['date']}"
                    if key not in _sent_news:
                        _sent_news.add(key)
                        await bot.send_message(chat_id=CHAT_ID,parse_mode="Markdown",
                                               text=fmt_news_alert(n,symbol))

            if not can_signal(symbol,now): continue

            df=get_price_data(symbol)
            if df is None or len(df)<60: continue

            ind=calc_ind(df)
            pat=detect_patterns(df)
            sr =calc_sr(df)
            fib=calc_fib(df)
            vol=calc_volume(df)
            htf=get_htf(symbol)
            trend=calc_trendline(df)
            smc  =calc_smc(df)
            sig=generate_signal(symbol,ind,pat,sr,fib,vol,sentiment,htf,trend,smc)

            # ── Confirmation bar mantiqi ──
            # Signal birinchi chiqqanda darhol yubormaymiz — "kutish ro'yxati"ga
            # qo'yamiz. Keyingi tekshiruvda (CHECK_INTERVAL daqiqadan keyin) agar
            # narx hali ham signal yo'nalishida bo'lsa — bu safar yuboramiz.
            # Bu soxta (false) signallarning ko'p qismini filtrlaydi.
            if REQUIRE_CONFIRMATION:
                prev = _pending.get(symbol)
                if sig:
                    if prev and prev["direction"] == sig["direction"]:
                        # Tasdiqlandi — narx hali ham o'sha yo'nalishda ketmoqda
                        confirmed = (
                            (sig["direction"]=="BUY"  and sig["price"] >= prev["price"]) or
                            (sig["direction"]=="SELL" and sig["price"] <= prev["price"])
                        )
                        del _pending[symbol]
                        if not confirmed:
                            sig = None  # narx orqaga ketdi — signal bekor
                    else:
                        # Birinchi marta chiqdi — kutish ro'yxatiga qo'yamiz, hozircha yubormaymiz
                        _pending[symbol] = {"direction": sig["direction"], "price": sig["price"]}
                        sig = None
                else:
                    _pending.pop(symbol, None)

            if sig:
                reg_signal(symbol,now)
                rem=MAX_DAILY_SIGNALS-_daily[symbol]["count"]
                msg=fmt_signal(symbol,sig,nl,rem)
                await bot.send_message(chat_id=CHAT_ID,text=msg,parse_mode="Markdown")
                log.info(f"Signal: {symbol} {sig['direction']} score={sig['score']}")

        except Exception as e:
            log.error(f"Xato ({symbol}): {e}")

# ══════════════════════════════════════════════
#  TELEGRAM KOMANDALAR
# ══════════════════════════════════════════════
async def cmd_start(update,context):
    await update.message.reply_text(
        "👋 *UltimateForexSignalBot v4.0*\n\n"
        "📊 *Kuzatiladigan aktivlar:*\n"
        "  🥇 XAUUSD — Oltin\n"
        "  🥈 XAGUSD — Kumush\n"
        "  ₿  BTCUSD — Bitcoin (24/7)\n"
        "  💶 EURUSD — Euro/Dollar\n"
        "  💷 GBPUSD — Funt/Dollar\n\n"
        f"⚙️ Tekshirish: har {CHECK_INTERVAL} daqiqa\n"
        f"⏰ Sessiya: {TRADING_START}:00–{TRADING_END}:00 UTC\n"
        f"📅 Kunlik limit: {MAX_DAILY_SIGNALS} ta/aktiv\n\n"
        "📋 *Komandalar:*\n"
        "/signal — Hozirgi signallar\n"
        "/status — Joriy narxlar\n"
        "/news — Yangiliklar\n"
        "/sentiment — Bozor kayfiyati\n"
        "/sr XAUUSD — Support/Resistance\n"
        "/fib BTCUSD — Fibonacci\n",
        parse_mode="Markdown"
    )

async def cmd_status(update,context):
    msg="📊 *Joriy Narxlar:*\n━━━━━━━━━━━━━━━━\n"
    for sym in SYMBOLS:
        df=get_price_data(sym,"1d","5m")
        if df is not None and len(df)>1:
            p =round(df["close"].iloc[-1],5)
            ch=round(df["close"].iloc[-1]-df["close"].iloc[0],5)
            e ="🟢" if ch>=0 else "🔴"
            se=SYMBOL_EMOJI.get(sym,"💱")
            msg+=f"{se}{e} *{sym}*: `{p}` ({'+' if ch>=0 else ''}{ch})\n"
    await update.message.reply_text(msg,parse_mode="Markdown")

async def cmd_signal(update,context):
    await update.message.reply_text("⏳ Barcha aktivlar tahlil qilinmoqda (SMC + Trendline bilan)...")
    sentiment=get_sentiment(); found=0
    for sym in SYMBOLS:
        df=get_price_data(sym)
        if df is None or len(df)<60: continue
        ind=calc_ind(df); pat=detect_patterns(df)
        sr=calc_sr(df); fib=calc_fib(df)
        vol=calc_volume(df); htf=get_htf(sym)
        trend=calc_trendline(df); smc=calc_smc(df)
        sig=generate_signal(sym,ind,pat,sr,fib,vol,sentiment,htf,trend,smc)
        if sig:
            found+=1
            msg=fmt_signal(sym,sig,check_news(sym),MAX_DAILY_SIGNALS)
            msg += "\n\n⚠️ _Bu /signal buyrug'i — darhol natija. Avtomatik signal esa tasdiqlash uchun 1 bar kutadi._"
            await update.message.reply_text(msg,parse_mode="Markdown")
    if not found:
        await update.message.reply_text("⏸ Hozircha kuchli signal yo'q.")

async def cmd_news(update,context):
    now=datetime.now(timezone.utc).replace(tzinfo=None)
    msg="📰 *Yaqin yangiliklar:*\n━━━━━━━━━━━━━━━━\n"
    found=False
    for n in NEWS_CALENDAR:
        nt=datetime.strptime(n["date"],"%Y-%m-%d %H:%M")
        diff=(nt-now).total_seconds()/60
        if 0<=diff<=1440:
            e={3:"🔴",2:"🟡",1:"⚪"}.get(n["impact"],"⚪")
            msg+=f"{e} {n['name']}\n  ⏰ {n['date']} | {int(diff//60)}s {int(diff%60)}d\n\n"
            found=True
    if not found: msg+="✅ 24 soatda muhim yangilik yo'q"
    await update.message.reply_text(msg,parse_mode="Markdown")

async def cmd_sentiment(update,context):
    s=get_sentiment()
    e=("😱" if s["extreme_fear"] else "😨" if s["fear"] else
       "😐" if s["neutral"]      else "😏" if s["greed"] else "🤑")
    await update.message.reply_text(
        f"🧠 *Fear & Greed Index*\n━━━━━━━━━━━━━━━━\n"
        f"{e} *{s['rating']}* — `{s['score']}/100`\n\n"
        f"_0-25: Extreme Fear (sotib olish imkoniyati)_\n"
        f"_25-45: Fear_\n_45-55: Neutral_\n"
        f"_55-75: Greed_\n_75-100: Extreme Greed_",
        parse_mode="Markdown"
    )

async def cmd_sr(update,context):
    sym=(context.args[0].upper() if context.args else "XAUUSD")
    df=get_price_data(sym)
    if df is None:
        await update.message.reply_text(f"❌ {sym} ma'lumot olib bo'lmadi"); return
    sr=calc_sr(df); se=SYMBOL_EMOJI.get(sym,"💱")
    msg=(f"{se} *{sym} — Support/Resistance*\n━━━━━━━━━━━━━━━━\n"
         f"💰 Narx: `{round(df['close'].iloc[-1],5)}`\n"
         f"🟢 Support: `{sr['support'] or 'topilmadi'}`"
         f"{' ⬅️ HOZIR' if sr['at_support'] else ''}\n"
         f"🔴 Resist:  `{sr['resistance'] or 'topilmadi'}`"
         f"{' ⬅️ HOZIR' if sr['at_resistance'] else ''}")
    await update.message.reply_text(msg,parse_mode="Markdown")

async def cmd_fib(update,context):
    sym=(context.args[0].upper() if context.args else "XAUUSD")
    df=get_price_data(sym)
    if df is None:
        await update.message.reply_text(f"❌ {sym} ma'lumot olib bo'lmadi"); return
    fib=calc_fib(df); se=SYMBOL_EMOJI.get(sym,"💱")
    msg=(f"{se} *{sym} — Fibonacci*\n━━━━━━━━━━━━━━━━\n"
         f"📈 Swing High: `{fib['swing_hi']}`\n"
         f"📉 Swing Low:  `{fib['swing_lo']}`\n\n")
    for k,v in fib["levels"].items():
        arrow=" ⬅️ HOZIR" if (fib["near"] and abs(v-fib["near"])<0.00001) else ""
        msg+=f"  *{k}*: `{v}`{arrow}\n"
    await update.message.reply_text(msg,parse_mode="Markdown")

# ══════════════════════════════════════════════
#  ISHGA TUSHIRISH
# ══════════════════════════════════════════════
# ══════════════════════════════════════════════
#  SOXTA HTTP SERVER (Render "Web Service" talabi uchun)
# ══════════════════════════════════════════════
class _PingHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"UltimateForexSignalBot ishlamoqda!")
    def log_message(self, format, *args):
        pass  # Konsolni keraksiz log bilan to'ldirmaslik uchun

def start_fake_server():
    try:
        port = int(os.environ.get("PORT", 10000))
        server = HTTPServer(("0.0.0.0", port), _PingHandler)
        log.info(f"✅ Soxta HTTP server {port}-portda ochildi (Render talabi uchun)")
        server.serve_forever()
    except Exception as e:
        log.error(f"❌ Soxta server xatosi: {e}")

def main():
    app=Application.builder().token(BOT_TOKEN).build()
    for cmd,fn in [("start",cmd_start),("status",cmd_status),
                   ("signal",cmd_signal),("news",cmd_news),
                   ("sentiment",cmd_sentiment),("sr",cmd_sr),("fib",cmd_fib)]:
        app.add_handler(CommandHandler(cmd,fn))
    app.job_queue.run_repeating(check_and_send,interval=CHECK_INTERVAL*60,first=15)
    log.info(f"UltimateForexSignalBot v4.0 ishga tushdi!")
    app.run_polling()

if __name__=="__main__":
    # PORT'ni HAMMA narsadan oldin, darhol ochamiz — Render buni tez ko'rishi kerak
    threading.Thread(target=start_fake_server, daemon=True).start()
    main()
