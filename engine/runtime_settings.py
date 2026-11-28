"""
engine/runtime_settings.py  (v6.7)
Bot parametrlarini Telegram ICHIDAN o'zgartirish — Render'ga kirmasdan, redeploy'siz.

Qanday ishlaydi:
  * Standart qiymat = kod / Render env (bot ishga tushganda o'qilgan qiymat).
  * Telegram'dan o'zgartirilgan qiymat bazaga (runtime_settings jadvali) yoziladi va
    DARHOL ishlaydi (config moduli + AMD profillari yangilanadi).
  * Bot qayta ishga tushsa — saqlangan qiymatlar bazadan qaytadan qo'llanadi.
    DIQQAT: DATABASE_URL (PostgreSQL) bo'lmasa SQLite har redeploy'da o'chadi — sozlamalar ham.
  * Bazadagi qiymat Render env'dan USTUN turadi. "♻️ По умолчанию" — qiymatni bazadan o'chiradi.

Buyruqlar:  /params  (tugmali menyu)   /set KEY VALUE   /reset_param KEY|all
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import config as C
from engine import db

logger = logging.getLogger("nozik.settings")


@dataclass(frozen=True)
class P:
    key: str
    kind: str            # "int" | "float" | "bool"
    group: str
    label: str           # tugmada ko'rinadigan qisqa nom (RU)
    desc: str            # tushuntirish (RU)
    lo: float = 0
    hi: float = 0
    step: float = 0
    restart: bool = False   # True: faqat qayta ishga tushganda qo'llanadi


G_AMD = "📈 AMD: основное"
G_AMD2 = "🔬 AMD: тонкая настройка (15m)"
G_PD = "🚀 Pump/Dump: пороги"
G_PDX = "🎯 Pump/Dump: SL / TP / пауза"
G_PDF = "🛡 Pump/Dump: фильтры"
G_MISC = "🧰 Прочее"

GROUPS = [G_AMD, G_AMD2, G_PD, G_PDX, G_PDF, G_MISC]

REGISTRY: List[P] = [
    # ---------------- AMD: основное ----------------
    P("ALERT_THRESHOLD", "int", G_AMD, "Мин. скор 15m", "Минимальный скор AMD-сигнала 15m (0-100). Выше = меньше, но качественнее сигналов.", 30, 100, 2),
    P("SWING_ALERT_THRESHOLD", "int", G_AMD, "Мин. скор 1h/4h", "Минимальный скор для 1h/4h сигналов.", 30, 100, 2),
    P("ALERT_COOLDOWN_SECONDS", "int", G_AMD, "Cooldown (сек)", "Пауза по одной монете после сигнала 15m, секунды (7200 = 2 ч).", 0, 172800, 1800),
    P("MAX_RISK_PCT", "float", G_AMD, "Макс. риск %", "Если расстояние до SL больше этого % — сигнал пропускается (15m).", 0.5, 20, 0.5),
    P("SCAN_INTERVAL_SECONDS", "int", G_AMD, "Скан 15m (сек)", "Как часто сканировать рынок (AMD 15m).", 60, 3600, 60),
    P("REQUIRE_STRUCTURE", "bool", G_AMD, "MSS/FVG обязательны", "Вкл: без MSS/FVG сигнал не отправляется. Выкл: влияет только на скор."),
    P("USE_BTC_FILTER", "bool", G_AMD, "BTC-фильтр", "Блокировать сигналы против сильного движения BTC."),
    P("MIN_24H_TURNOVER_USDT", "float", G_AMD, "Мин. оборот 24ч", "Мин. суточный оборот монеты, USDT (можно писать 500k, 2m).", 0, 1e10, 100000),
    P("MAX_24H_TURNOVER_USDT", "float", G_AMD, "Макс. оборот 24ч", "Макс. суточный оборот монеты, USDT (отсекает крупные монеты).", 0, 1e11, 50000000),
    P("MAX_CANDIDATES_PER_SCAN", "int", G_AMD, "Монет за скан", "Сколько монет анализировать за один скан.", 10, 1000, 50),
    P("MAX_CHASE_R", "float", G_AMD, "Не догонять (R)", "Если цена уже ушла от входа к TP больше чем на столько R — сигнал пропускается.", 0.1, 3, 0.1),
    P("EXPIRE_CANDLES", "int", G_AMD, "Срок сигнала 15m", "Через сколько 15m-свечей сигнал считается истёкшим (48 = 12 ч).", 4, 400, 4),

    # ---------------- AMD: тонкая настройка ----------------
    P("AMD_MAX_RANGE_PCT", "float", G_AMD2, "Макс. диапазон %", "Макс. ширина зоны накопления (15m).", 1, 20, 0.5),
    P("AMD_ACC_VOL_MAX", "float", G_AMD2, "Объём накопления ≤", "Объём в зоне накопления относительно нормы (меньше = тише).", 0.5, 3, 0.1),
    P("AMD_SWEEP_MIN_PCT", "float", G_AMD2, "Мин. снос %", "Мин. глубина сноса ликвидности (манипуляция).", 0.01, 2, 0.05),
    P("AMD_SWEEP_WICK_MIN", "float", G_AMD2, "Мин. тень сноса", "Мин. доля тени свечи при сносе (0-1).", 0.1, 0.9, 0.05),
    P("AMD_SWEEP_VOL_MIN", "float", G_AMD2, "Мин. объём сноса ×", "Объём свечи сноса ≥ нормы ×N.", 1, 5, 0.1),
    P("AMD_CONFIRM_VOL_MIN", "float", G_AMD2, "Объём подтв. ×", "Объём подтверждающей свечи ≥ нормы ×N.", 0.5, 4, 0.1),
    P("AMD_CONFIRM_BODY_MIN", "float", G_AMD2, "Тело подтв. свечи", "Мин. доля тела подтверждающей свечи (0-1).", 0.1, 0.9, 0.05),
    P("AMD_MIN_RR2", "float", G_AMD2, "Мин. RR до TP2", "Минимальное соотношение риск/прибыль до TP2.", 0.5, 4, 0.1),

    # ---------------- Pump/Dump: пороги ----------------
    P("USE_PUMP_DETECTOR", "bool", G_PD, "Детектор вкл/выкл", "Включить / выключить весь pump/dump детектор."),
    P("PUMP_MOVE_5M_PCT", "float", G_PD, "Движение 5м %", "Порог движения цены за 5 минут.", 0.5, 20, 0.5),
    P("PUMP_MOVE_15M_PCT", "float", G_PD, "Движение 15м %", "Порог движения цены за 15 минут.", 0.5, 30, 0.5),
    P("PUMP_VOL_X", "float", G_PD, "Объём ×", "Во сколько раз объём должен вырасти относительно нормы.", 1, 20, 0.5),
    P("PUMP_MIN_SCORE", "int", G_PD, "Мин. скор", "Минимальный скор pump/dump сигнала (0-100).", 30, 100, 2),
    P("PUMP_STRICT", "bool", G_PD, "Строгий режим", "Только чёткое движение (рекомендуется)."),
    P("PUMP_MIN_TURNOVER_USDT", "float", G_PD, "Мин. оборот 24ч", "Мин. суточный оборот монеты для pump/dump, USDT.", 0, 1e10, 100000),
    P("PUMP_MAX_TURNOVER_USDT", "float", G_PD, "Макс. оборот 24ч", "Макс. суточный оборот монеты для pump/dump, USDT.", 0, 1e11, 50000000),
    P("PUMP_SCAN_INTERVAL_SECONDS", "int", G_PD, "Скан pump (сек)", "Как часто сканировать pump/dump.", 30, 600, 10),
    P("PUMP_COOLDOWN_SECONDS", "int", G_PD, "Cooldown (сек)", "Пауза на одну монету и сторону после сигнала.", 0, 86400, 300),
    P("PUMP_MAX_ALERTS_PER_HOUR", "int", G_PD, "Макс. сигналов/час", "Защита от спама при обвале рынка.", 1, 60, 1),
    P("PUMP_MAX_ALERTS_PER_SCAN", "int", G_PD, "Макс. за скан", "Макс. сигналов за один скан.", 1, 20, 1),
    P("PUMP_MAX_CANDIDATES", "int", G_PD, "Кандидатов за скан", "Сколько монет проверять по 1m-свечам за скан.", 5, 100, 5),
    P("PUMP_EXPIRE_CANDLES", "int", G_PD, "Срок сигнала (5м св.)", "24 = 2 часа.", 3, 288, 3),
    P("PUMP_MAX_EXT_PCT", "float", G_PD, "Макс. ход за 30м %", "Если уже ушло больше — «поздно», сигнал пропускается.", 3, 60, 1),
    P("PUMP_MAX_RISK_PCT", "float", G_PD, "Макс. риск %", "Если SL дальше этого % — пропуск.", 0.5, 20, 0.5),
    P("PUMP_MIN_WINDOW_TURNOVER_USDT", "float", G_PD, "Мин. оборот за 5м", "Мин. оборот за последние 5 мин, USDT.", 0, 1e8, 10000),
    P("PUMP_BREAKOUT_HOURS", "int", G_PD, "Пробой диапазона (ч)", "Цена должна пробить диапазон за N часов.", 1, 48, 1),

    # ---------------- Pump/Dump: SL / TP / пауза ----------------
    P("PUMP_SL_ATR", "float", G_PDX, "SL + ×ATR", "Расширение SL на долю 1m ATR (защита от стоп-хантинга).", 0, 5, 0.25),
    P("PUMP_MAX_COST_R", "float", G_PDX, "Макс. издержки R", "Если комиссия+проскальзывание больше этого R — сигнала нет.", 0.02, 0.5, 0.02),
    P("PUMP_TP3_ENABLED", "bool", G_PDX, "TP3 вкл/выкл", "Третий TP для сильных импульсов (40/30/30)."),
    P("PUMP_TP3_RR", "float", G_PDX, "TP3 (R)", "TP3 = столько R от входа.", 1.5, 10, 0.5),
    P("PUMP_TP3_MIN_SCORE", "int", G_PDX, "TP3: мин. скор", "TP3 только если скор не ниже.", 50, 100, 2),
    P("PUMP_TP3_VOL_X", "float", G_PDX, "TP3: объём ×", "TP3 только если объём ≥ нормы ×N.", 1, 20, 0.5),
    P("PUMP_SL_COOLDOWN_SECONDS", "int", G_PDX, "Пауза после SL (сек)", "Не входить в монету+сторону после SL.", 0, 86400, 600),
    P("PUMP_STALE_CANDLES", "int", G_PDX, "Ранний выход (св.)", "0 = выкл. 12 = через 1 час без движения закрыть сделку.", 0, 120, 3),
    P("PUMP_STALE_MIN_MFE_R", "float", G_PDX, "Ранний выход: мин. R", "Если за этот срок цена не прошла столько R — ранний выход.", 0.1, 2, 0.1),
    P("PUMP_PAUSE_AFTER_SL", "int", G_PDX, "Пауза после N SL", "0 = выкл. После N SL подряд — пауза всех pump сигналов.", 0, 10, 1),
    P("PUMP_PAUSE_SECONDS", "int", G_PDX, "Длина паузы (сек)", "Сколько длится общая пауза.", 300, 43200, 600),
    P("PUMP_USE_CTX", "bool", G_PDF, "Taker + L/S", "Перед сигналом проверять реальные тейкер-объёмы и Long/Short аккаунтов (2 запроса)."),
    P("PUMP_USE_LIQ", "bool", G_PDF, "Ликвидации", "Учитывать поток ликвидаций (Binance WS) в скоре."),
    P("PUMP_TAKER_REJECT", "float", G_PDF, "Тейкеры: отказ ≤", "Строгий режим: если доля тейкеров за движение ≤ этого — сигнал отклоняется.", 0.2, 0.5, 0.02),
    P("PUMP_LIQ_MIN_USD", "float", G_PDF, "Ликвидации: мин. $", "Минимальная сумма ликвидаций за окно, чтобы влиять на скор (USD).", 1000, 1e7, 5000),
    P("PUMP_PRE", "bool", G_PD, "Предупр. «накопление»", "Предупреждение: OI растёт, цена тихая (возможен импульс). Не сигнал входа."),
    P("PUMP_PRE_STANDALONE", "bool", G_PD, "Накопление отдельно", "Выкл: «накопление» не шлётся отдельным сообщением, а добавляется строкой в сигнал по этой же монете. Вкл: отдельные предупреждения (только с понятным уклоном)."),
    P("PUMP_PRE_OI_PCT", "float", G_PD, "Накопление: OI ≥ %", "Рост OI за ~15 мин, при котором шлём предупреждение.", 1, 20, 0.5),
    P("PUMP_PRE_PRICE_PCT", "float", G_PD, "Накопление: цена ≤ %", "Максимальное движение цены за 15 мин (±%), чтобы считать её «тихой».", 0.2, 5, 0.2),
    P("AMD_USE_CTX", "bool", G_AMD2, "AMD: OI/funding/L-S", "Корректировать скор AMD-сигнала по OI, funding, L/S и тейкерам (±10 макс.)."),
    P("PUMP_TRAIL", "bool", G_PDX, "Подсказки SL/TP", "Следить за силой импульса и присылать, когда двигать SL/TP."),
    P("PUMP_TRAIL_MIN_R", "float", G_PDX, "Подсказки: мин. R", "Подсказки только когда сделка в плюсе не меньше этого R.", 0.1, 3, 0.1),
    P("PUMP_TRAIL_MAX_MSGS", "int", G_PDX, "Подсказок на сигнал", "Максимум подсказок по одному сигналу.", 1, 20, 1),
    P("PUMP_TRAIL_MIN_GAP_SEC", "int", G_PDX, "Пауза между подсказками", "Минимум секунд между подсказками по одному сигналу.", 300, 7200, 300),

    # ---------------- Pump/Dump: фильтры ----------------
    P("PUMP_TREND_FILTER", "bool", G_PDF, "Фильтр тренда 1ч", "Нет сигналов против 1h EMA/линии тренда."),
    P("PUMP_REQUIRE_TREND_DATA", "bool", G_PDF, "Нужны данные 1ч", "Новые монеты без 1h истории — без сигнала."),
    P("PUMP_ALLOW_REVERSAL", "bool", G_PDF, "Разрешить развороты", "Вкл: можно против 1h тренда при пробое линии."),
    P("PUMP_LINE_BUFFER", "float", G_PDF, "Буфер линии тренда", "0.01 = 1% буфер пробоя линии.", 0, 0.1, 0.005),
    P("PUMP_MIN_PULLBACK", "float", G_PDF, "Мин. откат", "Доля отката в импульсе (0 = выкл). Не входить на вертикальной вершине.", 0, 0.9, 0.05),
    P("PUMP_BTC_PENALTY", "int", G_PDF, "Штраф за BTC", "Сколько баллов вычесть за сигнал против режима BTC.", 0, 50, 5),
    P("PUMP_USE_BTC_BETA", "bool", G_PDF, "BTC β/residual", "Вычитать влияние BTC из движения монеты."),
    P("PUMP_CORR_HIGH", "float", G_PDF, "Corr высокая", "Выше — BTC-фильтр полностью.", 0.2, 1, 0.05),
    P("PUMP_CORR_LOW", "float", G_PDF, "Corr низкая", "Ниже — BTC-фильтр выключается для монеты.", 0, 0.8, 0.05),
    P("PUMP_RESID_MIN_RATIO", "float", G_PDF, "Мин. доля residual", "Доля порога после вычета BTC (0 = выкл).", 0, 1.5, 0.05),
    P("PUMP_BTC_FLASH_PCT", "float", G_PDF, "BTC flash %", "BTC против за 5м на столько % — блок (0 = выкл).", 0, 5, 0.1),
    P("PUMP_MAX_SPREAD_PCT", "float", G_PDF, "Макс. спред %", "Спред bid/ask шире — отказ (0 = выкл).", 0, 3, 0.05),
    P("PUMP_MIN_ATR_MULT", "float", G_PDF, "Мин. ×ATR", "Движение ≥ N × 1m ATR (0 = выкл).", 0, 20, 0.5),
    P("PUMP_MIN_PRESSURE", "float", G_PDF, "Мин. давление", "Давление покупок/продаж −1..+1 (строгий режим).", -1, 1, 0.05),
    P("PUMP_MAX_WICK_FRAC", "float", G_PDF, "Макс. тень", "Встречная тень свечи больше доли — отказ (0 = выкл).", 0, 1, 0.05),
    P("PUMP_FUNDING_EXTREME", "float", G_PDF, "Экстрем. funding %", "Выше — минус к скору (0.10 = 0.10%).", 0, 1, 0.01),
    P("PUMP_USE_ORDERBOOK", "bool", G_PDF, "Стакан", "Проверять баланс стакана перед сигналом."),
    P("PUMP_OB_GOOD", "float", G_PDF, "Стакан: хорошо ≥", "Доля bid/ask в сторону движения → +5 баллов.", 0.5, 0.9, 0.01),
    P("PUMP_OB_BAD", "float", G_PDF, "Стакан: плохо ≤", "Доля ниже этого → −5 баллов.", 0.1, 0.5, 0.01),

    # ---------------- Прочее ----------------
    P("PUMP_SEND_CHART", "bool", G_MISC, "График в сигнале", "Прикреплять картинку-график к pump/dump сигналу."),
    P("REPLY_TO_SIGNAL", "bool", G_MISC, "Ответ на сигнал", "TP/SL/изменения приходят reply на исходный сигнал."),
    P("SCAN_WORKERS", "int", G_MISC, "Потоков AMD-скана", "Сколько запросов к Bybit одновременно при AMD-скане (больше = быстрее; 6 безопасно, не выше 10).", 1, 10, 1),
    P("PUMP_WORKERS", "int", G_MISC, "Потоков pump-скана", "Сколько монет pump-детектор проверяет параллельно.", 1, 8, 1),
    P("USE_LIQ_STREAM", "bool", G_MISC, "Поток ликвидаций", "Подключение к потоку ликвидаций Binance (вступает в силу после перезапуска).", restart=True),
    P("PIN_ACTIVE_SIGNALS", "bool", G_MISC, "Закреп сигналов", "Закреплять открытый сигнал (нужны права pin)."),
    P("FEE_PCT", "float", G_MISC, "Комиссия % / сторона", "Taker-комиссия за одну сторону для расчёта R.", 0, 1, 0.005),
    P("SLIPPAGE_PCT", "float", G_MISC, "Проскальзывание %", "Проскальзывание за одну сторону.", 0, 2, 0.01),
    P("STATS_TZ_OFFSET", "int", G_MISC, "Часовой пояс (UTC+)", "Смещение для /pd_detail (5 = Ташкент).", -12, 14, 1),
]

BY_KEY: Dict[str, P] = {p.key: p for p in REGISTRY}
INDEX: Dict[str, int] = {p.key: i for i, p in enumerate(REGISTRY)}

# config kaliti -> amd_volume.CFG kaliti (15m), shuningdek swing profillari (SW=True)
_CFG_MAP: Dict[str, Tuple[str, bool]] = {
    "ALERT_THRESHOLD": ("min_score", False),
    "ALERT_COOLDOWN_SECONDS": ("cooldown_sec", False),
    "MAX_RISK_PCT": ("max_risk_pct", False),
    "REQUIRE_STRUCTURE": ("require_structure", True),
    "MIN_24H_TURNOVER_USDT": ("min_turnover", True),
    "MAX_24H_TURNOVER_USDT": ("max_turnover", True),
    "MAX_CANDIDATES_PER_SCAN": ("max_symbols", True),
    "MAX_CHASE_R": ("max_chase_r", True),
    "EXPIRE_CANDLES": ("expire_candles", False),
    "FEE_PCT": ("fee_pct", True),
    "SLIPPAGE_PCT": ("slip_pct", True),
    "AMD_MAX_RANGE_PCT": ("max_range_pct", False),
    "AMD_ACC_VOL_MAX": ("acc_vol_max", False),
    "AMD_SWEEP_MIN_PCT": ("sweep_min_pct", False),
    "AMD_SWEEP_WICK_MIN": ("sweep_wick_min", False),
    "AMD_SWEEP_VOL_MIN": ("sweep_vol_min", False),
    "AMD_CONFIRM_VOL_MIN": ("confirm_vol_min", False),
    "AMD_CONFIRM_BODY_MIN": ("confirm_body_min", False),
    "AMD_MIN_RR2": ("min_rr2", False),
}

# Ishlayotgan job'larni qayta rejalashtirish kerak bo'lgan parametrlar: kalit -> (job nomi, min interval)
_JOBS = {
    "SCAN_INTERVAL_SECONDS": ("background_scan", 30),
    "PUMP_SCAN_INTERVAL_SECONDS": ("pump_scan", 30),
}

# (past, yuqori) juftliklar: past < yuqori bo'lishi shart
_PAIRS = [
    ("MIN_24H_TURNOVER_USDT", "MAX_24H_TURNOVER_USDT"),
    ("PUMP_MIN_TURNOVER_USDT", "PUMP_MAX_TURNOVER_USDT"),
    ("PUMP_CORR_LOW", "PUMP_CORR_HIGH"),
    ("PUMP_OB_BAD", "PUMP_OB_GOOD"),
]

_DEFAULTS: Dict[str, object] = {}
_overrides: Dict[str, object] = {}
_ready = False
_warned_sqlite = [False]


# ---------------------------------------------------------------- qiymatlar
def _modules():
    from signals import amd_volume as A
    from signals import amd_swing as S
    return A, S


def _capture_defaults():
    """Standart qiymatlar: override qo'llashdan OLDIN kod/env'dan olingan qiymat."""
    A, S = _modules()
    for p in REGISTRY:
        if p.key in _DEFAULTS:
            continue
        if hasattr(C, p.key):
            _DEFAULTS[p.key] = getattr(C, p.key)
        elif p.key == "SWING_ALERT_THRESHOLD":
            _DEFAULTS[p.key] = S.MIN_SCORE
        elif p.key in _CFG_MAP:
            _DEFAULTS[p.key] = A.CFG[_CFG_MAP[p.key][0]]
        else:
            logger.warning("Parametr topilmadi: %s", p.key)


def default(key: str):
    return _DEFAULTS.get(key)


def get(key: str):
    if key in _overrides:
        return _overrides[key]
    if hasattr(C, key):
        return getattr(C, key)
    return _DEFAULTS.get(key)


def is_overridden(key: str) -> bool:
    return key in _overrides


def overridden_count() -> int:
    return len(_overrides)


def _push(key: str, val):
    """Qiymatni jonli tizimga qo'llash."""
    setattr(C, key, val)
    A, S = _modules()
    if key in _CFG_MAP:
        cfg_key, also_swing = _CFG_MAP[key]
        A.CFG[cfg_key] = val
        if also_swing:
            for prof in S.PROFILES.values():
                prof[cfg_key] = val
    if key == "SWING_ALERT_THRESHOLD":
        S.MIN_SCORE = int(val)
        for prof in S.PROFILES.values():
            prof["min_score"] = int(val)


