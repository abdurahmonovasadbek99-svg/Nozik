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

## Uch bosqichli tizim

| Signal taymfrem | Trend filtri | Modul | Muddat |
|---|---|---|---|
| 15m | 1h | `signals/amd_volume.py` | ~12 soat |
| 1h | 4h | `signals/amd_swing.py` | ~2 kun |
| 4h | 1d | `signals/amd_swing.py` | ~7 kun |

Uchalasi bir xil AMD strategiyasi, alohida statistika. 1h/4h modul buyruqlari:
`/swing`, `/swing_check SYMBOL 1h|4h`, `/swing_backtest SYMBOL 1h|4h`, `/swing_stats`.

Ixtiyoriy Render env: `SWING_TIMEFRAMES` (default `1h,4h`; `1d` ham qo'shsa bo'ladi),
`SWING_ALERT_THRESHOLD` (70), `SWING_SCAN_INTERVAL_SECONDS` (1800).
Parametrlar — `amd_swing.py` boshidagi `PROFILES` da.

## Другие пользователи (как добавить)

1. Человек открывает бота в Telegram, нажимает **/start** (без этого бот не сможет ему писать)
   и отправляет команду **/myid** — бот пришлёт его Telegram ID (число). Этот ID он отправляет вам.
   (Можно и через @userinfobot.)
2. Render → ваш сервис → **Environment** → переменная `ADMIN_CHAT_IDS` — перечислите все ID через запятую:
   `123456789,987654321,555666777`
3. **Save Changes** — Render сам перезапустит бота. Все ID из списка получают сигналы и могут пользоваться командами.
4. Для канала/группы: добавьте бота администратором и впишите ID канала (начинается с `-100...`) в тот же список —
   сигналы будут приходить в канал.

## Частота проверки 15m

По умолчанию бот проверяет рынок каждые **5 минут** (`SCAN_INTERVAL_SECONDS=300`), с выравниванием по часам
(:00, :05, :10 ...). Для 10 минут: Render → Environment → `SCAN_INTERVAL_SECONDS` = `600`.
Если там уже стоит `900`, измените или удалите её — переменная на Render важнее значения в коде.
