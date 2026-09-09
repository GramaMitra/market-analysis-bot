"""Persistence tests (tmp file, no MT5)."""
import pandas as pd
import pytest

from analysis.analyzer import analyze
from data.data_processor import prepare_ohlcv
from storage.database import Database


def _flat_df():
    closes = pd.Series([100.0] * 60, dtype=float)
    df = pd.DataFrame({"time": pd.date_range("2025-01-01", periods=60, freq="5min"),
                       "open": closes, "high": closes + 0.1, "low": closes - 0.1,
                       "close": closes, "tick_volume": 100})
    return prepare_ohlcv(df)


def test_save_and_read_back(tmp_path):
    db = Database(tmp_path / "t.sqlite3")
    result = analyze(_flat_df(), "EURUSD", "M5")
    rid = db.save_analysis(result, "REPORT-TEXT")
    assert rid == 1
    row = db.last_analysis("eurusd", "m5")     # case-insensitive lookup
    assert row is not None
    ts, regime, trend, score = row
    assert regime == result.regime.value
    assert trend == result.trend.label.value
    assert score == result.score


def test_last_analysis_missing_returns_none(tmp_path):
    db = Database(tmp_path / "t.sqlite3")
    assert db.last_analysis("NOSUCH", "M5") is None