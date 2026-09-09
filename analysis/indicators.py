"""
Deterministic technical indicators (pure math, no MT5, no I/O).

Conventions (documented so tests and future readers can verify):
* EMA / MACD : standard EMA with alpha = 2/(period+1), recursion seeded
  with the first value (pandas ewm(span=..., adjust=False)). Values are
  NaN until `period` observations exist (warm-up), mirroring MT5/TV.
* RSI / ATR  : Wilder's original smoothing. First value = SMA of the
  first `period` changes/true-ranges, then
  avg = (prev_avg*(period-1) + current) / period.
* RSI edge cases: no losses -> 100, no gains -> 0, no movement -> 50
  (zero movement is neutral, not "overbought").
* Rolling std uses sample std (ddof=1).

All functions raise ValueError/TypeError on empty, non-numeric or
NaN-containing input, and on impossible parameters.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


# ------------------------------------------------------------ validators --

def _validate_series(s: pd.Series, name: str) -> None:
    if not isinstance(s, pd.Series):
        raise TypeError(f"{name} must be a pandas Series, got {type(s).__name__}.")
    if len(s) == 0:
        raise ValueError(f"{name} is empty.")
    if not pd.api.types.is_numeric_dtype(s):
        raise TypeError(f"{name} must be numeric, got dtype {s.dtype}.")
    if s.isna().any():
        raise ValueError(f"{name} contains NaN values; validate/clean data first.")


def _validate_period(period: int) -> None:
    if not isinstance(period, (int, np.integer)) or period < 1:
        raise ValueError(f"period must be a positive integer, got {period!r}.")


# ------------------------------------------------------------ averages ----

def sma(close: pd.Series, period: int) -> pd.Series:
    """Simple moving average. NaN until `period` observations exist."""
    _validate_series(close, "close")
    _validate_period(period)
    return close.rolling(window=period, min_periods=period).mean()


def ema(close: pd.Series, period: int) -> pd.Series:
    """Exponential moving average (alpha = 2/(period+1), seeded at first value)."""
    _validate_series(close, "close")
    _validate_period(period)
    return close.ewm(span=period, adjust=False, min_periods=period).mean()


def rolling_std(close: pd.Series, period: int = 20) -> pd.Series:
    """Rolling sample standard deviation (ddof=1)."""
    _validate_series(close, "close")
    _validate_period(period)
    return close.rolling(window=period, min_periods=period).std(ddof=1)


# ------------------------------------------------------------ momentum ----

def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's RSI. NaN for the first `period` bars."""
    _validate_series(close, "close")
    _validate_period(period)
    n = len(close)
    if n < period + 1:
        raise ValueError(f"RSI needs at least period+1={period + 1} candles, got {n}.")

    delta = close.diff().to_numpy(dtype=float)
    gain = np.where(delta > 0.0, delta, 0.0)
    loss = np.where(delta < 0.0, -delta, 0.0)

    avg_gain = np.full(n, np.nan)
    avg_loss = np.full(n, np.nan)
    # Wilder seed: simple average of the first `period` changes.
    avg_gain[period] = gain[1:period + 1].mean()
    avg_loss[period] = loss[1:period + 1].mean()

    # Wilder recursion (explicit loop keeps the textbook formula verifiable;
    # at 500 bars the cost is negligible).
    for i in range(period + 1, n):
        avg_gain[i] = (avg_gain[i - 1] * (period - 1) + gain[i]) / period
        avg_loss[i] = (avg_loss[i - 1] * (period - 1) + loss[i]) / period

    out = np.full(n, np.nan)
    for i in range(period, n):
        g, l = avg_gain[i], avg_loss[i]
        if l == 0.0:
            out[i] = 100.0 if g > 0.0 else 50.0   # pure rise / zero movement
        else:
            rs = g / l
            out[i] = 100.0 - 100.0 / (1.0 + rs)

    return pd.Series(out, index=close.index, name=f"rsi_{period}")


def macd(close: pd.Series, fast: int = 12, slow: int = 26,
         signal: int = 9) -> tuple[pd.Series, pd.Series, pd.Series]:
    """MACD line, signal line, histogram. All NaN-prefixed during warm-up."""
    _validate_series(close, "close")
    for name, p in (("fast", fast), ("slow", slow), ("signal", signal)):
        _validate_period(p)
    if fast >= slow:
        raise ValueError(f"fast ({fast}) must be smaller than slow ({slow}).")

    macd_line = (ema(close, fast) - ema(close, slow)).rename("macd")
    # ewm ignores the leading NaNs of macd_line and seeds at its first valid value.
    signal_line = (macd_line.ewm(span=signal, adjust=False,
                                 min_periods=signal).mean().rename("signal"))
    histogram = (macd_line - signal_line).rename("histogram")
    return macd_line, signal_line, histogram


def roc(close: pd.Series, period: int = 9) -> pd.Series:
    """Rate of change in percent over `period` bars."""
    _validate_series(close, "close")
    _validate_period(period)
    if len(close) <= period:
        raise ValueError(f"ROC needs at least period+1={period + 1} candles, got {len(close)}.")
    return ((close / close.shift(period) - 1.0) * 100.0).rename(f"roc_{period}")


# ---------------------------------------------------------- volatility ----

def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    """True Range; first bar falls back to (high - low) since no prev close exists."""
    for s, name in ((high, "high"), (low, "low"), (close, "close")):
        _validate_series(s, name)
    if not len(high) == len(low) == len(close):
        raise ValueError("high, low and close must have the same length.")

    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    tr.iloc[0] = high.iloc[0] - low.iloc[0]
    return tr.rename("true_range")


def atr(high: pd.Series, low: pd.Series, close: pd.Series,
        period: int = 14) -> pd.Series:
    """Wilder's ATR. NaN for the first `period` bars."""
    _validate_period(period)
    n = len(close)
    if n < period + 1:
        raise ValueError(f"ATR needs at least period+1={period + 1} candles, got {n}.")

    tr = true_range(high, low, close).to_numpy(dtype=float)
    out = np.full(n, np.nan)
    out[period] = tr[1:period + 1].mean()          # Wilder seed (first complete TRs)
    for i in range(period + 1, n):
        out[i] = (out[i - 1] * (period - 1) + tr[i]) / period
    return pd.Series(out, index=close.index, name=f"atr_{period}")