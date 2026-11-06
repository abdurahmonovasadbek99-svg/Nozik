"""
Nozik Bot v3 (AMD) - Configuration
Barcha maxfiy kalitlar Render.com Environment Variables orqali beriladi.
Hech qachon kalitlarni kodga yozmang!
"""
import os


# Noto'g'ri formatdagi ID'lar butun botni ishga tushirishni to'xtatmasligi uchun
# xato beruvchi qiymatlar o'tkazib yuboriladi.
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


# --- Telegram ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
ADMIN_CHAT_IDS = _parse_admin_ids(os.environ.get("ADMIN_CHAT_IDS", ""))

# --- AMD strategiyasi (signals/amd_volume.py) ---
# Signal yuborish uchun minimal ball (0-100). Kamaytirsangiz signal ko'payadi,
# lekin aniqlik pasayadi.
ALERT_THRESHOLD = int(os.environ.get("ALERT_THRESHOLD", "70"))

# Bitta coin uchun signaldan keyin qayta signal berilmaydigan vaqt (soniya)
ALERT_COOLDOWN_SECONDS = int(os.environ.get("ALERT_COOLDOWN_SECONDS", "14400"))

# Maksimal risk: kirish bilan SL orasidagi masofa (% da)
MAX_RISK_PCT = float(os.environ.get("MAX_RISK_PCT", "3.5"))

# --- Skanerlash intervali (soniyada). 900 = 15 daqiqa (shamlar bilan mos) ---
SCAN_INTERVAL_SECONDS = int(os.environ.get("SCAN_INTERVAL_SECONDS", "900"))

# --- Universe: faqat KICHIK tokenlar ---
# 24 soatlik savdo hajmi (USDT) shu oraliqda bo'lgan juftliklar skanerlanadi.
# MAX dan yuqori (katta coinlar) chiqarib tashlanadi.
MIN_24H_TURNOVER_USDT = float(os.environ.get("MIN_24H_TURNOVER_USDT", "3000000"))
MAX_24H_TURNOVER_USDT = float(os.environ.get("MAX_24H_TURNOVER_USDT", "120000000"))
MAX_CANDIDATES_PER_SCAN = int(os.environ.get("MAX_CANDIDATES_PER_SCAN", "150"))
# Qo'shimcha chiqarib tashlanadigan symbollar (BTC, ETH va boshqa yirik coinlar
# allaqachon avtomatik chiqarib tashlangan)
EXCLUDE_SYMBOLS = [
    s.strip() for s in os.environ.get("EXCLUDE_SYMBOLS", "").split(",") if s.strip()
]

# --- BTC filtri: BTC kuchli tushayotganda altcoin LONG (yoki aksincha) signali o'tkazib yuboriladi ---
USE_BTC_FILTER = os.environ.get("USE_BTC_FILTER", "1") == "1"

# --- Signal natijasini kuzatish (SL / TP1 / TP2) ---
# Signal shuncha sham (15m) ichida TP yoki SL'ga yetmasa, yopiladi. 48 = 12 soat.
EXPIRE_CANDLES = int(os.environ.get("EXPIRE_CANDLES", "48"))
EVAL_CHECK_INTERVAL_SECONDS = int(os.environ.get("EVAL_CHECK_INTERVAL_SECONDS", "300"))

# --- Ma'lumotlar bazasi fayli (signal tarixi/statistika uchun) ---
# DIQQAT: Render bepul tarifda disk vaqtinchalik — har redeploy'da
# nozik.db yo'qoladi. Doimiy statistika kerak bo'lsa Render
# PostgreSQL'ga o'ting.
DB_PATH = os.environ.get("DB_PATH", "nozik.db")

# --- Davriy hisobotlar (UTC bo'yicha soat, 0-23) ---
DAILY_REPORT_HOUR_UTC = int(os.environ.get("DAILY_REPORT_HOUR_UTC", "6"))
WEEKLY_REPORT_WEEKDAY = int(os.environ.get("WEEKLY_REPORT_WEEKDAY", "0"))  # 0=Dushanba

# --- Health check server porti (Render uchun) ---
PORT = int(os.environ.get("PORT", "10000"))

# --- O'z-o'ziga ping (Render bepul tarifda uxlab qolmasligi uchun).
# RENDER_EXTERNAL_URL ni Render o'zi avtomatik beradi. ---
SELF_PING_URL = os.environ.get("RENDER_EXTERNAL_URL", "")
SELF_PING_INTERVAL_SECONDS = int(os.environ.get("SELF_PING_INTERVAL_SECONDS", "600"))
