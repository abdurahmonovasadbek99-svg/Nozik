"""
BTC bozor rejimi filtri.

Kripto bozorida deyarli barcha altcoinlar BTC harakatiga bog'liq. BTC kuchli tushayotgan
paytda altcoin LONG signali (yoki BTC kuchli o'sayotganda SHORT) ko'pincha oqimga qarshi
bo'lib, muvaffaqiyatsiz tugaydi. Bu modul BTC'ning so'nggi n ta YOPILGAN shamidagi
harakatni o'lchab, shunday signallarni o'tkazib yuborishga yordam beradi.

(Avvalgi ATR "o'lik bozor" funksiyalari hech qayerda ishlatilmagani uchun olib tashlandi;
past volatillik allaqachon accumulation diapazon filtri (min_range_pct) bilan qoplangan.)
"""
from __future__ import annotations

import logging

from signals.amd_volume import bybit_klines

logger = logging.getLogger("nozik.btc")


def btc_regime(interval: str = "60", n: int = 6, move_pct: float = 1.2) -> str:
    """'strong_up' | 'strong_down' | 'neutral'.
    Oxirgi n ta YOPILGAN sham: birinchisining ochilishidan oxirgisining yopilishigacha."""
    try:
        c = bybit_klines("BTCUSDT", interval, n + 2)
    except Exception as e:
        logger.warning(f"BTC rejimi olinmadi: {e}")
        return "neutral"
    if not c or len(c) < 3:
        return "neutral"
    c = c[:-1][-n:]                       # shakllanayotgan shamni tashlab, oxirgi n ta
    if not c or not c[0][1]:
        return "neutral"
    chg = (c[-1][4] - c[0][1]) / c[0][1] * 100
    if chg >= move_pct:
        return "strong_up"
    if chg <= -move_pct:
        return "strong_down"
    return "neutral"


def get_btc_regime() -> str:
    """15m modul uchun: BTC oxirgi 6 soat, 1.2%."""
    return btc_regime("60", 6, 1.2)


def conflicts_with_btc_regime(symbol: str, direction: str, regime: str) -> bool:
    """BTC/ETH uchun filtr qo'llanilmaydi. Altcoin: BTC kuchli tushayotganda LONG
    yoki kuchli o'sayotganda SHORT — oqimga qarshi."""
    if symbol in ("BTCUSDT", "ETHUSDT"):
        return False
    d = direction.upper()
    return (regime == "strong_down" and d == "LONG") or (regime == "strong_up" and d == "SHORT")
