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


# TUZATISH: avval har bir skanerlashda FAQAT eng yuqori 24 soatlik
# hajmga ega top-MAX_CANDIDATES_PER_SCAN (standart 40) ta juftlik
# olinar edi. Bu aynan asosiy maqsadga zid edi: chinakam kichik
# altcoinlar (top-40dan tashqarida qolganlar) HECH QACHON
# skanerlanmasdi, garchi ular MIN_24H_TURNOVER_USDT chegarasidan
# o'tgan bo'lsa ham. Endi "asosiy" (eng likvid) qism har doim, qolgan
# kichikroq coinlar esa navbat bilan (rotatsiya) - har skanerlashda
# boshqa partiya - qamrab olinadi, shunda bir necha sikldan keyin
# BARCHA nomzodlar tekshirilgan bo'ladi.
_rotation_offset = 0

# Har bir skanerlashda "asosiy" (eng yuqori hajmli, doim skanerlanadigan)
# qism va navbat bilan aylanadigan qismning ulushi
CORE_SLOTS_RATIO = 0.5


def get_candidates() -> list:
    """
    Bybit linear (USDT-perpetual) bozoridagi barcha coinlarni oladi,
    kam likvidlilarni (MIN_24H_TURNOVER_USDT dan past) chiqarib tashlaydi.

    Natija ikki qismdan iborat:
    - "Core": eng yuqori hajmli CORE_SLOTS_RATIO ulushi - har doim skanerlanadi.
    - "Rotation": qolgan barcha nomzodlar - har chaqiriqda navbatdagi
      partiyasi qaytariladi, shunda bir necha skanerlash siklidan keyin
      kichik altcoinlar ham albatta tekshirilgan bo'ladi.

    WATCHLIST'dagi coinlar har doim ro'yxatga kiritiladi (likvidlik
    filtridan qat'i nazar), chunki foydalanuvchi ularni doim kuzatishni
    xohlagan.
    """
    global _rotation_offset

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
    all_symbols = [s for s, _ in scored]

    core_count = max(1, int(MAX_CANDIDATES_PER_SCAN * CORE_SLOTS_RATIO))
    core_symbols = all_symbols[:core_count]
    rotation_pool = all_symbols[core_count:]

    rotation_batch_size = max(MAX_CANDIDATES_PER_SCAN - core_count, 0)
    rotation_batch = []
    if rotation_pool and rotation_batch_size > 0:
        pool_len = len(rotation_pool)
        _rotation_offset %= pool_len
        for i in range(rotation_batch_size):
            rotation_batch.append(rotation_pool[(_rotation_offset + i) % pool_len])
        _rotation_offset = (_rotation_offset + rotation_batch_size) % pool_len

    # WATCHLIST har doim ro'yxatda bo'lishi kerak, takrorlanmasdan
    combined = list(dict.fromkeys(WATCHLIST + core_symbols + rotation_batch))
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
