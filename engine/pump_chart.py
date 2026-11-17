"""
engine/pump_chart.py
Pump/Dump xabari uchun YENGIL grafik (PNG).

Render bepul tarifi (kam RAM/CPU) uchun:
  - faqat Figure + Agg (pyplot yo'q), 720x600 px, dpi=100 (AMD kartasidan ~3x kichik)
  - sham fitillari/tanalari bitta chaqiruvda (vlines + bar), alohida patch'lar yo'q
  - faqat yuboriladigan (filtrdan o'tgan) alertlar uchun chaqiriladi, ketma-ket (bir vaqtda 1 ta)
  - ish tugagach figura tozalanadi
Rasmda emoji ishlatilmaydi (matplotlib shriftida yo'q): ▲ ▼ ★ ✓ belgilari.
Xato bo'lsa chaqiruvchi matnni grafiksiz yuboradi.
"""
from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
from typing import Optional

from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.patches import FancyBboxPatch

BG, PANEL, EDGE, GRID = "#0b0e1f", "#12162c", "#232849", "#1a1f3a"
TXT, MUTED = "#e8eaf6", "#7d84a8"
GREEN, RED, AMBER, BLUE, GOLD = "#3ecf9b", "#ef6070", "#f5a623", "#5b8def", "#f7c948"
W, H = 720, 600


def _box(ov, x, y, w, h, fc, ec=None, r=14):
    ov.add_patch(FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0,rounding_size={r}",
                                fc=fc, ec=ec or fc, lw=1))


def _fmt(v: float) -> str:
    return f"{v:.6g}"


def generate_pump_chart(a) -> Optional[BytesIO]:
    """a: signals.pump_detector.Alert (a.candles — 1m shamlar [(ts,o,h,l,c,v), ...])"""
    c = list(a.candles)[-60:]
    if len(c) < 20:
        return None
    up = a.kind == "PUMP"
    col_main = GREEN if up else RED

    fig = Figure(figsize=(W / 100, H / 100), dpi=100)
    FigureCanvasAgg(fig)
    try:
        fig.patch.set_facecolor(BG)
        ov = fig.add_axes([0, 0, 1, 1])
        ov.set_xlim(0, W)
        ov.set_ylim(H, 0)
        ov.axis("off")

        # --- sarlavha
        ov.text(32, 40, a.symbol, color=TXT, fontsize=20, fontweight="bold", va="center")
        _box(ov, 470, 18, 218, 46, col_main, r=23)
        ov.text(579, 41, ("▲ PUMP · " if up else "▼ DUMP · ") + a.side, color=BG,
                fontsize=13, fontweight="bold", ha="center", va="center")
        stamp = datetime.fromtimestamp(c[-1][0] / 1000, tz=timezone.utc).strftime("%d %b %Y  %H:%M UTC")
        ov.text(32, 74, f"Pump/Dump detector  •  1m  •  {stamp}", color=MUTED, fontsize=7.5, va="center")

        # --- grafik paneli
        _box(ov, 20, 92, W - 40, 400, PANEL, EDGE, 14)
        ax = fig.add_axes([28 / W, 1 - 484 / H, (W - 92) / W, (484 - 104) / H])
        ax.set_facecolor("none")
        n = len(c)
        xs = list(range(n))
        cols = [GREEN if x[4] >= x[1] else RED for x in c]
        ax.vlines(xs, [x[3] for x in c], [x[2] for x in c], colors=cols, linewidth=0.8)
        ax.bar(xs, [abs(x[4] - x[1]) or 1e-12 for x in c], bottom=[min(x[1], x[4]) for x in c],
               width=0.62, color=cols)

        levels = [(a.tp2, GREEN, "TP2"), (a.tp1, GREEN, "TP1"), (a.entry, AMBER, "Вход"), (a.sl, RED, "SL")]
        ys = [x[3] for x in c] + [x[2] for x in c] + [v for v, _, _ in levels]
        ymin, ymax = min(ys), max(ys)
        pad = (ymax - ymin) * 0.05 or ymax * 0.01
        ax.set_ylim(ymin - pad, ymax + pad)
        fut = 14
        ax.set_xlim(-1, n + fut)
        for y, col, lab in levels:
            ax.axhline(y, color=col, lw=0.9, ls="--", alpha=0.9)
            ax.text(n + fut - 0.5, y, f" {lab} {_fmt(y)}", color=col, fontsize=6.5, va="bottom", ha="right")
        ax.axvspan(n - 5.5, n - 0.5, color=BLUE, alpha=0.10)
        ax.yaxis.tick_right()
        ax.tick_params(axis="y", colors=MUTED, labelsize=6, length=0)
        ax.tick_params(axis="x", bottom=False, labelbottom=False)
        ax.grid(axis="y", color=GRID, lw=0.6)
        for sp in ax.spines.values():
            sp.set_visible(False)

        # --- pastki qator (chip'lar)
        chips = [
            f"5 мин {a.ch5:+.1f}%",
            f"Объём x{a.vol_x:.1f}",
            "OI " + (f"{a.oi_chg:+.1f}%" if a.oi_chg is not None else "—"),
            "Пробой ✓" if a.breakout else "Пробой —",
        ]
        x = 20
        for t in chips:
            w = 24 + 7.2 * len(t)
            _box(ov, x, 506, w, 30, PANEL, EDGE, 15)
            ov.text(x + w / 2, 521, t, color=TXT, fontsize=8, ha="center", va="center")
            x += w + 8
        _box(ov, 20, 548, W - 40, 34, PANEL, EDGE, 14)
        ov.text(36, 565, f"Скор {a.score}/100" + ("  ★" if a.score >= 80 else ""),
                color=GOLD if a.score >= 80 else TXT, fontsize=9.5, fontweight="bold", va="center")
        ov.text(W - 36, 565, f"риск {a.risk_pct:.1f}%  ·  TP1 1R  ·  TP2 2R", color=MUTED,
                fontsize=8, ha="right", va="center")

        buf = BytesIO()
        fig.savefig(buf, format="png", facecolor=BG)
        buf.seek(0)
        return buf
    finally:
        fig.clear()
