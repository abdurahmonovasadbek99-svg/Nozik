"""
Umumiy Bybit kline yuklash moduli (YANGI).

MUAMMO: avval ict_smc, volume_oi va volume_bos_combo modullari
har biri alohida, bir xil kline'ni yuklar edi — har bir coin uchun
3x keraksiz tarmoq so'rovi.

YECHIM: aggregator bir marta yuklab, candles ro'yxatini barcha
modullarga uzatadi. Modullar candles=None bo'lsa o'zlari yuklaydi
(masalan, mustaqil test qilishda).
"""
import requests

BYBIT_BASE = "https://api.bybit.com"


def get_klines(symbol: str, interval: str = "15", limit: int = 100) -> list:
    """Bybit linear (USDT-perpetual) kline'larni kronologik (eskidan yangiga) tartibda qaytaradi."""
    url = f"{BYBIT_BASE}/v5/market/kline"
    params = {"category": "linear", "symbol": symbol, "interval": interval, "limit": limit}
    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    rows = list(reversed(r.json()["result"]["list"]))
    return [
        {
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
            "volume": float(row[5]),
        }
        for row in rows
    ]
