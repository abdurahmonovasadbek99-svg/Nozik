"""
engine/market_ctx.py  (v6.9)
Signal sifatini oshiruvchi bozor konteksti. Hammasi Bybit REST, faqat YAKUNIY signal oldidan
(skanerlash paytida emas) chaqiriladi — so'rovlar soni juda kam:

  * taker_share   — oxirgi ~5 daqiqadagi haqiqiy taker sotib olish ulushi (recent-trade, 1 so'rov)
  * long_share    — Long/Short account ratio (account-ratio, 1 so'rov)
  * pump_ctx      — pump/dump uchun yuqoridagilar + likvidatsiyalar (engine.liq, xotiradan)
  * enrich_signal — AMD signaliga OI / funding / L/S / taker qo'shadi (ball +- va "🧭" qatori)

Har bir qiymat olinmasa None: filtr jimgina o'tkazib yuboriladi, signal to'xtamaydi.
Sinxron funksiyalar — async koddan asyncio.to_thread bilan chaqiring.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

import config as C
from signals import amd_volume as A

logger = logging.getLogger("nozik.ctx")


def _f(x) -> Optional[float]:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def taker_share(sym: str, window_sec: int = 300, min_trades: int = 20) -> Optional[float]:
    """Taker SOTIB OLISH ulushi (0..1), notional bo'yicha. Yetarli savdo bo'lmasa None."""
    d = A._get("https://api.bybit.com/v5/market/recent-trade",
               {"category": "linear", "symbol": sym, "limit": 1000})
    time.sleep(0.02)
    try:
        if not d or d.get("retCode") != 0:
            return None
        cut = (time.time() - window_sec) * 1000
        buy = sell = 0.0
        n = 0
        for t in d["result"]["list"]:
            if float(t["time"]) < cut:
                continue
            usd = float(t["price"]) * float(t["size"])
            n += 1
            if t["side"] == "Buy":
                buy += usd
            else:
                sell += usd
        if n < min_trades or buy + sell <= 0:
            return None
        return buy / (buy + sell)
    except Exception:
        return None


def long_share(sym: str) -> Optional[float]:
    """Long/Short account ratio: LONG akkauntlar ulushi (0..1). Olinmasa None."""
    d = A._get("https://api.bybit.com/v5/market/account-ratio",
               {"category": "linear", "symbol": sym, "period": "5min", "limit": 1})
    time.sleep(0.1)
    try:
        if not d or d.get("retCode") != 0:
            return None
        row = d["result"]["list"][0]
        v = _f(row.get("buyRatio"))
        return v if v is not None and 0 <= v <= 1 else None
    except Exception:
        return None


def pump_ctx(sym: str, up: bool) -> dict:
    """Pump/dump uchun kontekst, HARAKAT TOMONIGA nisbatan:
    taker (harakat tomonidagi taker ulushi), crowd (harakat tomonidagi akkaunt ulushi),
    liq_with / liq_against (USD)."""
    ctx: dict = {"taker": None, "crowd": None, "liq_with": 0.0, "liq_against": 0.0, "liq_ok": False}
    if C.PUMP_USE_CTX:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=2) as ex:           # v7.0: ikkalasi bir vaqtda
            ft, fl = ex.submit(taker_share, sym), ex.submit(long_share, sym)
            t, ls = ft.result(), fl.result()
        if t is not None:
            ctx["taker"] = t if up else 1 - t
        if ls is not None:
            ctx["crowd"] = ls if up else 1 - ls
    if C.PUMP_USE_LIQ:
        from engine import liq
        s = liq.summary(sym, up)
        if s is not None:
            ctx["liq_with"], ctx["liq_against"] = s
            ctx["liq_ok"] = True
    return ctx


# ------------------------------------------------------------------ AMD
_OI_INTERVAL = {"15m": ("15min", 9), "1h": ("1h", 9), "4h": ("4h", 7), "1d": ("4h", 7)}


def _oi_change(sym: str, tf: str) -> Optional[float]:
    iv, lim = _OI_INTERVAL.get(tf, ("1h", 9))
    d = A._get("https://api.bybit.com/v5/market/open-interest",
               {"category": "linear", "symbol": sym, "intervalTime": iv, "limit": lim})
    time.sleep(0.1)
    try:
        if not d or d.get("retCode") != 0:
            return None
        rows = d["result"]["list"]                 # yangi -> eski
        if len(rows) < 3:
            return None
        new, old = float(rows[0]["openInterest"]), float(rows[-1]["openInterest"])
        return (new / old - 1) * 100 if old > 0 else None
    except Exception:
        return None


def _funding(sym: str) -> Optional[float]:
    d = A._get("https://api.bybit.com/v5/market/tickers", {"category": "linear", "symbol": sym})
    time.sleep(0.1)
    try:
        if not d or d.get("retCode") != 0:
            return None
        v = _f(d["result"]["list"][0].get("fundingRate"))
        return v * 100 if v is not None else None
    except Exception:
        return None


def score_amd(side: str, funding: Optional[float], oi: Optional[float],
              crowd: Optional[float], taker: Optional[float]) -> tuple:
    """Sof funksiya: (ball tuzatishi, [chiplar]). crowd/taker — SIGNAL TOMONIDAGI ulush (0..1)."""
    adj = 0
    chips = []
    if funding is not None:
        chips.append(f"funding {funding:+.3f}%")
        mine = funding if side == "LONG" else -funding           # signal tomonida musbat = olomon shu tomonda
        if mine >= C.AMD_FUNDING_CROWDED:
            adj -= 5
        elif mine <= -C.AMD_FUNDING_FUEL:
            adj += 3
    if oi is not None:
        chips.append(f"OI {oi:+.1f}%")
        if oi >= 2.0:
            adj += 3                                              # yangi pozitsiyalar kirmoqda
        elif oi <= -4.0:
            adj -= 3                                              # pozitsiyalar yopilmoqda — davom kuchsizroq
    if crowd is not None:
        chips.append(f"L/S {crowd * 100:.0f}% за")
        if crowd >= C.PUMP_LS_CROWDED:
            adj -= 4
        elif crowd <= C.PUMP_LS_FUEL:
            adj += 3
    if taker is not None:
        chips.append(f"тейкеры {taker * 100:.0f}% за")
        if taker >= C.PUMP_TAKER_GOOD:
            adj += 4
        elif taker <= C.PUMP_TAKER_BAD:
            adj -= 4
    adj = max(-C.AMD_CTX_MAX_ADJ, min(C.AMD_CTX_MAX_ADJ, adj))
    return adj, chips


def enrich_signal(s, min_score: int) -> bool:
    """AMD signaliga kontekst qo'shadi: s.score ni tuzatadi, s.ctx_line ni to'ldiradi.
    False — tuzatilgan ball chegaradan past (signalni yubormaslik kerak). Xatoda True (signal yo'qolmasin)."""
    if not C.AMD_USE_CTX:
        return True
    try:
        up = s.side == "LONG"
        funding = _funding(s.symbol)
        oi = _oi_change(s.symbol, s.tf)
        ls = long_share(s.symbol)
        crowd = (ls if up else 1 - ls) if ls is not None else None
        t = taker_share(s.symbol)
        taker = (t if up else 1 - t) if t is not None else None
        adj, chips = score_amd(s.side, funding, oi, crowd, taker)
        s.ctx_line = " · ".join(chips)
        s.ctx_adj = adj
        s.score = max(0, min(100, int(s.score) + adj))
        if s.score < min_score:
            logger.info(f"{s.symbol} [{s.tf}]: kontekst ({adj:+d}) bilan skor {s.score} < {min_score} — yuborilmadi")
            return False
    except Exception as e:
        logger.warning(f"{getattr(s, 'symbol', '?')}: kontekst xatosi: {e}")
    return True
