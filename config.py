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
MIN_24H_TURNOVER_USDT = _f("MIN_24H_TURNOVER_USDT", "500000")      # v6.4: AMD uchun 3M -> 500K
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

# --- v6.4: pump/dump sifati (BTC beta/residual, spread, ATR, bosim, funding, orderbook) ---
PUMP_USE_BTC_BETA = os.environ.get("PUMP_USE_BTC_BETA", "1") == "1"      # har coin uchun BTC korrelyatsiya/beta
PUMP_CORR_HIGH = _f("PUMP_CORR_HIGH", "0.6")          # shundan yuqori: BTC filtri to'liq
PUMP_CORR_LOW = _f("PUMP_CORR_LOW", "0.3")            # shundan past: coin BTC'ga bog'liq emas — BTC filtri o'chadi
PUMP_RESID_MIN_RATIO = _f("PUMP_RESID_MIN_RATIO", "0.6")   # BTC ta'siri ayirilgach harakat chegaraning shuncha ulushidan kam bo'lsa — rad (0 = o'chiq)
PUMP_BTC_FLASH_PCT = _f("PUMP_BTC_FLASH_PCT", "0.7")  # BTC 5m da shuncha % qarshi yursa va corr yuqori bo'lsa — blok (0 = o'chiq)
PUMP_MAX_SPREAD_PCT = _f("PUMP_MAX_SPREAD_PCT", "0.30")    # bid/ask spread shundan keng bo'lsa — rad (0 = o'chiq)
PUMP_MIN_ATR_MULT = _f("PUMP_MIN_ATR_MULT", "3")      # harakat bazaviy 1m ATR dan kamida shuncha marta katta (0 = o'chiq)
PUMP_MIN_PRESSURE = _f("PUMP_MIN_PRESSURE", "0.10")   # sotib olish/sotish bosimi (-1..+1), strict rejimda minimal (taker/CVD o'rniga sham bo'yicha baho)
PUMP_MAX_WICK_FRAC = _f("PUMP_MAX_WICK_FRAC", "0.60") # oxirgi 2 shamda qarshi soya shamning shuncha ulushidan katta bo'lsa — rad (0 = o'chiq)
PUMP_FUNDING_EXTREME = _f("PUMP_FUNDING_EXTREME", "0.10")  # funding (%) shundan oshsa (harakat tomonida) — ball ayiriladi
PUMP_USE_ORDERBOOK = os.environ.get("PUMP_USE_ORDERBOOK", "1") == "1"    # yakuniy signal oldidan orderbook tengligi (1 ta qo'shimcha so'rov)
PUMP_OB_GOOD = _f("PUMP_OB_GOOD", "0.58")             # harakat tomonidagi bid/ask ulushi >= shu: +5 ball
PUMP_OB_BAD = _f("PUMP_OB_BAD", "0.35")               # <= shu: -5 ball

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

# --- Telegram Mini App (jonli grafik tugmasi signal rasmi ostida) ---
# Manzil HTTPS bo'lishi shart. Render'da RENDER_EXTERNAL_URL avtomatik; boshqa joyda WEBAPP_URL bering.
WEBAPP_URL = (os.environ.get("WEBAPP_URL") or os.environ.get("RENDER_EXTERNAL_URL", "")).rstrip("/")
USE_WEBAPP = os.environ.get("USE_WEBAPP", "1") == "1" and WEBAPP_URL.startswith("https://")


# --- v6.5: signalga bog'lab yuborish, MFE/MAE, erta chiqish, SL-pauza ---
REPLY_TO_SIGNAL = os.environ.get("REPLY_TO_SIGNAL", "1") == "1"        # TP/SL/o'zgarish xabarlari asl signalga reply bo'lib boradi
PIN_ACTIVE_SIGNALS = os.environ.get("PIN_ACTIVE_SIGNALS", "0") == "1"  # ochiq signalni "zakrepit" qilish, yopilganda olib tashlash
PUMP_STALE_CANDLES = _i("PUMP_STALE_CANDLES", "0")                    # 5m shamlar; 0 = o'chiq. Masalan 12 = 1 soat
PUMP_STALE_MIN_MFE_R = _f("PUMP_STALE_MIN_MFE_R", "0.5")              # shu muddatda narx kamida shuncha R ga bormagan bo'lsa - erta chiqish
PUMP_PAUSE_AFTER_SL = _i("PUMP_PAUSE_AFTER_SL", "3")                  # ketma-ket shuncha SL bo'lsa pump signallari pauza (0 = o'chiq)
PUMP_PAUSE_SECONDS = _i("PUMP_PAUSE_SECONDS", "3600")
STATS_TZ_OFFSET = _i("STATS_TZ_OFFSET", "5")                          # soat bo'yicha tahlil uchun (5 = Toshkent)