def fmt(p: P, v) -> str:
    if p.kind == "bool":
        return "вкл" if v else "выкл"
    if p.kind == "int":
        return f"{int(v):,}".replace(",", " ")
    return f"{float(v):g}" if abs(float(v)) < 1e6 else f"{int(float(v)):,}".replace(",", " ")


# ---------------------------------------------------------------- parsing
_TRUE = {"1", "true", "on", "yes", "y", "ha", "da", "да", "вкл", "включить", "on."}
_FALSE = {"0", "false", "off", "no", "n", "yoq", "yo'q", "yoq.", "net", "нет", "выкл", "выключить"}


def parse(p: P, raw: str):
    """(qiymat, xato). Xato bo'lsa qiymat None."""
    s = str(raw).strip().lower().replace(" ", "").replace("_", "")
    if p.kind == "bool":
        if s in _TRUE:
            return True, None
        if s in _FALSE:
            return False, None
        return None, "Ожидается: вкл / выкл (или 1 / 0)."
    s = s.replace(",", ".")
    mult = 1.0
    if s and s[-1] in "kmb" and "e" not in s:
        mult = {"k": 1e3, "m": 1e6, "b": 1e9}[s[-1]]
        s = s[:-1]
    try:
        x = float(s) * mult
    except ValueError:
        return None, "Нужно число (можно 500k, 2m)."
    if x != x or x in (float("inf"), float("-inf")):
        return None, "Некорректное число."
    if x < p.lo or x > p.hi:
        return None, f"Допустимо: {p.lo:g} … {p.hi:g}."
    if p.kind == "int":
        if abs(x - round(x)) > 1e-9:
            return None, "Нужно целое число."
        return int(round(x)), None
    return float(x), None


