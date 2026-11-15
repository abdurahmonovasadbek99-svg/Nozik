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
