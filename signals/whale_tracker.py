"""
Whale tracking signal moduli.
Whale Alert API orqali so'nggi yirik on-chain tranzaksiyalarni tekshiradi.
Birjaga pul kirsa (exchange inflow) -> ko'pincha sotish signali (short bias).
Birjadan pul chiqsa (exchange outflow) -> ko'pincha ushlab turish/xarid signali (long bias).

TUZATISH: candles parametri interfeys bir xilligi uchun qo'shildi
(aggregator barcha modullarga bir xil chaqiriq qiladi), lekin bu
modul undan foydalanmaydi.
"""
import requests
from config import WHALE_ALERT_API_KEY

WHALE_ALERT_BASE = "https://api.whale-alert.io/v1"

# Coin symbol -> Whale Alert blockchain/asset nomi mosligi (kerak bo'yicha kengaytiring)
SYMBOL_MAP = {
    "BTCUSDT": ("bitcoin", "btc"),
    "ETHUSDT": ("ethereum", "eth"),
    "BNBUSDT": ("binancechain", "bnb"),
    "SOLUSDT": ("solana", "sol"),
    "XRPUSDT": ("ripple", "xrp"),
}

# Minimal tranzaksiya qiymati (USD) - shundan kichigi e'tiborga olinmaydi
MIN_USD_VALUE = 1_000_000


def analyze(symbol: str, candles: list = None, lookback_minutes: int = 30) -> dict:
    if not WHALE_ALERT_API_KEY:
        return {"score": 0, "direction": "neutral", "details": {"error": "API key yo'q"}}

    mapping = SYMBOL_MAP.get(symbol)
    if not mapping:
        return {"score": 0, "direction": "neutral", "details": {"error": "symbol mos kelmadi"}}

    blockchain, currency = mapping
    import time
    start_ts = int(time.time()) - lookback_minutes * 60

    try:
        r = requests.get(
            f"{WHALE_ALERT_BASE}/transactions",
            params={
                "api_key": WHALE_ALERT_API_KEY,
                "min_value": MIN_USD_VALUE,
                "start": start_ts,
                "currency": currency,
            },
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        transactions = data.get("transactions", [])
    except Exception as e:
        return {"score": 0, "direction": "neutral", "details": {"error": str(e)}}

    inflow_usd = 0
    outflow_usd = 0

    for tx in transactions:
        to_type = tx.get("to", {}).get("owner_type", "")
        from_type = tx.get("from", {}).get("owner_type", "")
        usd_value = tx.get("amount_usd", 0)

        if to_type == "exchange" and from_type != "exchange":
            inflow_usd += usd_value
        elif from_type == "exchange" and to_type != "exchange":
            outflow_usd += usd_value

    net_flow = outflow_usd - inflow_usd  # musbat -> birjadan chiqish (long bias)
    total_flow = inflow_usd + outflow_usd

    if total_flow == 0:
        return {"score": 0, "direction": "neutral", "details": {"transactions": 0}}

    # Score: qancha katta oqim bo'lsa, shuncha yuqori
    if total_flow >= 50_000_000:
        base_score = 80
    elif total_flow >= 20_000_000:
        base_score = 60
    elif total_flow >= 5_000_000:
        base_score = 40
    else:
        base_score = 20

    imbalance_ratio = abs(net_flow) / total_flow  # 0..1, qanchalik bir tomonlama
    score = min(int(base_score * (0.5 + imbalance_ratio)), 100)

    direction = "long" if net_flow > 0 else "short" if net_flow < 0 else "neutral"

    return {
        "score": score,
        "direction": direction,
        "details": {
            "inflow_usd": round(inflow_usd, 2),
            "outflow_usd": round(outflow_usd, 2),
            "tx_count": len(transactions),
        },
    }
