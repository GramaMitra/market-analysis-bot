"""Unit tests for the data layer: normalization, validation, resampling."""
from datetime import datetime

import pandas as pd
import pytest

from data.data_processor import prepare_ohlcv, resample_ohlcv, validate_ohlc


def make_ohlcv(rows):
    return pd.DataFrame(rows,
                        columns=["time", "open", "high", "low", "close", "tick_volume"])


# ---------------------------------------------------- prepare / validate --
def test_prepare_coerces_and_sorts():
    df = make_ohlcv([
        (datetime(2025, 1, 1, 0, 10), "1.2", 2, 1, 1.5, 10),
        (datetime(2025, 1, 1, 0, 5), "1.1", 2, 1, 1.2, 5),
    ])
    out = prepare_ohlcv(df)
    assert list(out["time"]) == [datetime(2025, 1, 1, 0, 5), datetime(2025, 1, 1, 0, 10)]
    assert out["open"].dtype.kind == "f"


def test_validate_drops_structurally_bad_candles():
    df = make_ohlcv([
        (datetime(2025, 1, 1, 0, 5), 1.0, 2.0, 0.5, 1.5, 10),
        (datetime(2025, 1, 1, 0, 10), 1.5, 1.4, 0.9, 1.2, 10),   # high < close
        (datetime(2025, 1, 1, 0, 15), 1.2, 1.8, 1.1, 1.7, 10),
    ])
    assert len(validate_ohlc(df, "TEST")) == 2


def test_validate_removes_duplicates():
    t = datetime(2025, 1, 1, 0, 5)
    df = make_ohlcv([(t, 1, 2, 0.5, 1.5, 10), (t, 1, 2, 0.5, 1.6, 12)])
    assert len(validate_ohlc(df, "TEST")) == 1


def test_validate_raises_when_all_invalid():
    df = make_ohlcv([(datetime(2025, 1, 1), 5.0, 1.0, 4.0, 2.0, 1)])   # high < low
    with pytest.raises(ValueError):
        validate_ohlc(df, "TEST")


# ------------------------------------------------------------ resampling --
def test_resample_m5_to_m15_aggregates():
    df = make_ohlcv([
        (datetime(2025, 1, 1, 10, 0), 1.0, 2.0, 0.5, 1.5, 10),
        (datetime(2025, 1, 1, 10, 5), 1.5, 3.0, 1.0, 2.5, 20),
        (datetime(2025, 1, 1, 10, 10), 2.5, 4.0, 2.0, 3.0, 30),
        (datetime(2025, 1, 1, 10, 15), 3.0, 3.5, 2.5, 3.0, 5),
        (datetime(2025, 1, 1, 10, 20), 3.0, 5.0, 2.9, 4.5, 6),
        (datetime(2025, 1, 1, 10, 25), 4.5, 5.0, 4.0, 5.0, 7),
    ])
    out = resample_ohlcv(df, "M5", "M15")
    assert len(out) == 2
    first, second = out.iloc[0], out.iloc[1]
    assert first["open"] == pytest.approx(1.0)
    assert first["high"] == pytest.approx(4.0)
    assert first["low"] == pytest.approx(0.5)
    assert first["close"] == pytest.approx(3.0)
    assert first["tick_volume"] == 60
    assert second["close"] == pytest.approx(5.0)
    assert second["tick_volume"] == 18


def test_resample_drops_empty_gap_bins():
    # gap between 10:10 and 10:45 -> empty 10:15 / 10:30 bins must not appear
    df = make_ohlcv([
        (datetime(2025, 1, 1, 10, 0), 1, 2, 0.5, 1.5, 1),
        (datetime(2025, 1, 1, 10, 5), 1.5, 2, 1, 1.2, 1),
        (datetime(2025, 1, 1, 10, 10), 1.2, 2, 1, 1.8, 1),
        (datetime(2025, 1, 1, 10, 45), 1.8, 2.5, 1.7, 2.2, 1),
        (datetime(2025, 1, 1, 10, 50), 2.2, 3, 2, 2.8, 1),
        (datetime(2025, 1, 1, 10, 55), 2.8, 3, 2.5, 2.6, 1),
    ])
    out = resample_ohlcv(df, "M5", "M15")
    assert list(out["time"]) == [datetime(2025, 1, 1, 10, 0), datetime(2025, 1, 1, 10, 45)]


def test_resample_rejects_downsampling_and_unknown_tf():
    df = make_ohlcv([(datetime(2025, 1, 1), 1, 2, 0.5, 1.5, 1)])
    with pytest.raises(ValueError):
        resample_ohlcv(df, "M15", "M5")     # downsampling
    with pytest.raises(ValueError):
        resample_ohlcv(df, "M5", "M7")      # not a standard timeframe