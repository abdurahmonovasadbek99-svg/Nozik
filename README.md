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

## Pump/Dump detektori (v6) — AMD'dan ALOHIDA

AMD "sweep'dan keyingi qaytish"ni qidiradi, to'g'ri yo'nalishda uchib ketgan coinlarni ko'rmaydi.
`signals/pump_detector.py` aynan shularni ushlaydi:

1. Har 60 soniyada BITTA so'rov (Bybit tickers) — narx/OI snapshotlari xotirada saqlanadi.
   5 daqiqada ≥3% yoki 15 daqiqada ≥5% harakat qilgan coinlar nomzod bo'ladi.
2. Nomzodlar uchun 1m shamlar: hajm ≥ x3 (oddiydan), impuls toza, qaytish ≤40%, 30 daqiqada ≤15% ketgan,
   taxminiy risk ≤5%. Ball (0-100) ≥ 60 bo'lsa — darhol xabar.
3. Ball: harakat kuchi, hajm, OI o'sishi (+), qaytish yo'qligi, BTC trendiga qarshi (−), kech qolganlik (−).

Xabardagi SL = impuls yarmi, TP1 = 1R, TP2 = 2R (taxminiy). Natijalar `tf="pump"` bilan yoziladi va
5m shamlar bilan kuzatiladi — **AMD statistikasiga aralashmaydi** (`/report` da alohida qator).

| Buyruq | Vazifasi |
|---|---|
| `/pd_scan` | Pump/dump skanini hozir ishga tushirish |
| `/pd_check SYMBOL` | Bitta coin: nega signal bor/yo'qligi (har shart ko'rsatiladi) |
| `/pd_stats` | Detektor statistikasi (R hisobida, xarajatlardan keyin) |
| `/pd_backtest [SYMBOL]` | Detektorni tarixiy 1m ma'lumotda sinash (~5 kun). **Aniqlikni shu bilan o'lchang** |

Sozlamalar (Render env): `USE_PUMP_DETECTOR` (1), `PUMP_SCAN_INTERVAL_SECONDS` (60),
`PUMP_MIN_TURNOVER_USDT` (1000000), `PUMP_MAX_TURNOVER_USDT` (300000000), `PUMP_MOVE_5M_PCT` (3),
`PUMP_MOVE_15M_PCT` (5), `PUMP_VOL_X` (3), `PUMP_MAX_EXT_PCT` (15), `PUMP_MAX_RISK_PCT` (5),
`PUMP_MIN_SCORE` (60), `PUMP_COOLDOWN_SECONDS` (1800), `PUMP_MAX_ALERTS_PER_SCAN` (4),
`PUMP_MAX_ALERTS_PER_HOUR` (15), `PUMP_MAX_CANDIDATES` (25), `PUMP_EXPIRE_CANDLES` (24 = 2 soat),
`PUMP_MIN_WINDOW_TURNOVER_USDT` (30000).

**Qat'iy rejim (`PUMP_STRICT=1`, standart):** signal faqat shunda chiqadi, agar (a) oxirgi 4 shamdan ≥3 tasi va oxirgi
yopilgan sham harakat tomonida bo'lsa, (b) OI ≥2% tushmayotgan bo'lsa (bu yangi talab emas, pozitsiyalar yopilishi),
(c) narx oxirgi `PUMP_BREAKOUT_HOURS` (6) soatlik 5m diapazon chegarasini buzgan bo'lsa (diapazon ichidagi
mahalliy sakrash emas), (d) ball ≥ `PUMP_MIN_SCORE` (70). `/pd_check` har shartni ko'rsatadi.

**Grafik (`PUMP_SEND_CHART=1`):** 720x600 px yengil PNG (~40 KB, ~0.3 s), faqat filtrdan o'tgan alertlarga,
ketma-ket. O'chirish: `PUMP_SEND_CHART=0`.

Eslatma: bot qayta ishga tushganda narx tarixi ~5 daqiqa (15m chegara uchun ~15 daqiqa) yig'iladi.
Bu detektor impuls ogohlantirishi: AMD signalidan sifati pastroq, kech kirish xavfi bor.
Avval 1–2 hafta `/pd_stats` ni kuzating, keyin chegaralarni sozlang.

## Render sozlamalari

- Start Command: `python bot.py`, `PYTHON_VERSION` = `3.11.9`
- Majburiy: `TELEGRAM_BOT_TOKEN`, `ADMIN_CHAT_IDS`
- **Tavsiya: `DATABASE_URL`** — doimiy PostgreSQL (Neon / Supabase bepul tarifi). Busiz statistika
  va cooldown har redeploy'da o'chadi.
- Region: Bybit AQSh hududidan 403 beradi — Singapore yoki Frankfurt tanlang (403 logda ko'rinadi).
- Ixtiyoriy: `ALERT_THRESHOLD`, `MIN_24H_TURNOVER_USDT` (standart 500000), `MAX_24H_TURNOVER_USDT`,
  `MAX_CANDIDATES_PER_SCAN`, `MAX_RISK_PCT`, `USE_BTC_FILTER`, `EXCLUDE_SYMBOLS`,
  `FEE_PCT` (0.055), `SLIPPAGE_PCT` (0.07), `MAX_CHASE_R` (0.5), `REQUIRE_STRUCTURE`,
  `BACKTEST_BARS` (3000), `BACKTEST_TOP_N` (12), `SWING_TIMEFRAMES`, `SWING_ALERT_THRESHOLD`,
  `SWING_SCAN_INTERVAL_SECONDS` (1800), `SCAN_INTERVAL_SECONDS` (300)

## Struktura

- `bot.py` — Telegram interfeys va background joblar
- `config.py` — sozlamalar (Render env orqali)
- `signals/amd_volume.py` — **yagona strategiya yadrosi**: analyze, scan, backtest, ma'lumot yuklash
- `signals/amd_swing.py` — 1h/4h/1d profillari va buyruqlari
- `signals/pump_detector.py` — pump/dump detektori (AMD'dan alohida): skaner, ball, Telegram buyruqlari
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
