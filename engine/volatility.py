"""
Volatillik (ATR) va bozor rejimi (BTC dominance) moduli — YANGI.

1) ATR (Average True Range):
   Har bir coin narxining o'ziga xos "tabiiy tebranish kengligi"ni
   o'lchaydi. Buning 2 ta muhim vazifasi bor:
   - Volatillik filtri: agar bozor "o'lik" (ATR% juda past) bo'lsa,
     har qanday BOS/breakout signal ko'pincha soxta (fakeout) bo'ladi -
     shunday paytda signal yubormaymiz.
   - Adaptiv baholash: "signal muvaffaqiyatli" degani nima - buni
     endi har coin uchun BIR XIL qattiq % (masalan 1%) bilan emas,
     o'sha coinning O'Z tabiiy tebranishiga (ATR%) nisbatan aniqlaymiz.
     Sabab: 1% harakat BTC uchun katta yutuq, ba'zi volatil altcoin
     uchun esa oddiy shovqin bo'lishi mumkin.

2) BTC bozor rejimi:
   Kripto bozorida deyarli barcha altcoinlar BTC harakatiga kuchli
   bog'liq ("BTC dominance"). Agar BTC keskin pasayayotgan bo'lsa,
   biror altcoin uchun "long" signali kelsa ham, ko'pincha bu signal
   umumiy oqimga qarshi suzib, muvaffaqiyatsiz tugaydi. Bu modul BTC
   1 soatlik momentumini tekshirib, kuchli qarama-qarshi holatlarda
   ogohlantiradi.
"""
from signals.klines import get_klines


def compute_atr_pct(candles: list, period: int = 14) -> float:
    """So'nggi `period` sham bo'yicha ATR ni joriy narxga nisbatan foizda qaytaradi.
    Yetarli ma'lumot bo'lmasa 0.0 qaytaradi (filtrlar bunda "noaniq" deb o'tkazib yuboradi)."""
    if len(candles) < period + 1:
        return 0.0

    true_ranges = []
    for i in range(1, len(candles)):
        high = candles[i]["high"]
        low = candles[i]["low"]
        prev_close = candles[i - 1]["close"]
        tr = max(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close),
        )
        true_ranges.append(tr)

    recent_tr = true_ranges[-period:]
    atr = sum(recent_tr) / len(recent_tr)
    last_price = candles[-1]["close"]
    return (atr / last_price) * 100 if last_price else 0.0


# ATR% bundan past bo'lsa - bozor "o'lik", yangi signal yubormaymiz
# (breakoutlar ko'pincha soxta bo'ladi)
MIN_ATR_PCT_FOR_SIGNAL = 0.15

# BTC 1 soatlik narx o'zgarishi shundan katta bo'lsa - "kuchli" rejim
BTC_STRONG_MOVE_PCT = 1.2


def is_market_too_dead(candles: list) -> bool:
    """True bo'lsa - volatillik juda past, signal ishonchsiz bo'lishi mumkin."""
    atr_pct = compute_atr_pct(candles)
    if atr_pct == 0.0:
        return False  # yetarli data yo'q - filtrlab qo'ymaymiz, boshqa modullarga ishonamiz
    return atr_pct < MIN_ATR_PCT_FOR_SIGNAL


def get_btc_regime() -> str:
    """BTCUSDT so'nggi 1 soatlik (4 x 15m emas, to'g'ridan-to'g'ri 60m) harakatiga
    qarab 'strong_up', 'strong_down' yoki 'neutral' qaytaradi."""
    try:
        candles = get_klines("BTCUSDT", interval="60", limit=6)
    except Exception:
        return "neutral"

    if len(candles) < 2:
        return "neutral"

    first_close = candles[0]["close"]
    last_close = candles[-1]["close"]
    if not first_close:
        return "neutral"

    change_pct = (last_close - first_close) / first_close * 100

    if change_pct >= BTC_STRONG_MOVE_PCT:
        return "strong_up"
    if change_pct <= -BTC_STRONG_MOVE_PCT:
        return "strong_down"
    return "neutral"


def conflicts_with_btc_regime(symbol: str, direction: str, btc_regime: str) -> bool:
    """BTC/ETH kabi asosiy coinlar uchun bu filtr qo'llanilmaydi (ular
    o'zi BTC harakatining bir qismi). Faqat altcoinlar uchun: agar BTC
    kuchli tushayotgan bo'lsa-yu, altcoin 'long' signal bersa (yoki
    aksincha) - bu qarama-qarshi oqim, ehtiyot bo'lish kerak."""
    if symbol in ("BTCUSDT", "ETHUSDT"):
        return False
    if btc_regime == "strong_down" and direction == "long":
        return True
    if btc_regime == "strong_up" and direction == "short":
        return True
    return False
