# v6.3: Telegram Mini App — jonli grafik (signal rasmi ostida tugma)

- Har signal (pump va AMD) rasmi ostida "📊 Живой график" tugmasi chiqadi (Telegram Mini App, WebApp).
- Sahifa: 1m shamlar har 3 soniyada yangilanadi; SL / Вход / TP1 / TP2 / TP3 chiziqlari, signal vaqti, joriy narx,
  jonli R va %, holat ("TP1 взят · SL → вход" va h.k. — sim.py bilan bir xil qoidalar), 1м/5м/15м/1ч tugmalari, "Все цели".
  Grafik ustida barmoqni yuqori/pastga surish — shamlar sonini o'zgartiradi.
- Bybit ma'lumoti SERVER orqali olinadi (Render) — telefonda Bybit bloklangan bo'lsa ham ishlaydi.
- Xavfsizlik: /api/* faqat Telegram initData (HMAC) to'g'ri va foydalanuvchi ADMIN_CHAT_IDS ichida bo'lsa ishlaydi.
- Yangi modul: webapp/ (server.py, page.html). bot.py dagi health-server shu serverga almashtirildi (bir port, ko'p oqimli).
- Sozlash: Render'da RENDER_EXTERNAL_URL avtomatik (HTTPS). Boshqa joyda `WEBAPP_URL=https://...`. O'chirish: `USE_WEBAPP=0`.
  Faqat sinash uchun `WEBAPP_OPEN=1` (tekshiruvsiz API) — ishlatgandan keyin o'chiring.
- Tugma ishlamasa (masalan guruh chat) — xabar tugmasiz yuboriladi, signal yo'qolmaydi.

# v6.2 (davomi): TP3 kuchli impulsda + jonli bosqich xabarlari

1. **TP3 faqat kuchli impulsda** (`PUMP_TP3_ENABLED=1`): ball >= `PUMP_TP3_MIN_SCORE`(80), hajm >= x`PUMP_TP3_VOL_X`(5),
   6 soatlik diapazon sindi, BTC va 1h trendga qarshi emas, OI tushmayapti, harakat >= 1.2x chegara.
   TP3 = kirishdan `PUMP_TP3_RR`(3) R. Pozitsiya 40/30/30: TP1 da SL -> kirish, TP2 da SL -> TP1, TP3 da qolgan 30%.
   Oddiy signallar eski qoida bo'yicha (TP1 50% + BE, TP2).
2. Yangi natija statuslari: `tp3`, `lock` (TP1+TP2 olingan, qoldiq TP1 da yopildi). `/pd_stats`, `/pd_backtest`, matn va grafik yangilandi.
3. **Jonli bosqich xabarlari**: TP1/TP2 olinganda bot "qancha yoping, SL ni qayerga suring" xabarini yuboradi (5 daqiqalik sham yopilgandan keyin).
4. DB: `signals.tp3` ustuni avtomatik qo'shiladi (eski baza buzilmaydi). `tp1_hit` ustuni endi bosqich (0..3) saqlaydi.
5. Sim: `sim.step3`, `sim.expire_gross3` (backtest va jonli statistika bir xil qoida).

Test: sintetik (migratsiya, evaluator, step3, TP3 chiqishi, grafik, backtest yo'li). Haqiqiy bozorda TP3 ga yetish ulushi noma'lum.

# v6.1 → v6.2: pump/dump — SL urilishini kamaytirish (sifat filtrlari)

Sabab (20 ta savdo: SL 8, TP1+BE 8, TP2 3, muddat 1; xarajatgacha +0.57R, keyin -0.97R):
- kirish impuls cho'qqisida (vertikal "blow-off"), keyin odatiy 40-60% qaytish SL ni uradi;
- 1h trend / trend chizig'i tekshirilmasdi (faqat 6 soatlik diapazon + BTC uchun -10 ball);
- kichik riskli signallarda komissiya+slippage ~0.08R/savdo (20 savdoda -1.54R) foydani yeb qo'ydi.

1. **1h trend filtri** (`PUMP_TREND_FILTER=1`): EMA20/EMA50 + oxirgi 2 swing bo'yicha trend chizig'i
   (LONG: pasayuvchi qarshilik, SHORT: o'suvchi qo'llab-quvvatlash). Chiziq buzilmagan yoki chiziq yo'q va EMA trendga qarshi — rad.
   Trend bo'yicha +8, chiziq buzilgan +4; EMA'ga qarshi, lekin chiziq buzilgan — -5 (burilish urinishi).
2. **Vertikal cho'qqiga kirmaslik** (`PUMP_MIN_PULLBACK=0.10`): impuls yo'lida kamida 10% orqaga qaytish bo'lmasa rad.
   Eski "narx ekstremumda +5 ball" olib tashlandi; endi 5-30% qaytish va davom etish +5.
3. **SL kengaytirildi**: max(impuls/2, oxirgi 10 sham strukturasi) + `PUMP_SL_ATR`(0.5) × 1m ATR (stop-hunt shovqini).
4. **Xarajat darvozasi** (`PUMP_MAX_COST_R=0.12`): komissiya+slippage shu R dan oshsa signal yo'q (risk >= ~2.1%).
5. **SL-cooldown** (`PUMP_SL_COOLDOWN_SECONDS=7200`): SL urgan coin+yo'nalishga 2 soat qayta kirilmaydi.
6. BTC rejimiga qarshi jarima 10 -> 15 (`PUMP_BTC_PENALTY`). Limitlar: skanda 4 -> 2, soatiga 15 -> 8.
7. `/pd_check`, `/settings`, signal matni va `/pd_backtest` (1h tarix vaqt bo'yicha to'g'ri joylashtiriladi) yangilandi.

Test: faqat sintetik (trendga qarshi/mos, vertikal/zinapoya, LONG/SHORT, backtest yo'li). Haqiqiy Bybit ma'lumotida
SAMARASI ISBOTLANMAGAN — avval `/pd_backtest`, so'ng jonli statistikani kuzating. Eski xatti-harakat: Render env'da
`PUMP_TREND_FILTER=0 PUMP_MIN_PULLBACK=0 PUMP_SL_ATR=0 PUMP_MAX_COST_R=9 PUMP_SL_COOLDOWN_SECONDS=0`.

# v6 → v6.1: aniqroq signal + yengil grafik

1. **Qat'iy rejim** (`PUMP_STRICT=1`): davom etayotgan harakat (≥3/4 sham), OI ≥2% tushsa rad, 6 soatlik diapazon
   sinishi (5m) majburiy; sinish ballga +10. Standart `PUMP_MIN_SCORE` 60 → 70.
2. **`/pd_backtest`**: jonli bilan bir xil `evaluate()` ni ~5 kunlik 1m tarixda sinaydi (xarajatlar R da).
   Chegaralarni taxmin bilan emas, natija bilan sozlang.
3. **Grafik** (`engine/pump_chart.py`): alohida yengil renderer. Figure+Agg, 720x600, dpi 100, vlines+bar;
   sandboxda ~0.3 s, ~37 KB, birinchi ~40 grafikdan keyin xotira ~+29 MB'da to'xtaydi (oqish yo'q);
   xabar yuborilgach `gc.collect()`. Xato bo'lsa matn grafiksiz ketadi.
4. Python 3.11 moslik: f-string ichida backslash yo'q (Render 3.11.9).

Test qilinmagan: haqiqiy Bybit/Telegram, Render'dagi real xotira. Sinov sintetik ma'lumotda.

# v5 → v6: Pump/Dump detektori

Muammo: AMD faqat "akkumulyatsiya → sweep → qaytish" naqshini ko'radi, shuning uchun to'g'ri
yo'nalishda uchib ketgan pump/dump coinlar signal bermasdi.

1. **Yangi `signals/pump_detector.py`** (AMD'ga tegilmagan): tickers snapshotlari orqali narx harakati
   (5m/15m), keyin 1m shamlarda hajm sakrashi, impuls tozaligi, qaytish, kech qolganlik, OI va BTC rejimi.
2. **Aylanma chegarasi 1M USDT** (AMD'da 3M): kichik coinlar pump boshlanishidan oldin ham ko'rinadi.
3. **Bazaviy hajm "trimmed" o'rtacha**: oldingi spike shamlari baza hajmini shishirib, yangi sakrashni
   yashirmaydi.
4. **Alohida statistika**: `tf="pump"`; `/report` da AMD umumiy natijasiga kirmaydi (`get_stats_since(exclude_tf=...)`).
5. **Spamdan himoya**: cooldown (coin+yo'nalish), skanda max 4 ta, soatiga max 15 ta (bozor qulaganda).
6. Yangi buyruqlar: `/pd_scan`, `/pd_check`, `/pd_stats`; `/settings` da detektor sozlamalari.

## Test qilingan (tarmoqsiz, sintetik)
Sof/tahlil funksiyasi: toza pump, dump, shovqin, past hajm, qaytish, ortiqcha cho'zilgan, noliquid, BTC jarima;
mock tickers bilan to'liq skan (warm-up, nomzod tanlash, cooldown), DB yozish, evaluator (TP2), Telegram yuborish,
`bot.py` importi. Haqiqiy Bybit/Telegram bilan ISHLAB KO'RILMAGAN — birinchi kunlarda `/pd_check` va logni kuzating.
Bybit tickers'dagi `openInterestValue` maydoni bo'lmasa OI ballsiz ishlaydi (xatosiz).

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
