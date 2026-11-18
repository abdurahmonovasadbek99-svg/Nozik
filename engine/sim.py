"""
engine/sim.py
Savdo simulyatsiyasi uchun YAGONA joy: evaluator (jonli signal kuzatuvi) va
backtest bir xil qoidalardan foydalanadi, shuning uchun natijalar bir-biriga mos.

Qoidalar:
  - SL urilsa                         -> -1R
  - TP1 urilsa: 50% yopiladi, SL breakeven'ga suriladi
      - TP2 urilsa                    -> 0.5*RR1 + 0.5*RR2
      - kirish narxiga qaytsa         -> 0.5*RR1
  - По истечении срока: остаток позиции закрывается по цене закрытия последней свечи
    (avval 0R deb olinardi — bu natijani chiroyli ko'rsatardi)
  - Bir sham ichida SL ham, TP ham urilsa — SL hisoblanadi (konservativ).
  - Komissiya + slippage R hisobida ayriladi (cost_r).
"""
from __future__ import annotations

from typing import Optional, Tuple

_BYBIT_SPECIAL = {"D": 86_400_000, "W": 604_800_000, "M": 2_592_000_000}
_UNIT_MS = {"m": 60_000, "h": 3_600_000, "d": 86_400_000, "w": 604_800_000}


def tf_ms(interval: str) -> int:
    """Bybit interval ('15', '60', '240', 'D', 'W') -> millisekund."""
    if interval in _BYBIT_SPECIAL:
        return _BYBIT_SPECIAL[interval]
    return int(interval) * 60_000


def bn_ms(interval: str) -> int:
    """Binance interval ('15m', '1h', '4h', '1d') -> millisekund."""
    return int(interval[:-1]) * _UNIT_MS[interval[-1]]


def cost_r(entry: float, sl: float, fee_pct: float, slip_pct: float) -> float:
    """Aylanma (kirish + chiqish) komissiya va slippage, R birligida.
    fee_pct / slip_pct — BIR TOMON uchun, % da. Pozitsiya 2 qismda yopilsa ham
    jami aylanma hajm 2 tomonga teng."""
    if entry <= 0:
        return 0.0
    risk_pct = abs(entry - sl) / entry * 100
    if risk_pct <= 0:
        return 0.0
    return 2 * (fee_pct + slip_pct) / risk_pct


def step(side: str, entry: float, sl: float, tp1: float, tp2: float,
         rr1: float, rr2: float, hit1: bool, hi: float, lo: float
         ) -> Tuple[bool, Optional[str], Optional[float]]:
    """Bitta YOPILGAN sham. Qaytaradi: (tp1_hit, status|None, gross_R|None).
    status: 'sl' | 'be' | 'tp2' | None (hali ochiq)."""
    long_ = side == "LONG"
    stop = entry if hit1 else sl
    if (lo <= stop) if long_ else (hi >= stop):
        return hit1, ("be" if hit1 else "sl"), (0.5 * rr1 if hit1 else -1.0)
    if not hit1 and ((hi >= tp1) if long_ else (lo <= tp1)):
        hit1 = True
    if hit1 and ((hi >= tp2) if long_ else (lo <= tp2)):
        return True, "tp2", 0.5 * rr1 + 0.5 * rr2
    return hit1, None, None


def expire_gross(side: str, entry: float, sl: float, rr1: float,
                 hit1: bool, last_close: float) -> float:
    """По истечении срока остаток позиции закрывается по последней цене закрытия."""
    risk = abs(entry - sl)
    if risk <= 0:
        return 0.0
    move = (last_close - entry) if side == "LONG" else (entry - last_close)
    r_close = move / risk
    if hit1:
        return 0.5 * rr1 + 0.5 * max(r_close, 0.0)   # qolgan qism uchun stop = breakeven
    return max(r_close, -1.0)


# ----------------------------------------------------------- 3 ta TP (kuchli impuls)
# Pozitsiya 40/30/30: TP1 da 40% yopiladi va SL -> kirish (BE); TP2 da yana 30% va SL -> TP1;
# TP3 da qolgan 30%. (stage: 0 = hali TP1 yo'q, 1 = TP1 olingan, 2 = TP2 olingan)
W3 = (0.4, 0.3, 0.3)


def step3(side: str, entry: float, sl: float, tp1: float, tp2: float, tp3: float,
          rr1: float, rr2: float, rr3: float, stage: int, hi: float, lo: float
          ) -> Tuple[int, Optional[str], Optional[float]]:
    """Bitta YOPILGAN sham. Qaytaradi: (stage, status|None, gross_R|None).
    status: 'sl' | 'be' | 'lock' (TP1+TP2 olingan, qoldiq TP1 da yopildi) | 'tp3' | None."""
    long_ = side == "LONG"
    stop = sl if stage == 0 else (entry if stage == 1 else tp1)
    if (lo <= stop) if long_ else (hi >= stop):
        if stage == 0:
            return 0, "sl", -1.0
        if stage == 1:
            return 1, "be", W3[0] * rr1
        return 2, "lock", W3[0] * rr1 + W3[1] * rr2 + W3[2] * rr1
    if stage == 0 and ((hi >= tp1) if long_ else (lo <= tp1)):
        stage = 1
    if stage == 1 and ((hi >= tp2) if long_ else (lo <= tp2)):
        stage = 2
    if stage == 2 and ((hi >= tp3) if long_ else (lo <= tp3)):
        return 3, "tp3", W3[0] * rr1 + W3[1] * rr2 + W3[2] * rr3
    return stage, None, None


def expire_gross3(side: str, entry: float, sl: float, rr1: float, rr2: float,
                  stage: int, last_close: float) -> float:
    risk = abs(entry - sl)
    if risk <= 0:
        return 0.0
    r_close = ((last_close - entry) if side == "LONG" else (entry - last_close)) / risk
    if stage == 0:
        return max(r_close, -1.0)
    if stage == 1:
        return W3[0] * rr1 + (1 - W3[0]) * max(r_close, 0.0)
    return W3[0] * rr1 + W3[1] * rr2 + W3[2] * max(r_close, rr1)