def _check_pairs(key: str, val) -> Optional[str]:
    for lo_k, hi_k in _PAIRS:
        if key == lo_k and float(val) > float(get(hi_k)):
            return f"{lo_k} не может быть больше {hi_k} ({fmt(BY_KEY[hi_k], get(hi_k))})."
        if key == hi_k and float(val) < float(get(lo_k)):
            return f"{hi_k} не может быть меньше {lo_k} ({fmt(BY_KEY[lo_k], get(lo_k))})."
    return None


# ---------------------------------------------------------------- baza
def _ensure_table():
    with db.tx() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS runtime_settings ("
            "param TEXT PRIMARY KEY, val TEXT NOT NULL, updated_ts BIGINT NOT NULL)"
        )


def _save(key: str, val) -> bool:
    try:
        sval = ("1" if val else "0") if isinstance(val, bool) else repr(val)
        with db.tx() as conn:
            cur = conn.execute("UPDATE runtime_settings SET val=?, updated_ts=? WHERE param=?",
                               (sval, int(time.time()), key))
            if (cur.rowcount or 0) <= 0:
                conn.execute("INSERT INTO runtime_settings(param, val, updated_ts) VALUES(?,?,?)",
                             (key, sval, int(time.time())))
        return True
    except Exception as e:
        logger.error("Sozlamani saqlab bo'lmadi (%s): %s", key, e)
        return False


