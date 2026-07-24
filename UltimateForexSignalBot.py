#!/usr/bin/env python3
"""
UltimateForexSignalBot v27.0 (Precise Entry) — Telegram Signal Bot
═══════════════════════════════════════════════════
Juftliklar: EURUSD, GBPUSD, AUDUSD, USDJPY, NZDUSD

Signal manbalari (ICT / Smart Money Concepts asosida):
  1.  EMA trend (10/50) — umumiy yo'nalish
  2.  ICT Premium/Discount zonalar — Equilibrium asosida
  3.  ICT Killzones — London/NY yuqori faollik soatlari
  4.  ADX — trend kuchi filtri
  5.  Yapon shamlari patternlari (Pin Bar, Engulfing, Hammer, Morning/Evening
      Star, Three White Soldiers/Black Crows, Harami, Double Top/Bottom, Doji)
  6.  Fibonacci darajalari (0.382, 0.5, 0.618)
  7.  Support / Resistance (SNR) darajalari
  8.  Volume tahlili
  9.  Sentiment (Fear & Greed Index)
 10.  Trendline breakout — klassik chiziqli trend siniши
 11.  Smart Money: BOS / CHoCH (Market Structure)
 12.  Smart Money: Order Blocks
 13.  Smart Money: Imbalans / Fair Value Gap (FVG)
 14.  Smart Money: Liquidity zones (stop-hunt ogohlantirishi)
 15.  Multi-timeframe tasdiqlash (15m + 4h)

Filtrlar:
  - Risk-Reward (min 1.8)
  - Volatillik (juda tinch/notinch bozorni chetlab o'tish)
  - Correlation (EURUSD/GBPUSD ziddiyati)
  - Confirmation bar (signal 1 bar kutib tasdiqlanadi)

Eslatma: RSI, MACD, Stochastic, Bollinger Bands ATAYLAB olib
tashlangan — bular "lagging" (kechikuvchi) indikatorlar bo'lib, ICT/SMC
metodologiyasida narx harakati (price action) va institutsional order
oqimi tahlili ustunlik qiladi.

Intraday/Swing:
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
FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY", "")  # finnhub.io — bepul ro'yxatdan o'ting

# Juftliklar va Yahoo Finance tickerlari
SYMBOL_MAP = {
    "EURUSD":  "EURUSD=X",  # Euro/Dollar
    "GBPUSD":  "GBPUSD=X",  # Funt/Dollar
    "AUDUSD":  "AUDUSD=X",  # Avstraliya dollari/AQSh dollari
    "USDJPY":  "JPY=X",     # Dollar/Yaponiya yenasi
    "NZDUSD":  "NZDUSD=X",  # Yangi Zelandiya dollari/AQSh dollari
}
SYMBOLS = list(SYMBOL_MAP.keys())

CRYPTO_SYMBOLS = set()   # Hozircha kripto yo'q
INDEX_SYMBOLS  = set()   # Hozircha indeks yo'q

# Intraday sozlamalar
CHECK_INTERVAL        = 12   # daqiqa (server yukini kamaytirish uchun oshirildi)
MAX_DAILY_SIGNALS     = 2    # har juftlik + har rejim uchun (bitta aniq signal maqsadida kamaytirildi)
TRADING_START         = 7    # UTC (London sessiyasi boshlanishi)
TRADING_END           = 21   # UTC (NY sessiyasi tugashi)
ASIA_SESSION_START    = 23   # UTC (Tokyo sessiyasi boshlanishi)
ASIA_SESSION_END      = 8    # UTC (Tokyo sessiyasi tugashi, ertasi kun)
EOD_REMINDER_HOUR     = 20   # UTC
MIN_SCORE             = 9    # Minimal ball (avval 6 edi — qattiqroq filtr uchun oshirildi)
REQUIRE_CONFIRMATION  = True # Signal chiqqach 1 bar tasdiqlashini kutish

# ══════════════════════════════════════════════
#  YANGILIKLAR — FINNHUB API ORQALI AVTOMATIK
# ══════════════════════════════════════════════
# Qo'lda yozilgan jadval o'rniga endi Finnhub.io iqtisodiy taqvimidan
# real vaqtda olinadi. Bepul API kalitni https://finnhub.io da oling
# va Render'da FINNHUB_API_KEY environment variable sifatida kiriting.
#
# Agar FINNHUB_API_KEY bo'sh bo'lsa, bot ishlayveradi, lekin yangilik
# ogohlantirishlarisiz (faqat texnik signal bilan).

# Qaysi valyuta har bir juftlikka daxldor (Finnhub "country" maydoniga qarab)
PAIR_COUNTRY_MAP = {
    "EURUSD": {"EU", "US"},
    "GBPUSD": {"GB", "US"},
    "AUDUSD": {"AU", "US"},
    "USDJPY": {"US", "JP"},
    "NZDUSD": {"NZ", "US"},
}

_news_cache = {"data": None, "updated": None}

def fetch_news_calendar() -> list:
    """
    Finnhub'dan keyingi 14 kunlik iqtisodiy taqvimni oladi va bizning
    ichki formatga o'giradi. Natija 1 soatga keshlanadi (ortiqcha
    so'rov yubormaslik uchun).
    """
    now = datetime.now(timezone.utc)
    if _news_cache["data"] is not None and _news_cache["updated"] is not None:
        if (now - _news_cache["updated"]).seconds < 3600:
            return _news_cache["data"]

    if not FINNHUB_API_KEY:
        return []

    try:
        frm = now.strftime("%Y-%m-%d")
        to  = (now + pd.Timedelta(days=14)).strftime("%Y-%m-%d")
        r = requests.get(
            "https://finnhub.io/api/v1/calendar/economic",
            params={"from": frm, "to": to, "token": FINNHUB_API_KEY},
            timeout=10
        )
        raw = r.json().get("economicCalendar", [])

        events = []
        for ev in raw:
            impact_map = {"low": 1, "medium": 2, "high": 3}
            impact = impact_map.get(str(ev.get("impact", "")).lower(), 1)
            if impact < 2:
                continue  # kichik ta'sirli yangiliklarni o'tkazib yuboramiz

            country = ev.get("country", "")
            pairs = [p for p, countries in PAIR_COUNTRY_MAP.items() if country in countries]
            if not pairs:
                continue

            date_str = ev.get("time", "")  # "2026-07-03 12:30:00"
            if not date_str:
                continue
            date_fmt = date_str[:16]  # "YYYY-MM-DD HH:MM"

            emoji = "🔴" if impact == 3 else "🟡"
            events.append({
                "date":   date_fmt,
                "name":   f"{emoji} {ev.get('event', 'Iqtisodiy yangilik')}",
                "impact": impact,
                "pairs":  pairs,
            })

        _news_cache["data"]    = events
        _news_cache["updated"] = now
        log.info(f"📰 Finnhub'dan {len(events)} ta yangilik yuklandi")
        return events

    except Exception as e:
        log.error(f"Finnhub yangiliklar xatosi: {e}")
        return _news_cache["data"] or []

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
#  VWAP (Volume Weighted Average Price)
# ══════════════════════════════════════════════
def calc_vwap(df: pd.DataFrame) -> dict:
    """
    VWAP — institutsional treyderlarning asosiy referens narxi.
    Narx VWAP'dan yuqorida = kunlik bosim BUY tomonda (aksincha SELL).
    Forex'da haqiqiy tick-volume yo'q bo'lgani uchun (H+L+C)/3 * volume
    proksisi ishlatiladi — bu yetarlicha ishonchli taxmin beradi.
    """
    try:
        typical = (df["high"] + df["low"] + df["close"]) / 3
        vol = df["volume"].replace(0, 1)  # nol volume bo'lsa 1 deb olamiz
        cum_vol = vol.cumsum()
        cum_tp_vol = (typical * vol).cumsum()
        vwap = (cum_tp_vol / cum_vol).iloc[-1]
        price = df["close"].iloc[-1]
        return {
            "vwap": round(vwap, 5),
            "above": price > vwap,
            "below": price < vwap,
            "distance_pct": round(abs(price - vwap) / price * 100, 3) if price else 0,
        }
    except Exception:
        return {"vwap": None, "above": False, "below": False, "distance_pct": 0}

# ══════════════════════════════════════════════
#  OPENING RANGE BREAKOUT (ORB)
# ══════════════════════════════════════════════
def calc_orb(df: pd.DataFrame, now: datetime, session_start_hour: int) -> dict:
    """
    London/NY ochilishidan keyingi birinchi 30 daqiqalik range hisoblanadi.
    Bu range'dan tashqariga chiqish (breakout) statistik jihatdan kuchli
    davom etish signali beradi — professional scalperlar orasida eng
    ko'p ishlatiladigan usullardan biri.
    """
    try:
        session_open = now.replace(hour=session_start_hour, minute=0, second=0, microsecond=0)
        if now < session_open:
            session_open -= pd.Timedelta(days=1)
        window_end = session_open + pd.Timedelta(minutes=30)

        df_local = df.copy()
        df_local["time"] = pd.to_datetime(df_local["time"]).dt.tz_localize(None)
        mask = (df_local["time"] >= session_open.replace(tzinfo=None)) & \
               (df_local["time"] <= window_end.replace(tzinfo=None))
        orb_bars = df_local[mask]

        if len(orb_bars) < 2:
            return {"available": False}

        orb_high = orb_bars["high"].max()
        orb_low  = orb_bars["low"].min()
        price = df["close"].iloc[-1]

        return {
            "available": True,
            "orb_high": round(orb_high, 5),
            "orb_low": round(orb_low, 5),
            "breakout_up": price > orb_high,
            "breakout_down": price < orb_low,
        }
    except Exception:
        return {"available": False}

# ══════════════════════════════════════════════
#  MOMENTUM CANDLE + RETEST
# ══════════════════════════════════════════════
def calc_momentum_retest(df: pd.DataFrame) -> dict:
    """
    Kuchli (ATR'dan katta) sham paydo bo'lgach, narx o'sha shamning
    tanasiga (body) qaytib kelib "retest" qilishi — professional
    scalperlarning eng ko'p ishlatadigan kirish texnikalaridan biri.
    Retest darajasidan qayta sakrash kuchli davom etish signali beradi.
    """
    try:
        o, h, l, c = df["open"].values, df["high"].values, df["low"].values, df["close"].values
        atr = ta.volatility.AverageTrueRange(df["high"], df["low"], df["close"], 14).average_true_range().iloc[-1]
        if len(c) < 5 or atr <= 0:
            return {"bullish_retest": False, "bearish_retest": False}

        # Oxirgi 5 barda ATR'dan 1.5x katta sham qidiramiz
        for i in range(len(c) - 5, len(c) - 1):
            body = abs(c[i] - o[i])
            if body < atr * 1.5:
                continue
            is_bull_momentum = c[i] > o[i]
            momentum_level = c[i] if is_bull_momentum else o[i]  # sham yopilish/ochilish darajasi
            price = c[-1]
            near_level = abs(price - momentum_level) < atr * 0.3

            if is_bull_momentum and near_level and price > l[-1]:
                return {"bullish_retest": True, "bearish_retest": False, "level": round(momentum_level, 5)}
            if not is_bull_momentum and near_level and price < h[-1]:
                return {"bullish_retest": False, "bearish_retest": True, "level": round(momentum_level, 5)}

        return {"bullish_retest": False, "bearish_retest": False}
    except Exception:
        return {"bullish_retest": False, "bearish_retest": False}

# ══════════════════════════════════════════════
#  ROUND NUMBER MAGNETISM
# ══════════════════════════════════════════════
def calc_round_number(price: float, symbol: str) -> dict:
    """
    Narx psixologik butun raqamlarga (masalan 1.1000, 2400.00) tortiladi
    va ko'pincha shu darajalarda to'xtaydi yoki qaytadi — bank/institutsional
    order'lar odatda shu "aylanma" raqamlarga qo'yiladi.
    """
    # Juftlik turiga qarab "dumaloq" daraja qadamini aniqlaymiz
    if symbol in ("XAUUSD", "XAGUSD"):
        step = 10.0 if symbol == "XAUUSD" else 0.5
    elif "JPY" in symbol:
        step = 0.5
    else:
        step = 0.0050  # forex uchun 50 pip

    nearest = round(price / step) * step
    distance = abs(price - nearest)
    close_enough = distance < step * 0.15

    return {
        "near_round": close_enough,
        "level": round(nearest, 5),
    }

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
                             "bear_engulf","doji","double_top","double_bottom",
                             "morning_star","evening_star",
                             "three_white_soldiers","three_black_crows",
                             "bull_harami","bear_harami",
                             "hammer","hanging_man"]}
    if n < 3: return p
    body = abs(c[-1]-o[-1]); rng = h[-1]-l[-1]
    uw = h[-1]-max(c[-1],o[-1]); lw = min(c[-1],o[-1])-l[-1]

    # ── Trendni aniqlash (oxirgi patternni to'g'ri talqin qilish uchun) ──
    # Hammer past trenddan keyin bo'lsa qaytish, Hanging Man yuqori trenddan
    # keyin bo'lsa qaytish belgisi — shuning uchun oldingi 5 barga qaraymiz.
    prior_trend_down = n >= 6 and c[-6] > c[-2]
    prior_trend_up   = n >= 6 and c[-6] < c[-2]

    if rng > 0:
        if lw > body*2 and uw < body*0.5:
            p["bullish_pin"] = True
            if prior_trend_down: p["hammer"] = True
        if uw > body*2 and lw < body*0.5:
            p["bearish_pin"] = True
            if prior_trend_up: p["hanging_man"] = True
        if body < rng*0.1: p["doji"] = True

    pt=max(o[-2],c[-2]); pb=min(o[-2],c[-2])
    ct=max(o[-1],c[-1]); cb=min(o[-1],c[-1])
    if c[-2]<o[-2] and c[-1]>o[-1] and ct>=pt and cb<=pb: p["bull_engulf"] = True
    if c[-2]>o[-2] and c[-1]<o[-1] and ct>=pt and cb<=pb: p["bear_engulf"] = True

    # ── Harami — kichik sham oldingi kattaning "ichida" (Engulfing'ning teskarisi) ──
    if c[-2]<o[-2] and ct<=pt and cb>=pb and (ct-cb) < (pt-pb)*0.6:
        p["bull_harami"] = True
    if c[-2]>o[-2] and ct<=pt and cb>=pb and (ct-cb) < (pt-pb)*0.6:
        p["bear_harami"] = True

    # ── Morning Star / Evening Star (3 shamli qaytish patterni) ──
    if n >= 3:
        b1 = abs(c[-3]-o[-3]); b2 = abs(c[-2]-o[-2]); b3 = abs(c[-1]-o[-1])
        # Morning Star: katta qizil → kichik (indecision) → katta yashil
        if c[-3]<o[-3] and b1>0 and b2 < b1*0.4 and c[-1]>o[-1] and b3 > b1*0.6 and c[-1] > (o[-3]+c[-3])/2:
            p["morning_star"] = True
        # Evening Star: katta yashil → kichik → katta qizil
        if c[-3]>o[-3] and b1>0 and b2 < b1*0.4 and c[-1]<o[-1] and b3 > b1*0.6 and c[-1] < (o[-3]+c[-3])/2:
            p["evening_star"] = True

    # ── Three White Soldiers / Three Black Crows (3 shamli trend davomiyligi) ──
    if n >= 3:
        if (c[-3]>o[-3] and c[-2]>o[-2] and c[-1]>o[-1] and
            c[-2]>c[-3] and c[-1]>c[-2] and
            o[-2]>o[-3] and o[-2]<c[-3] and o[-1]>o[-2] and o[-1]<c[-2]):
            p["three_white_soldiers"] = True
        if (c[-3]<o[-3] and c[-2]<o[-2] and c[-1]<o[-1] and
            c[-2]<c[-3] and c[-1]<c[-2] and
            o[-2]<o[-3] and o[-2]>c[-3] and o[-1]<o[-2] and o[-1]>c[-2]):
            p["three_black_crows"] = True

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

    # CHoCH (Change of Character) — trend YO'NALISHI o'zgarganini bildiradi.
    # Bullish CHoCH: trend PASTGA ketayotgan edi (pastki nuqtalar pasayib
    # bormoqda), keyin narx BIRINCHI MARTA oldingi swing high'ni sindirsa —
    # bu pastga trendning tugab, yuqoriga o'zgarganini bildiradi.
    if len(swing_lo_idx) >= 2:
        prev_lo, cur_lo = l[swing_lo_idx[-2]], l[swing_lo_idx[-1]]
        if cur_lo < prev_lo and len(swing_hi_idx) >= 1 and price > h[swing_hi_idx[-1]]:
            result["choch_bullish"] = True
    # Bearish CHoCH: trend YUQORIGA ketayotgan edi (yuqori nuqtalar
    # ko'tarilib bormoqda), keyin narx BIRINCHI MARTA oldingi swing low'ni
    # sindirsa — bu yuqoriga trendning tugab, pastga o'zgarganini bildiradi.
    if len(swing_hi_idx) >= 2:
        prev_hi, cur_hi = h[swing_hi_idx[-2]], h[swing_hi_idx[-1]]
        if cur_hi > prev_hi and len(swing_lo_idx) >= 1 and price < l[swing_lo_idx[-1]]:
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
#  ICT: PREMIUM / DISCOUNT ZONALAR
# ══════════════════════════════════════════════
def calc_premium_discount(df: pd.DataFrame, lookback: int = 50) -> dict:
    """
    ICT konsepti: oxirgi swing range 50% (Equilibrium) ga bo'linadi.
    - Discount zona (past 50%) — faqat BUY qidiriladi
    - Premium zona (yuqori 50%) — faqat SELL qidiriladi
    Bu "arzon joydan sotib ol, qimmat joydan sot" mantig'i.
    """
    if len(df) < lookback:
        lookback = len(df)
    rec = df.tail(lookback)
    swing_hi = rec["high"].max()
    swing_lo = rec["low"].min()
    eq = (swing_hi + swing_lo) / 2  # Equilibrium (50%)
    price = df["close"].iloc[-1]

    zone = "premium" if price > eq else "discount"
    pct_in_range = round((price - swing_lo) / (swing_hi - swing_lo) * 100, 1) if swing_hi != swing_lo else 50.0

    return {
        "zone": zone,
        "equilibrium": round(eq, 5),
        "swing_hi": round(swing_hi, 5),
        "swing_lo": round(swing_lo, 5),
        "pct_in_range": pct_in_range,   # 0% = eng past, 100% = eng yuqori
    }

# ══════════════════════════════════════════════
#  ICT: KILLZONES (yuqori likvidlik savdo soatlari)
# ══════════════════════════════════════════════
def get_ict_killzone(now: datetime) -> str | None:
    """
    ICT konsepti bo'yicha eng faol savdo oynalari (UTC vaqtida):
      - Asia Killzone:      00:00-03:00 (Tokyo ochilishi, likvidlik shakllanishi)
      - London Killzone:    07:00-10:00
      - New York Killzone:  12:00-15:00
      - London Close:       15:00-17:00
    Bu vaqtlarda institutsional harakat ehtimoli yuqori hisoblanadi.
    """
    h = now.hour
    if 0 <= h < 3:
        return "Asia Killzone"
    if 7 <= h < 10:
        return "London Killzone"
    if 12 <= h < 15:
        return "New York Killzone"
    if 15 <= h < 17:
        return "London Close"
    return None

# ══════════════════════════════════════════════
#  INDIKATORLAR
# ══════════════════════════════════════════════
def calc_ind(df: pd.DataFrame) -> dict:
    c,h,l = df["close"],df["high"],df["low"]
    e10=ta.trend.EMAIndicator(c,10).ema_indicator()
    e50=ta.trend.EMAIndicator(c,50).ema_indicator()
    adx=ta.trend.ADXIndicator(h,l,c,14)
    atr=ta.volatility.AverageTrueRange(h,l,c,14).average_true_range()
    return {
        "price":   round(c.iloc[-1],5),
        "e10":     e10.iloc[-1], "e10_1": e10.iloc[-2],
        "e50":     e50.iloc[-1], "e50_1": e50.iloc[-2],
        "adx":     round(adx.adx().iloc[-1],2),
        "atr":     round(atr.iloc[-1],5),
    }

# ══════════════════════════════════════════════
#  HTF TREND (4 soatlik)
# ══════════════════════════════════════════════
def get_htf(symbol: str) -> str | None:
    """Katta rasm — 4H trend (Swing va Intraday uchun umumiy yo'nalish tasdiqlash)"""
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

def get_tf_bias(symbol: str, period: str, interval: str) -> str | None:
    """Bitta timeframe uchun tez EMA(5/13) asosida yo'nalishni aniqlaydi"""
    try:
        df = get_price_data(symbol, period, interval)
        if df is None or len(df) < 20:
            return None
        c = df["close"]
        e5  = ta.trend.EMAIndicator(c, 5).ema_indicator()
        e13 = ta.trend.EMAIndicator(c, 13).ema_indicator()
        if e5.iloc[-1] > e13.iloc[-1]: return "BUY"
        if e5.iloc[-1] < e13.iloc[-1]: return "SELL"
        return None
    except Exception:
        return None

def get_scalp_confluence(symbol: str, direction: str) -> dict:
    """
    Scalping uchun Multi-Timeframe Confluence — 5m, 15m va 1H bir vaqtda
    tekshiriladi. Signal faqat KAMIDA 2 ta timeframe mos kelsagina
    "tasdiqlangan" hisoblanadi (barchasi shart emas, lekin ko'pchilik).
    Bu eng aniq, shovqindan tozalangan kirish nuqtasini beradi.
    """
    tf_5m  = get_tf_bias(symbol, "1d", "5m")
    tf_15m = get_tf_bias(symbol, "5d", "15m")
    tf_1h  = get_tf_bias(symbol, "1mo", "1h")

    biases = [tf_5m, tf_15m, tf_1h]
    matching = sum(1 for b in biases if b == direction)
    total_known = sum(1 for b in biases if b is not None)

    return {
        "confirmed": matching >= 2,          # kamida 2/3 timeframe mos
        "matching": matching,
        "total": total_known,
        "detail": f"5m:{tf_5m or '–'} 15m:{tf_15m or '–'} 1H:{tf_1h or '–'}",
    }

# ══════════════════════════════════════════════
#  SIGNAL GENERATSIYA
# ══════════════════════════════════════════════
def generate_signal(symbol,ind,pat,sr,fib,vol,sentiment,htf,trend=None,smc=None,pd_zone=None,killzone=None,mode="scalp",vwap=None,orb=None,mom_retest=None,round_num=None) -> dict | None:
    B=0; S=0; R=[]
    p=ind["price"]; atr=ind["atr"]; adx=ind["adx"]
    trend  = trend or {}
    smc    = smc or {}
    pd_zone= pd_zone or {}
    vwap   = vwap or {}
    orb    = orb or {}
    mom_retest = mom_retest or {}
    round_num  = round_num or {}

    # 1. EMA (umumiy trend yo'nalishi)
    if ind["e10_1"]<ind["e50_1"] and ind["e10"]>ind["e50"]: B+=2; R.append("📈 EMA kesishdi (yuqori)")
    elif ind["e10"]>ind["e50"]: B+=1; R.append("📈 Trend: yuqori")
    if ind["e10_1"]>ind["e50_1"] and ind["e10"]<ind["e50"]: S+=2; R.append("📉 EMA kesishdi (pastga)")
    elif ind["e10"]<ind["e50"]: S+=1; R.append("📉 Trend: pastga")

    # 2. ICT Premium/Discount — faqat to'g'ri zonadan signal qidiramiz
    if pd_zone:
        if pd_zone["zone"] == "discount":
            B+=2; R.append(f"💰 Discount zonada ({pd_zone['pct_in_range']}%) — BUY qulay")
            S = max(0, S-2)  # Premium zonada bo'lmasa SELL ehtimoli pasayadi
        else:
            S+=2; R.append(f"💎 Premium zonada ({pd_zone['pct_in_range']}%) — SELL qulay")
            B = max(0, B-2)


    # 6. ADX
    if adx<20:
        B=int(B*0.6); S=int(S*0.6)
        R.append(f"⚠️ ADX kuchsiz ({adx})")
    else:
        R.append(f"💪 ADX kuchli ({adx})")

    # 7. Klassik yapon shamlari patternlari
    if pat["bullish_pin"]:   B+=2; R.append("🕯️ Bullish Pin Bar")
    if pat["bull_engulf"]:   B+=2; R.append("🕯️ Bullish Engulfing")
    if pat["double_bottom"]: B+=2; R.append("📐 Double Bottom")
    if pat["hammer"]:        B+=2; R.append("🔨 Hammer (pastdan qaytish)")
    if pat["morning_star"]:  B+=3; R.append("🌟 Morning Star (kuchli qaytish)")
    if pat["three_white_soldiers"]: B+=3; R.append("🕯️🕯️🕯️ Three White Soldiers (kuchli davomiylik)")
    if pat["bull_harami"]:   B+=1; R.append("➕ Bullish Harami (trend zaiflashmoqda)")

    if pat["bearish_pin"]:   S+=2; R.append("🕯️ Bearish Pin Bar")
    if pat["bear_engulf"]:   S+=2; R.append("🕯️ Bearish Engulfing")
    if pat["double_top"]:    S+=2; R.append("📐 Double Top")
    if pat["hanging_man"]:   S+=2; R.append("🔨 Hanging Man (yuqoridan qaytish)")
    if pat["evening_star"]:  S+=3; R.append("🌟 Evening Star (kuchli qaytish)")
    if pat["three_black_crows"]: S+=3; R.append("🕯️🕯️🕯️ Three Black Crows (kuchli davomiylik)")
    if pat["bear_harami"]:   S+=1; R.append("➕ Bearish Harami (trend zaiflashmoqda)")

    if pat["doji"]:
        B=max(0,B-1); S=max(0,S-1)
        R.append("➖ Doji — bozor ikkilanmoqda")

    # 8. Fibonacci
    # 8. Fibonacci retracement — trend yo'nalishi bilan birga ishlaydi.
    # Agar umumiy trend YUQORIGA (EMA asosida) bo'lsa va narx Fib darajasiga
    # (masalan 0.5, 0.618) pastdan qaytib kelgan bo'lsa — bu klassik "buy the
    # dip" imkoniyati. Aksincha trend PASTGA bo'lsa va narx Fib darajasiga
    # yuqoridan qaytgan bo'lsa — "sell the rally" imkoniyati.
    if fib["near"] and fib["near_type"] in ("0.382","0.500","0.618"):
        if ind["e10"] > ind["e50"]:
            B+=2; R.append(f"📐 Fib {fib['near_type']} qaytish (trend yuqori): {fib['near']}")
        elif ind["e10"] < ind["e50"]:
            S+=2; R.append(f"📐 Fib {fib['near_type']} qaytish (trend past): {fib['near']}")

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

    # 11. Sentiment — DIQQAT: bu AQSh aksiya bozori ko'rsatkichi (S&P 500),
    # forex juftliklariga bilvosita ta'sir qiladi, shuning uchun ball og'irligi
    # pasaytirilgan (endi faqat ozgina qo'shimcha ta'sir, hal qiluvchi emas).
    fg=sentiment["score"]
    if sentiment["extreme_fear"]:  B+=1; R.append(f"😱 Extreme Fear ({fg})")
    elif sentiment["extreme_greed"]: S+=1; R.append(f"🤑 Extreme Greed ({fg})")
    else:                          R.append(f"😐 Sentiment: {fg}")

    # 12. HTF (Top-Down Analysis) — Scalping uchun QATTIQ filtr
    if mode == "scalp":
        # Scalping'da 1H/4H trendga zid signal UMUMAN qabul qilinmaydi —
        # bu "shovqinga qarshi savdo qilish" xatosining oldini oladi.
        if htf=="UP" and S>B:
            R.append("⛔ 4H trend yuqoriga, lekin SELL signal — Top-Down filtri rad etdi")
            return None
        if htf=="DOWN" and B>S:
            R.append("⛔ 4H trend pastga, lekin BUY signal — Top-Down filtri rad etdi")
            return None
        if htf=="UP": R.append("✅ 4H trend: yuqoriga (Top-Down tasdiqlandi)")
        elif htf=="DOWN": R.append("✅ 4H trend: pastga (Top-Down tasdiqlandi)")
    else:
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
        B+=3; R.append(f"⚡ Imbalans (Bullish FVG) ichida: {fvg_b['bottom']}-{fvg_b['top']}")
    if fvg_s and fvg_s["bottom"] <= p <= fvg_s["top"]:
        S+=3; R.append(f"⚡ Imbalans (Bearish FVG) ichida: {fvg_s['bottom']}-{fvg_s['top']}")

    if smc.get("liquidity_high") and p < smc["liquidity_high"] < p + atr*2:
        R.append(f"💧 Yuqori likvidlik zonasi yaqinda: {smc['liquidity_high']} (stop-hunt xavfi)")
    if smc.get("liquidity_low") and p - atr*2 < smc["liquidity_low"] < p:
        R.append(f"💧 Past likvidlik zonasi yaqinda: {smc['liquidity_low']} (stop-hunt xavfi)")

    # ── VWAP (institutsional referens narx) ──
    if vwap.get("vwap"):
        if vwap["above"]:
            B+=1; R.append(f"📊 VWAP ustida: {vwap['vwap']} (bosim BUY tomonda)")
        elif vwap["below"]:
            S+=1; R.append(f"📊 VWAP ostida: {vwap['vwap']} (bosim SELL tomonda)")

    # ── Opening Range Breakout (ORB) ──
    if orb.get("available"):
        if orb["breakout_up"]:
            B+=2; R.append(f"🚀 ORB breakout yuqoriga: {orb['orb_high']}")
        elif orb["breakout_down"]:
            S+=2; R.append(f"🚀 ORB breakout pastga: {orb['orb_low']}")

    # ── Momentum Candle + Retest ──
    if mom_retest.get("bullish_retest"):
        B+=2; R.append(f"⚡ Momentum retest (bullish): {mom_retest.get('level')}")
    if mom_retest.get("bearish_retest"):
        S+=2; R.append(f"⚡ Momentum retest (bearish): {mom_retest.get('level')}")

    # ── Round Number Magnetism ──
    if round_num.get("near_round"):
        R.append(f"🎯 Dumaloq raqam yaqinida: {round_num['level']} (kutilmagan qaytish xavfi)")

    # ── ICT Killzone — barcha ballar yig'ilgandan KEYIN kuchaytiriladi ──
    # Bu institutsional faollik vaqtida (London/NY/Asia Killzone) allaqachon
    # aniqlangan signalning ishonchliligini oshiradi — signal manbasi emas,
    # balki mavjud signalni tasdiqlovchi ko'paytiruvchi omil.
    if killzone and (B > 0 or S > 0):
        B = int(B*1.3); S = int(S*1.3)
        R.append(f"⏰ ICT Killzone: {killzone} (yuqori faollik vaqti)")

    # Natija
    direction=None; score=0
    if B>=MIN_SCORE and B>S: direction,score = "BUY",B
    elif S>=MIN_SCORE and S>B: direction,score = "SELL",S
    if not direction: return None

    # ── VOLATILLIK FILTRI ──
    # ATR narxga nisbatan juda kichik bo'lsa (juda tinch bozor) — signal ishonchsiz,
    # juda katta bo'lsa (juda notinch, masalan yangilik payti) — xavf yuqori.
    atr_pct = (atr / p) * 100 if p > 0 else 0
    if atr_pct < 0.03:
        R.append(f"⚠️ Volatillik juda past ({round(atr_pct,3)}%) — bozor tinch, signal rad etildi")
        return None
    if atr_pct > 2.5:
        R.append(f"⚠️ Volatillik juda yuqori ({round(atr_pct,3)}%) — xavfli, signal rad etildi")
        return None

    # ── SL/TP — rejimga qarab (Scalp: 5m tez/kichik, Intraday: 1H sekinroq/kattaroq) ──
    if mode == "scalp":
        sl_mult, tp1_mult, tp2_mult = 0.8, 1.5, 2.5
    else:  # intraday
        sl_mult, tp1_mult, tp2_mult = 1.2, 2.2, 3.5

    sl  = round(p - atr*sl_mult, 5)  if direction=="BUY" else round(p + atr*sl_mult, 5)
    tp1 = round(p + atr*tp1_mult, 5) if direction=="BUY" else round(p - atr*tp1_mult, 5)
    tp2 = round(p + atr*tp2_mult, 5) if direction=="BUY" else round(p - atr*tp2_mult, 5)

    # ── RISK-REWARD FILTRI ──
    # TP1 gacha bo'lgan masofa SL gacha bo'lgan masofadan kamida 1.6 baravar katta
    # bo'lishi kerak, aks holda signal "yomon savdo" hisoblanadi va rad etiladi.
    risk   = abs(p - sl)
    reward = abs(tp1 - p)
    rr     = round(reward / risk, 2) if risk > 0 else 0
    min_rr = 1.6
    if rr < min_rr:
        R.append(f"⚠️ Risk/Reward past ({rr}) — kamida {min_rr} talab qilinadi, signal rad etildi")
        return None

    strength=("🔥🔥 ULTRA" if score>=14 else "🔥 JUDA KUCHLI" if score>=10
              else "✅ KUCHLI" if score>=7 else "🟡 O'RTA")

    # ── ENTRY ZONE — bitta narx o'rniga oralig' ──
    # ATR asosida narx atrofida "qulay kirish zonasi" hisoblanadi — bozor
    # spread/shovqin tufayli bitta aniq narxga tushish shart emasligini bildiradi.
    entry_buffer = atr * 0.25
    if direction == "BUY":
        entry_low, entry_high = round(p - entry_buffer, 5), round(p, 5)
    else:
        entry_low, entry_high = round(p, 5), round(p + entry_buffer, 5)

    # ── LIMIT ORDER TAKLIFI ──
    # Agar narx allaqachon impulsiv harakat qilgan bo'lsa (ADX yuqori),
    # darhol bozor narxida kirish o'rniga, kichik pullback kutib, arzonroq
    # (yoki qimmatroq, SELL uchun) narxda limit order qo'yishni tavsiya qilamiz.
    limit_price = None
    if adx >= 25:  # kuchli trend — pullback kutish mantiqli
        pullback = atr * 0.4
        limit_price = round(p - pullback, 5) if direction == "BUY" else round(p + pullback, 5)

    # ── INVALIDATION DARAJASI ──
    # Signal "bekor" hisoblanadigan chegara — SL'dan biroz kattaroq masofa,
    # chunki bu yerga yetgach signalning asosiy g'oyasi (masalan Order Block,
    # trend) o'zi buzilgan bo'ladi, hatto SL urilmagan bo'lsa ham ehtiyot bo'lish kerak.
    invalidation = round(sl - atr*0.3, 5) if direction == "BUY" else round(sl + atr*0.3, 5)

    return {"direction":direction,"strength":strength,"score":score,"mode":mode,
            "price":p,"sl":sl,"tp1":tp1,"tp2":tp2,"rr":rr,
            "entry_low":entry_low,"entry_high":entry_high,
            "limit_price":limit_price,"invalidation":invalidation,
            "adx":adx,"atr":atr,"pd_zone":pd_zone,"killzone":killzone,
            "reasons":R,"sr":sr,"fib":fib,"sentiment":sentiment}

# ══════════════════════════════════════════════
#  YANGILIK TEKSHIRISH
# ══════════════════════════════════════════════
def check_news(symbol: str) -> list:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    out = []
    for n in fetch_news_calendar():
        if symbol not in n["pairs"]: continue
        try:
            nt = datetime.strptime(n["date"],"%Y-%m-%d %H:%M")
        except ValueError:
            continue
        diff = (nt-now).total_seconds()/60
        if -30<=diff<=120: out.append({**n,"diff_min":int(diff)})
    return out

# ══════════════════════════════════════════════
#  XABAR FORMATLASH
# ══════════════════════════════════════════════
SYMBOL_EMOJI = {
    "EURUSD":"💶","GBPUSD":"💷","AUDUSD":"🇦🇺",
    "USDJPY":"🇯🇵","NZDUSD":"🇳🇿"
}

def fmt_signal(symbol,sig,news,remaining) -> str:
    se = SYMBOL_EMOJI.get(symbol,"💱")
    de = "🟢" if sig["direction"]=="BUY" else "🔴"
    now= datetime.now(timezone.utc).strftime("%H:%M")
    mode_label = "⚡ Scalp" if sig.get("mode")=="scalp" else "📊 Intraday"

    msg=(f"{se} {de} *{symbol} — {sig['direction']}* {sig['strength']} | {mode_label}\n"
         f"📍 Entry: `{sig['entry_low']}–{sig['entry_high']}`\n"
         f"🎯TP1 `{sig['tp1']}`  🛡SL `{sig['sl']}`\n"
         f"⚖️R:R 1:{sig['rr']}  ⭐{sig['score']}/30  🕐{now}\n")

    if sig.get("limit_price"):
        lo = "pastroq" if sig["direction"]=="BUY" else "yuqoriroq"
        msg += f"⏳ Limit order taklifi: `{sig['limit_price']}` ({lo} pullback kutish)\n"

    msg += f"❌ Invalidation: `{sig['invalidation']}` (bu darajadan o'tsa g'oya bekor)\n"

    if sig["score"] >= STRONG_SIGNAL_OVERRIDE_SCORE:
        msg += "🔥 _Juda kuchli signal — cooldown chetlab o'tildi!_\n"

    pz = sig.get("pd_zone")
    zone_bits = []
    if pz:
        zone_bits.append("💰Discount" if pz["zone"]=="discount" else "💎Premium")
    if sig.get("killzone"):
        zone_bits.append(f"⏰{sig['killzone']}")
    if zone_bits:
        msg += " · ".join(zone_bits) + "\n"

    # Faqat eng muhim (kuchli) sabablarni ko'rsatamiz — to'liq ro'yxat emas
    top_reasons = [r for r in sig["reasons"] if any(
        e in r for e in ["🌟","🕯️🕯️🕯️","🧠","🚀","⚡ Imbalans","🟦","🟥","⛔","✅ Multi-TF"]
    )][:4]
    if not top_reasons:
        top_reasons = sig["reasons"][:3]
    if top_reasons:
        msg += "\n" + "\n".join(f"• {r}" for r in top_reasons) + "\n"

    if news:
        n = news[0]
        t = f"{n['diff_min']}daq" if n["diff_min"]>0 else "HOZIR"
        msg += f"\n⚠️ {n['name']} — {t}"

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
_sent_signal_msgs = []  # [{"chat_id":..., "message_id":..., "expire_at":...}] — avtomatik o'chirish uchun

# ── WIN-RATE TRACKING ──
# Har yuborilgan signal shu ro'yxatga qo'shiladi va keyingi tekshiruvlarda
# narx TP1/TP2 yoki SL ga yetganmi kuzatiladi. Bu orqali botning HAQIQIY
# aniqligini (taxmin emas, real natija) hisoblab boramiz.
_tracked_signals = []  # [{"symbol","mode","direction","entry","sl","tp1","tp2","opened_at","status"}]
_stats = {"total": 0, "tp1_hit": 0, "tp2_hit": 0, "sl_hit": 0, "open": 0}

def is_session(symbol: str, now: datetime) -> bool:
    """Barcha juftliklar London+NY yoki Osiyo (Tokyo) sessiyasida ishlaydi"""
    if symbol in CRYPTO_SYMBOLS:
        return True
    if symbol in INDEX_SYMBOLS:
        # AQSh fond birjasi taxminan 13:30-20:00 UTC (dam olish kunlari yopiq)
        return now.weekday() < 5 and 13 <= now.hour < 20

    in_london_ny = TRADING_START <= now.hour < TRADING_END
    # Osiyo sessiyasi kechqurun boshlanib, ertalab tugaydi (23:00 → 08:00),
    # ya'ni tun yarmidan o'tadi — shuning uchun "yoki" mantig'i bilan tekshiramiz
    in_asia = now.hour >= ASIA_SESSION_START or now.hour < ASIA_SESSION_END

    return in_london_ny or in_asia

def get_current_session_name(now: datetime) -> str:
    """Xabarda ko'rsatish uchun joriy sessiya nomini qaytaradi"""
    h = now.hour
    if 7 <= h < 13:
        return "🇬🇧 London"
    if 13 <= h < 16:
        return "🇬🇧🇺🇸 London+NY"
    if 16 <= h < 21:
        return "🇺🇸 New York"
    if h >= 23 or h < 8:
        return "🇯🇵 Osiyo (Tokyo)"
    return "😴 Tinch vaqt"

SIGNAL_COOLDOWN_MINUTES = 120  # Bir juftlik uchun signal yuborilgach 2 soat kutiladi
STRONG_SIGNAL_OVERRIDE_SCORE = 16  # Shu balldan yuqori signal cooldownni chetlab o'tadi

def can_signal(symbol,now,score=0) -> bool:
    today=now.strftime("%Y-%m-%d")
    if symbol not in _daily or _daily[symbol]["date"]!=today:
        _daily[symbol]={"date":today,"count":0,"last_sent":None}
    rec = _daily[symbol]
    if rec["count"] >= MAX_DAILY_SIGNALS:
        return False
    # ── Cooldown: oxirgi signaldan keyin yetarli vaqt o'tmagan bo'lsa rad ──
    # Bundan mustasno: agar signal JUDA KUCHLI bo'lsa (STRONG_SIGNAL_OVERRIDE_SCORE
    # dan yuqori), cooldown chetlab o'tiladi — chunki bunday sifatli imkoniyatni
    # shunchaki vaqt o'tmagani uchun yo'qotib yubormaslik kerak.
    if rec.get("last_sent") is not None and score < STRONG_SIGNAL_OVERRIDE_SCORE:
        elapsed_min = (now - rec["last_sent"]).total_seconds() / 60
        if elapsed_min < SIGNAL_COOLDOWN_MINUTES:
            return False
    return True

def reg_signal(symbol,now):
    today=now.strftime("%Y-%m-%d")
    if symbol not in _daily or _daily[symbol]["date"]!=today:
        _daily[symbol]={"date":today,"count":0,"last_sent":None}
    _daily[symbol]["count"]+=1
    _daily[symbol]["last_sent"]=now

# Korrelyatsiyalashgan juftliklar — bittasi BUY, ikkinchisi SELL bersa,
# ikkalasi ham bir xil AQSh dollari harakatidan kelib chiqqan bo'lishi mumkin,
# shuning uchun ziddiyat bo'lsa ikkalasi ham ehtiyot yuzasidan filtrlanadi.
CORRELATED_PAIRS = [("EURUSD", "GBPUSD")]

async def update_signal_tracking(bot):
    """
    Ochiq (kuzatilayotgan) signallarning joriy narxini tekshiradi va
    TP1/TP2/SL ga yetganini aniqlaydi. Natija _stats ga yoziladi —
    bu botning HAQIQIY win-rate'ini beradi (taxmin emas).
    """
    price_cache = {}
    now = datetime.now(timezone.utc)
    for sig in _tracked_signals:
        if sig["status"] != "open":
            continue
        symbol = sig["symbol"]
        if symbol not in price_cache:
            df = get_price_data(symbol, "1d", "5m")
            price_cache[symbol] = df["close"].iloc[-1] if df is not None and len(df) > 0 else None
        price = price_cache[symbol]
        if price is None:
            continue

        d = sig["direction"]
        hit_tp2 = (d == "BUY" and price >= sig["tp2"]) or (d == "SELL" and price <= sig["tp2"])
        hit_tp1 = (d == "BUY" and price >= sig["tp1"]) or (d == "SELL" and price <= sig["tp1"])
        hit_sl  = (d == "BUY" and price <= sig["sl"])  or (d == "SELL" and price >= sig["sl"])

        # Status DARHOL o'zgartiriladi (xabar yuborishdan oldin) — shu orqali
        # agar funksiya biror sabab bilan tez orada yana chaqirilsa, bu
        # signal endi "open" bo'lmagani uchun qayta ishlanmaydi va
        # xabar TAKRORLANMAYDI.
        result_msg = None
        if hit_tp2:
            sig["status"] = "tp2_hit"
            _stats["tp2_hit"] += 1; _stats["open"] -= 1
            result_msg = f"🎯🎯 *{symbol} [{sig['mode']}] — TP2 GA YETDI!* Signal to'liq yopildi."
        elif hit_tp1:
            sig["status"] = "tp1_hit"
            _stats["tp1_hit"] += 1; _stats["open"] -= 1
            result_msg = f"🎯 *{symbol} [{sig['mode']}] — TP1 ga yetdi!* Foyda qayd etildi."
        elif hit_sl:
            sig["status"] = "sl_hit"
            _stats["sl_hit"] += 1; _stats["open"] -= 1
            result_msg = f"🛑 *{symbol} [{sig['mode']}] — SL ga yetdi.* Zarar qayd etildi."

        if result_msg:
            sent = await bot.send_message(chat_id=CHAT_ID, parse_mode="Markdown", text=result_msg)
            # Natija xabari ham 20 daqiqadan keyin avtomatik o'chiriladi
            _sent_signal_msgs.append({
                "chat_id": CHAT_ID, "message_id": sent.message_id,
                "expire_at": now + pd.Timedelta(minutes=20),
            })

    # Xotira tejash uchun 500 tadan ortiq bo'lsa eski yopiq signallarni tozalaymiz
    if len(_tracked_signals) > 500:
        _tracked_signals[:] = [s for s in _tracked_signals if s["status"] == "open"][-300:]

async def check_and_send(context: ContextTypes.DEFAULT_TYPE):
    bot=context.bot
    now=datetime.now(timezone.utc)
    today=now.strftime("%Y-%m-%d")

    # Ochiq signallarni tekshirish (win-rate tracking)
    await update_signal_tracking(bot)

    # EOD eslatmasi + barcha ochiq sделkalarni yopish + kunlik hisobot + reset
    if now.hour==EOD_REMINDER_HOUR and now.minute<CHECK_INTERVAL and today not in _eod_sent:
        _eod_sent.add(today)
        await bot.send_message(chat_id=CHAT_ID,parse_mode="Markdown",
            text=("🌙 *KUN OXIRI — BARCHA SDELKALAR YOPILMOQDA*\n━━━━━━━━━━━━━━━━━━\n"
                  "Ochiq pozitsiyalar joriy narx bo'yicha yakunlanadi.\n"
                  "Tunda spread kengayadi — shuning uchun kun yakunida hisob-kitob qilinadi."))

        # ── Barcha OCHIQ signallarni joriy narx bo'yicha majburan yopish ──
        price_cache_eod = {}
        for sig in _tracked_signals:
            if sig["status"] != "open":
                continue
            symbol = sig["symbol"]
            if symbol not in price_cache_eod:
                df = get_price_data(symbol, "1d", "5m")
                price_cache_eod[symbol] = df["close"].iloc[-1] if df is not None and len(df) > 0 else None
            price = price_cache_eod[symbol]
            if price is None:
                continue

            d = sig["direction"]
            profit = (price - sig["entry"]) if d == "BUY" else (sig["entry"] - price)
            if profit > 0:
                sig["status"] = "eod_profit"
                _stats["tp1_hit"] += 1
            else:
                sig["status"] = "eod_loss"
                _stats["sl_hit"] += 1
            _stats["open"] -= 1

        # ── Kunlik statistika hisoboti (endi barcha sделka yopilgan holda) ──
        closed_today = _stats["tp1_hit"] + _stats["tp2_hit"] + _stats["sl_hit"]
        if closed_today > 0:
            win_rate = round((_stats["tp1_hit"] + _stats["tp2_hit"]) / closed_today * 100, 1)
            report = (
                f"📊 *KUNLIK YAKUNIY HISOBOT*\n━━━━━━━━━━━━━━━━━━\n"
                f"📨 Jami signal: `{_stats['total']}`\n"
                f"🔒 Barchasi yopildi: `{closed_today}`\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"🎯 TP1: `{_stats['tp1_hit']}`  🎯🎯 TP2: `{_stats['tp2_hit']}`  🛑 SL: `{_stats['sl_hit']}`\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"✅ *Bugungi yakuniy win-rate: {win_rate}%*\n\n"
                f"_Ertaga statistika 0 dan boshlanadi._"
            )
        else:
            report = (
                f"📊 *KUNLIK YAKUNIY HISOBOT*\n━━━━━━━━━━━━━━━━━━\n"
                f"📨 Jami signal: `{_stats['total']}`\n"
                f"⏳ Bugun signal bo'lmadi.\n\n"
                f"_Ertaga statistika 0 dan boshlanadi._"
            )
        await bot.send_message(chat_id=CHAT_ID, parse_mode="Markdown", text=report)

        # ── Statistikani to'liq nolga tushirish (barchasi yopilgani uchun ochiq qolmaydi) ──
        _stats["total"] = 0
        _stats["open"] = 0
        _stats["tp1_hit"] = 0
        _stats["tp2_hit"] = 0
        _stats["sl_hit"] = 0

    sentiment=get_sentiment()
    candidate_signals = []   # [(symbol, mode, sig, nl)] — confirmation'dan o'tgan signallar

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

            # ── NEWS BLACKOUT ──
            # Yuqori ta'sirli (impact=3) yangilikdan 30 daqiqa oldin va
            # 15 daqiqa keyin — signal generatsiyasi TO'LIQ to'xtatiladi.
            # Bu paytda narx harakati texnik tahlilga bo'ysunmaydi (spread
            # kengayadi, spike'lar bo'ladi), shuning uchun har qanday
            # signal ishonchsiz bo'ladi.
            in_blackout = any(
                n["impact"] == 3 and -15 <= n["diff_min"] <= 30
                for n in nl
            )
            if in_blackout:
                continue

            htf=get_htf(symbol)
            killzone=get_ict_killzone(now)

            # ── Kunlik limitni oldindan tekshirish (ball bilan bog'liq emas) ──
            today=now.strftime("%Y-%m-%d")
            if symbol not in _daily or _daily[symbol]["date"]!=today:
                _daily[symbol]={"date":today,"count":0,"last_sent":None}
            if _daily[symbol]["count"] >= MAX_DAILY_SIGNALS:
                continue

            # ── Ikkala rejim: Scalping (5m) va Intraday (1h) ──
            for mode, period, interval in (("scalp","1d","5m"), ("intraday","1mo","1h")):
                confirm_key = f"{symbol}_{mode}"  # Confirmation kutish ro'yxati uchun (mode bilan alohida)

                df=get_price_data(symbol, period=period, interval=interval)
                min_bars = 20 if mode == "scalp" else 60
                if df is None or len(df)<min_bars: continue

                ind=calc_ind(df)
                pat=detect_patterns(df)
                sr =calc_sr(df)
                fib=calc_fib(df)
                vol=calc_volume(df)
                trend=calc_trendline(df)
                smc  =calc_smc(df)
                pd_zone=calc_premium_discount(df)
                vwap_data = calc_vwap(df)
                orb_data  = calc_orb(df, now, TRADING_START)
                mom_retest = calc_momentum_retest(df)
                round_num  = calc_round_number(ind["price"], symbol)
                sig=generate_signal(symbol,ind,pat,sr,fib,vol,sentiment,htf,trend,smc,pd_zone,killzone,mode,
                                     vwap_data,orb_data,mom_retest,round_num)

                # ── Cooldown tekshiruvi (ball bilan) ──
                # Signal hisoblangandan keyin tekshiramiz — agar u JUDA KUCHLI
                # bo'lsa (STRONG_SIGNAL_OVERRIDE_SCORE dan yuqori), cooldown
                # chetlab o'tiladi. Oddiy signal esa cooldown ichida bo'lsa rad etiladi.
                if sig and not can_signal(symbol, now, sig["score"]):
                    sig = None

                # ── Confirmation mantiqi (har rejim uchun alohida) ──
                # Intraday uchun 2 marta ketma-ket bir xil yo'nalishda signal
                # kelishi kerak (shovqinni filtrlash uchun), Swing uchun 1 bar yetarli.
                required_confirmations = 2 if mode == "scalp" else 1
                if REQUIRE_CONFIRMATION:
                    prev = _pending.get(confirm_key)
                    if sig:
                        if prev and prev["direction"] == sig["direction"]:
                            still_valid = (
                                (sig["direction"]=="BUY"  and sig["price"] >= prev["price"]) or
                                (sig["direction"]=="SELL" and sig["price"] <= prev["price"])
                            )
                            if not still_valid:
                                del _pending[confirm_key]
                                sig = None
                            elif prev["count"] + 1 >= required_confirmations:
                                del _pending[confirm_key]
                                # sig tayyor — yuboriladi
                            else:
                                _pending[confirm_key] = {"direction": sig["direction"],
                                                          "price": sig["price"],
                                                          "count": prev["count"] + 1}
                                sig = None
                        else:
                            _pending[confirm_key] = {"direction": sig["direction"],
                                                      "price": sig["price"], "count": 1}
                            sig = None if required_confirmations > 1 else sig
                            if sig:
                                _pending.pop(confirm_key, None)
                    else:
                        _pending.pop(confirm_key, None)

                # ── Scalping: Multi-Timeframe Confluence (5m+15m+1H) ──
                # FAQAT Scalp rejimi uchun qo'llaniladi — signal faqat kamida
                # 2/3 timeframe bir xil yo'nalishni ko'rsatsagina o'tadi.
                # Intraday o'zining 1H+4H Top-Down filtriga tayanadi, unga
                # yana 5m confluence qo'shish ortiqcha qattiqlashtiradi.
                if sig and mode == "scalp":
                    conf = get_scalp_confluence(symbol, sig["direction"])
                    if not conf["confirmed"]:
                        sig["reasons"].append(
                            f"⏸ Multi-TF confluence yetarli emas "
                            f"({conf['matching']}/{conf['total']}) — {conf['detail']}"
                        )
                        sig = None
                    else:
                        sig["reasons"].append(f"✅ Multi-TF confluence: {conf['detail']}")

                if sig:
                    candidate_signals.append((symbol, mode, sig, nl))

        except Exception as e:
            log.error(f"Xato ({symbol}): {e}")

    # ── CORRELATION FILTRI (har rejim ichida alohida tekshiriladi) ──
    # Bog'liq juftliklar bir xil rejimda qarama-qarshi yo'nalishda signal
    # bersa — ikkalasi ham bekor qilinadi.
    by_mode = {"intraday": {}, "swing": {}}
    for symbol, mode, sig, nl in candidate_signals:
        by_mode[mode][symbol] = (sig, nl)

    rejected = set()
    for mode in ("intraday", "swing"):
        for a, b in CORRELATED_PAIRS:
            if a in by_mode[mode] and b in by_mode[mode]:
                if by_mode[mode][a][0]["direction"] == by_mode[mode][b][0]["direction"]:
                    rejected.add((a, mode)); rejected.add((b, mode))
                    log.info(f"Correlation filtri ({mode}): {a} va {b} bir xil yo'nalishda — rad etildi")

    already_sent_symbols = set()
    for symbol, mode, sig, nl in candidate_signals:
        if (symbol, mode) in rejected: continue
        if symbol in already_sent_symbols:
            continue  # Shu tsiklda bu juftlik uchun allaqachon signal yuborildi
        already_sent_symbols.add(symbol)
        reg_signal(symbol, now)  # Symbol darajasida — 2 soatlik cooldown shu yerdan boshlanadi
        rem = MAX_DAILY_SIGNALS - _daily[symbol]["count"]
        msg = fmt_signal(symbol, sig, nl, rem)
        sent = await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="Markdown")
        # Muddati o'tganda avtomatik o'chirish uchun ro'yxatga qo'shamiz.
        # Intraday tezroq eskiradi (1 soat), Swing sekinroq (6 soat).
        expire_hours = 0.5 if mode == "scalp" else 1.5
        _sent_signal_msgs.append({
            "chat_id": CHAT_ID, "message_id": sent.message_id,
            "expire_at": now + pd.Timedelta(hours=expire_hours),
        })
        # ── Win-rate kuzatuviga qo'shish ──
        _tracked_signals.append({
            "symbol": symbol, "mode": mode, "direction": sig["direction"],
            "entry": sig["price"], "sl": sig["sl"], "tp1": sig["tp1"], "tp2": sig["tp2"],
            "opened_at": now, "status": "open",
        })
        _stats["total"] += 1
        _stats["open"] += 1
        log.info(f"Signal: {symbol} [{mode}] {sig['direction']} score={sig['score']}")

    # ── Muddati o'tgan signal xabarlarini o'chirish ──
    still_pending = []
    for item in _sent_signal_msgs:
        if now >= item["expire_at"]:
            try:
                await bot.delete_message(chat_id=item["chat_id"], message_id=item["message_id"])
            except Exception:
                pass  # Xabar allaqachon o'chirilgan yoki 48 soatdan eski bo'lishi mumkin
        else:
            still_pending.append(item)
    _sent_signal_msgs[:] = still_pending

# ══════════════════════════════════════════════
#  TELEGRAM KOMANDALAR
# ══════════════════════════════════════════════
async def cmd_start(update,context):
    try:
        await _set_bot_commands(context.application)
    except Exception as e:
        log.error(f"Komandalar menyusi xatosi: {e}")
    await update.message.reply_text(
        "👋 *UltimateForexSignalBot v27.0 (Precise Entry)*\n\n"
        "📊 *Kuzatiladigan aktivlar:*\n"
        "  💶 EURUSD — Euro/Dollar\n"
        "  💷 GBPUSD — Funt/Dollar\n"
        "  🇦🇺 AUDUSD — Avstraliya/Dollar\n"
        "  🇯🇵 USDJPY — Dollar/Yena\n"
        "  🇳🇿 NZDUSD — Yangi Zelandiya/Dollar\n\n"
        "🧠 *Strategiya:* ICT / Smart Money Concepts\n"
        "  • Imbalans (Fair Value Gap)\n"
        "  • Order Blocks\n"
        "  • BOS / CHoCH (Market Structure)\n"
        "  • Premium/Discount zonalar\n"
        "  • ICT Killzones\n"
        "  • SNR (Support/Resistance)\n"
        "  • VWAP, ORB, Momentum Retest\n\n"
        f"⚙️ Tekshirish: har {CHECK_INTERVAL} daqiqa\n"
        f"⏰ Sessiya: London+NY ({TRADING_START}:00–{TRADING_END}:00) + 🇯🇵 Osiyo ({ASIA_SESSION_START}:00–{ASIA_SESSION_END}:00) UTC\n"
        f"📅 Kunlik limit: {MAX_DAILY_SIGNALS} ta/aktiv\n"
        f"⏳ Har juftlik uchun 1 ta signal, {SIGNAL_COOLDOWN_MINUTES//60} soat cooldown\n"
        f"🔥 Juda kuchli signal ({STRONG_SIGNAL_OVERRIDE_SCORE}+/30) cooldownni chetlab o'tadi\n"
        f"🎯 Rejim: SCALPING (5m) + INTRADAY (1H) — birga ishlaydi\n"
        f"🧹 Signallar 30 daqiqadan keyin avtomatik o'chiriladi\n\n"
        "📋 *Komandalar:*\n"
        "/signal — Hozirgi signallar\n"
        "/status — Joriy narxlar\n"
        "/news — Yangiliklar\n"
        "/sentiment — Bozor kayfiyati\n"
        "/sr EURUSD — Support/Resistance\n"
        "/fib EURUSD — Fibonacci\n"
        "/stats — Haqiqiy win-rate statistikasi\n",
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
    await update.message.reply_text("⏳ Barcha aktivlar tahlil qilinmoqda (Scalping Multi-TF Confluence bilan)...")
    sentiment=get_sentiment(); found=0
    now=datetime.now(timezone.utc)
    for sym in SYMBOLS:
        htf=get_htf(sym)
        killzone=get_ict_killzone(now)
        for mode, period, interval in (("scalp","1d","5m"), ("intraday","1mo","1h")):
            df=get_price_data(sym, period=period, interval=interval)
            min_bars = 20 if mode == "scalp" else 60
            if df is None or len(df)<min_bars: continue
            ind=calc_ind(df); pat=detect_patterns(df)
            sr=calc_sr(df); fib=calc_fib(df)
            vol=calc_volume(df)
            trend=calc_trendline(df); smc=calc_smc(df)
            pd_zone=calc_premium_discount(df)
            vwap_data = calc_vwap(df)
            orb_data  = calc_orb(df, now, TRADING_START)
            mom_retest = calc_momentum_retest(df)
            round_num  = calc_round_number(ind["price"], sym)
            sig=generate_signal(sym,ind,pat,sr,fib,vol,sentiment,htf,trend,smc,pd_zone,killzone,mode,
                                 vwap_data,orb_data,mom_retest,round_num)
            if sig:
                if mode == "scalp":
                    conf = get_scalp_confluence(sym, sig["direction"])
                    sig["reasons"].append(
                        ("✅" if conf["confirmed"] else "⏸") +
                        f" Multi-TF confluence: {conf['detail']}"
                    )
                    if not conf["confirmed"]:
                        continue  # tasdiqlanmagan scalp signalni ko'rsatmaymiz
                found+=1
                msg=fmt_signal(sym,sig,check_news(sym),MAX_DAILY_SIGNALS)
                msg += "\n\n⚠️ _Bu /signal buyrug'i — darhol natija. Avtomatik signal qo'shimcha confirmation bar bilan keladi._"
                await update.message.reply_text(msg,parse_mode="Markdown")
    if not found:
        await update.message.reply_text("⏸ Hozircha kuchli signal yo'q (na Scalp, na Intraday).")

async def cmd_news(update,context):
    now=datetime.now(timezone.utc).replace(tzinfo=None)
    msg="📰 *Yaqin yangiliklar (Finnhub):*\n━━━━━━━━━━━━━━━━\n"
    found=False
    events = fetch_news_calendar()
    if not events and not FINNHUB_API_KEY:
        await update.message.reply_text(
            "⚠️ FINNHUB_API_KEY sozlanmagan. finnhub.io dan bepul kalit oling "
            "va Render'da Environment Variables'ga qo'shing.",
            parse_mode="Markdown"
        )
        return
    for n in events:
        try:
            nt=datetime.strptime(n["date"],"%Y-%m-%d %H:%M")
        except ValueError:
            continue
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
    sym=(context.args[0].upper() if context.args else "EURUSD")
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
    sym=(context.args[0].upper() if context.args else "EURUSD")
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

async def cmd_stats(update,context):
    """Botning HAQIQIY natijalarini ko'rsatadi — taxmin emas, kuzatilgan real natija"""
    s = _stats
    closed = s["tp1_hit"] + s["tp2_hit"] + s["sl_hit"]
    if closed == 0:
        await update.message.reply_text(
            "📊 *Statistika*\n━━━━━━━━━━━━━━━━\n"
            f"Jami yuborilgan signal: `{s['total']}`\n"
            f"Ochiq (kuzatilmoqda): `{s['open']}`\n\n"
            "⏳ Hali yopilgan (TP/SL ga yetgan) signal yo'q. "
            "Statistika signallar yopilgach to'planadi.",
            parse_mode="Markdown"
        )
        return

    win_rate = round((s["tp1_hit"] + s["tp2_hit"]) / closed * 100, 1)
    msg = (
        f"📊 *Botning Haqiqiy Statistikasi*\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"📨 Jami yuborilgan: `{s['total']}`\n"
        f"🔓 Hozir ochiq: `{s['open']}`\n"
        f"🔒 Yopilgan: `{closed}`\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"🎯 TP1 ga yetdi: `{s['tp1_hit']}`\n"
        f"🎯🎯 TP2 ga yetdi: `{s['tp2_hit']}`\n"
        f"🛑 SL ga yetdi: `{s['sl_hit']}`\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"✅ *Win-rate: {win_rate}%*\n\n"
        f"_Bu ko'rsatkich bugungi kun uchun (har kuni soat "
        f"{EOD_REMINDER_HOUR}:00 UTC da avtomatik 0 dan boshlanadi va "
        f"kunlik hisobot yuboriladi)._"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

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

async def _set_bot_commands(app):
    """Telegram '/' menyusiga barcha komandalarni tavsif bilan o'rnatadi"""
    from telegram import BotCommand
    commands = [
        BotCommand("start",     "🏠 Botni ishga tushirish"),
        BotCommand("signal",    "📡 Hozirgi signallarni tekshirish"),
        BotCommand("status",    "📊 Joriy narxlarni ko'rish"),
        BotCommand("news",      "📰 Yaqin yangiliklar"),
        BotCommand("sentiment", "🧠 Bozor kayfiyati (Fear & Greed)"),
        BotCommand("sr",        "🧱 Support/Resistance (masalan: /sr EURUSD)"),
        BotCommand("fib",       "📐 Fibonacci darajalari (masalan: /fib EURUSD)"),
        BotCommand("stats",     "📊 Botning haqiqiy win-rate statistikasi"),
    ]
    await app.bot.set_my_commands(commands)
    log.info("✅ Bot komandalar menyusi o'rnatildi")

def main():
    app=Application.builder().token(BOT_TOKEN).build()
    for cmd,fn in [("start",cmd_start),("status",cmd_status),
                   ("signal",cmd_signal),("news",cmd_news),
                   ("sentiment",cmd_sentiment),("sr",cmd_sr),("fib",cmd_fib),
                   ("stats",cmd_stats)]:
        app.add_handler(CommandHandler(cmd,fn))
    app.job_queue.run_repeating(check_and_send,interval=CHECK_INTERVAL*60,first=15)
    log.info(f"UltimateForexSignalBot v27.0 (Precise Entry) ishga tushdi!")
    app.run_polling(drop_pending_updates=True)

if __name__=="__main__":
    # PORT'ni HAMMA narsadan oldin, darhol ochamiz — Render buni tez ko'rishi kerak
    threading.Thread(target=start_fake_server, daemon=True).start()

    # Eslatma: agar bot kutilmagan xato bilan yiqilsa, jarayon to'liq
    # to'xtaydi va Render buni "Failed"/"Exited" deb belgilaydi — lekin
    # Render'ning o'z platformasi jarayon yiqilganda uni AVTOMATIK qayta
    # ishga tushiradi (bu Render'ning standart xatti-harakati bepul va
    # pullik tariflarda ham). Shu sababli bu yerda qo'lda "while True"
    # restart loop qilish shart emas — bu asyncio event loop bilan
    # ziddiyatga olib kelishi mumkin ("Event loop is closed" xatosi).
    main()
