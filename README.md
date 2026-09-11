# Nozik Bot v2

Bybit USDT-perpetual bozoridagi barcha juftliklarni (katta va kichik
tokenlar) doimiy skanerlab, hajm, OI, whale oqimi, ICT/SMC va sentiment
modullarining confluence'i asosida Telegram orqali signal yuboruvchi bot.

## Imkoniyatlar

- Butun bozor skanerlash (500+ juftlik, kichik tokenlar ham)
- 5 ta signal moduli: volume+OI, whale tracking, ICT/SMC, sentiment, hajm+BOS combo
- Signal aniqlik statistikasi (SQLite)
- Kunlik va haftalik hisobotlar
- Adminlar uchun kirish chegarasi

## Ishga tushirish (Render)

1. Ushbu reponi Render'ga ulang — `render.yaml` avtomatik sozlaydi
2. Render Environment Variables'ga qo'shing:
   - `TELEGRAM_BOT_TOKEN` (majburiy) — @BotFather'dan
   - `ADMIN_CHAT_IDS` (majburiy) — Telegram ID'laringiz, vergul bilan
   - Ixtiyoriy: `WHALE_ALERT_API_KEY`, `LUNARCRUSH_API_KEY`, `BYBIT_API_KEY` va h.k.
3. Deploy tugmasini bosing

## Buyruqlar

| Buyruq | Vazifasi |
|---|---|
| `/scan` | Butun bozorni hozir tekshirish |
| `/check SYMBOL` | Bitta coinni tekshirish |
| `/pump_stats` | Umumiy signal aniqligi |
| `/report` | 24 soat / 7 kunlik hisobot |
| `/watchlist` | Kuzatiladigan coinlar |

## Struktura

- `bot.py` — Telegram interfeys va background joblar
- `engine/aggregator.py` — 5 moduldan confluence score
- `engine/evaluator.py` — signal statistikasi (SQLite)
- `signals/` — signal modullari + umumiy kline yuklovchi
- `keepalive.py` — Render bepul tarifda uxlamasligi uchun

## Diqqat

- `nozik.db` Render bepul tarifda vaqtinchalik — har redeploy'da
  statistika tozalanadi. Doimiy saqlash uchun Render PostgreSQL ishlating.