def _delete(key: str) -> bool:
    try:
        with db.tx() as conn:
            conn.execute("DELETE FROM runtime_settings WHERE param=?", (key,))
        return True
    except Exception as e:
        logger.error("Sozlamani o'chirib bo'lmadi (%s): %s", key, e)
        return False


def init():
    """init_db() dan KEYIN, job'lar rejalashtirilishidan OLDIN chaqiriladi."""
    global _ready
    _capture_defaults()
    try:
        _ensure_table()
        with db.tx() as conn:
            rows = conn.execute("SELECT param, val FROM runtime_settings").fetchall()
    except Exception as e:
        logger.error("runtime_settings o'qib bo'lmadi: %s", e)
        rows = []
    n = 0
    for key, sval in rows:
        p = BY_KEY.get(key)
        if p is None:
            continue
        val, err = parse(p, sval)
        if err:
            logger.warning("Saqlangan qiymat yaroqsiz, o'tkazildi: %s=%r (%s)", key, sval, err)
            continue
        _overrides[key] = val
        _push(key, val)
        n += 1
    _ready = True
    if n:
        logger.info("Telegram'dan o'zgartirilgan %d ta parametr qo'llandi", n)


# ---------------------------------------------------------------- o'zgartirish
def _reschedule(app, key: str, interval: int):
    name, minimum = _JOBS[key]
    jq = getattr(app, "job_queue", None)
    if jq is None:
        return
    interval = max(minimum, int(interval))
    for job in jq.get_jobs_by_name(name):
        cb = job.callback
        job.schedule_removal()
        first = interval - (time.time() % interval) + 15
        jq.run_repeating(cb, interval=interval, first=first, name=name)


