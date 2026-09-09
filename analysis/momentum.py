"""Momentum classification: RSI + MACD histogram + ROC.

Strength (STRONG/MODERATE/WEAK/NEUTRAL) comes from |score|;
direction comes from the sign. Normalized to -100..+100.
"""
from __future__ import annotations

import pandas as pd

from analysis.indicators import macd, roc, rsi
from analysis.models import MomentumLabel, MomentumResult

MIN_BARS = 60
W_RSI = 40
W_HIST_SIGN = 25
W_HIST_SLOPE = 10
W_ROC = 15
STRONG_TH, MODERATE_TH, WEAK_TH = 55, 25, 10


def compute_momentum(close: pd.Series) -> MomentumResult:
    n = len(close)
    if n < MIN_BARS:
        raise ValueError(f"Momentum needs at least {MIN_BARS} candles, got {n}.")

    rsi_v = float(rsi(close, 14).iloc[-1])
    _, _, hist = macd(close)
    h_now = float(hist.iloc[-1])
    h_prev = float(hist.iloc[-4])
    roc_v = float(roc(close, 9).iloc[-1])

    raw = ((rsi_v - 50.0) / 50.0 * W_RSI
           + (W_HIST_SIGN if h_now > 0 else -W_HIST_SIGN)
           + (W_HIST_SLOPE if h_now > h_prev else -W_HIST_SLOPE)
           + (W_ROC if roc_v > 0 else -W_ROC))
    score = round(100.0 * raw / (W_RSI + W_HIST_SIGN + W_HIST_SLOPE + W_ROC))

    strength = abs(score)
    if strength >= STRONG_TH:
        label = MomentumLabel.STRONG
    elif strength >= MODERATE_TH:
        label = MomentumLabel.MODERATE
    elif strength >= WEAK_TH:
        label = MomentumLabel.WEAK
    else:
        label = MomentumLabel.NEUTRAL

    detail = (f"RSI {rsi_v:.1f}; MACD histogram {'positive' if h_now > 0 else 'negative'} "
              f"and {'rising' if h_now > h_prev else 'falling'}; ROC(9) {roc_v:+.3f}%")
    return MomentumResult(label=label, score=score, rsi=rsi_v,
                          macd_hist=h_now, roc=roc_v, detail=detail)