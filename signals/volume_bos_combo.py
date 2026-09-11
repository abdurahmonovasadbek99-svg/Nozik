"""
Volume Spike + BOS (Break of Structure) kombinatsiya moduli — FAQAT FYUCHERSLAR.

Mantiq:
  BOS (tuzilma sinishi) yolg'iz holda ko'pincha "fakeout" (yolg'on sinish)
  bo'lib chiqadi. Ammo BOS paytida savdo HAJMI keskin sakrasa, bu real
  pul kirganini bildiradi va sinish "haqiqiy" bo'lish ehtimoli oshadi.

Ma'lumot manbai: Bybit "linear" (USDT-perpetual fyuchers) bozori.
Spot bozor UMUMAN ishlatilmaydi.

TUZATISH: kline'ni aggregator dan (candles parametr) oladi —
ortiqcha takroriy so'rov yo'q.
"""
from signals.klines import get_klines


def _find_swing_points(candles, lookback=3):
    swing_highs, swing_lows = [], []
    for i in range(lookback, len(candles) - lookback):
        window = candles[i - lookback:i + lookback + 1]
        if candles[i]["high"] == max(c["high"] for c in window):
            swing_highs.append((i, candles[i]["high"]))
        if candles[i]["low"] == min(c["low"] for c in window):
            swing_lows.append((i, candles[i]["low"]))
    return swing_highs, swing_lows


def _detect_bos(candles, swing_highs, swing_lows):
    if not swing_highs or not swing_lows:
        return None
    last_close = candles[-1]["close"]
    if last_close > swing_highs[-1][1]:
        return "bullish"
    if last_close < swing_lows[-1][1]:
        return "bearish"
    return None


def _volume_spike_ratio(candles) -> float:
    volumes = [c["volume"] for c in candles]
    last_volume = volumes[-1]
    prior = volumes[:-1]
    avg_volume = sum(prior) / len(prior) if prior else 0
    if avg_volume == 0:
        return 0.0
    return last_volume / avg_volume


def analyze(symbol: str, candles: list = None) -> dict:
    if candles is None:
        try:
            candles = get_klines(symbol, limit=60)
        except Exception as e:
            return {"score": 0, "direction": "neutral", "details": {"error": str(e)}}

    if len(candles) < 20:
        return {"score": 0, "direction": "neutral", "details": {"error": "yetarli data yo'q"}}

    swing_highs, swing_lows = _find_swing_points(candles)
    bos = _detect_bos(candles, swing_highs, swing_lows)
    volume_ratio = _volume_spike_ratio(candles)

    if bos is None:
        return {
            "score": 0,
            "direction": "neutral",
            "details": {"bos": None, "volume_ratio": round(volume_ratio, 2)},
        }

    direction = "long" if bos == "bullish" else "short"

    if volume_ratio >= 3:
        score = 100
    elif volume_ratio >= 2:
        score = 80
    elif volume_ratio >= 1.5:
        score = 55
    else:
        score = 25

    return {
        "score": score,
        "direction": direction,
        "details": {
            "bos": bos,
            "volume_ratio": round(volume_ratio, 2),
            "confirmed": volume_ratio >= 1.5,
        },
    }
