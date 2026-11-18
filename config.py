"""
Nozik Bot v4 (AMD) - Configuration
Barcha maxfiy kalitlar Render.com Environment Variables orqali beriladi.
Hech qachon kalitlarni kodga yozmang!
"""
import os


def _parse_admin_ids(raw: str) -> list:
    ids = []
    for x in raw.split(","):
        x = x.strip()
        if not x:
            continue
        try:
            ids.append(int(x))
        except ValueError:
            pass
    return ids


def _f(name: str, default: str) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return float(default)


def _i(name: str, default: str) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return int(default)


# --- Telegram ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
ADMIN_CHAT_IDS = _parse_admin_ids(os.environ.get("ADMIN_CHAT_IDS", ""))

# --- AMD strategiyasi ---
ALERT_THRESHOLD = _i("ALERT_THRESHOLD", "62")
ALERT_COOLDOWN_SECONDS = _i("ALERT_COOLDOWN_SECONDS", "7200")
MAX_RISK_PCT = _f("MAX_RISK_PCT", "5")
SCAN_INTERVAL_SECONDS = _i("SCAN_INTERVAL_SECONDS", "300")

# MSS/FVG: 1 bo'lsa kamida bittasi bo'lmagan signal umuman yuborilmaydi.
# 0 bo'lsa — faqat ballga ta'sir qiladi (+6 / +6 / yo'q bo'lsa -6).
REQUIRE_STRUCTURE = os.environ.get("REQUIRE_STRUCTURE", "0") == "1"

# --- Universe: faqat KICHIK tokenlar ---
MIN_24H_TURNOVER_USDT = _f("MIN_24H_TURNOVER_USDT", "3000000")
MAX_24H_TURNOVER_USDT = _f("MAX_24H_TURNOVER_USDT", "300000000")
MAX_CANDIDATES_PER_SCAN = _i("MAX_CANDIDATES_PER_SCAN", "400")
EXCLUDE_SYMBOLS = [
    s.strip() for s in os.environ.get("EXCLUDE_SYMBOLS", "").split(",") if s.strip()
]

# --- BTC filtri ---
USE_BTC_FILTER = os.environ.get("USE_BTC_FILTER", "1") == "1"

# --- Pump/Dump detektori (AMD'dan ALOHIDA modul: signals/pump_detector.py) ---
USE_PUMP_DETECTOR = os.environ.get("USE_PUMP_DETECTOR", "1") == "1"
PUMP_SCAN_INTERVAL_SECONDS = _i("PUMP_SCAN_INTERVAL_SECONDS", "60")
PUMP_MIN_TURNOVER_USDT = _f("PUMP_MIN_TURNOVER_USDT", "1000000")      # AMD'dan past: 1M
PUMP_MAX_TURNOVER_USDT = _f("PUMP_MAX_TURNOVER_USDT", "300000000")
PUMP_MOVE_5M_PCT = _f("PUMP_MOVE_5M_PCT", "3")        # 5 daqiqada shuncha % harakat
PUMP_MOVE_15M_PCT = _f("PUMP_MOVE_15M_PCT", "5")      # yoki 15 daqiqada shuncha %
PUMP_VOL_X = _f("PUMP_VOL_X", "3")                    # hajm oddiydan necha marta oshgan bo'lishi kerak
PUMP_MAX_EXT_PCT = _f("PUMP_MAX_EXT_PCT", "15")       # 30 daqiqada shundan ko'p ketgan bo'lsa - kech
PUMP_MAX_RISK_PCT = _f("PUMP_MAX_RISK_PCT", "5")      # taxminiy SL masofasi shundan katta bo'lsa - o'tkazib yuboriladi
PUMP_MIN_SCORE = _i("PUMP_MIN_SCORE", "70")
PUMP_COOLDOWN_SECONDS = _i("PUMP_COOLDOWN_SECONDS", "1800")   # bir coin, bir yo'nalish
PUMP_MIN_WINDOW_TURNOVER_USDT = _f("PUMP_MIN_WINDOW_TURNOVER_USDT", "30000")  # oxirgi 5 daq. oborot (noto'g'ri tezlik filtri)
PUMP_MAX_ALERTS_PER_SCAN = _i("PUMP_MAX_ALERTS_PER_SCAN", "2")
PUMP_MAX_ALERTS_PER_HOUR = _i("PUMP_MAX_ALERTS_PER_HOUR", "8")   # bozor qulaganda spamdan himoya
PUMP_MAX_CANDIDATES = _i("PUMP_MAX_CANDIDATES", "25")          # bir skanda 1m shamlari tekshiriladigan max coin
PUMP_EXPIRE_CANDLES = _i("PUMP_EXPIRE_CANDLES", "24")          # 5m shamlar: 24 = 2 soat
PUMP_STRICT = os.environ.get("PUMP_STRICT", "1") == "1"       # qat'iy rejim: faqat aniq harakat (tavsiya)
PUMP_BREAKOUT_HOURS = _i("PUMP_BREAKOUT_HOURS", "6")          # shuncha soatlik diapazon chegarasi buzilishi kerak
# --- v6.2: sifat filtrlari (SL urilish ulushini kamaytirish) ---
PUMP_TREND_FILTER = os.environ.get("PUMP_TREND_FILTER", "1") == "1"   # 1h EMA + trend chizig'iga qarshi signal yo'q
PUMP_MIN_PULLBACK = _f("PUMP_MIN_PULLBACK", "0.10")   # impulsda kamida shuncha ulush orqaga qaytish bo'lishi kerak (0 = o'chiq). Vertikal "blow-off" cho'qqiga kirmaslik
PUMP_SL_ATR = _f("PUMP_SL_ATR", "0.5")                # SL ni 1m ATR ning shuncha ulushiga kengaytirish (stop-hunt shovqini)
PUMP_MAX_COST_R = _f("PUMP_MAX_COST_R", "0.12")       # komissiya+slippage shu R dan oshsa signal yo'q (risk juda kichik)
PUMP_BTC_PENALTY = _i("PUMP_BTC_PENALTY", "15")       # BTC rejimiga qarshi signal ballidan ayriladigan
PUMP_SL_COOLDOWN_SECONDS = _i("PUMP_SL_COOLDOWN_SECONDS", "7200")  # SL urgan coin+yo'nalishga qayta kirmaslik
# --- TP3: faqat KUCHLI impulsda (3 ta TP: 40/30/30, TP1 da SL->BE, TP2 da SL->TP1) ---
PUMP_TP3_ENABLED = os.environ.get("PUMP_TP3_ENABLED", "1") == "1"
PUMP_TP3_RR = _f("PUMP_TP3_RR", "3")                  # TP3 = kirishdan shuncha R
PUMP_TP3_MIN_SCORE = _i("PUMP_TP3_MIN_SCORE", "80")   # kuchli impuls: ball
PUMP_TP3_VOL_X = _f("PUMP_TP3_VOL_X", "5")            # kuchli impuls: hajm oddiydan kamida shuncha marta
PUMP_SEND_CHART = os.environ.get("PUMP_SEND_CHART", "1") == "1"  # xabarga grafik biriktirish
PUMP_BACKTEST_BARS = _i("PUMP_BACKTEST_BARS", "7200")         # 1m shamlar: 7200 = 5 kun

