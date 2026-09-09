"""Unit tests for analysis.indicators (pure math, no MT5 needed).

Run from the project root:  python -m pytest -v
"""
import numpy as np
import pandas as pd
import pytest

from analysis.indicators import (atr, ema, macd, roc, rolling_std, rsi, sma,
                                 true_range)


def series(values):
    return pd.Series(values, dtype=float)


# ---------------------------------------------------------------- EMA -----
def test_ema_of_constant_series_is_constant():
    e = ema(series([5.0] * 20), 10)
    assert e.iloc[-1] == pytest.approx(5.0)
    assert e.isna().sum() == 9                    # warm-up: period-1 NaNs


def test_ema_manual_recurrence():
    # alpha = 2/(3+1) = 0.5; e0=1, e1=.5*2+.5*1=1.5, e2=.5*3+.5*1.5=2.25
    e = ema(series([1.0, 2.0, 3.0]), 3)
    assert e.isna().tolist() == [True, True, False]
    assert e.iloc[2] == pytest.approx(2.25)


def test_ema_rejects_bad_input():
    with pytest.raises(ValueError):
        ema(series([]), 5)
    with pytest.raises(ValueError):
        ema(series([1.0, np.nan, 3.0]), 2)
    with pytest.raises(ValueError):
        ema(series([1.0, 2.0]), 0)


# ---------------------------------------------------------------- RSI -----
def test_rsi_monotonic_rise_is_100():
    assert rsi(series(np.arange(1.0, 40.0)), 14).iloc[-1] == pytest.approx(100.0)


def test_rsi_monotonic_fall_is_0():
    assert rsi(series(np.arange(40.0, 1.0, -1.0)), 14).iloc[-1] == pytest.approx(0.0)


def test_rsi_flat_series_is_50():
    assert rsi(series([7.0] * 30), 14).iloc[-1] == pytest.approx(50.0)


def test_rsi_hand_computed_wilder_values():
    r = rsi(series([10.0, 11.0, 10.5, 12.5]), 2)
    assert r.isna().tolist() == [True, True, False, False]
    # seed: avg_gain=.5, avg_loss=.25 -> RSI = 100 - 100/3 = 66.667
    assert r.iloc[2] == pytest.approx(66.6667, abs=1e-4)
    # next: gain=1.25, loss=.125 -> RS=10 -> RSI = 100 - 100/11 = 90.909
    assert r.iloc[3] == pytest.approx(90.9091, abs=1e-4)


def test_rsi_too_short_raises():
    with pytest.raises(ValueError):
        rsi(series([1.0, 2.0, 3.0]), 14)


# ---------------------------------------------------------------- ATR -----
def test_atr_constant_range_is_constant():
    n = 30
    a = atr(series([11.0] * n), series([9.0] * n), series([10.0] * n), 14)
    assert a.isna().sum() == 14
    assert a.iloc[14] == pytest.approx(2.0)       # first Wilder value at index == period
    assert a.iloc[-1] == pytest.approx(2.0)


def test_atr_gap_hand_computed():
    high = series([12.0, 13.0, 14.0, 18.0, 14.0])
    low = series([10.0, 11.0, 12.0, 15.0, 11.0])
    close = series([11.0, 12.0, 13.0, 16.0, 12.0])
    # TRs: 2, 2, 2, then gap bar max(3, |18-13|=5, 2)=5, then max(3, 2, |11-16|=5)=5
    assert true_range(high, low, close).tolist() == pytest.approx([2.0, 2.0, 2.0, 5.0, 5.0])
    a = atr(high, low, close, 3)
    assert a.isna().tolist() == [True, True, True, False, False]
    assert a.iloc[3] == pytest.approx((2 + 2 + 5) / 3)          # 3.0 (seed)
    assert a.iloc[4] == pytest.approx((3.0 * 2 + 5) / 3)        # 11/3 = 3.6667


def test_atr_too_short_raises():
    with pytest.raises(ValueError):
        atr(series([1.0] * 3), series([0.5] * 3), series([0.8] * 3), 14)


# --------------------------------------------------------------- MACD -----
def test_macd_constant_series_is_zero():
    m, s, h = macd(series([100.0] * 60))
    assert m.iloc[-1] == pytest.approx(0.0, abs=1e-9)
    assert s.iloc[-1] == pytest.approx(0.0, abs=1e-9)
    assert h.iloc[-1] == pytest.approx(0.0, abs=1e-9)


def test_macd_positive_in_sustained_rally():
    m, s, h = macd(series(np.linspace(1.0, 2.0, 60)), fast=5, slow=10, signal=3)
    assert m.iloc[-1] > 0
    assert h.iloc[-1] > 0        # MACD above its signal while the trend persists


def test_macd_rejects_fast_ge_slow():
    with pytest.raises(ValueError):
        macd(series([1.0] * 50), fast=26, slow=12)


# ---------------------------------------------------------------- ROC -----
def test_roc_known_values():
    r = roc(series([100.0, 110.0, 121.0]), 2)
    assert r.isna().tolist() == [True, True, False]
    assert r.iloc[2] == pytest.approx(21.0)


def test_roc_single_period():
    assert roc(series([100.0, 110.0]), 1).iloc[1] == pytest.approx(10.0)


# -------------------------------------------------------- sma / rollstd ---
def test_sma_known_values():
    s = sma(series([1.0, 2.0, 3.0, 4.0]), 2)
    assert s.iloc[1] == pytest.approx(1.5)
    assert s.iloc[3] == pytest.approx(3.5)


def test_rolling_std_known_value():
    r = rolling_std(series([2.0, 4.0, 6.0]), 3)
    assert r.isna().tolist() == [True, True, False]
    assert r.iloc[2] == pytest.approx(2.0)        # sample std (ddof=1)