def set_value(key: str, raw, app=None) -> Tuple[bool, str]:
    """(ok, xabar). Qiymatni tekshiradi, qo'llaydi va saqlaydi."""
    p = BY_KEY.get(key)
    if p is None:
        return False, f"Нет такого параметра: {key}"
    val, err = parse(p, raw)
    if err:
        return False, err
    perr = _check_pairs(key, val)
    if perr:
        return False, perr
    old = get(key)
    _overrides[key] = val
    _push(key, val)
    if val == _DEFAULTS.get(key):
        # standartga teng — override saqlamaymiz
        _overrides.pop(key, None)
        saved = _delete(key)
    else:
        saved = _save(key, val)
    if key in _JOBS and app is not None:
        try:
            _reschedule(app, key, val)
        except Exception as e:
            logger.error("Job qayta rejalashtirilmadi (%s): %s", key, e)
    logger.info("Parametr o'zgardi: %s %r -> %r", key, old, val)
    msg = f"✅ {p.label}: {fmt(p, old)} → {fmt(p, val)}"
    if not saved:
        msg += "\n⚠️ В базу сохранить не удалось — действует до перезапуска."
    elif db.BACKEND != "postgres" and not _warned_sqlite[0]:
        _warned_sqlite[0] = True   # faqat bir marta eslatamiz
        msg += "\nℹ️ База SQLite: после redeploy на Render настройки сбросятся. Для постоянства подключите DATABASE_URL (PostgreSQL)."
    return True, msg


