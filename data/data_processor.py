"""
Candle normalization, structural validation and resampling.

Pure DataFrame layer: no MetaTrader imports. mt5_client feeds raw MT5
records through prepare_ohlcv()/validate_ohlc(); the same functions will
accept historical CSV/SQLite data in research mode (Phase 24).
"""
from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger("data.data_processor")

REQUIRED_COLUMNS = {"time", "open", "high", "low", "close"}

# standard timeframes -> minutes and pandas offset rules
TF_MINUTES = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60, "H4": 240, "D1": 1440}
RESAMPLE_RULES = {"M1": "1min", "M5": "5min", "M15": "15min", "M30": "30min",
                  "H1": "1h", "H4": "4h", "D1": "1D"}

_KEEP = ("time", "open", "high", "low", "close", "tick_volume")


def prepare_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize column dtypes and order; sort chronologically."""
    if "time" not in df.columns:
        raise ValueError("Input DataFrame has no 'time' column.")
    df = df.copy()
    df["time"] = pd.to_datetime(df["time"])
    for col in _KEEP[1:]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    keep = [c for c in _KEEP if c in df.columns]
    return df[keep].sort_values("time").reset_index(drop=True)


def validate_ohlc(df: pd.DataFrame, symbol: str = "") -> pd.DataFrame:
    """Structural validation/cleaning. Raises ValueError if nothing survives."""
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"OHLC data for {symbol} is missing columns: {sorted(missing)}")

    label = f"{symbol}: " if symbol else ""

    before = len(df)
    df = df.dropna(subset=["open", "high", "low", "close"])
    if before - len(df):
        logger.warning("%sdropped %d rows with NaN prices", label, before - len(df))

    before = len(df)
    df = (df.drop_duplicates(subset="time")
            .sort_values("time")
            .reset_index(drop=True))
    if before - len(df):
        logger.warning("%sremoved %d duplicate timestamps", label, before - len(df))

    # high must dominate, low must be dominated
    bad = df["high"] < df[["open", "close", "low"]].max(axis=1)
    bad |= df["low"] > df[["open", "close", "high"]].min(axis=1)
    if bad.any():
        logger.warning("%sdropping %d structurally invalid candles",
                       label, int(bad.sum()))
        df = df[~bad].reset_index(drop=True)

    if df.empty:
        raise ValueError(f"All candles for {symbol} failed validation.")
    return df


def resample_ohlcv(df: pd.DataFrame, source_tf: str, target_tf: str) -> pd.DataFrame:
    """Aggregate lower-timeframe candles into a higher timeframe (upsampling only).

    Output candles are left-labeled (a 10:00 M15 candle covers 10:00-10:15,
    matching MT5). Empty bins (weekends, session gaps) are dropped. The final
    bucket may be built from a still-forming source candle and is re-validated
    through the same validate_ohlc() used for live data.
    """
    src, tgt = source_tf.upper(), target_tf.upper()
    for tf in (src, tgt):
        if tf not in TF_MINUTES:
            raise ValueError(f"Unknown timeframe '{tf}'. Supported: {sorted(TF_MINUTES)}")
    if TF_MINUTES[tgt] < TF_MINUTES[src]:
        raise ValueError(f"Cannot resample {src} -> {tgt}: target must be >= source.")
    if TF_MINUTES[tgt] % TF_MINUTES[src] != 0:
        raise ValueError(f"{tgt} is not a whole multiple of {src}; candles would misalign.")
    if src == tgt:
        return df.copy()
    if tgt == "D1":
        logger.warning("D1 resampling uses calendar boundaries; "
                       "prefer fetching D1 directly from MT5.")

    agg: dict[str, str] = {"open": "first", "high": "max", "low": "min", "close": "last"}
    if "tick_volume" in df.columns:
        agg["tick_volume"] = "sum"

    out = (df.set_index("time")
             .resample(RESAMPLE_RULES[tgt], label="left", closed="left")
             .agg(agg)
             .dropna(subset=["open", "high", "low", "close"])   # drop empty bins
             .reset_index())

    out = validate_ohlc(out)
    logger.info("Resampled %d x %s -> %d x %s candles", len(df), src, len(out), tgt)
    return out