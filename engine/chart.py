"""
Signal kartasi (rasm) generatsiyasi — "Fxabot" dizayni uslubida:
  sarlavha + yo'nalish tugmasi, AMD belgilari (A · M · D), SL/Entry/TP zonalari,
  ko'rsatkichlar paneli, signal sifati (baho + progress) va konfluens chiplari.

Thread-safe: pyplot emas, Figure ob'ekti ishlatiladi (asyncio.to_thread ichida xavfsiz).
Rasmda emoji ishlatilmaydi (matplotlib shriftida yo'q) — faqat DejaVu belgilar (▲ ▼ ✓ ✗ → •).
"""
from datetime import datetime, timezone
from io import BytesIO
from math import ceil, floor, log10

from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.patches import FancyBboxPatch, Rectangle
from matplotlib.ticker import FuncFormatter, MaxNLocator

# ---------------------------------------------------------------- ranglar
BG = "#0b0e1f"
PANEL = "#12162c"
PANEL_EDGE = "#232849"
GRID = "#1a1f3a"
TXT = "#e8eaf6"
MUTED = "#7d84a8"
DIM = "#4a5075"
GREEN = "#3ecf9b"
RED = "#ef6070"
AMBER = "#f5a623"
BLUE = "#5b8def"
PURPLE = "#a78bfa"
GOLD = "#f7c948"

# ---------------------------------------------------------------- matnlar (til shu yerda)
T = {
    "strategy": "AMD Strategy",
    "acc": "A · Accumulation",
    "man": "M · Manipulation",
    "dist": "D · Distribution",
    "range_high": "Range High",
    "range_low": "Range Low",
    "entry": "ВХОД",
    "sl": "СТОП-ЛОСС",
    "quality": "КАЧЕСТВО СИГНАЛА",
    "htf": "Старший ТФ",
    "htf_up": "рост ↑",
    "htf_down": "падение ↓",
    "htf_na": "нет данных",
    "risk": "Риск",
    "footer": "A · Accumulation   →   M · Manipulation   →   D · Distribution",
    "disclaimer": "Не является финансовой рекомендацией. Рискуйте не более 1–2% депозита.",
}


# ---------------------------------------------------------------- yordamchilar
def grade_of(score: int):
    """(harf, rang) — signal sifati bahosi."""
    if score >= 85:
        return "A+", GREEN
    if score >= 75:
        return "A", GREEN
    if score >= 65:
        return "B", AMBER
    if score >= 55:
        return "C", "#f08a4b"
    return "D", RED


def _dec(ref: float) -> int:
    """Narx kattaligiga qarab kasr xonalari (taxminan 5 ta muhim raqam)."""
    if not ref or ref <= 0:
        return 4
    return max(0, min(10, 4 - int(floor(log10(ref)))))


def _fmt(x, dec: int) -> str:
    return f"{x:.{dec}f}"


def _ts_sec(ts):
    if ts is None:
        return None
    ts = float(ts)
    return ts / 1000.0 if ts > 1e11 else ts


def _dt(ts):
    t = _ts_sec(ts)
    return datetime.fromtimestamp(t, tz=timezone.utc) if t else None


def _rbox(ov, x, y, w, h, fc, ec=None, lw=0.8, r=10, alpha=1.0, z=1, ls="-"):
    ov.add_patch(FancyBboxPatch(
        (x, y), w, h, boxstyle=f"round,pad=0,rounding_size={min(r, h / 2)}",
        fc=fc, ec=ec if ec else "none", lw=lw, alpha=alpha, zorder=z, ls=ls))


