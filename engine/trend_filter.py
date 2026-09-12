"""
Trend filtri moduli.
15 daqiqalik signal 1 soatlik umumiy trendga QARSHI bo'lsa,
signal "shovqin" bo'lish ehtimoli yuqori (whipsaw). Bu modul
1 soatlik EMA50'ga nisbatan narx qayerda turganini tekshiradi.
"""
from signals.klines import get_klines


def _ema(values: list, period: int) -> float:
    if len(values) < period:
        period = len(values)
    if period == 0:
        return 0.0
    k = 2 / (period + 1)
    ema = sum(values[:period]) / period
    for price in values[period:]:
        ema = price * k + ema * (1 - k)
    return ema


def get_trend(symbol: str) -> str:
    """1 soatlik grafikda EMA50'ga nisbatan 'up', 'down' yoki 'flat' qaytaradi."""
    try:
        candles = get_klines(symbol, interval="60", limit=100)
    except Exception:
        return "flat"

    if len(candles) < 20:
        return "flat"

    closes = [c["close"] for c in candles]
    ema50 = _ema(closes, min(50, len(closes)))
    last_close = closes[-1]

    diff_pct = (last_close - ema50) / ema50 * 100 if ema50 else 0

    if diff_pct > 0.3:
        return "up"
    elif diff_pct < -0.3:
        return "down"
    return "flat"


def is_aligned(direction: str, trend: str) -> bool:
    """Signal yo'nalishi umumiy trend bilan mos keladimi.
    'flat' trend har ikkala yo'nalishga ham ruxsat beradi (aniq trend yo'q)."""
    if trend == "flat":
        return True
    if direction == "long" and trend == "up":
        return True
    if direction == "short" and trend == "down":
        return True
    return False
