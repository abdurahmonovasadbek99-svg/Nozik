"""
Sentiment signal moduli.
LunarCrush API orqali ijtimoiy tarmoqlardagi mention hajmi va sentiment
o'zgarishini kuzatadi. Keskin o'sish -> potensial pump signalining
ijtimoiy tasdig'i.
"""
import requests
from config import LUNARCRUSH_API_KEY

LUNARCRUSH_BASE = "https://lunarcrush.com/api4/public"

# Bybit symbol (BTCUSDT) -> LunarCrush coin belgisi (btc)
def _to_lc_symbol(symbol: str) -> str:
    return symbol.replace("USDT", "").lower()


def analyze(symbol: str) -> dict:
    if not LUNARCRUSH_API_KEY:
        return {"score": 0, "direction": "neutral", "details": {"error": "API key yo'q"}}

    coin = _to_lc_symbol(symbol)

    try:
        r = requests.get(
            f"{LUNARCRUSH_BASE}/coins/{coin}/v1",
            headers={"Authorization": f"Bearer {LUNARCRUSH_API_KEY}"},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json().get("data", {})
    except Exception as e:
        return {"score": 0, "direction": "neutral", "details": {"error": str(e)}}

    social_volume_24h = data.get("social_volume_24h", 0)
    social_volume_prev = data.get("social_volume_24h_previous", social_volume_24h) or 1
    galaxy_score = data.get("galaxy_score", 50)  # 0-100, LunarCrush umumiy metrikasi
    sentiment_pct = data.get("sentiment", 50)  # 0-100, ijobiy foiz

    volume_change_pct = ((social_volume_24h - social_volume_prev) / social_volume_prev) * 100

    score = 0
    if volume_change_pct >= 100:
        score += 50
    elif volume_change_pct >= 50:
        score += 30
    elif volume_change_pct >= 20:
        score += 15

    if galaxy_score >= 70:
        score += 30
    elif galaxy_score >= 50:
        score += 15

    score = min(score, 100)

    direction = "long" if sentiment_pct >= 60 else "short" if sentiment_pct <= 40 else "neutral"

    return {
        "score": score,
        "direction": direction,
        "details": {
            "social_volume_change_pct": round(volume_change_pct, 2),
            "galaxy_score": galaxy_score,
            "sentiment_pct": sentiment_pct,
        },
    }
