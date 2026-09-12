"""
Sentiment signal moduli - BEPUL, COIN-SPETSIFIK versiya.

TUZATISH: avval Fear & Greed Index ishlatilgan edi, lekin u BUTUN
bozor uchun umumiy ko'rsatkich edi - kichik altcoinlar (masalan
TMXUSDT, EVAAUSDT) ko'pincha umumiy bozordan mustaqil harakat qiladi,
shuning uchun noto'g'ri yo'naltirishi mumkin edi.

YANGI YECHIM: Bybit'ning har bir coin uchun alohida FUNDING RATE
ma'lumotidan foydalanadi. Bu API kalit talab qilmaydi va aynan shu
coin bo'yicha traderlar pozitsiyasini ko'rsatadi:
- Funding rate juda musbat -> ko'pchilik long ochgan (crowd greed) ->
  teskari (short) signal - haddan tashqari long'lar tez-tez likvidatsiya
  bilan tugaydi
- Funding rate juda manfiy -> ko'pchilik short ochgan (crowd fear) ->
  teskari (long) signal
"""
import requests

BYBIT_BASE = "https://api.bybit.com"

# Chegaralar (funding rate, odatda har 8 soatda hisoblanadi)
THRESHOLD_HIGH = 0.001    # 0.1%
THRESHOLD_MED = 0.0005    # 0.05%
THRESHOLD_LOW = 0.0002    # 0.02%


def analyze(symbol: str, candles: list = None) -> dict:
    try:
        r = requests.get(
            f"{BYBIT_BASE}/v5/market/tickers",
            params={"category": "linear", "symbol": symbol},
            timeout=10,
        )
        r.raise_for_status()
        result_list = r.json().get("result", {}).get("list", [])
        if not result_list:
            return {"score": 0, "direction": "neutral", "details": {"error": "ma'lumot topilmadi"}}
        funding_rate = float(result_list[0].get("fundingRate", 0) or 0)
    except Exception as e:
        return {"score": 0, "direction": "neutral", "details": {"error": str(e)}}

    abs_rate = abs(funding_rate)

    if abs_rate >= THRESHOLD_HIGH:
        score = 80
    elif abs_rate >= THRESHOLD_MED:
        score = 50
    elif abs_rate >= THRESHOLD_LOW:
        score = 25
    else:
        score = 0

    if score == 0:
        direction = "neutral"
    else:
        # Musbat funding -> crowd long -> teskari (short); manfiy -> teskari (long)
        direction = "short" if funding_rate > 0 else "long"

    return {
        "score": score,
        "direction": direction,
        "details": {"funding_rate": funding_rate, "funding_rate_pct": round(funding_rate * 100, 4)},
    }
