"""Deterministic signal-EVENT detection.

A "signal" here is a factual state transition of an indicator or price
relative to a level: a crossover happened, RSI left a zone, volatility
expanded. Events are descriptive, never directives: this module must
never emit BUY/SELL, entries, stops, targets or probabilities
(spec §29/§30). The forbidden-word test pins this contract.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

from analysis.indicators import atr as atr_fn
from analysis.indicators import ema, macd as macd_fn, rsi as rsi_fn

log = logging.getLogger("analysis.signals")

FORBIDDEN_WORDS = ("buy", "sell", "entry ", "target", "profit",
                   "probability", "predict", "advice")

KIND_EMA_UP = "EMA_CROSS_UP"
KIND_EMA_DOWN = "EMA_CROSS_DOWN"
KIND_RSI_ENTER_OB = "RSI_ENTERED_OVERBOUGHT"
KIND_RSI_EXIT_OB = "RSI_EXITED_OVERBOUGHT"
KIND_RSI_ENTER_OS = "RSI_ENTERED_OVERSOLD"
KIND_RSI_EXIT_OS = "RSI_EXITED_OVERSOLD"
KIND_MACD_POS = "MACD_HIST_FLIPPED_POSITIVE"
KIND_MACD_NEG = "MACD_HIST_FLIPPED_NEGATIVE"
KIND_NEAR_SUPPORT = "PRICE_NEAR_SUPPORT"
KIND_NEAR_RESISTANCE = "PRICE_NEAR_RESISTANCE"
KIND_VOL_EXPANSION = "VOLATILITY_EXPANSION"
KIND_VOL_CONTRACTION = "VOLATILITY_CONTRACTION"


@dataclass(frozen=True)
class SignalEvent:
    kind: str
    bar_time: pd.Timestamp
    detail: str

    def human(self) -> str:
        return f"{_HUMAN[self.kind]} ({self.detail})" if self.detail \
            else _HUMAN[self.kind]


_HUMAN = {
    KIND_EMA_UP: "EMA20 crossed above EMA50",
    KIND_EMA_DOWN: "EMA20 crossed below EMA50",
    KIND_RSI_ENTER_OB: "RSI entered the overbought zone (>70)",
    KIND_RSI_EXIT_OB: "RSI left the overbought zone (back below 70)",
    KIND_RSI_ENTER_OS: "RSI entered the oversold zone (<30)",
    KIND_RSI_EXIT_OS: "RSI left the oversold zone (back above 30)",
    KIND_MACD_POS: "MACD histogram turned positive (downward momentum fading)",
    KIND_MACD_NEG: "MACD histogram turned negative (upward momentum fading)",
    KIND_NEAR_SUPPORT: "Price is near algorithmic support",
    KIND_NEAR_RESISTANCE: "Price is near algorithmic resistance",
    KIND_VOL_EXPANSION: "Volatility expanding (ATR percentile rising)",
    KIND_VOL_CONTRACTION: "Volatility contracting (ATR percentile falling)",
}


def _near_level(price: float, level: float | None,
                atr_value: float, tol_atr: float) -> bool:
    return level is not None and abs(price - level) <= tol_atr * atr_value


def _midrank_percentile(value: float, history: np.ndarray) -> float:
    """Percentile (0..100) of `value` within `history`, midrank for ties."""
    hist = history[~np.isnan(history)]
    if len(hist) == 0:
        return np.nan
    less = float((hist < value).sum())
    ties = float((hist == value).sum())
    return 100.0 * (less + 0.5 * ties) / len(hist)


def detect_signals(df: pd.DataFrame, result, window: int = 2,
                   rsi_ob: float = 70.0, rsi_os: float = 30.0,
                   vol_exp_pctl: float = 85.0, vol_con_pctl: float = 25.0,
                   sr_tol_atr: float = 0.5) -> list[SignalEvent]:
    """Detect state-transition events within the last `window` bars.

    `result` is the AnalysisResult for the SAME df (used for S/R levels,
    ATR and price digits). Pure function: no I/O, no network.
    """
    n = len(df)
    if n < 60 or window < 1:
        return []

    close = df["close"].astype(float).reset_index(drop=True)
    times = df["time"].reset_index(drop=True)
    start = max(50, n - window)          # EMA50 first valid at idx 49

    e20 = ema(close, 20).to_numpy(dtype=float)
    e50 = ema(close, 50).to_numpy(dtype=float)
    rsi_v = rsi_fn(close, 14).to_numpy(dtype=float)
    _, _, hist = macd_fn(close)
    hist = hist.to_numpy(dtype=float)
    atr_s = atr_fn(df["high"], df["low"], close, 14).to_numpy(dtype=float)

    events: list[SignalEvent] = []
    seen: set[tuple[str, pd.Timestamp]] = set()

    def emit(kind: str, i: int, detail: str = "") -> None:
        key = (kind, times.iloc[i])
        if key not in seen:
            seen.add(key)
            events.append(SignalEvent(kind, times.iloc[i], detail))

    for i in range(start, n):
        # --- EMA20/EMA50 crossover -------------------------------------
        if not (np.isnan(e20[i - 1]) or np.isnan(e50[i - 1])):
            if e20[i - 1] <= e50[i - 1] and e20[i] > e50[i]:
                emit(KIND_EMA_UP, i, f"EMA20 {e20[i]:.5g} > EMA50 {e50[i]:.5g}")
            elif e20[i - 1] >= e50[i - 1] and e20[i] < e50[i]:
                emit(KIND_EMA_DOWN, i, f"EMA20 {e20[i]:.5g} < EMA50 {e50[i]:.5g}")

        # --- RSI zone transitions --------------------------------------
        if not np.isnan(rsi_v[i - 1]):
            p, c = rsi_v[i - 1], rsi_v[i]
            if p > rsi_os and c <= rsi_os:
                emit(KIND_RSI_ENTER_OS, i, f"RSI {c:.1f}")
            elif p <= rsi_os and c > rsi_os:
                emit(KIND_RSI_EXIT_OS, i, f"RSI {c:.1f}")
            elif p < rsi_ob and c >= rsi_ob:
                emit(KIND_RSI_ENTER_OB, i, f"RSI {c:.1f}")
            elif p >= rsi_ob and c < rsi_ob:
                emit(KIND_RSI_EXIT_OB, i, f"RSI {c:.1f}")

        # --- MACD histogram sign flip ----------------------------------
        if not (np.isnan(hist[i - 1]) or np.isnan(hist[i])):
            if hist[i - 1] <= 0 < hist[i]:
                emit(KIND_MACD_POS, i, f"hist {hist[i]:.5g}")
            elif hist[i - 1] >= 0 > hist[i]:
                emit(KIND_MACD_NEG, i, f"hist {hist[i]:.5g}")

        # --- Volatility regime transitions (ATR percentile) ------------
        if i >= 15 and not np.isnan(atr_s[i - 1]) and not np.isnan(atr_s[i]):
            p_prev = _midrank_percentile(atr_s[i - 1], atr_s[:i])
            p_cur = _midrank_percentile(atr_s[i], atr_s[:i + 1])
            if not np.isnan(p_prev) and not np.isnan(p_cur):
                if p_prev < vol_exp_pctl <= p_cur:
                    emit(KIND_VOL_EXPANSION, i, f"ATR percentile {p_cur:.0f}")
                elif p_prev > vol_con_pctl >= p_cur:
                    emit(KIND_VOL_CONTRACTION, i, f"ATR percentile {p_cur:.0f}")

    # --- S/R proximity (current bar only; cooldown handles repetition) --
    c_now = float(close.iloc[-1])
    atr_now = float(atr_s[-1]) if not np.isnan(atr_s[-1]) else 0.0
    if atr_now > 0:
        if _near_level(c_now, result.structure.support, atr_now, sr_tol_atr):
            emit(KIND_NEAR_SUPPORT, n - 1,
                 f"support {result.structure.support:.{result.digits}f}, "
                 f"dist {abs(c_now - result.structure.support) / atr_now:.2f} ATR")
        if _near_level(c_now, result.structure.resistance, atr_now, sr_tol_atr):
            emit(KIND_NEAR_RESISTANCE, n - 1,
                 f"resistance {result.structure.resistance:.{result.digits}f}, "
                 f"dist {abs(c_now - result.structure.resistance) / atr_now:.2f} ATR")

    return events