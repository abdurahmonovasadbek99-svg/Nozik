import os

# --- Telegram ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
ADMIN_CHAT_IDS = [
    int(x) for x in os.environ.get("ADMIN_CHAT_IDS", "").split(",") if x.strip()
]

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
    "volume_oi": 30,
    "whale": 25,
    "ict_smc": 30,
    "sentiment": 15,
}

# --- Xabar yuborish uchun minimal umumiy score (0-100) ---
ALERT_THRESHOLD = int(os.environ.get("ALERT_THRESHOLD", "65"))

# --- Skanerlash intervali (soniyada) ---
SCAN_INTERVAL_SECONDS = int(os.environ.get("SCAN_INTERVAL_SECONDS", "300"))

# --- Ma'lumotlar bazasi fayli (signal tarixi/statistika uchun) ---
DB_PATH = os.environ.get("DB_PATH", "nozik.db")

# --- Health check server porti (Render uchun) ---
PORT = int(os.environ.get("PORT", "10000"))
