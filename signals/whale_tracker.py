"""
Whale tracking signal moduli - BEPUL versiya.

TUZATISH: Whale Alert (pullik, faqat yirik on-chain coinlarni kuzatadi)
o'rniga Bybit'ning o'z ochiq "recent trades" endpointidan foydalanadi.
API kalit shart emas. Mantiq: so'nggi savdolar orasidan katta hajmli
(MIN_TRADE_USD dan yuqori) yakka savdolarni "whale" deb hisoblaydi va
ularning buy/sell tomonini solishtiradi.

CHEKLOV: bu chinakam on-chain hamyon harakati emas, balki birjadagi
katta yakka savdolarning proksisi. Lekin bepul va istalgan Bybit
symbol uchun ishlaydi (TMX, EVA kabi kichik altcoinlar ham).

TUZATISH: endi "whale" chegarasi FAQAT qat'iy $50k emas - shu
symbolning o'zi so'nggi 1000 savdosidagi O'RTACHA savdo hajmiga
NISBATAN ham baholanadi. Sabab: /v5/market/recent-trade "so'nggi N ta
savdo"ni qaytaradi, vaqt oralig'ini emas. BTCUSDT kabi juda likvid
coinlarda 1000 savdo bir necha soniyani qamrab olishi mumkin, kichik
altcoinda esa bir necha soatni. Shu sababli qat'iy dollar chegarasi
katta coin uchun juda oson, kichik/o'rtacha coin uchun deyarli
imkonsiz bo'lib qolardi. Endi chegara: symbolning o'z tipik savdo
hajmidan sezilarli darajada katta bo'lgan savdolar "whale" hisoblanadi
(nisbiy), MIN_TRADE_USD esa faqat mutlaq quyi chegara sifatida qoladi.
"""
import requests

BYBIT_BASE = "https://api.bybit.com"

# Minimal savdo qiymati (USD) - mutlaq quyi chegara, bundan kichik
# savdolar hech qachon "whale" bo'la olmaydi (juda mayda coinlar uchun ham)
MIN_TRADE_USD = 10_000

# Bitta savdo "whale" deb hisoblanishi uchun, shu symbolning o'rtacha
# savdo hajmidan necha barobar katta bo'lishi kerak
WHALE_RELATIVE_MULTIPLIER = 8


def analyze(symbol: str, candles: list = None, limit: int = 1000) -> dict:
    try:
        r = requests.get(
            f"{BYBIT_BASE}/v5/market/recent-trade",
            params={"category": "linear", "symbol": symbol, "limit": min(limit, 1000)},
            timeout=10,
        )
        r.raise_for_status()
        trades = r.json().get("result", {}).get("list", [])
    except Exception as e:
        return {"score": 0, "direction": "neutral", "details": {"error": str(e)}}

    trade_values = []
    for t in trades:
        try:
            price = float(t["price"])
            size = float(t["size"])
        except (KeyError, ValueError):
            continue
        trade_values.append((price * size, t.get("side")))

    if not trade_values:
        return {"score": 0, "direction": "neutral", "details": {"whale_trades": 0}}

    # TUZATISH: chegara endi shu symbolning o'z tipik savdo hajmiga
    # nisbatan hisoblanadi (qarang: yuqoridagi modul docstring'i)
    avg_trade_usd = sum(v for v, _ in trade_values) / len(trade_values)
    whale_threshold = max(MIN_TRADE_USD, avg_trade_usd * WHALE_RELATIVE_MULTIPLIER)

    buy_usd = 0.0
    sell_usd = 0.0
    whale_count = 0

    for usd_value, side in trade_values:
        if usd_value < whale_threshold:
            continue
        whale_count += 1
        if side == "Buy":
            buy_usd += usd_value
        else:
            sell_usd += usd_value

    total = buy_usd + sell_usd
    if total == 0:
        return {"score": 0, "direction": "neutral", "details": {"whale_trades": 0}}

    imbalance_ratio = abs(buy_usd - sell_usd) / total

    # TUZATISH: avval bu yerda mutlaq $ chegaralar (5M/2M/500k) ishlatilardi
    # - bu BTCUSDT kabi coinlarni deyarli har doim "80 ball" bilan
    # mukofotlab, kichik altcoinlarni deyarli hech qachon 40 balldan
    # yuqoriga chiqarmasdi (chunki ularning umumiy savdo hajmi tabiiy
    # ravishda kichik). Endi whale hajmi HAR BIR COIN o'zining shu
    # oynadagi umumiy namuna hajmiga NISBATAN baholanadi - shunda katta
    # va kichik coinlar taqqoslanadigan bo'ladi.
    total_sampled_volume = sum(v for v, _ in trade_values)
    whale_share = total / total_sampled_volume if total_sampled_volume > 0 else 0

    if whale_share >= 0.5:
        base_score = 80
    elif whale_share >= 0.3:
        base_score = 60
    elif whale_share >= 0.15:
        base_score = 40
    else:
        base_score = 20

    score = min(int(base_score * (0.5 + imbalance_ratio)), 100)
    direction = "long" if buy_usd > sell_usd else "short" if sell_usd > buy_usd else "neutral"

    return {
        "score": score,
        "direction": direction,
        "details": {
            "buy_usd": round(buy_usd, 2),
            "sell_usd": round(sell_usd, 2),
            "whale_trades": whale_count,
            "whale_share": round(whale_share, 3),
        },
    }
