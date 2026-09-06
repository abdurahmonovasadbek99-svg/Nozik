"""
Confluence Aggregator.
4 ta signal modulini chaqirib, og'irlikka asoslangan umumiy score
va yakuniy yo'nalishni hisoblaydi.
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import SIGNAL_WEIGHTS
from signals import volume_oi, whale_tracker, ict_smc, sentiment

SIGNAL_MODULES = {
    "volume_oi": volume_oi,
    "whale": whale_tracker,
    "ict_smc": ict_smc,
    "sentiment": sentiment,
}


def analyze_symbol(symbol: str) -> dict:
    """
    Bitta coin uchun barcha signallarni yig'ib, umumiy confluence natijani qaytaradi.
    """
    results = {}
    weighted_score = 0
    direction_votes = {"long": 0, "short": 0, "neutral": 0}

    for name, module in SIGNAL_MODULES.items():
        try:
            result = module.analyze(symbol)
        except Exception as e:
            result = {"score": 0, "direction": "neutral", "details": {"error": str(e)}}

        results[name] = result
        weight = SIGNAL_WEIGHTS.get(name, 0)
        weighted_score += (result["score"] / 100) * weight
        direction_votes[result["direction"]] += result["score"]

    # Yakuniy yo'nalish - eng ko'p og'irlashtirilgan ovoz olgan tomon
    final_direction = max(direction_votes, key=direction_votes.get)
    if direction_votes[final_direction] == 0:
        final_direction = "neutral"

    return {
        "symbol": symbol,
        "confluence_score": round(weighted_score, 1),
        "direction": final_direction,
        "signals": results,
    }


def scan_watchlist(watchlist: list) -> list:
    """Butun watchlist bo'yicha tahlil qilib, natijalarni score bo'yicha saralaydi."""
    all_results = [analyze_symbol(symbol) for symbol in watchlist]
    all_results.sort(key=lambda x: x["confluence_score"], reverse=True)
    return all_results
