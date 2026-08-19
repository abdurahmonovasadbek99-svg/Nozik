# Pump/Dump Screener — Nozik botga ulash (v2, aniqlik oshirilgan)

Bybit USDT Perpetual (fyuchers) bozorini kuzatib, narx + hajm birga portlaganda
signal beradi. **v2** versiyasida oldingi variantdagi 5 ta kamchilik tuzatildi.

## Nima o'zgardi (v1 → v2)

| Muammo | Yechim |
|---|---|
| Kam likvidli coinlarda ko'p false-signal | 4 qatlamli filtr: narx+hajm → momentum konsistensiyasi → sham tanasi (wick emas) → 15m tasdig'i |
| Signal kech kelardi | O'zgarishsiz qoldi (5m asos), lekin endi filtrlar orqali sifatsiz signallar kesiladi — kam, lekin ishonchli signal |
| Trend davom etadimi bilinmasdi | Har signal 15m taymfreymda ham tekshiriladi: mos kelsa "✅ TASDIQLANGAN", kelmasa "⚠️ ERTA" deb belgilanadi. Avtomatik alertlarga faqat TASDIQLANGAN signallar boradi |
| Manipulyatsiya/wash-trade ajratilmasdi | "Impulse-candle" filtri — signal beruvchi sham tanasi/range nisbati past bo'lsa (faqat fitna, real harakat emas) signal chiqarilmaydi. Bittagina sham emas, kamida 2 ta sham bir yo'nalishda bo'lishi shart |
| Statistik tekshirilmagan edi | **Yangi**: har yuborilgan signal 20 daqiqadan keyin avtomatik tekshiriladi — narx davom etdimi, qaytdimi. `/pump_stats` buyrug'i real aniqlik % ni ko'rsatadi |

## 1. Fayllarni joylashtirish

```
nozik_bot/
├── main.py
├── pump_screener/
│   ├── __init__.py
│   ├── bybit_client.py
│   ├── config.py
│   ├── detector.py
│   ├── db.py
│   └── handlers.py
└── ...
```

## 2. Kutubxonalar

`requirements.txt` ga (agar yo'q bo'lsa):

```
aiohttp>=3.9
aiosqlite>=0.19
```

## 3. main.py ga ulash

```python
import asyncio
from pump_screener.handlers import pump_router, pump_watcher, outcome_evaluator

dp.include_router(pump_router)

async def on_startup(bot):
    ...  # mavjud kodlar
    asyncio.create_task(pump_watcher(bot))
    asyncio.create_task(outcome_evaluator())
```

## 4. Buyruqlar

- `/pump` — bir martalik skaner, top 15 signal (TASDIQLANGAN va ERTA, ikkalasi ham ko'rinadi)
- `/pump_on` / `/pump_off` — avtomatik alert obunasi (faqat TASDIQLANGAN signallar yuboriladi)
- `/pump_stats` — **real aniqlik statistikasi**: oxirgi 7 kun va barcha vaqt bo'yicha necha % signal haqiqatan davom etgani

## 5. Signal qanday tekshiriladi (4 bosqich)

1. **Narx + hajm**: oxirgi 3 shamda (15 daq) narx 5%+ o'zgargan VA hajm 20 shamlik baseline'dan 3x+ ko'p
2. **Momentum konsistensiyasi**: 3 shamdan kamida 2 tasi bir yo'nalishda bo'lishi kerak (bitta random wick emas)
3. **Impulse-candle**: eng kuchli sham tanasi/range nisbati 0.4+ bo'lishi kerak (faqat fitna emas)
4. **15m tasdig'i**: yuqori taymfreymda ham yo'nalish mos kelsa — TASDIQLANGAN, aks holda ERTA

## 6. Sozlash

`config.py` dagi asosiy parametrlar:

- `PRICE_CHANGE_THRESHOLD_PCT`, `VOLUME_RATIO_THRESHOLD` — asosiy chegaralar
- `MIN_CONSISTENT_CANDLES`, `MIN_BODY_RATIO` — shovqin filtri qattiqligi
- `OUTCOME_CHECK_MINUTES` — natija necha daqiqadan keyin tekshirilsin

**Tavsiya**: birinchi 3-5 kun `/pump_stats` ni kuzating, so'ng real natijalarga qarab
`PRICE_CHANGE_THRESHOLD_PCT` yoki `MIN_BODY_RATIO` ni moslashtiring.

## Eslatma — hali ham cheklovlar bor

- Bu hamon oddiy statistik filtr, ICT/SMC darajasidagi tahlil emas — o'zingizning
  grafik tahlilingiz o'rnini bosmaydi, faqat "qayerga qarash kerak"ni ko'rsatadi
- Order-book/likvidlik chuqurligi tekshirilmaydi (Bybit public API'da bepul yo'q)
- `/pump_stats` statistikasi faqat TASDIQLANGAN va yuborilgan signallar bo'yicha —
  yetarli ma'lumot to'planishi uchun kamida 2-3 kun kerak
