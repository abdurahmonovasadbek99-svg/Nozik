"""
Volume / Open Interest spike signal moduli.
Bybit va Binance futures API'laridan hajm va OI ma'lumotlarini olib,
so'nggi qiymatlarni tarixiy o'rtacha bilan solishtiradi.
"""
import statistics
import requests

BYBIT_BASE = "https://api.bybit.com"
BINANCE_BASE = "https://fapi.binance.com"


def _bybit_kline_volumes(symbol: str, interval: str = "15", limit: int = 20):
    url = f"{BYBIT_BASE}/v5/market/kline"
    params = {"category": "linear", "symbol": symbol, "interval": interval, "limit": limit}
    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    rows = r.json()["result"]["list"]
    rows = list(reversed(rows))
    volumes = [float(row[5]) for row in rows]
    closes = [float(row[4]) for row in rows]
    return volumes, closes


def _bybit_open_interest(symbol: str, interval: str = "15min", limit: int = 20):
    url = f"{BYBIT_BASE}/v5/market/open-interest"
    params = {"category": "linear", "symbol": symbol, "intervalTime": interval, "limit": limit}
    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    rows = r.json()["result"]["list"]
    rows = list(reversed(rows))
    return [float(row["openInterest"]) for row in rows]


def analyze(symbol: str) -> dict:
    try:
        volumes, closes = _bybit_kline_volumes(symbol)
        oi = _bybit_open_interest(symbol)
    except Exception as e:
        return {"score": 0, "direction": "neutral", "details": {"error": str(e)}}

    if len(volumes) < 5 or len(oi) < 5:
        return {"score": 0, "direction": "neutral", "details": {"error": "yetarli data yo'q"}}

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

    return {
        "score": score,
        "direction": direction,
        "details": {
            "volume_ratio": round(volume_ratio, 2),
            "oi_change_pct": round(oi_change_pct, 2),
            "price_change_pct": round(price_change_pct, 2),
        },
    }
