"""
Pump/dump aniqlash logikasi — aniqlikni oshirish uchun 4 ta filtr birga ishlatiladi:

1. Narx o'zgarishi (WINDOW_CANDLES ichida) + hajm portlashi (uzoq BASELINE'ga nisbatan)
2. Momentum konsistensiyasi — bitta katta sham emas, kamida N ta sham bir yo'nalishda
3. Impulse-candle filtri — asosiy sham "tanasi" katta bo'lishi kerak (faqat fitna/wick emas,
   bu wash-trading yoki bitta katta orderdan farqlaydi)
4. Yuqori timeframe (15m) tasdig'i — signal 5m va 15m da bir xil yo'nalishda bo'lsa "TASDIQLANGAN",
   bo'lmasa "ERTA" (hali tasdiqlanmagan, ehtiyot bo'lish kerak) deb belgilanadi
"""

import asyncio
import logging
from dataclasses import dataclass

from .bybit_client import BybitClient
from . import config

logger = logging.getLogger("pump.detector")


@dataclass
class PumpSignal:
    symbol: str
    price_change_pct: float
    volume_ratio: float
    last_price: float
    turnover_24h: float
    confirmed: bool          # 15m timeframe ham tasdiqladimi
    body_ratio: float
    consistent_candles: int
    score: float

    def format(self) -> str:
        direction = "🟢 PUMP" if self.price_change_pct > 0 else "🔴 DUMP"
        status = "✅ TASDIQLANGAN" if self.confirmed else "⚠️ ERTA (ehtiyot bo'ling)"
        window_min = config.WINDOW_CANDLES * int(config.KLINE_INTERVAL)
        return (
            f"{direction} <b>{self.symbol}</b> — {status}\n"
            f"   Narx: {self.price_change_pct:+.2f}% ({window_min} daq)\n"
            f"   Hajm: {self.volume_ratio:.1f}x (baseline'ga nisbatan)\n"
            f"   Momentum: {self.consistent_candles}/{config.WINDOW_CANDLES} sham bir yo'nalishda\n"
            f"   Narx: {self.last_price:g}\n"
            f"   Skor: {self.score:.1f}"
        )


def _score(price_change_pct: float, volume_ratio: float, confirmed: bool, body_ratio: float) -> float:
    base = abs(price_change_pct) * 1.0 + volume_ratio * 2.0 + body_ratio * 3.0
    return base * (1.5 if confirmed else 1.0)


def _body_ratio(candle: dict) -> float:
    """Sham tanasi (open-close) / range (high-low) nisbati. 1.0 = toza yo'nalish, 0.0 = faqat fitna."""
    rng = candle["high"] - candle["low"]
    if rng <= 0:
        return 0.0
    body = abs(candle["close"] - candle["open"])
    return body / rng


async def _check_symbol(
    client: BybitClient, symbol: str, ticker: dict, sem: asyncio.Semaphore
) -> PumpSignal | None:
    turnover_24h = float(ticker.get("turnover24h", 0))
    if turnover_24h < config.MIN_TURNOVER_USDT:
        return None

    async with sem:
        try:
            baseline_candles = await client.get_klines(
                symbol, interval=config.KLINE_INTERVAL, limit=config.BASELINE_CANDLES
            )
        except Exception as e:
            logger.warning(f"{symbol}: klines olishda xato — {e}")
            return None

    if len(baseline_candles) < config.BASELINE_CANDLES:
        return None

    window = baseline_candles[-config.WINDOW_CANDLES:]
    baseline = baseline_candles[: -config.WINDOW_CANDLES]

    # --- 1. Narx o'zgarishi (oyna) ---
    first_open = window[0]["open"]
    last_close = window[-1]["close"]
    if first_open <= 0:
        return None
    price_change_pct = (last_close - first_open) / first_open * 100

    if abs(price_change_pct) < config.PRICE_CHANGE_THRESHOLD_PCT:
        return None

    # --- 2. Hajm portlashi (uzoq baseline'ga nisbatan) ---
    baseline_avg_volume = sum(c["volume"] for c in baseline) / max(len(baseline), 1)
    window_avg_volume = sum(c["volume"] for c in window) / len(window)
    volume_ratio = window_avg_volume / baseline_avg_volume if baseline_avg_volume > 0 else 0

    if volume_ratio < config.VOLUME_RATIO_THRESHOLD:
        return None

    # --- 3. Momentum konsistensiyasi (bitta wick emas) ---
    direction_up = price_change_pct > 0
    consistent = sum(
        1 for c in window
        if (c["close"] > c["open"]) == direction_up
    )
    if consistent < config.MIN_CONSISTENT_CANDLES:
        return None

    # --- 4. Impulse-candle filtri (faqat fitna emas, real tana) ---
    strongest_candle = max(window, key=lambda c: abs(c["close"] - c["open"]))
    body_ratio = _body_ratio(strongest_candle)
    if body_ratio < config.MIN_BODY_RATIO:
        return None

    # --- 5. Yuqori timeframe (15m) tasdig'i ---
    confirmed = False
    try:
        async with sem:
            confirm_candles = await client.get_klines(
                symbol, interval=config.CONFIRM_INTERVAL, limit=config.CONFIRM_LOOKBACK
            )
        if len(confirm_candles) >= 2:
            htf_change = confirm_candles[-1]["close"] - confirm_candles[0]["open"]
            confirmed = (htf_change > 0) == direction_up
    except Exception as e:
        logger.warning(f"{symbol}: HTF tasdig'ida xato — {e}")

    return PumpSignal(
        symbol=symbol,
        price_change_pct=price_change_pct,
        volume_ratio=volume_ratio,
        last_price=last_close,
        turnover_24h=turnover_24h,
        confirmed=confirmed,
        body_ratio=body_ratio,
        consistent_candles=consistent,
        score=_score(price_change_pct, volume_ratio, confirmed, body_ratio),
    )


async def scan_market(client: BybitClient) -> list[PumpSignal]:
    """Butun Bybit USDT Perpetual bozorini skanerlaydi, pump/dump signallarini qaytaradi."""
    tickers = await client.get_tickers()
    symbols = list(tickers.keys())
    logger.info(f"Skanerlanmoqda: {len(symbols)} juftlik")

    sem = asyncio.Semaphore(config.MAX_CONCURRENT_REQUESTS)
    tasks = [_check_symbol(client, s, tickers[s], sem) for s in symbols]
    results = await asyncio.gather(*tasks, return_exceptions=False)

    signals = [r for r in results if r is not None]
    signals.sort(key=lambda s: s.score, reverse=True)
    return signals