def reset(key: str, app=None) -> Tuple[bool, str]:
    p = BY_KEY.get(key)
    if p is None:
        return False, f"Нет такого параметра: {key}"
    d = _DEFAULTS.get(key)
    old = get(key)
    _overrides.pop(key, None)
    _push(key, d)
    _delete(key)
    if key in _JOBS and app is not None:
        try:
            _reschedule(app, key, d)
        except Exception as e:
            logger.error("Job qayta rejalashtirilmadi (%s): %s", key, e)
    return True, f"♻️ {p.label}: {fmt(p, old)} → {fmt(p, d)} (по умолчанию)"


def reset_all(app=None) -> int:
    keys = list(_overrides.keys())
    for k in keys:
        reset(k, app)
    return len(keys)


def nudge(key: str, direction: int, app=None) -> Tuple[bool, str]:
    p = BY_KEY[key]
    cur = get(key)
    new = float(cur) + direction * p.step
    new = min(max(new, p.lo), p.hi)
    if p.kind == "int":
        new = int(round(new))
    else:
        new = round(new, 6)
    if new == cur:
        return False, "Достигнут предел диапазона."
    return set_value(key, new, app)


# ---------------------------------------------------------------- Telegram UI
def _is_admin(update) -> bool:
    user = update.effective_user
    return user is not None and user.id in C.ADMIN_CHAT_IDS


