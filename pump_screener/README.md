# Pump/Dump Screener — UltimateForexSignalBot.py ga ulash

**Muhim**: bu modul `python-telegram-bot` (PTB) kutubxonasi uchun yozilgan —
sizning botingiz aynan shu kutubxonada ekan (`Application`, `CommandHandler`, `job_queue`).

## 1. Kutubxona

`requirements.txt` ga (agar `aiosqlite` yo'q bo'lsa) qo'shing:

```
aiosqlite>=0.19
```

`aiohttp` va `python-telegram-bot` allaqachon bor (botingiz ishlatyapti).

## 2. Fayl tuzilishi (allaqachon to'g'ri joylashtirilgan)

```
Nozik/
├── UltimateForexSignalBot.py
├── pump_screener/
│   ├── __init__.py
│   ├── bybit_client.py
│   ├── config.py
│   ├── detector.py
│   ├── db.py
│   └── handlers.py
```

## 3. UltimateForexSignalBot.py ga qo'shish — aniq qayerga

### a) Import (faylning boshiga, boshqa importlar bilan birga)

```python
from pump_screener.handlers import (
    cmd_pump, cmd_pump_on, cmd_pump_off, cmd_pump_stats,
    pump_watcher_job, outcome_evaluator_job, pump_db_init,
)
import pump_screener.config as pump_config
```

### b) `commands` ro'yxatiga qo'shish (BotCommand qatorlari orasiga)

Sizning ekraningizdagi shu joyga:

```python
commands = [
    BotCommand("start",     "🏠 Botni ishga tushirish"),
    ...
    BotCommand("stats",     "📊 Botning haqiqiy w..."),
    BotCommand("pump",      "🚀 Pump/Dump screener (Bybit fyuchers)"),
    BotCommand("pump_on",   "🔔 Avtomatik pump alertlarni yoqish"),
    BotCommand("pump_off",  "🔕 Avtomatik pump alertlarni o'chirish"),
    BotCommand("pump_stats","📈 Pump screener aniqlik statistikasi"),
]
```

### c) `main()` funksiyasi ichida — handler ro'yxatiga qo'shish

Sizda shunday qism bor:

```python
for cmd, fn in [("start", cmd_start), ("status", cmd_status),
                 ("signal", cmd_signal), ("news", cmd_news),
                 ("sentiment", cmd_sentiment), ("sr", cmd_sr),
                 ("stats", cmd_stats)]:
    app.add_handler(CommandHandler(cmd, fn))
```

Shu ro'yxatga 4 ta yangi juftlikni qo'shing:

```python
for cmd, fn in [("start", cmd_start), ("status", cmd_status),
                 ("signal", cmd_signal), ("news", cmd_news),
                 ("sentiment", cmd_sentiment), ("sr", cmd_sr),
                 ("stats", cmd_stats),
                 ("pump", cmd_pump), ("pump_on", cmd_pump_on),
                 ("pump_off", cmd_pump_off), ("pump_stats", cmd_pump_stats)]:
    app.add_handler(CommandHandler(cmd, fn))
```

### d) Fon vazifalarini job_queue ga qo'shish

Sizda shu qatorlar bor:

```python
app.job_queue.run_repeating(check_and_send, interval=...)
app.job_queue.run_repeating(self_ping, interval=600...)
```

Ularning ostiga qo'shing:

```python
app.job_queue.run_repeating(pump_watcher_job, interval=pump_config.SCAN_INTERVAL_SECONDS, first=15)
app.job_queue.run_repeating(outcome_evaluator_job, interval=120, first=30)
```

### e) Baza (pump.db) ni ishga tushirishdan oldin tayyorlash

`app = Application.builder().token(BOT_TOKEN).build()` qatorini shunga o'zgartiring
(bitta `.post_init(...)` qo'shiladi, xolos):

```python
app = Application.builder().token(BOT_TOKEN).post_init(pump_db_init).build()
```

Agar sizda `post_init` allaqachon boshqa funksiya uchun ishlatilgan bo'lsa, skrinshot
yuboring — ikkalasini birlashtirib beraman.

## 4. Natijada nima o'zgaradi

`UltimateForexSignalBot.py` da atigi **5 joyga qo'shimcha qator** kiritiladi —
mavjud forex-signal logikangizga (`check_and_send`, `cmd_signal` va h.k.) hech narsa tegmaydi.

## 5. Buyruqlar

- `/pump` — bir martalik skaner, top 15 signal
- `/pump_on` / `/pump_off` — avtomatik alert obunasi
- `/pump_stats` — real aniqlik statistikasi (7 kunlik va umumiy)

## 6. Deploy va tekshirish

1. Barcha o'zgarishlarni commit qiling
2. Render avtomatik deploy qiladi — **Logs** bo'limini kuzating
3. Xatolik chiqsa (`ModuleNotFoundError: telegram` yoki boshqa), log matnini yuboring
4. Ishga tushgach: Telegram'da botga `/pump` yuboring — 10-20 soniyada javob kelishi kerak
   (300+ juftlik skanerlangani uchun bir oz vaqt oladi)

## Eslatma

- Barcha sozlamalar `pump_screener/config.py` da — threshold'larni o'zgartirish uchun
  shu faylni tahrirlang, `UltimateForexSignalBot.py` ga tegishli emas
- `/pump_stats` uchun kamida 2-3 kun ma'lumot to'planishi kerak
