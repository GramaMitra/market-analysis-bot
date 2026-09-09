"""Volatility classification: current ATR vs its own recent history.

Percentile uses a midrank so a perfectly flat ATR series maps to the
50th percentile (MEDIUM), not LOW or EXTREME.
"""
from __future__ import annotations

import pandas as pd

from analysis.models import VolatilityLabel, VolatilityResult

LOW_TH, MEDIUM_TH, HIGH_TH = 25, 60, 85


def compute_volatility(atr_series: pd.Series) -> VolatilityResult:
    hist = atr_series.dropna()
    if len(hist) < 10:
        raise ValueError(f"Volatility needs at least 10 ATR values, got {len(hist)}.")

    cur = float(hist.iloc[-1])
    less = int((hist < cur).sum())
    ties = int((hist == cur).sum())
    percentile = 100.0 * (less + 0.5 * ties) / len(hist)

    if percentile < LOW_TH:
        label = VolatilityLabel.LOW
    elif percentile < MEDIUM_TH:
        label = VolatilityLabel.MEDIUM
    elif percentile < HIGH_TH:
        label = VolatilityLabel.HIGH
    else:
        label = VolatilityLabel.EXTREME

    detail = (f"ATR {cur:.5g} at the {_ordinal(int(percentile))} percentile "
              f"of last {len(hist)} bars")
    return VolatilityResult(label=label, atr=cur, atr_percentile=percentile,
                            detail=detail)


def _ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"

