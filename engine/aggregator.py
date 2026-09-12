"""
Confluence Aggregator.
5 ta signal modulini chaqirib, og'irlikka asoslangan umumiy score
va yakuniy yo'nalishni hisoblaydi.

TUZATISH: kline ma'lumotlari endi BU YERDA bir marta yuklanib,
modullarga uzatiladi. Avval ict_smc, volume_oi va
volume_bos_combo har biri alohida bir xil kline'ni yuklar edi
(har bir coin uchun 3x ortiqcha so'rov).
"""
from config import SIGNAL_WEIGHTS
from signals import volume_oi, whale_tracker, ict_smc, sentiment, volume_bos_combo
from signals.klines import get_klines

SIGNAL_MODULES = {
    "volume_oi": volume_oi,
    "whale": whale_tracker,
    "ict_smc": ict_smc,
    "sentiment": sentiment,
    "volume_bos_combo": volume_bos_combo,
}


def analyze_symbol(symbol: str) -> dict:
    """
    Bitta coin uchun barcha signallarni yig'ib, umumiy confluence natijani qaytaradi.

    Aniqlikni oshirish uchun endi nafaqat og'irlashtirilgan score, balki
    NECHTA modul bir xil yo'nalishga OVOZ bergani ham hisoblanadi
    (agreement_count). Bitta modul yolg'iz baland score bilan butun
    signalni "long"ga burib yubormasligi uchun bot.py shu sonni
    MIN_SIGNAL_AGREEMENT bilan solishtirib filtrlaydi.
    """
    results = {}
    weighted_score = 0
    direction_votes = {"long": 0, "short": 0, "neutral": 0}
    direction_counts = {"long": 0, "short": 0, "neutral": 0}

    # Kline'ni bir marta yuklaymiz (xato bo'lsa modullar o'zlari
    # neutral qaytaradi)
    try:
        candles = get_klines(symbol)
    except Exception:
        candles = []

    for name, module in SIGNAL_MODULES.items():
        try:
            result = module.analyze(symbol, candles=candles)
        except Exception as e:
            result = {"score": 0, "direction": "neutral", "details": {"error": str(e)}}

        results[name] = result
        weight = SIGNAL_WEIGHTS.get(name, 0)
        weighted_score += (result["score"] / 100) * weight
        direction_votes[result["direction"]] += result["score"]
        direction_counts[result["direction"]] += 1

    final_direction = max(direction_votes, key=direction_votes.get)
    if direction_votes[final_direction] == 0:
        final_direction = "neutral"

    return {
        "symbol": symbol,
        "confluence_score": round(weighted_score, 1),
        "direction": final_direction,
        "agreement_count": direction_counts[final_direction],
        "signal_count": len(SIGNAL_MODULES),
        "signals": results,
        "candles": candles,
    }


def scan_watchlist(watchlist: list) -> list:
    """Butun watchlist bo'yicha tahlil qilib, natijalarni score bo'yicha saralaydi."""
    all_results = [analyze_symbol(symbol) for symbol in watchlist]
    all_results.sort(key=lambda x: x["confluence_score"], reverse=True)
    return all_results
