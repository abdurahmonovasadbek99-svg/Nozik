"""
Bybit v5 REST API client (public endpoints, API key kerak emas).
Faqat linear (USDT Perpetual) bozorlar bilan ishlaydi.
"""

import aiohttp
import asyncio
import logging

logger = logging.getLogger("pump.bybit")

BASE_URL = "https://api.bybit.com"


class BybitClient:
    def __init__(self, session: aiohttp.ClientSession | None = None):
        self._session = session
        self._owns_session = session is None

    async def __aenter__(self):
        if self._session is None:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=15)
            )
        return self

    async def __aexit__(self, *exc):
        if self._owns_session and self._session:
            await self._session.close()

    async def _get(self, path: str, params: dict) -> dict:
        url = f"{BASE_URL}{path}"
        async with self._session.get(url, params=params) as resp:
            data = await resp.json()
            if data.get("retCode") != 0:
                raise RuntimeError(f"Bybit API xato: {data.get('retMsg')}")
            return data["result"]

    async def get_usdt_perp_symbols(self) -> list[str]:
        """Barcha aktiv USDT Perpetual juftliklarni qaytaradi."""
        result = await self._get(
            "/v5/market/instruments-info",
            {"category": "linear"},
        )
        symbols = [
            item["symbol"]
            for item in result.get("list", [])
            if item.get("quoteCoin") == "USDT" and item.get("status") == "Trading"
        ]
        return symbols

    async def get_tickers(self) -> dict[str, dict]:
        """Barcha linear tickerlarni bir so'rovda oladi (24h narx/hajm)."""
        result = await self._get("/v5/market/tickers", {"category": "linear"})
        return {item["symbol"]: item for item in result.get("list", [])}

    async def get_open_interest(
        self, symbol: str, interval_time: str = "5min", limit: int = 6
    ) -> list[dict]:
        """
        Open Interest tarixi — narx harakati ortida haqiqiy pozitsiya ochilyaptimi
        yoki shunchaki likvidatsiya/wash-trade shovqinimi, shuni ajratish uchun.
        Qaytadi: eskidan yangiga [{oi, timestamp}, ...]
        """
        result = await self._get(
            "/v5/market/open-interest",
            {
                "category": "linear",
                "symbol": symbol,
                "intervalTime": interval_time,
                "limit": limit,
            },
        )
        raw = result.get("list", [])  # yangi->eski keladi
        raw.reverse()
        return [
            {"oi": float(item["openInterest"]), "timestamp": int(item["timestamp"])}
            for item in raw
        ]

    async def get_klines(self, symbol: str, interval: str = "5", limit: int = 6) -> list[dict]:
        """
        interval: '1','3','5','15',... (daqiqa)
        Qaytadi: eskidan yangiga qarab tartiblangan candle list
        [{open, high, low, close, volume, turnover, start}, ...]
        """
        result = await self._get(
            "/v5/market/kline",
            {"category": "linear", "symbol": symbol, "interval": interval, "limit": limit},
        )
        raw = result.get("list", [])  # Bybit yangi->eski beradi
        raw.reverse()
        candles = []
        for c in raw:
            candles.append(
                {
                    "start": int(c[0]),
                    "open": float(c[1]),
                    "high": float(c[2]),
                    "low": float(c[3]),
                    "close": float(c[4]),
                    "volume": float(c[5]),
                    "turnover": float(c[6]),
                }
            )
        return candles
