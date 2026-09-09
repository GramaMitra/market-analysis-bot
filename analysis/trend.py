"""Trend classification via EMA confluence.

Score: weighted votes (close vs EMA50, EMA20 vs EMA50, EMA50 vs EMA200,
EMA20 slope). Slope is measured in ATR units per bar so thresholds are
symbol- and timeframe-independent. Normalized to -100..+100.

Label logic:
* A compressed EMA fan (|EMA20-EMA50| small vs ATR) with a flat slope
  means the directional votes are dominated by noise (e.g. seed bias on
  flat series). Such conditions are labeled RANGING even if the raw
  score is high -- this prevents "BULLISH" calls on flat markets.
* Price hugging EMA20 also demotes to RANGING when the score is not
  clearly directional.
"""
from __future__ import annotations

import pandas as pd

from analysis.indicators import ema
from analysis.models import TrendLabel, TrendResult

MIN_BARS = 60
W_CLOSE_VS_E50 = 15
W_E20_VS_E50 = 20
W_E50_VS_E200 = 15
W_SLOPE = 25
SLOPE_BARS = 5
SLOPE_THRESHOLD = 0.12      # ATR units per bar
HUG_FACTOR = 0.25           # |close - EMA20| <= HUG_FACTOR * ATR -> hugging
FAN_COMPRESSION_ATR = 0.5   # |EMA20 - EMA50| <= this * ATR -> compressed
BULL_THRESHOLD = 45
BEAR_THRESHOLD = -45


def compute_trend(close: pd.Series, atr_value: float) -> TrendResult:
    n = len(close)
    if n < MIN_BARS:
        raise ValueError(f"Trend needs at least {MIN_BARS} candles, got {n}.")
    if atr_value is None or atr_value <= 0:
        raise ValueError("Trend needs a valid ATR value (> 0).")

    e20_s = ema(close, 20)
    e50_s = ema(close, 50)
    e200_s = ema(close, 200) if n >= 200 else None

    c = float(close.iloc[-1])
    e20 = float(e20_s.iloc[-1])
    e50 = float(e50_s.iloc[-1])
    e200 = (float(e200_s.iloc[-1])
            if e200_s is not None and pd.notna(e200_s.iloc[-1]) else None)

    parts: list[str] = []
    raw = 0.0
    total = W_CLOSE_VS_E50 + W_E20_VS_E50 + W_SLOPE

    if c > e50:
        raw += W_CLOSE_VS_E50
        parts.append("close above EMA50")
    else:
        raw -= W_CLOSE_VS_E50
        parts.append("close below EMA50")

    if e20 > e50:
        raw += W_E20_VS_E50
        parts.append("EMA20 > EMA50")
    else:
        raw -= W_E20_VS_E50
        parts.append("EMA20 < EMA50")

    if e200 is not None:
        total += W_E50_VS_E200
        if e50 > e200:
            raw += W_E50_VS_E200
            parts.append("EMA50 > EMA200")
        else:
            raw -= W_E50_VS_E200
            parts.append("EMA50 < EMA200")

    slope = (e20 - float(e20_s.iloc[-1 - SLOPE_BARS])) / (SLOPE_BARS * atr_value)
    slope_flat = abs(slope) <= SLOPE_THRESHOLD
    if slope > SLOPE_THRESHOLD:
        raw += W_SLOPE
        parts.append("EMA20 slope rising")
    elif slope < -SLOPE_THRESHOLD:
        raw -= W_SLOPE
        parts.append("EMA20 slope falling")
    else:
        parts.append("EMA20 slope flat")

    score = round(100.0 * raw / total)

    hug = abs(c - e20) <= HUG_FACTOR * atr_value
    fan_compressed = abs(e20 - e50) <= FAN_COMPRESSION_ATR * atr_value
    if hug:
        parts.append("price hugging EMA20")
    if fan_compressed:
        parts.append("EMA fan compressed")

    if fan_compressed and slope_flat:
        label = TrendLabel.RANGING
    elif score >= BULL_THRESHOLD:
        label = TrendLabel.BULLISH
    elif score <= BEAR_THRESHOLD:
        label = TrendLabel.BEARISH
    elif hug or fan_compressed:
        label = TrendLabel.RANGING
    else:
        label = TrendLabel.UNCERTAIN

    return TrendResult(label=label, score=score, ema20=e20,
                       ema50=e50, ema200=e200,
                       detail="; ".join(parts))