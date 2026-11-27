"""
engine/liq.py  (v6.9)
Binance USDT-M futures'ning BARCHA likvidatsiyalarini bitta WebSocket orqali eshitadi
(wss://fstream.binance.com/ws/!forceOrder@arr) va har coin uchun oxirgi ~15 daqiqalik
yig'indini XOTIRADA saqlaydi. So'rov yo'q, CPU/xotira juda oz.

Eslatma: Binance'da ro'yxatda bo'lmagan (faqat Bybit) coinlar uchun ma'lumot bo'lmaydi —
summary() None qaytaradi va filtr o'tkazib yuboriladi. Ulanish uzilsa bot filtrsiz ishlayveradi.
Binance'ning "S" maydoni: SELL = LONG pozitsiya likvidatsiya qilindi; BUY = SHORT likvidatsiya qilindi.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from typing import Deque, Dict, Optional, Tuple

import config as C

logger = logging.getLogger("nozik.liq")

URL = "wss://fstream.binance.com/ws/!forceOrder@arr"
KEEP_SECONDS = 900

_EV: Dict[str, Deque[Tuple[float, str, float]]] = {}      # sym -> deque[(ts, "long"|"short", usd)]
STATE = {"connected": False, "events": 0, "last_ts": 0.0, "last_error": "", "reconnects": 0}


def parse(raw) -> list:
    """WS xabaridan [(symbol, kind, usd, ts)] ro'yxati. Noto'g'ri xabar -> []."""
    try:
        d = json.loads(raw) if isinstance(raw, (str, bytes, bytearray)) else raw
    except Exception:
        return []
    items = d if isinstance(d, list) else [d]
    out = []
    for it in items:
        try:
            if not isinstance(it, dict) or it.get("e") != "forceOrder":
                continue
            o = it["o"]
            sym = o["s"]
            qty = float(o.get("z") or o.get("q") or 0)
            px = float(o.get("ap") or 0) or float(o.get("p") or 0)
            usd = qty * px
            if usd <= 0:
                continue
            kind = "long" if o.get("S") == "SELL" else "short"
            ts = float(o.get("T") or it.get("E") or 0) / 1000.0 or time.time()
            out.append((sym, kind, usd, ts))
        except Exception:
            continue
    return out


def record(sym: str, kind: str, usd: float, ts: Optional[float] = None) -> None:
    ts = ts or time.time()
    dq = _EV.setdefault(sym, deque())
    dq.append((ts, kind, usd))
    cut = time.time() - KEEP_SECONDS
    while dq and dq[0][0] < cut:
        dq.popleft()
    STATE["events"] += 1
    STATE["last_ts"] = time.time()


def summary(sym: str, up: bool, secs: Optional[int] = None) -> Optional[Tuple[float, float]]:
    """(harakatni QO'LLAB-QUVVATLAYDIGAN, harakatga QARSHI) likvidatsiya USD yig'indisi.
    up=True (pump): short likvidatsiyalar qo'llab-quvvatlaydi (short squeeze), long — qarshi.
    Oqim ishlamayotgan bo'lsa None (filtr o'tkaziladi)."""
    if not STATE["connected"]:
        return None
    secs = secs or C.PUMP_LIQ_WINDOW_SEC
    cut = time.time() - secs
    long_usd = short_usd = 0.0
    for ts, kind, usd in _EV.get(sym, ()):
        if ts >= cut:
            if kind == "long":
                long_usd += usd
            else:
                short_usd += usd
    return (short_usd, long_usd) if up else (long_usd, short_usd)


async def run() -> None:
    """Fon vazifa: ulanadi, tinglaydi, uzilsa qayta ulanadi (5 -> 300 s kutish). Kutubxona yo'q bo'lsa — o'chadi."""
    try:
        import websockets
    except ImportError:
        logger.warning("websockets o'rnatilmagan — likvidatsiya oqimi o'chiq (requirements.txt ni tekshiring)")
        return
    delay = 5
    while True:
        try:
            async with websockets.connect(URL, ping_interval=20, ping_timeout=20, max_size=2 ** 20) as ws:
                STATE["connected"] = True
                STATE["last_error"] = ""
                delay = 5
                logger.info("Likvidatsiya oqimi ulandi (Binance !forceOrder@arr)")
                async for raw in ws:
                    for sym, kind, usd, ts in parse(raw):
                        record(sym, kind, usd, ts)
        except asyncio.CancelledError:
            STATE["connected"] = False
            raise
        except Exception as e:
            STATE["last_error"] = str(e)[:100]
            logger.warning(f"Likvidatsiya oqimi uzildi: {e}")
        STATE["connected"] = False
        STATE["reconnects"] += 1
        await asyncio.sleep(delay)
        delay = min(300, delay * 2)
