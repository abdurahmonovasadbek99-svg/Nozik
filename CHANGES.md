# v3 → v4: nima tuzatildi

## Strategiya / hisob-kitob xatolari
1. **Backtest xarajatlarsiz edi** → komissiya + slippage (R da) ayriladi; natija "xarajatgacha/keyin" ko'rsatiladi.
2. **Backtest jonli logikaga mos emas edi** (1h trend va Binance hajmi umuman hisobga olinmas, past ball chegarasi) →
   endi trend va Binance tarixiy ma'lumoti VAQT BO'YICHA to'g'ri joylashtiriladi (kelajakka qarash yo'q), to'liq ball chegarasi.
3. **Backtest tarixi 10 kun edi** → sahifalab 3000 sham (~31 kun, `BACKTEST_BARS`), + `/backtest_top` (ko'p token jamlangan, PF, nechta token plyusda).
4. **Muddat tugaganda natija 0R deb olinardi** → qolgan pozitsiya oxirgi yopilish narxida baholanadi (backtest va statistikada).
5. **MSS/FVG yo'q edi** → qo'shildi (ball + ixtiyoriy majburiy).
6. **Eskirgan kirish narxi** → signal yuborilishidan oldin joriy narx tekshiriladi; kirishdan `MAX_CHASE_R` dan ko'p ketgan yoki SL'dan o'tgan signal yuborilmaydi; xabarda "qaysi narxgacha kirish mumkin" ko'rsatiladi.

## Ma'lumot / barqarorlik
7. **Statistika va cooldown redeploy'da o'chardi** → PostgreSQL (`DATABASE_URL`), yo'q bo'lsa SQLite (WAL, timeout). Postgres ishlamasa bot to'xtamaydi.
8. **Cooldown BTC-filtr bilan o'tkazib yuborilgan signalga ham qo'yilardi** → endi faqat haqiqatan yuborilgan signaldan boshlanadi (DB'dan).
9. **Binance symbol nomi mos kelmasdi** (`SHIB1000USDT` ↔ `1000SHIBUSDT`) → Binance ro'yxatidan avtomatik moslanadi; topilmasa xabarda aniq yoziladi.
10. **Bir xil yopilgan sham 3 marta (5 daqiqalik skan) qayta tahlil qilinardi** → bitta sham — bitta skan (API yuki ~3x kam).
11. **Swing skaneri sham yopilishiga tekislanmagan edi** (30 daqiqagacha kechikish) → :00/:30 ga tekislandi.
12. **Qayta urinish yo'q edi** (429/5xx) → 2 marta qayta uriniladi; 403/451 (region) logda ko'rinadi.

## Kod sifati
13. **~250 qator takror kod** (swing = 15m nusxasi, ikki evaluator, ikki backtest) → yagona yadro. Endi tuzatish bitta joyda.
14. SL/TP qoidalari bitta joyda (`engine/sim.py`) — backtest va jonli statistika bir xil.
15. Rasm izohi 1024 belgidan oshsa signal yuborilmay qolardi → matn alohida xabar bo'lib ketadi.
16. Grafik yasash event loop'ni bloklardi va pyplot thread-safe emas edi → `Figure` + alohida thread.
17. SQLite bir vaqtda yozishda "database is locked" xavfi → WAL + 30s timeout.
18. Ishlatilmagan ATR funksiyalari va takroriy `klines.py` olib tashlandi.
19. Hisobotlar endi barcha taymfreymlarni qamraydi (avval faqat 15m).

## Test qilinmagan (tarmoq yo'q edi)
- Haqiqiy Bybit/Binance/Telegram/PostgreSQL bilan ishlash. Sintetik ma'lumot, mock va soxta psycopg2 bilan tekshirildi.

## v5 — Signal kartasi dizayni (Fxabot uslubida)
- engine/chart.py: butunlay yangi. Qora-ko'k karta: sarlavha + LONG/SHORT tugmasi, A·M·D belgilari
  (Accumulation qutisi, Manipulation sweep belgisi, Distribution), SL/ENTRY/TP1/TP2 zonalari,
  4 ta ko'rsatkich qutisi (narx, %, R), SIGNAL SIFATI (A+/A/B/C/D + progress), konfluens chiplari.
- engine/tg.py: signal matni HTML (<b>, <code>, <i>) va русский; parse_mode="HTML" qo'shildi;
  meta_of(); to_dicts() endi vaqt (ts) ham beradi.
- signals/amd_volume.py: Signal'ga sweep_i, range_i, mss, fvg, bn_ok, htf_ok, sweep_x ... maydonlari qo'shildi
  (strategiya mantig'i O'ZGARMAGAN, faqat karta uchun ma'lumot saqlanadi).
- bot.py, signals/amd_swing.py: signal yuborishda meta + parse_mode="HTML" uzatiladi.
