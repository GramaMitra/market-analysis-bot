"""Market structure: swing detection, HH/HL/LH/LL classification,
range detection and support/resistance via swing clustering.

Honesty note (per spec): this is heuristic. Swing confirmation lags by
SWING_RIGHT bars, and detected S/R levels are statistical, not barriers.
"""
from __future__ import annotations

import pandas as pd

from analysis.models import StructureLabel, StructureResult, SwingPoint

SWING_LEFT = 3
SWING_RIGHT = 3
SR_TOL_ATR = 0.75        # cluster tolerance in ATR units
SR_MIN_TOUCHES = 2
RANGE_BAND_ATR = 8.0     # recent swings within this band -> RANGE
SR_FALLBACK_BARS = 100


def detect_swings(df: pd.DataFrame,
                  left: int = SWING_LEFT,
                  right: int = SWING_RIGHT) -> tuple[list[SwingPoint], list[SwingPoint]]:
    """Fractal swing points: local extremes with left/right neighbors.

    A point qualifies if it is the extreme of its window AND unique within
    it (rejects ties/plateaus). Confirmation lags by `right` bars by design.
    """
    highs = df["high"].to_numpy(dtype=float)
    lows = df["low"].to_numpy(dtype=float)
    times = df["time"].reset_index(drop=True)
    swing_highs: list[SwingPoint] = []
    swing_lows: list[SwingPoint] = []

    for i in range(left, len(df) - right):
        win_h = highs[i - left: i + right + 1]
        win_l = lows[i - left: i + right + 1]
        if highs[i] >= win_h.max() and int((win_h == highs[i]).sum()) == 1:
            swing_highs.append(SwingPoint(i, times.iloc[i], float(highs[i]), "high"))
        if lows[i] <= win_l.min() and int((win_l == lows[i]).sum()) == 1:
            swing_lows.append(SwingPoint(i, times.iloc[i], float(lows[i]), "low"))
    return swing_highs, swing_lows


def _cluster(prices: list[float], tol: float) -> list[tuple[float, int]]:
    """Greedy 1-D clustering; returns (mean_price, touches) for clusters >= 2."""
    clusters: list[list[float]] = []
    for p in sorted(prices):
        if clusters and p - clusters[-1][-1] <= tol:
            clusters[-1].append(p)
        else:
            clusters.append([p])
    return [(sum(c) / len(c), len(c)) for c in clusters if len(c) >= SR_MIN_TOUCHES]


def _nearest_above(levels: list[float], close: float) -> float | None:
    above = [p for p in levels if p > close]
    return min(above) if above else None


def _nearest_below(levels: list[float], close: float) -> float | None:
    below = [p for p in levels if p < close]
    return max(below) if below else None


def build_structure(df: pd.DataFrame, atr_value: float) -> StructureResult:
    if df.empty:
        raise ValueError("Structure needs candle data.")
    if atr_value is None or atr_value <= 0:
        raise ValueError("Structure needs a valid ATR value (> 0).")

    swing_highs, swing_lows = detect_swings(df)
    close = float(df["close"].iloc[-1])

    label = StructureLabel.UNCERTAIN
    score = 0
    description = "Not enough confirmed swings"

    if len(swing_highs) >= 2 and len(swing_lows) >= 2:
        hh = swing_highs[-1].price > swing_highs[-2].price
        hl = swing_lows[-1].price > swing_lows[-2].price
        if hh and hl:
            label, score, description = (StructureLabel.UPTREND_STRUCTURE, 60,
                                         "Higher High / Higher Low")
        elif not hh and not hl:
            label, score, description = (StructureLabel.DOWNTREND_STRUCTURE, -60,
                                         "Lower High / Lower Low")
        else:
            recent = ([s.price for s in swing_highs[-2:]] +
                      [s.price for s in swing_lows[-2:]])
            if max(recent) - min(recent) <= RANGE_BAND_ATR * atr_value:
                label, score, description = (StructureLabel.RANGE, 0,
                                             "Price compressed in a range")
            else:
                description = "Mixed swings (expansion, no clean structure)"

    # --- support / resistance ------------------------------------------------
    # Candidate levels = individual swing prices PLUS cluster means
    # (multi-touch zones). "Nearest" means nearest in PRICE regardless of
    # touch count: a single-swing high sitting between price and a strong
    # cluster is still the nearest barrier the market actually printed.
    tol = SR_TOL_ATR * atr_value
    res_clusters = _cluster([s.price for s in swing_highs], tol)
    sup_clusters = _cluster([s.price for s in swing_lows], tol)

    high_levels = sorted({s.price for s in swing_highs} | {m for m, _ in res_clusters})
    low_levels = sorted({s.price for s in swing_lows} | {m for m, _ in sup_clusters})

    resistance = _nearest_above(high_levels, close)
    if resistance is None:
        rolling_max = float(df["high"].tail(SR_FALLBACK_BARS).max())
        if rolling_max > close:
            resistance = rolling_max

    support = _nearest_below(low_levels, close)
    if support is None:
        rolling_min = float(df["low"].tail(SR_FALLBACK_BARS).min())
        if rolling_min < close:
            support = rolling_min

    swings = sorted(swing_highs + swing_lows, key=lambda s: s.index)
    return StructureResult(label=label, score=score, description=description,
                           support=support, resistance=resistance, swings=swings)