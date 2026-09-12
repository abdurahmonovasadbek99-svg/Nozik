"""
Whale tracking signal moduli - BEPUL versiya.

TUZATISH: Whale Alert (pullik, faqat yirik on-chain coinlarni kuzatadi)
o'rniga Bybit'ning o'z ochiq "recent trades" endpointidan foydalanadi.
API kalit shart emas. Mantiq: so'nggi savdolar orasidan katta hajmli
(MIN_TRADE_USD dan yuqori) yakka savdolarni "whale" deb hisoblaydi va
ularning buy/sell tomonini solishtiradi.

CHEKLOV: bu chinakam on-chain hamyon harakati emas, balki birjadagi
katta yakka savdolarning proksisi. Lekin bepul va istalgan Bybit
symbol uchun ishlaydi (TMX, EVA kabi kichik altcoinlar ham).
"""
import requests

BYBIT_BASE = "https://api.bybit.com"

# Minimal savdo qiymati (USD) - shundan katta yakka savdolar "whale" deb hisoblanadi
MIN_TRADE_USD = 50_000


def analyze(symbol: str, candles: list = None, limit: int = 1000) -> dict:
    try:
        r = requests.get(
            f"{BYBIT_BASE}/v5/market/recent-trade",
            params={"category": "linear", "symbol": symbol, "limit": min(limit, 1000)},
            timeout=10,
        )
        r.raise_for_status()
        trades = r.json().get("result", {}).get("list", [])
    except Exception as e:
        return {"score": 0, "direction": "neutral", "details": {"error": str(e)}}

    buy_usd = 0.0
    sell_usd = 0.0
    whale_count = 0

    for t in trades:
        try:
            price = float(t["price"])
            size = float(t["size"])
        except (KeyError, ValueError):
            continue
        usd_value = price * size
        if usd_value < MIN_TRADE_USD:
            continue
        whale_count += 1
        if t.get("side") == "Buy":
            buy_usd += usd_value
        else:
            sell_usd += usd_value

    total = buy_usd + sell_usd
    if total == 0:
        return {"score": 0, "direction": "neutral", "details": {"whale_trades": 0}}

    imbalance_ratio = abs(buy_usd - sell_usd) / total

    if total >= 5_000_000:
        base_score = 80
    elif total >= 2_000_000:
        base_score = 60
    elif total >= 500_000:
        base_score = 40
    else:
        base_score = 20

    score = min(int(base_score * (0.5 + imbalance_ratio)), 100)
    direction = "long" if buy_usd > sell_usd else "short" if sell_usd > buy_usd else "neutral"

    return {
        "score": score,
        "direction": direction,
        "details": {
            "buy_usd": round(buy_usd, 2),
            "sell_usd": round(sell_usd, 2),
            "whale_trades": whale_count,
        },
    }
