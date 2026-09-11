"""
ICT/SMC signal moduli.
Bybit kline ma'lumotlaridan:
- BOS (Break of Structure) / CHoCH (Change of Character)
- Order Block aniqlash
- Liquidity sweep (swing high/low'larni "yutib o'tish")
ni aniqlaydi va shu asosda score/direction qaytaradi.

Eslatma: bu soddalashtirilgan, qoidaga asoslangan (rule-based) implementatsiya.
Sizning ICT/SMC bilimingizga mos ravishda parametrlarni keyinchalik nozik sozlash mumkin.

TUZATISH: kline'ni aggregator dan (candles parametr) oladi —
ortiqcha takroriy so'rov yo'q.
"""
from signals.klines import get_klines


def _find_swing_points(candles, lookback=3):
    """Oddiy swing high/low aniqlash: markazdagi sham eng baland/past bo'lsa."""
    swing_highs, swing_lows = [], []
    for i in range(lookback, len(candles) - lookback):
        window = candles[i - lookback:i + lookback + 1]
        if candles[i]["high"] == max(c["high"] for c in window):
            swing_highs.append((i, candles[i]["high"]))
        if candles[i]["low"] == min(c["low"] for c in window):
            swing_lows.append((i, candles[i]["low"]))
    return swing_highs, swing_lows


def _detect_bos_choch(candles, swing_highs, swing_lows):
    """
    Oxirgi narx eng so'nggi swing high'dan yuqoriga chiqsa -> bullish BOS
    Oxirgi narx eng so'nggi swing low'dan pastga tushsa -> bearish BOS
    """
    if not swing_highs or not swing_lows or not candles:
        return None
    last_close = candles[-1]["close"]
    last_swing_high = swing_highs[-1][1]
    last_swing_low = swing_lows[-1][1]

    if last_close > last_swing_high:
        return "bullish_bos"
    if last_close < last_swing_low:
        return "bearish_bos"
    return None


def _detect_liquidity_sweep(candles, swing_highs, swing_lows):
    """
    Narx swing extremumni bir muddat "yutib o'tib" (wick bilan), keyin
    tananing yopilishi orqaga qaytgan bo'lsa - liquidity sweep.
    """
    if len(candles) < 3 or not swing_highs or not swing_lows:
        return None

    last = candles[-1]
    prev_high = swing_highs[-1][1] if swing_highs else None
    prev_low = swing_lows[-1][1] if swing_lows else None

    if prev_high and last["high"] > prev_high and last["close"] < prev_high:
        return "sell_side_sweep"  # yuqori likvidlikni yutib, pastga qaytdi
    if prev_low and last["low"] < prev_low and last["close"] > prev_low:
        return "buy_side_sweep"  # pastki likvidlikni yutib, yuqoriga qaytdi
    return None


def _find_order_block(candles, direction: str):
    """
    Oddiy order block: BOS'dan oldingi qarama-qarshi rangdagi oxirgi sham.
    direction: 'bullish' yoki 'bearish'
    """
    for i in range(len(candles) - 2, max(len(candles) - 15, 0), -1):
        c = candles[i]
        is_bearish_candle = c["close"] < c["open"]
        is_bullish_candle = c["close"] > c["open"]
        if direction == "bullish" and is_bearish_candle:
            return {"index": i, "high": c["high"], "low": c["low"]}
        if direction == "bearish" and is_bullish_candle:
            return {"index": i, "high": c["high"], "low": c["low"]}
    return None


def analyze(symbol: str, candles: list = None) -> dict:
    if candles is None:
        try:
            candles = get_klines(symbol)
        except Exception as e:
            return {"score": 0, "direction": "neutral", "details": {"error": str(e)}}

    if len(candles) < 20:
        return {"score": 0, "direction": "neutral", "details": {"error": "yetarli data yo'q"}}

    swing_highs, swing_lows = _find_swing_points(candles)
    bos = _detect_bos_choch(candles, swing_highs, swing_lows)
    sweep = _detect_liquidity_sweep(candles, swing_highs, swing_lows)

    score = 0
    direction = "neutral"
    ob = None

    if bos == "bullish_bos":
        score += 50
        direction = "long"
        ob = _find_order_block(candles, "bullish")
    elif bos == "bearish_bos":
        score += 50
        direction = "short"
        ob = _find_order_block(candles, "bearish")

    if sweep == "buy_side_sweep":
        score += 30
        direction = "long" if direction == "neutral" else direction
    elif sweep == "sell_side_sweep":
        score += 30
        direction = "short" if direction == "neutral" else direction

    if ob:
        score += 20

    score = min(score, 100)

    return {
        "score": score,
        "direction": direction,
        "details": {
            "bos_choch": bos,
            "liquidity_sweep": sweep,
            "order_block": ob,
        },
    }
