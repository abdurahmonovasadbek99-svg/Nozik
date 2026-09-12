"""
Universe / Prescreen moduli.
Bybit'dagi barcha USDT-perpetual coinlar orasidan skanerlash uchun
nomzodlarni tanlaydi: past likvidlik (kam 24 soatlik savdo hajmi)
va istisno qilingan symbollarni chiqarib tashlaydi.

DIQQAT: bu fayl avval arxivda yo'q edi - bot.py uni import qiladi
(get_candidates, get_current_price), shuning uchun bu fayl bo'lmasa
bot ishga tushmas edi.
"""
import requests

from config import (
    QUOTE_ASSET,
    MIN_24H_TURNOVER_USDT,
    MAX_CANDIDATES_PER_SCAN,
    EXCLUDE_SYMBOLS,
    WATCHLIST,
)

BYBIT_BASE = "https://api.bybit.com"


def get_candidates() -> list:
    """
    Bybit linear (USDT-perpetual) bozoridagi barcha coinlarni oladi,
    kam likvidlilarni (MIN_24H_TURNOVER_USDT dan past) chiqarib tashlaydi,
    24 soatlik savdo hajmi bo'yicha kamayish tartibida saralaydi va
    eng yuqoridagi MAX_CANDIDATES_PER_SCAN tasini qaytaradi.

    WATCHLIST'dagi coinlar har doim ro'yxatga kiritiladi (likvidlik
    filtridan qat'i nazar), chunki foydalanuvchi ularni doim kuzatishni
    xohlagan.
    """
    try:
        r = requests.get(
            f"{BYBIT_BASE}/v5/market/tickers",
            params={"category": "linear"},
            timeout=15,
        )
        r.raise_for_status()
        tickers = r.json().get("result", {}).get("list", [])
    except Exception:
        # Tarmoq xatosi bo'lsa, hech bo'lmasa WATCHLIST bilan davom etamiz
        return list(dict.fromkeys(WATCHLIST))

    scored = []
    for t in tickers:
        symbol = t.get("symbol", "")
        if not symbol.endswith(QUOTE_ASSET):
            continue
        if symbol in EXCLUDE_SYMBOLS:
            continue
        try:
            turnover = float(t.get("turnover24h", 0) or 0)
        except ValueError:
            continue
        if turnover < MIN_24H_TURNOVER_USDT:
            continue
        scored.append((symbol, turnover))

    scored.sort(key=lambda x: x[1], reverse=True)
    top_symbols = [s for s, _ in scored[:MAX_CANDIDATES_PER_SCAN]]

    # WATCHLIST har doim ro'yxatda bo'lishi kerak, takrorlanmasdan
    combined = list(dict.fromkeys(WATCHLIST + top_symbols))
    return combined


def get_current_price(symbol: str) -> float:
    """Berilgan symbol uchun so'nggi narxni qaytaradi (topilmasa 0)."""
    try:
        r = requests.get(
            f"{BYBIT_BASE}/v5/market/tickers",
            params={"category": "linear", "symbol": symbol},
            timeout=10,
        )
        r.raise_for_status()
        result_list = r.json().get("result", {}).get("list", [])
        if not result_list:
            return 0.0
        return float(result_list[0].get("lastPrice", 0) or 0)
    except Exception:
        return 0.0
