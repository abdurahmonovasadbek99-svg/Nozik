"""
Universe / Prescreen moduli.

Muammo: eski versiya faqat qo'lda yozilgan 5 ta katta coin (WATCHLIST)ni
tekshirar edi, shuning uchun kichik/alt tokenlarda boshlanayotgan
pump/dump'lar ko'rinmay qolardi.

Yechim (ikki bosqichli funnel):
  1-bosqich (arzon): Bybit'dan BITTA so'rov bilan barcha linear USDT
     juftliklarining 24 soatlik narx/hajm ma'lumotini olamiz, o'lik
     coinlarni chetlab o'tamiz va "g'ayrioddiy faollik"ka qarab saralaymiz.
  2-bosqich (qimmat): faqat eng faol N ta nomzod (MAX_CANDIDATES_PER_SCAN)
     to'liq confluence tahliliga (ict_smc, volume_oi, whale, sentiment)
     yuboriladi.

Shu tarzda 500+ juftlikning barchasi e'tiborga olinadi (kichik tokenlar
ham), lekin har 5 daqiqada faqat bir nechta og'ir so'rov ketadi.
"""
import requests

from config import (
    QUOTE_ASSET,
    MIN_24H_TURNOVER_USDT,
    MAX_CANDIDATES_PER_SCAN,
    EXCLUDE_SYMBOLS,
    WATCHLIST,
)

BYBIT_BASE = "https://api.bybit.com"


def fetch_all_tickers() -> list:
    """
    Bybit linear (USDT perpetual) bozoridagi barcha juftliklar uchun
    24 soatlik statistikani BITTA so'rovda qaytaradi.
    """
    url = f"{BYBIT_BASE}/v5/market/tickers"
    r = requests.get(url, params={"category": "linear"}, timeout=15)
    r.raise_for_status()
    return r.json()["result"]["list"]


def _activity_score(ticker: dict) -> float:
    """
    Faqat bulk ticker ma'lumoti asosida tezkor "g'ayrioddiy faollik" bahosi.
    Kichik token bo'lsa ham, narxi/diapazoni keskin siljigan bo'lsa yuqori
    ball oladi — hajm kattaligiga qarab kamsitilmaydi.
    """
    try:
        last = float(ticker.get("lastPrice", 0) or 0)
        high = float(ticker.get("highPrice24h", 0) or 0)
        low = float(ticker.get("lowPrice24h", 0) or 0)
        pct_change = abs(float(ticker.get("price24hPcnt", 0) or 0)) * 100
    except (TypeError, ValueError):
        return 0.0

    range_pct = ((high - low) / low * 100) if low > 0 else 0.0
    # Ikkalasidan kattarog'ini olamiz: ba'zan 24h yopilish narxi tinch
    # ko'rinsa-da, kun ichida keskin pump/dump bo'lib, orqaga qaytgan bo'ladi.
    return max(pct_change, range_pct)


def get_candidates(max_candidates: int = None, extra_symbols: list = None) -> list:
    """
    Skanerlash uchun nomzod symbollar ro'yxatini qaytaradi:
    - o'lik/illikvid coinlar chetlab o'tiladi (MIN_24H_TURNOVER_USDT)
    - qolganlar "g'ayrioddiy faollik" bo'yicha saralanadi
    - eng faol `max_candidates` tasi olinadi
    - WATCHLIST / extra_symbols har doim ro'yxatga qo'shiladi (mavjud bo'lsa)

    Bybit so'rovi ishlamasa (tarmoq xatosi va h.k.), WATCHLIST'ga qaytadi
    (eski xatti-harakat) — bot butunlay to'xtab qolmasligi uchun.
    """
    if max_candidates is None:
        max_candidates = MAX_CANDIDATES_PER_SCAN

    try:
        tickers = fetch_all_tickers()
    except Exception:
        return list(dict.fromkeys((extra_symbols or []) + WATCHLIST))

    scored = []
    for t in tickers:
        symbol = t.get("symbol", "")
        if not symbol.endswith(QUOTE_ASSET):
            continue
        if symbol in EXCLUDE_SYMBOLS:
            continue
        try:
            turnover = float(t.get("turnover24h", 0) or 0)
        except (TypeError, ValueError):
            turnover = 0.0
        if turnover < MIN_24H_TURNOVER_USDT:
            continue
        scored.append((symbol, _activity_score(t)))

    scored.sort(key=lambda x: x[1], reverse=True)
    top_symbols = [s for s, _ in scored[:max_candidates]]

    # Har doim asosiy watchlist + qo'lda berilgan qo'shimchalar kiritiladi
    always_include = (extra_symbols or []) + WATCHLIST
    final = list(dict.fromkeys(always_include + top_symbols))
    return final


def get_current_price(symbol: str) -> float:
    """Bitta symbol uchun joriy narxni qaytaradi (baholash/hisobot uchun)."""
    url = f"{BYBIT_BASE}/v5/market/tickers"
    r = requests.get(url, params={"category": "linear", "symbol": symbol}, timeout=10)
    r.raise_for_status()
    rows = r.json()["result"]["list"]
    if not rows:
        raise ValueError(f"{symbol} uchun narx topilmadi")
    return float(rows[0]["lastPrice"])