# --- Haqiqiy xarajatlar (BIR TOMON uchun, %). Backtest va statistika R'dan ayriladi ---
# Bybit USDT-perp taker ~0.055%. Slippage kichik tokenlarda 0.05-0.15% bo'lishi mumkin.
FEE_PCT = _f("FEE_PCT", "0.055")
SLIPPAGE_PCT = _f("SLIPPAGE_PCT", "0.07")

# --- "Poezdga yetib olish" filtri ---
# Signal kelgan paytdagi narx kirishdan TP tomonga shuncha R dan ko'p ketgan bo'lsa,
# signal o'tkazib yuboriladi (kirish narxi eskirgan; RR buzilgan).
MAX_CHASE_R = _f("MAX_CHASE_R", "0.8")

# --- Signal natijasini kuzatish ---
EXPIRE_CANDLES = _i("EXPIRE_CANDLES", "48")          # 15m uchun: 48 = 12 soat
EVAL_CHECK_INTERVAL_SECONDS = _i("EVAL_CHECK_INTERVAL_SECONDS", "300")

# --- Backtest ---
BACKTEST_BARS = _i("BACKTEST_BARS", "3000")          # 15m uchun ~31 kun
BACKTEST_TOP_N = _i("BACKTEST_TOP_N", "12")          # /backtest_top nechta token

# --- Ma'lumotlar bazasi ---
# DATABASE_URL berilsa — PostgreSQL (doimiy, tavsiya etiladi). Aks holda SQLite fayli
# (Render bepul tarifda har redeploy'da o'chadi).
DATABASE_URL = os.environ.get("DATABASE_URL", "")
DB_PATH = os.environ.get("DB_PATH", "nozik.db")

# --- Davriy hisobotlar (UTC bo'yicha soat, 0-23) ---
DAILY_REPORT_HOUR_UTC = _i("DAILY_REPORT_HOUR_UTC", "6")
WEEKLY_REPORT_WEEKDAY = _i("WEEKLY_REPORT_WEEKDAY", "0")  # 0=Dushanba

# --- Health check server porti (Render uchun) ---
PORT = _i("PORT", "10000")

# --- O'z-o'ziga ping ---
SELF_PING_URL = os.environ.get("RENDER_EXTERNAL_URL", "")
SELF_PING_INTERVAL_SECONDS = _i("SELF_PING_INTERVAL_SECONDS", "240")