def _home():
    from telegram import InlineKeyboardButton as B, InlineKeyboardMarkup as M
    rows = []
    for gi, g in enumerate(GROUPS):
        n = sum(1 for p in REGISTRY if p.group == g)
        ch = sum(1 for p in REGISTRY if p.group == g and p.key in _overrides)
        rows.append([B(f"{g} ({n}{f', изм. {ch}' if ch else ''})", callback_data=f"rs:g:{gi}")])
    if _overrides:
        rows.append([B(f"♻️ Сбросить всё ({len(_overrides)})", callback_data="rs:ra")])
    text = (
        "⚙️ Параметры бота\n\n"
        "Выберите раздел. Изменения применяются сразу, без перезапуска и без Render.\n"
        f"Изменено вручную: {len(_overrides)}\n\n"
        "Быстро: /set ИМЯ ЗНАЧЕНИЕ (например /set PUMP_MIN_SCORE 75)"
    )
    return text, M(rows)


def _group(gi: int):
    from telegram import InlineKeyboardButton as B, InlineKeyboardMarkup as M
    g = GROUPS[gi]
    items = [(i, p) for i, p in enumerate(REGISTRY) if p.group == g]
    rows, line = [], []
    for i, p in items:
        mark = "✎ " if p.key in _overrides else ""
        line.append(B(f"{mark}{p.label}: {fmt(p, get(p.key))}", callback_data=f"rs:p:{i}"))
        if len(line) == 2:
            rows.append(line)
            line = []
    if line:
        rows.append(line)
    rows.append([B("‹ Назад", callback_data="rs:h")])
    return f"{g}\n\nНажмите на параметр, чтобы изменить. ✎ = изменён вручную.", M(rows)


def _param(i: int, note: str = ""):
    from telegram import InlineKeyboardButton as B, InlineKeyboardMarkup as M
    p = REGISTRY[i]
    gi = GROUPS.index(p.group)
    cur, dflt = get(p.key), _DEFAULTS.get(p.key)
    lines = [f"{p.label}", p.key, "",
             f"Сейчас: {fmt(p, cur)}" + (" ✎" if p.key in _overrides else ""),
             f"По умолчанию: {fmt(p, dflt)}"]
    if p.kind != "bool":
        lines.append(f"Диапазон: {p.lo:g} … {p.hi:g} (шаг {p.step:g})")
    lines += ["", p.desc]
    if p.restart:
        lines.append("⚠️ Вступит в силу после перезапуска.")
    if note:
        lines += ["", note]
    rows = []
    if p.kind == "bool":
        rows.append([B("🔴 Выключить" if cur else "🟢 Включить", callback_data=f"rs:t:{i}")])
    else:
        rows.append([B(f"➖ {p.step:g}", callback_data=f"rs:d:{i}"),
                     B(f"➕ {p.step:g}", callback_data=f"rs:u:{i}")])
        rows.append([B("✏️ Ввести значение", callback_data=f"rs:e:{i}")])
    rows.append([B("♻️ По умолчанию", callback_data=f"rs:r:{i}"),
                 B("‹ Назад", callback_data=f"rs:g:{gi}")])
    return "\n".join(lines), M(rows)


async def _show(q, text, markup):
    try:
        await q.edit_message_text(text, reply_markup=markup)
    except Exception as e:  # "message is not modified" va h.k.
        if "not modified" not in str(e).lower():
            logger.warning("edit_message_text: %s", e)


async def cmd_params(update, context):
    if not _is_admin(update):
        return
    context.user_data.pop("rs_wait", None)
    text, markup = _home()
    await update.message.reply_text(text, reply_markup=markup)


