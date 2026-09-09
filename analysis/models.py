"""Shared data models for the analysis layer."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

import pandas as pd


class TrendLabel(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    RANGING = "RANGING"
    UNCERTAIN = "UNCERTAIN"


class MomentumLabel(str, Enum):
    STRONG = "STRONG"
    MODERATE = "MODERATE"
    WEAK = "WEAK"
    NEUTRAL = "NEUTRAL"


class VolatilityLabel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    EXTREME = "EXTREME"


class StructureLabel(str, Enum):
    UPTREND_STRUCTURE = "UPTREND_STRUCTURE"
    DOWNTREND_STRUCTURE = "DOWNTREND_STRUCTURE"
    RANGE = "RANGE"
    UNCERTAIN = "UNCERTAIN"


class Regime(str, Enum):
    TRENDING_UP = "TRENDING_UP"
    TRENDING_DOWN = "TRENDING_DOWN"
    RANGING = "RANGING"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    LOW_VOLATILITY = "LOW_VOLATILITY"
    UNCERTAIN = "UNCERTAIN"


class Alignment(str, Enum):
    ALIGNED = "ALIGNED"
    PARTIALLY_ALIGNED = "PARTIALLY_ALIGNED"
    CONFLICTING = "CONFLICTING"
    UNCERTAIN = "UNCERTAIN"


@dataclass(frozen=True)
class SwingPoint:
    index: int
    time: pd.Timestamp
    price: float
    kind: str          # "high" | "low"


@dataclass
class TrendResult:
    label: TrendLabel
    score: int                     # -100 .. +100 (normalized)
    ema20: float | None
    ema50: float | None
    ema200: float | None
    detail: str


@dataclass
class MomentumResult:
    label: MomentumLabel
    score: int                     # -100 .. +100
    rsi: float | None
    macd_hist: float | None
    roc: float | None
    detail: str


@dataclass
class VolatilityResult:
    label: VolatilityLabel
    atr: float
    atr_percentile: float          # 0..100 vs the symbol's own recent ATR history
    detail: str


@dataclass
class StructureResult:
    label: StructureLabel
    score: int                     # -60 / 0 / +60
    description: str
    support: float | None
    resistance: float | None
    swings: list[SwingPoint] = field(repr=False, default_factory=list)


@dataclass
class AnalysisResult:
    symbol: str
    timeframe: str
    generated_at: pd.Timestamp
    close: float
    digits: int
    candles_used: int
    has_ema200: bool
    trend: TrendResult
    momentum: MomentumResult
    volatility: VolatilityResult
    structure: StructureResult
    regime: Regime
    regime_reason: str
    alignment: Alignment = Alignment.UNCERTAIN
    mtf_trends: dict[str, TrendLabel] = field(default_factory=dict)
    score: int = 0                 # 0..100 "analytical alignment", NOT probability
    confidence: str = "LOW"        # LOW / MODERATE / HIGH