# ---------------------------------------------------------------- asosiy
def generate_candle_chart(symbol: str, candles: list, direction: str = "neutral",
                          levels: dict = None, tf_label: str = "15m", meta: dict = None) -> BytesIO:
    """Signal kartasi (PNG, BytesIO). Sham yo'q bo'lsa None.

    candles : [{"open","high","low","close","ts"(ixtiyoriy)}, ...]
    levels  : range_high, range_low, entry, sl, tp1, tp2 (hammasi ixtiyoriy)
    meta    : score, ts, rr1, rr2, risk_pct, sweep_i, range_i, mss, fvg, bn_ok, htf_ok, htf
    """
    if not candles:
        return None
    levels = levels or {}
    meta = meta or {}
    entry, sl = levels.get("entry"), levels.get("sl")
    tp1, tp2 = levels.get("tp1"), levels.get("tp2")
    rh, rl = levels.get("range_high"), levels.get("range_low")
    has_signal = bool(entry and sl and tp1 and tp2) and direction in ("long", "short")
    is_short = direction == "short"

    W = 720
    H = 905 if has_signal else 640
    fig = Figure(figsize=(W / 100, H / 100), dpi=150)
    FigureCanvasAgg(fig)
    fig.patch.set_facecolor(BG)

    ov = fig.add_axes([0, 0, 1, 1], zorder=0)       # "piksel" koordinata qatlami
    ov.set_xlim(0, W)
    ov.set_ylim(H, 0)
    ov.axis("off")

    def rect_of(x0, y0, x1, y1):
        return [x0 / W, 1 - y1 / H, (x1 - x0) / W, (y1 - y0) / H]

    # ------------------------------------------------ sarlavha
    ov.text(36, 52, symbol, color=TXT, fontsize=24, fontweight="bold", va="center")
    if has_signal:
        pill_col = RED if is_short else GREEN
        pill_txt = "▼ SHORT" if is_short else "▲ LONG"
        _rbox(ov, 490, 24, 194, 54, pill_col, r=27, z=2)
        ov.text(587, 51, pill_txt, color=BG, fontsize=17, fontweight="bold", ha="center", va="center", zorder=3)
    dt = _dt(meta.get("ts") or candles[-1].get("ts"))
    stamp = dt.strftime("%d %b %Y  %H:%M UTC") if dt else ""
    sub = f"{T['strategy']}  •  {tf_label}" + (f"  •  {stamp}" if stamp else "")
    ov.text(36, 88, sub, color=MUTED, fontsize=8, va="center")

    # ------------------------------------------------ grafik paneli
    cy0, cy1 = 108, (598 if has_signal else H - 30)
    _rbox(ov, 24, cy0, W - 48, cy1 - cy0, PANEL, ec=PANEL_EDGE, r=16, z=1)
    ax = fig.add_axes(rect_of(34, cy0 + 12, W - 82, cy1 - 36), zorder=2)
    ax.set_facecolor("none")

    n = len(candles)
    future = max(16, int(n * 0.8)) if has_signal else 6
    xmax = n + future

    # Y oralig'i
    ys = [c["low"] for c in candles] + [c["high"] for c in candles]
    if has_signal:
        ys += [entry, sl, tp1, tp2]
    ymin, ymax = min(ys), max(ys)
    span = (ymax - ymin) or ymax * 0.01
    pad_top = span * (0.14 if (has_signal and is_short) else 0.06)
    pad_bot = span * (0.14 if (has_signal and not is_short) else 0.06)
    ymin, ymax = ymin - pad_bot, ymax + pad_top
    yspan = ymax - ymin
    ax.set_xlim(-1, xmax)
    ax.set_ylim(ymin, ymax)
    dec = _dec(candles[-1]["close"])

    # setka
    ax.yaxis.set_major_locator(MaxNLocator(7))
    ax.yaxis.tick_right()
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _p: _fmt(v, dec)))
    ax.grid(axis="y", color=GRID, linewidth=0.7)
    ax.set_axisbelow(True)
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.tick_params(axis="y", colors=MUTED, labelsize=6.5, length=0, pad=6)

    # vaqt belgilari (kelajak uchun ham)
    tss = [_ts_sec(c.get("ts")) for c in candles]
    if all(t for t in tss) and n >= 2:
        interval = tss[-1] - tss[-2]
        step = max(1, ceil(xmax / 6))
        ticks = list(range(max(1, step // 2), xmax, step))
        fmt_str = "%d %b %H:%M" if interval < 86400 else "%d %b"

        def _lab(i):
            t = tss[-1] + (i - (n - 1)) * interval
            return datetime.fromtimestamp(t, tz=timezone.utc).strftime(fmt_str)
        ax.set_xticks(ticks)
        ax.set_xticklabels([_lab(i) for i in ticks])
        ax.tick_params(axis="x", colors=MUTED, labelsize=6, length=0, pad=6)
    else:
        ax.set_xticks([])

    # ---- Accumulation qutisi + diapazon chiziqlari
    sweep_i = meta.get("sweep_i", -1)
    range_i = max(0, meta.get("range_i", 0))
    if rh and rl:
        x_start = range_i - 0.5 if (has_signal and sweep_i > range_i) else -0.5
        x_end = (sweep_i - 0.5) if (has_signal and sweep_i > range_i) else n - 0.5
        ax.add_patch(Rectangle((x_start, rl), x_end - x_start, rh - rl,
                               fc=BLUE, ec=BLUE, alpha=0.13, lw=0, zorder=1))
        ax.add_patch(Rectangle((x_start, rl), x_end - x_start, rh - rl,
                               fc="none", ec=BLUE, alpha=0.55, lw=0.8, ls=(0, (3, 3)), zorder=1))
        line_end = (n - 1) if has_signal else n - 0.5
        ax.plot([x_start, line_end], [rh, rh], color=GOLD, lw=0.8, ls=":", alpha=0.85, zorder=1)
        ax.plot([x_start, line_end], [rl, rl], color=GOLD, lw=0.8, ls=":", alpha=0.55, zorder=1)
        ax.text(x_start + 0.3, rh + yspan * 0.012, f"{T['range_high']} {_fmt(rh, dec)}",
                color=GOLD, fontsize=6, fontweight="bold", va="bottom", ha="left", zorder=4)
        if not has_signal:
            ax.text(x_start + 0.3, rl - yspan * 0.012, f"{T['range_low']} {_fmt(rl, dec)}",
                    color=GOLD, fontsize=6, fontweight="bold", va="top", ha="left", zorder=4)
        if has_signal and sweep_i > range_i:
            ax.text(x_start + 0.3, rl - yspan * 0.012, T["acc"], color=BLUE, fontsize=6.8,
                    fontweight="bold", va="top", ha="left", zorder=4)

    # ---- SL / TP zonalari
    if has_signal:
        zx = n - 0.5
        zw = xmax - zx
        ax.add_patch(Rectangle((zx, min(entry, sl)), zw, abs(sl - entry),
                               fc=RED, alpha=0.20, lw=0, zorder=1))
        ax.add_patch(Rectangle((zx, min(entry, tp2)), zw, abs(tp2 - entry),
                               fc=GREEN, alpha=0.11, lw=0, zorder=1))

    # ---- shamlar
    for i, c in enumerate(candles):
        col = GREEN if c["close"] >= c["open"] else RED
        ax.plot([i, i], [c["low"], c["high"]], color=col, lw=0.9, zorder=3, solid_capstyle="butt")
        bl = min(c["open"], c["close"])
        bh = abs(c["close"] - c["open"]) or (c["high"] - c["low"]) * 0.02 or yspan * 0.001
        ax.add_patch(Rectangle((i - 0.32, bl), 0.64, bh, fc=col, ec=col, lw=0.3, zorder=4))

    # ---- AMD belgilari + darajalar
    if has_signal:
        # Manipulation (sweep shami)
        if 0 <= sweep_i < n:
            sc = candles[sweep_i]
            if is_short:
                py = sc["high"] + yspan * 0.015
                ax.plot([sweep_i], [py], marker="v", color=GOLD, ms=6, zorder=6)
                ty = ymax - yspan * 0.035
                va = "top"
            else:
                py = sc["low"] - yspan * 0.015
                ax.plot([sweep_i], [py], marker="^", color=GOLD, ms=6, zorder=6)
                ty = ymin + yspan * 0.035
                va = "bottom"
            tx = min(max(sweep_i, 2), n + future * 0.35)
            ax.annotate(T["man"], xy=(sweep_i, py), xytext=(tx + 1.5, ty), color=GOLD,
                        fontsize=6.8, fontweight="bold", ha="left", va=va, zorder=6,
                        arrowprops=dict(arrowstyle="-", color=GOLD, lw=0.8, alpha=0.9,
                                        shrinkA=2, shrinkB=2))
        # Distribution (tasdiq shami)
        if is_short:
            dy = max(entry - yspan * 0.13, ymin + yspan * 0.07)
        else:
            dy = min(entry + yspan * 0.13, ymax - yspan * 0.07)
        ax.annotate(T["dist"], xy=(n - 1, entry), xytext=(n - 1.5, dy), color=PURPLE,
                    fontsize=6.8, fontweight="bold", ha="right",
                    va="top" if is_short else "bottom", zorder=6,
                    arrowprops=dict(arrowstyle="-", color=PURPLE, lw=0.8, shrinkA=2, shrinkB=2))

        items = [
            (T["entry"], entry, TXT, False),
            ("SL", sl, RED, True),
            ("TP1", tp1, GREEN, True),
            ("TP2", tp2, GREEN, True),
        ]
        for name, val, col, dotted in items:
            ax.plot([n - 1, xmax], [val, val], color=col, lw=0.9,
                    ls=":" if dotted else (0, (4, 3)), alpha=0.95, zorder=5)
            ax.text(xmax - 0.4, val, f"{name} {_fmt(val, dec)}", color=col, fontsize=6.2,
                    fontweight="bold", ha="right", va="center", zorder=7,
                    bbox=dict(boxstyle="round,pad=0.28", fc=BG, ec=col, lw=0.8))

    # ------------------------------------------------ pastki panellar
    if has_signal:
        # --- 4 ta ko'rsatkich qutisi
        by0, bh = 616, 82
        gap = 12
        bw = (W - 72 - 3 * gap) / 4

        def pct(v):
            return (v - entry) / entry * 100

        rr1 = meta.get("rr1")
        rr2 = meta.get("rr2")
        boxes = [
            (T["entry"], _fmt(entry, dec), TXT, "SHORT" if is_short else "LONG"),
            (T["sl"], _fmt(sl, dec), RED, f"{pct(sl):+.2f}%"),
            ("TP1", _fmt(tp1, dec), GREEN, f"{pct(tp1):+.2f}%" + (f"  ·  {rr1:.1f}R" if rr1 else "")),
            ("TP2", _fmt(tp2, dec), GREEN, f"{pct(tp2):+.2f}%" + (f"  ·  {rr2:.1f}R" if rr2 else "")),
        ]
        for i, (lab, val, col, sub_t) in enumerate(boxes):
            bx = 36 + i * (bw + gap)
            _rbox(ov, bx, by0, bw, bh, PANEL, ec=PANEL_EDGE, r=12, z=1)
            cx = bx + bw / 2
            ov.text(cx, by0 + 19, lab, color=MUTED, fontsize=6.3, fontweight="bold", ha="center", va="center", zorder=3)
            ov.text(cx, by0 + 44, val, color=col, fontsize=12.5, fontweight="bold", ha="center", va="center", zorder=3)
            ov.text(cx, by0 + 67, sub_t, color=MUTED, fontsize=6.3, ha="center", va="center", zorder=3)

        # --- signal sifati paneli
        score = int(meta.get("score", 0))
        g, gcol = grade_of(score)
        qy0, qh = 714, 112
        _rbox(ov, 36, qy0, W - 72, qh, PANEL, ec=PANEL_EDGE, r=12, z=1)
        ov.text(56, qy0 + 22, T["quality"], color=MUTED, fontsize=6.5, fontweight="bold", va="center", zorder=3)
        ov.text(W - 56, qy0 + 22, f"{g}  •  {score}/100", color=gcol, fontsize=10.5,
                fontweight="bold", ha="right", va="center", zorder=3)
        bar_x, bar_w = 56, W - 112
        _rbox(ov, bar_x, qy0 + 36, bar_w, 7, "#232849", r=3.5, z=2)
        _rbox(ov, bar_x, qy0 + 36, max(8, bar_w * score / 100), 7, gcol, r=3.5, z=3)

        htf = meta.get("htf") or ""
        htf_ok = meta.get("htf_ok")
        if htf_ok is None:
            htf_txt = T["htf_na"]
        else:
            up = (direction == "long") == bool(htf_ok)
            htf_txt = T["htf_up"] if up else T["htf_down"]
        parts = [f"{T['htf']}{' ' + htf if htf else ''}: {htf_txt}"]
        if meta.get("risk_pct") is not None:
            parts.append(f"{T['risk']} {meta['risk_pct']:.2f}%")
        if rr1 and rr2:
            parts.append(f"R:R 1:{rr1:.1f} – 1:{rr2:.1f}")
        ov.text(56, qy0 + 58, "  •  ".join(parts), color=MUTED, fontsize=6.6, va="center", zorder=3)

        # --- konfluens chiplari
        def chip_state(v):
            return {True: "✓", False: "✗", None: "–"}[v]
        chips = [
            ("Sweep ✓", True),
            (f"MSS {chip_state(meta.get('mss'))}", bool(meta.get("mss"))),
            (f"FVG {chip_state(meta.get('fvg'))}", bool(meta.get("fvg"))),
            (f"Binance {chip_state(meta.get('bn_ok'))}", meta.get("bn_ok") is True),
        ]
        cx = 56
        cyy = qy0 + 87
        for text, active in chips:
            cw = 18 + 6.4 * len(text)
            _rbox(ov, cx, cyy - 11, cw, 22, "none", ec=AMBER if active else DIM, lw=1.0 if active else 0.8,
                  r=11, z=3)
            ov.text(cx + cw / 2, cyy, text, color=AMBER if active else DIM, fontsize=6.4,
                    fontweight="bold", ha="center", va="center", zorder=4)
            cx += cw + 10

        # --- pastki yozuv
        ov.text(W / 2, 856, T["footer"], color=MUTED, fontsize=6.5, ha="center", va="center")
        ov.text(W / 2, 878, T["disclaimer"], color=DIM, fontsize=5.8, ha="center", va="center")

    buf = BytesIO()
    fig.savefig(buf, format="png", facecolor=fig.get_facecolor())
    buf.seek(0)
    return buf