async def cmd_set(update, context):
    if not _is_admin(update):
        return
    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text(
            "Использование: /set ИМЯ ЗНАЧЕНИЕ\n"
            "Примеры:\n/set PUMP_MIN_SCORE 75\n/set PUMP_STRICT off\n/set MIN_24H_TURNOVER_USDT 300k\n\n"
            "Список параметров и кнопки: /params"
        )
        return
    key = args[0].upper()
    ok, msg = set_value(key, " ".join(args[1:]), context.application)
    await update.message.reply_text(msg)


async def cmd_reset_param(update, context):
    if not _is_admin(update):
        return
    args = context.args or []
    if not args:
        await update.message.reply_text("Использование: /reset_param ИМЯ  или  /reset_param all")
        return
    if args[0].lower() == "all":
        n = reset_all(context.application)
        await update.message.reply_text(f"♻️ Сброшено параметров: {n}")
        return
    ok, msg = reset(args[0].upper(), context.application)
    await update.message.reply_text(msg)


async def on_callback(update, context):
    q = update.callback_query
    if q is None:
        return
    if not _is_admin(update):
        await q.answer("Нет доступа", show_alert=True)
        return
    parts = (q.data or "").split(":")
    act = parts[1] if len(parts) > 1 else "h"
    app = context.application
    note = ""
    try:
        if act == "h":
            context.user_data.pop("rs_wait", None)
            await q.answer()
            return await _show(q, *_home())
        if act == "g":
            context.user_data.pop("rs_wait", None)
            await q.answer()
            return await _show(q, *_group(int(parts[2])))
        if act == "ra":
            from telegram import InlineKeyboardButton as B, InlineKeyboardMarkup as M
            await q.answer()
            return await _show(q, f"Сбросить ВСЕ ручные настройки ({len(_overrides)}) к значениям по умолчанию?",
                               M([[B("✅ Да, сбросить", callback_data="rs:ra2"), B("Отмена", callback_data="rs:h")]]))
        if act == "ra2":
            n = reset_all(app)
            await q.answer(f"Сброшено: {n}")
            return await _show(q, *_home())

        i = int(parts[2])
        p = REGISTRY[i]
        if act == "p":
            await q.answer()
        elif act in ("u", "d"):
            ok, note = nudge(p.key, 1 if act == "u" else -1, app)
            await q.answer(note.splitlines()[0][:190] if note else "")
            if ok:
                note = "✅ Сохранено"
            else:
                note = ""
        elif act == "t":
            ok, msg = set_value(p.key, "off" if get(p.key) else "on", app)
            await q.answer("Готово" if ok else msg[:190])
            note = "✅ Сохранено" if ok else msg
            if ok and "SQLite" in msg:
                note = msg.split("\n", 1)[1]
        elif act == "r":
            ok, msg = reset(p.key, app)
            await q.answer("Сброшено")
            note = "♻️ Возвращено значение по умолчанию"
        elif act == "e":
            context.user_data["rs_wait"] = (p.key, time.time())
            await q.answer()
            await q.message.reply_text(
                f"✏️ {p.label} ({p.key})\nСейчас: {fmt(p, get(p.key))}\n"
                + ("Отправьте: вкл или выкл." if p.kind == "bool"
                   else f"Отправьте число ({p.lo:g} … {p.hi:g}). Можно 500k, 2m.")
                + "\nДля отмены отправьте: x"
            )
            return
        await _show(q, *_param(i, note))
    except Exception as e:
        logger.error("settings callback xatosi: %s", e)
        try:
            await q.answer("Ошибка", show_alert=False)
        except Exception:
            pass


async def handle_text(update, context) -> bool:
    """bot.py handle_menu_text boshida chaqiriladi. Matn qiymat sifatida iste'mol qilingan bo'lsa True."""
    wait = context.user_data.get("rs_wait")
    if not wait or not _is_admin(update):
        return False
    key, ts = wait
    if time.time() - ts > 180:
        context.user_data.pop("rs_wait", None)
        return False
    text = (update.message.text or "").strip()
    if text.lower() in ("x", "х", "cancel", "отмена", "bekor"):
        context.user_data.pop("rs_wait", None)
        await update.message.reply_text("Отменено.")
        return True
    ok, msg = set_value(key, text, context.application)
    if ok:
        context.user_data.pop("rs_wait", None)
        await update.message.reply_text(msg)
        pt, markup = _param(INDEX[key])
        await update.message.reply_text(pt, reply_markup=markup)
    else:
        await update.message.reply_text(f"❌ {msg}\nПопробуйте ещё раз или отправьте x для отмены.")
    return True


def register(app):
    from telegram.ext import CommandHandler, CallbackQueryHandler
    app.add_handler(CommandHandler("params", cmd_params))
    app.add_handler(CommandHandler("set", cmd_set))
    app.add_handler(CommandHandler("reset_param", cmd_reset_param))
    app.add_handler(CallbackQueryHandler(on_callback, pattern=r"^rs:"))
