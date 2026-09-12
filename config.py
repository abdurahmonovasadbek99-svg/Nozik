"""
Nozik Bot - Configuration
Barcha maxfiy kalitlar Render.com Environment Variables orqali beriladi.
Hech qachon kalitlarni kodga yozmang!
"""
import os


# TUZATISH: noto'g'ri formatdagi ID'lar butun botni ishga tushirishni
# to'xtatardi. Endi xato beruvchi qiymatlar o'tkazib yuboriladi.
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

# --- Exchange APIs (Volume / Open Interest) ---
BYBIT_API_KEY = os.environ.get("BYBIT_API_KEY", "")
BYBIT_API_SECRET = os.environ.get("BYBIT_API_SECRET", "")
BINANCE_API_KEY = os.environ.get("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.environ.get("BINANCE_API_SECRET", "")

# --- On-chain / Whale tracking ---
WHALE_ALERT_API_KEY = os.environ.get("WHALE_ALERT_API_KEY", "")
ETHERSCAN_API_KEY = os.environ.get("ETHERSCAN_API_KEY", "")

# --- Sentiment ---
LUNARCRUSH_API_KEY = os.environ.get("LUNARCRUSH_API_KEY", "")

# --- Kuzatiladigan coinlar ---
WATCHLIST = os.environ.get(
    "WATCHLIST", "BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT"
).split(",")

# --- Signal og'irliklari (confluence score uchun, jami 100) ---
SIGNAL_WEIGHTS = {
    "volume_oi": 25,
    "whale": 20,
    "ict_smc": 25,
    "sentiment": 10,
    "volume_bos_combo": 20,
}

# --- Xabar yuborish uchun minimal umumiy score (0-100) ---
ALERT_THRESHOLD = int(os.environ.get("ALERT_THRESHOLD", "75"))

# --- Hajm+BOS combo o'zi juda kuchli bo'lsa (tasdiqlangan breakout),
# boshqa modullarni kutmasdan darhol signal yuborish uchun chegara.
# TUZATISH: 80 -> 92 ga oshirildi - bitta modulning yolg'iz signal
# berish holatlari kamaytirildi (bu "confluence" tamoyilini buzardi) ---
STRONG_COMBO_THRESHOLD = int(os.environ.get("STRONG_COMBO_THRESHOLD", "92"))

# --- Skanerlash intervali (soniyada) ---
SCAN_INTERVAL_SECONDS = int(os.environ.get("SCAN_INTERVAL_SECONDS", "300"))

# --- Ma'lumotlar bazasi fayli (signal tarixi/statistika uchun) ---
# DIQQAT: Render bepul tarifda disk vaqtinchalik — har redeploy'da
# nozik.db yo'qoladi. Doimiy statistika kerak bo'lsa Render
# PostgreSQL'ga o'ting.
DB_PATH = os.environ.get("DB_PATH", "nozik.db")

# --- Universe / Prescreen (kichik tokenlarni ham skanerlash uchun) ---
QUOTE_ASSET = os.environ.get("QUOTE_ASSET", "USDT")
# TUZATISH: 200,000 -> 1,500,000 ga oshirildi. Juda kam savdo qilinadigan
# coinlarda spread katta va narx tasodifiy sakraydi - signal "kuchli"
# ko'ringani bilan aslida shovqin bo'ladi.
MIN_24H_TURNOVER_USDT = float(os.environ.get("MIN_24H_TURNOVER_USDT", "1500000"))
MAX_CANDIDATES_PER_SCAN = int(os.environ.get("MAX_CANDIDATES_PER_SCAN", "40"))
EXCLUDE_SYMBOLS = [
    s.strip() for s in os.environ.get("EXCLUDE_SYMBOLS", "").split(",") if s.strip()
]

# --- Signal aniqligi: kamida nechta modul bir xil yo'nalishda rozi bo'lishi kerak ---
# TUZATISH: 2 -> 3 ga oshirildi (5 tadan 3tasi rozi bo'lishi shart)
MIN_SIGNAL_AGREEMENT = int(os.environ.get("MIN_SIGNAL_AGREEMENT", "3"))

# --- Signalni qachon baholash (necha soniyadan keyin natijani tekshirish) ---
EVAL_AFTER_SECONDS = int(os.environ.get("EVAL_AFTER_SECONDS", "3600"))
EVAL_CHECK_INTERVAL_SECONDS = int(os.environ.get("EVAL_CHECK_INTERVAL_SECONDS", "900"))

# --- Davriy hisobotlar (UTC bo'yicha soat, 0-23) ---
DAILY_REPORT_HOUR_UTC = int(os.environ.get("DAILY_REPORT_HOUR_UTC", "6"))
WEEKLY_REPORT_WEEKDAY = int(os.environ.get("WEEKLY_REPORT_WEEKDAY", "0"))  # 0=Dushanba

# --- Health check server porti (Render uchun) ---
PORT = int(os.environ.get("PORT", "10000"))

# --- O'z-o'ziga ping (Render bepul tarifda 15 daqiqa harakatsizlikdan keyin
# uxlab qolmasligi uchun). RENDER_EXTERNAL_URL ni Render "web service"
# uchun avtomatik o'zi beradi (https://xxx.onrender.com) — qo'lda kiritish
# shart emas.
SELF_PING_URL = os.environ.get("RENDER_EXTERNAL_URL", "")
SELF_PING_INTERVAL_SECONDS = int(os.environ.get("SELF_PING_INTERVAL_SECONDS", "600"))
