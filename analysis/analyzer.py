"""Analysis engine: combines components into regime, MTF alignment,
overall analytical-alignment score and confidence.

SCORING CONTRACT (per project spec):
* The score measures AGREEMENT between deterministic components.
* It is NOT a probability of profit and must never be presented as one.
* Volatility is non-directional: EXTREME volatility caps confidence at
  MODERATE and dominates the regime instead.
"""
from __future__ import annotations

import pandas as pd

from analysis.indicators import atr as atr_fn
from analysis.models import (Alignment, AnalysisResult, MomentumLabel, Regime,
                             StructureLabel, TrendLabel, TrendResult, VolatilityLabel)
from analysis.momentum import compute_momentum
from analysis.structure import build_structure
from analysis.trend import compute_trend
from analysis.volatility import compute_volatility

MIN_CANDLES = 60
W_TREND, W_MOMENTUM, W_STRUCTURE, W_MTF = 0.35, 0.25, 0.25, 0.15
CONF_HIGH, CONF_MODERATE = 70, 45


def analyze(df: pd.DataFrame, symbol: str, timeframe: str, digits: int = 5) -> AnalysisResult:
    """Run the full deterministic analysis on one validated candle set."""
    for col in ("time", "open", "high", "low", "close"):
        if col not in df.columns:
            raise ValueError(f"Candle data for {symbol} missing column '{col}'.")
    if len(df) < MIN_CANDLES:
        raise ValueError(f"Analysis needs at least {MIN_CANDLES} candles, "
                         f"got {len(df)} for {symbol} {timeframe}.")

    atr_series = atr_fn(df["high"], df["low"], df["close"], 14)
    atr_value = float(atr_series.iloc[-1])

    trend = compute_trend(df["close"], atr_value)
    momentum = compute_momentum(df["close"])
    volatility = compute_volatility(atr_series)
    structure = build_structure(df, atr_value)

    regime, reason = _classify_regime(trend, volatility.label,
                                      structure.label, structure.description)
    score, confidence = _score(trend.score, momentum.score, structure.score,
                               None, trend.ema200 is not None,
                               volatility.label)

    return AnalysisResult(
        symbol=symbol, timeframe=timeframe,
        generated_at=pd.Timestamp.now(tz="UTC"),
        close=float(df["close"].iloc[-1]), digits=digits,
        candles_used=len(df), has_ema200=trend.ema200 is not None,
        trend=trend, momentum=momentum, volatility=volatility,
        structure=structure, regime=regime, regime_reason=reason,
        score=score, confidence=confidence,
    )


def alignment_from_trends(trends: dict[str, TrendLabel]) -> Alignment:
    """Map timeframe trend labels to an alignment verdict."""
    signs = {1 if t == TrendLabel.BULLISH else -1 if t == TrendLabel.BEARISH else 0
             for t in trends.values()}
    active = signs - {0}
    if not trends or not active:
        return Alignment.UNCERTAIN
    if len(active) == 2:
        return Alignment.CONFLICTING
    if len(signs) == 1:
        return Alignment.ALIGNED
    return Alignment.PARTIALLY_ALIGNED


def add_mtf(result: AnalysisResult,
            mtf_results: dict[str, AnalysisResult]) -> AnalysisResult:
    """Attach multi-timeframe context and recompute alignment/score/confidence."""
    result.mtf_trends = {tf: r.trend.label for tf, r in mtf_results.items()}
    result.alignment = alignment_from_trends(result.mtf_trends)

    mtf_scores = [r.trend.score for r in mtf_results.values()]
    mtf_mean = sum(mtf_scores) / len(mtf_scores) if mtf_scores else None
    result.score, result.confidence = _score(
        result.trend.score, result.momentum.score, result.structure.score,
        mtf_mean, result.has_ema200, result.volatility.label)
    return result


def _score(trend_s: int, momentum_s: int, structure_s: int,
           mtf_mean: float | None, has_ema200: bool,
           vol_label: VolatilityLabel) -> tuple[int, str]:
    comps = [(W_TREND, trend_s), (W_MOMENTUM, momentum_s), (W_STRUCTURE, structure_s)]
    if mtf_mean is not None:
        comps.append((W_MTF, mtf_mean))
    total_w = sum(w for w, _ in comps)
    mean_dir = sum(w * s for w, s in comps) / (100.0 * total_w)
    score = max(0, min(100, round(abs(mean_dir) * 100)))

    confidence = "HIGH" if score >= CONF_HIGH else \
                 "MODERATE" if score >= CONF_MODERATE else "LOW"
    # Honesty caps: incomplete history or extreme volatility -> never claim HIGH.
    if confidence == "HIGH" and (not has_ema200 or vol_label == VolatilityLabel.EXTREME):
        confidence = "MODERATE"
    return score, confidence


def _classify_regime(trend: TrendResult, vol: VolatilityLabel,
                     structure: StructureLabel,
                     structure_desc: str) -> tuple[Regime, str]:
    slope = ("rising" if "slope rising" in trend.detail else
             "falling" if "slope falling" in trend.detail else "flat")
    if vol == VolatilityLabel.EXTREME:
        return Regime.HIGH_VOLATILITY, (
            "ATR is in the top band of its recent range; conditions are "
            f"unstable regardless of direction ({structure_desc.lower()}).")
    if trend.label == TrendLabel.BULLISH and structure != StructureLabel.DOWNTREND_STRUCTURE:
        easing = " Directional pressure is easing while the trend holds." if slope == "flat" else ""
        return Regime.TRENDING_UP, (
            f"Price holds above the EMA cluster; EMA20 slope is {slope}; "
            f"swing structure: {structure_desc}.{easing}")
    if trend.label == TrendLabel.BEARISH and structure != StructureLabel.UPTREND_STRUCTURE:
        easing = " Directional pressure is easing while the trend holds." if slope == "flat" else ""
        return Regime.TRENDING_DOWN, (
            f"Price holds below the EMA cluster; EMA20 slope is {slope}; "
            f"swing structure: {structure_desc}.{easing}")
    if trend.label == TrendLabel.RANGING or structure == StructureLabel.RANGE:
        return Regime.RANGING, ("Price oscillates around compressed EMAs; "
                                "swings show no directional progression.")
    if vol == VolatilityLabel.LOW:
        return Regime.LOW_VOLATILITY, ("ATR sits in the lowest band of its recent "
                                       "range and directional signals are weak.")
    return Regime.UNCERTAIN, "Signals are mixed; no dominant condition detected."