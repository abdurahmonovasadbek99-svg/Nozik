"""
Volume / Open Interest spike signal moduli.
Bybit futures API'idan hajm va OI ma'lumotlarini olib,
so'nggi qiymatlarni tarixiy o'rtacha bilan solishtiradi.

TUZATISHLAR:
- Kline'ni aggregator dan (candles parametr) oladi — takroriy so'rov yo'q
- Yo'nalish aniqlanmagan (neutral) lekin score yuqori bo'lgan holatda
  score 40 ga cheklanadi. Aks holda yuqori "neutral" ovoz boshqa
  modullarning real yo'nalishini bo'g'ib qo'yardi.
"""
import statistics
import requests

from signals.klines import get_klines

BYBIT_BASE = "https://api.bybit.com"


def _bybit_open_interest(symbol: str, interval: str = "15min", limit: int = 20):
    url = f"{BYBIT_BASE}/v5/market/open-interest"
    params = {"category": "linear", "symbol": symbol, "intervalTime": interval, "limit": limit}
    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    rows = r.json()["result"]["list"]
    rows = list(reversed(rows))
    return [float(row["openInterest"]) for row in rows]


def analyze(symbol: str, candles: list = None) -> dict:
    if candles is None:
        try:
            candles = get_klines(symbol, limit=20)
        except Exception as e:
            return {"score": 0, "direction": "neutral", "details": {"error": str(e)}}

    try:
        oi = _bybit_open_interest(symbol)
    except Exception as e:
        return {"score": 0, "direction": "neutral", "details": {"error": str(e)}}

    if len(candles) < 5 or len(oi) < 5:
        return {"score": 0, "direction": "neutral", "details": {"error": "yetarli data yo'q"}}

    volumes = [c["volume"] for c in candles]
    closes = [c["close"] for c in candles]

    last_volume = volumes[-1]
    avg_volume = statistics.mean(volumes[:-1])
    volume_ratio = last_volume / avg_volume if avg_volume > 0 else 1

    oi_change_pct = ((oi[-1] - oi[0]) / oi[0]) * 100 if oi[0] > 0 else 0
    price_change_pct = ((closes[-1] - closes[0]) / closes[0]) * 100 if closes[0] > 0 else 0

    score = 0
    if volume_ratio >= 3:
        score += 50
    elif volume_ratio >= 2:
        score += 30
    elif volume_ratio >= 1.5:
        score += 15

    if abs(oi_change_pct) >= 10:
        score += 50
    elif abs(oi_change_pct) >= 5:
        score += 30
    elif abs(oi_change_pct) >= 2:
        score += 15

    score = min(score, 100)

    if oi_change_pct > 2 and price_change_pct > 0:
        direction = "long"
    elif oi_change_pct > 2 and price_change_pct < 0:
        direction = "short"
    else:
        direction = "neutral"

    # TUZATISH: yo'nalish yo'q bo'lsa confluence ovozini bo'g'maslik uchun
    if direction == "neutral":
        score = min(score, 40)

    return {
        "score": score,
        "direction": direction,
        "details": {
            "volume_ratio": round(volume_ratio, 2),
            "oi_change_pct": round(oi_change_pct, 2),
            "price_change_pct": round(price_change_pct, 2),
        },
    }
