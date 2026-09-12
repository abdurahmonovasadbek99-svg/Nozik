"""
Grafik generatsiya moduli.
Sham (candle) ma'lumotlaridan oddiy candlestick rasm yasab,
Telegram'ga rasm sifatida yuborish uchun tayyorlaydi.
Matplotlib'dan foydalanadi ("Agg" backend - serverda ekran kerak emas).
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from io import BytesIO

GREEN = "#26a69a"
RED = "#ef5350"


def generate_candle_chart(symbol: str, candles: list, direction: str = "neutral") -> BytesIO:
    """Sham ro'yxatidan PNG rasm (BytesIO) yasaydi. Bo'sh bo'lsa None qaytaradi."""
    if not candles:
        return None

    fig, ax = plt.subplots(figsize=(8, 4.5), dpi=110)
    fig.patch.set_facecolor("#0e1117")
    ax.set_facecolor("#0e1117")

    for i, c in enumerate(candles):
        color = GREEN if c["close"] >= c["open"] else RED
        ax.plot([i, i], [c["low"], c["high"]], color=color, linewidth=1, zorder=1)
        body_low = min(c["open"], c["close"])
        body_height = abs(c["close"] - c["open"]) or (c["high"] - c["low"]) * 0.01
        ax.add_patch(
            plt.Rectangle((i - 0.3, body_low), 0.6, body_height, color=color, zorder=2)
        )

    dir_colors = {"long": GREEN, "short": RED, "neutral": "#999999"}
    dir_label = {"long": "LONG", "short": "SHORT", "neutral": "NEUTRAL"}.get(direction, direction.upper())
    ax.set_title(f"{symbol}  •  15m", color="white", fontsize=13, pad=28)
    ax.text(
        0.5, 1.06, dir_label, transform=ax.transAxes, ha="center",
        color=dir_colors.get(direction, "white"), fontsize=12, fontweight="bold",
    )
    ax.set_xlim(-1, len(candles))
    ax.tick_params(colors="white", labelsize=8)
    for spine in ax.spines.values():
        spine.set_color("#333")
    ax.grid(color="#222", linewidth=0.5, alpha=0.5)

    plt.tight_layout()
    buf = BytesIO()
    plt.savefig(buf, format="png", facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf
