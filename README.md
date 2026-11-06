# Nozik Bot v3 (AMD)

Bybit USDT-perpetual bozoridagi **kichik tokenlarni** AMD strategiyasi
(Accumulation → Manipulation → Distribution) va Bybit/Binance hajm o'zgarishi
bo'yicha skanerlab, Telegram orqali aniq signal (Kirish / SL / TP1 / TP2) yuboruvchi bot.

## Strategiya

1. **Accumulation** — tor diapazon (0.8–5%), hajm o'rtachadan past.
2. **Manipulation** — narx diapazon chegarasidan fitil bilan chiqib, qaytib kiradi (sweep), hajm keskin oshadi.
3. **Distribution** — qarama-qarshi tomonga kuchli sham diapazon o'rtasidan o'tadi, hajm tasdiqlaydi → signal.

Ball (0-100): sweep/tasdiq hajmi, Binance hajmi tasdig'i, 1h trend, RR va diapazon sifati.
Ball `ALERT_THRESHOLD` dan past bo'lsa, signal yuborilmaydi.

## Buyruqlar

| Buyruq | Vazifasi |
|---|---|
| `/scan` | Bozorni hozir tekshirish |
| `/check SYMBOL` | Bitta coinning AMD holati + grafik |
| `/backtest SYMBOL` | Tarixiy sinov (50% TP1, 50% TP2) |
| `/pump_stats` | Signal statistikasi (R hisobida) |
| `/report` | 24 soat / 7 kunlik hisobot |
| `/settings` | Joriy sozlamalar |

## Render sozlamalari

- Start Command: `python bot.py`
- `PYTHON_VERSION` = `3.11.9`
- Majburiy: `TELEGRAM_BOT_TOKEN`, `ADMIN_CHAT_IDS`
- Ixtiyoriy: `ALERT_THRESHOLD`, `MIN_24H_TURNOVER_USDT`, `MAX_24H_TURNOVER_USDT`,
  `MAX_CANDIDATES_PER_SCAN`, `MAX_RISK_PCT`, `USE_BTC_FILTER`, `EXCLUDE_SYMBOLS` (qolganlari `config.py` da)
- Region: Bybit AQSh hududidan 403 beradi — Singapore yoki Frankfurt tanlang.

## Struktura

- `bot.py` — Telegram interfeys va background joblar
- `config.py` — sozlamalar (Render env orqali)
- `signals/amd_volume.py` — AMD strategiyasi, universe, backtest
- `signals/klines.py` — umumiy Bybit kline yuklovchi
- `engine/evaluator.py` — signal natijasi (SL/TP, R hisobida) — SQLite
- `engine/chart.py` — sham grafigi (diapazon, kirish, SL, TP chiziqlari bilan)
- `engine/volatility.py` — BTC bozor rejimi filtri
- `keepalive.py` — Render bepul tarifda uxlamasligi uchun

## Diqqat

- `nozik.db` Render bepul tarifda vaqtinchalik — har redeploy'da statistika tozalanadi.
- Hech bir strategiya foyda kafolatlamaydi. Avval `/backtest` va kichik risk bilan sinang.
