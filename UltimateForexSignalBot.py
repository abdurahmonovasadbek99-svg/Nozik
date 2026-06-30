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

import os, logging
from datetime import datetime, timezone
import requests, pandas as pd, ta
from telegram.ext import Application, CommandHandler, ContextTypes

# ══════════════════════════════════════════════
#  SOZLAMALAR
# ══════════════════════════════════════════════
import os
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
CHAT_ID   = os.environ.get("CHAT_ID", "YOUR_CHAT_ID_HERE")

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
def generate_signal(symbol,ind,pat,sr,fib,vol,sentiment,htf) -> dict | None:
    B=0; S=0; R=[]
    p=ind["price"]; atr=ind["atr"]; adx=ind["adx"]

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
         f"⭐ Ball:  `{sig['score']}/20`\n"
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
            sig=generate_signal(symbol,ind,pat,sr,fib,vol,sentiment,htf)

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
    await update.message.reply_text("⏳ Barcha aktivlar tahlil qilinmoqda...")
    sentiment=get_sentiment(); found=0
    for sym in SYMBOLS:
        df=get_price_data(sym)
        if df is None or len(df)<60: continue
        ind=calc_ind(df); pat=detect_patterns(df)
        sr=calc_sr(df); fib=calc_fib(df)
        vol=calc_volume(df); htf=get_htf(sym)
        sig=generate_signal(sym,ind,pat,sr,fib,vol,sentiment,htf)
        if sig:
            found+=1
            msg=fmt_signal(sym,sig,check_news(sym),MAX_DAILY_SIGNALS)
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
    main()
