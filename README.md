# Nozik Bot v4 (AMD)

Bybit USDT-perpetual bozoridagi **kichik tokenlarni** AMD strategiyasi
(Accumulation → Manipulation → Distribution) + MSS/FVG + Bybit/Binance hajm bo'yicha
skanerlab, Telegram orqali aniq signal (Kirish / SL / TP1 / TP2) yuboruvchi bot.

## Strategiya

1. **Accumulation** — tor diapazon, hajm o'rtachadan past.
2. **Manipulation** — narx diapazon chegarasidan fitil bilan chiqib, qaytib kiradi (sweep), hajm keskin oshadi.
3. **Distribution** — qarama-qarshi tomonga kuchli sham diapazon o'rtasidan o'tadi, hajm tasdiqlaydi → signal.
4. **Structure (v4)** — MSS (sweepdan keyingi tuzilma chegarasi buzildi) va FVG (imbalance):
   har biri +6 ball; ikkalasi ham yo'q bo'lsa −6. `REQUIRE_STRUCTURE=1` bo'lsa ikkalasi yo'q signal umuman yuborilmaydi.

Ball (0-100): sweep/tasdiq hajmi, MSS/FVG, Binance hajmi, trend filtri, RR va diapazon sifati.
Ball `ALERT_THRESHOLD` dan past bo'lsa, signal yuborilmaydi.

## Uch bosqichli tizim (BITTA yadro: `signals/amd_volume.py`)

| Signal taymfrem | Trend filtri | Profil | Muddat |
|---|---|---|---|
| 15m | 1h | `amd_volume.CFG` | ~12 soat |
| 1h | 4h | `amd_swing.PROFILES["1h"]` | ~2 kun |
| 4h | 1d | `amd_swing.PROFILES["4h"]` | ~7 kun |

`1d` ham bor (`SWING_TIMEFRAMES=1h,4h,1d`).

## Buyruqlar

| Buyruq | Vazifasi |
|---|---|
| `/scan`, `/swing` | Bozorni hozir tekshirish (15m / 1h+4h) |
| `/check SYMBOL`, `/swing_check SYMBOL 1h\|4h` | Bitta coin holati + grafik |
| `/backtest SYMBOL`, `/swing_backtest SYMBOL 1h\|4h` | Bitta token tarixiy sinovi |
| `/backtest_top`, `/swing_backtest_top 1h\|4h` | **Ko'p token bo'yicha jamlangan sinov (ishonchliroq)** |
| `/pump_stats`, `/swing_stats` | Jonli signal statistikasi (R hisobida, xarajatlardan keyin) |
| `/report` | 24 soat / 7 kunlik hisobot (barcha taymfreymlar) |
| `/settings` | Joriy sozlamalar |

## Render sozlamalari

- Start Command: `python bot.py`, `PYTHON_VERSION` = `3.11.9`
- Majburiy: `TELEGRAM_BOT_TOKEN`, `ADMIN_CHAT_IDS`
- **Tavsiya: `DATABASE_URL`** — doimiy PostgreSQL (Neon / Supabase bepul tarifi). Busiz statistika
  va cooldown har redeploy'da o'chadi.
- Region: Bybit AQSh hududidan 403 beradi — Singapore yoki Frankfurt tanlang (403 logda ko'rinadi).
- Ixtiyoriy: `ALERT_THRESHOLD`, `MIN_24H_TURNOVER_USDT`, `MAX_24H_TURNOVER_USDT`,
  `MAX_CANDIDATES_PER_SCAN`, `MAX_RISK_PCT`, `USE_BTC_FILTER`, `EXCLUDE_SYMBOLS`,
  `FEE_PCT` (0.055), `SLIPPAGE_PCT` (0.07), `MAX_CHASE_R` (0.5), `REQUIRE_STRUCTURE`,
  `BACKTEST_BARS` (3000), `BACKTEST_TOP_N` (12), `SWING_TIMEFRAMES`, `SWING_ALERT_THRESHOLD`,
  `SWING_SCAN_INTERVAL_SECONDS` (1800), `SCAN_INTERVAL_SECONDS` (300)

## Struktura

- `bot.py` — Telegram interfeys va background joblar
- `config.py` — sozlamalar (Render env orqali)
- `signals/amd_volume.py` — **yagona strategiya yadrosi**: analyze, scan, backtest, ma'lumot yuklash
- `signals/amd_swing.py` — 1h/4h/1d profillari va buyruqlari
- `engine/sim.py` — SL/TP/xarajat qoidalari (evaluator va backtest uchun BIR XIL)
- `engine/evaluator.py` — signal natijasi, statistika, cooldown (DB)
- `engine/db.py` — PostgreSQL / SQLite qatlami
- `engine/tg.py` — xabar matnlari, rasm + matn yuborish
- `engine/chart.py` — sham grafigi
- `engine/volatility.py` — BTC bozor rejimi filtri
- `keepalive.py` — Render bepul tarifda uxlamasligi uchun

## Diqqat

- Hech bir strategiya foyda kafolatlamaydi. Avval `/backtest_top` va kichik risk bilan sinang.
- v4 da MSS/FVG ball taqsimotini o'zgartirdi: `ALERT_THRESHOLD` ni `/backtest_top` natijasiga qarab qayta sozlang.
- Backtest 15m uchun ~31 kun (`BACKTEST_BARS`). Bu qisqa davr — turli bozor rejimlarini qamrab olmaydi.

## Другие пользователи (как добавить)

1. Человек открывает бота в Telegram, нажимает **/start** и отправляет **/myid** — бот пришлёт его Telegram ID.
2. Render → ваш сервис → **Environment** → переменная `ADMIN_CHAT_IDS` — ID через запятую: `123456789,987654321`
3. **Save Changes** — Render перезапустит бота.
4. Для канала/группы: добавьте бота администратором и впишите ID канала (`-100...`) в тот же список.
