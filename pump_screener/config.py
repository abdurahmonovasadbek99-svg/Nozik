"""Pump screener sozlamalari — bu yerdan chegaralarni o'zgartirishingiz mumkin."""

# --- Asosiy oyna (signal shu yerdan hisoblanadi) ---
KLINE_INTERVAL = "5"          # daqiqa (Bybit interval)
WINDOW_CANDLES = 3            # narx o'zgarishi shu oxirgi N shamdan hisoblanadi (5m*3 = 15 daq)

# --- Hajm bazasi (uzoqroq tarix — "normal hajm qancha" ni bilish uchun) ---
BASELINE_CANDLES = 20         # o'rtacha hajm shu oxirgi 20 shamdan (baseline, oxirgi WINDOW_CANDLES chiqarib tashlanadi)

# --- Yuqori timeframe tasdig'i (kech/soxta signallarni kamaytirish uchun) ---
CONFIRM_INTERVAL = "15"       # 15 daqiqalik shamda ham xuddi shu yo'nalish bormi tekshiriladi
CONFIRM_LOOKBACK = 3

# --- Skanerlash ---
SCAN_INTERVAL_SECONDS = 300   # bozorni necha soniyada bir marta skanerlash (5 daq)
MAX_CONCURRENT_REQUESTS = 6   # bir vaqtda nechta symbol so'ralsin (rate-limit uchun)

# --- Pump/dump mezonlari ---
PRICE_CHANGE_THRESHOLD_PCT = 5.0   # oyna ichida narx necha % o'zgarishi kerak
VOLUME_RATIO_THRESHOLD = 3.0       # oxirgi oyna hajmi baseline'dan necha marta ko'p bo'lishi kerak
MIN_TURNOVER_USDT = 500_000        # 24h aylanma shundan kam bo'lsa — chiqarib tashlanadi (shell/low-liq filtri)

# --- Shovqin filtri (yolg'on signallarni kamaytirish) ---
MIN_CONSISTENT_CANDLES = 2         # WINDOW_CANDLES ichida kamida shuncha sham bir yo'nalishda bo'lishi kerak
MIN_BODY_RATIO = 0.4               # eng kuchli shamning tanasi/range nisbati (past bo'lsa — faqat fitna/wick, real emas)

# --- Cooldown (bir xil signalni qayta-qayta yubormaslik uchun) ---
ALERT_COOLDOWN_MINUTES = 45

# --- /pump buyrug'i uchun ---
SCREENER_TOP_N = 15  # /pump bosilganda nechta natija ko'rsatilsin
