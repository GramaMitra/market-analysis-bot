"""Signal-event detection tests (pure, no MT5/Telegram).

Window semantics: the live monitor scans only the newest few bars each
cycle (events are caught as they happen). Tests scan WIDE (default 250)
so mid-fixture transitions are inside the scanned range.
"""
from analysis.analyzer import analyze
from analysis.signals import (FORBIDDEN_WORDS, KIND_EMA_UP, KIND_MACD_POS,
                              KIND_RSI_EXIT_OS, KIND_VOL_EXPANSION,
                              detect_signals)
from tests.test_analysis import make_df


def v_shape(n=300, depth=25.0):
    """Deep fall then full recovery: forces RSI zone exit, MACD flip,
    and an EMA cross-up inside the recovery."""
    half = n // 2
    return [150.0 - (i / half) * depth for i in range(half)] + \
           [125.0 + (i / (n - half)) * depth for i in range(n - half)]


def _detect(closes, window=250):
    df = make_df(closes)
    result = analyze(df, "TEST", "M5", digits=5)
    return df, detect_signals(df, result, window=window)


def test_ema_cross_up_in_v_shape_recovery():
    _, events = _detect(v_shape())
    assert any(e.kind == KIND_EMA_UP for e in events)


def test_rsi_leaves_oversold():
    _, events = _detect(v_shape())
    assert any(e.kind == KIND_RSI_EXIT_OS for e in events)


def test_macd_flips_positive():
    _, events = _detect(v_shape())
    assert any(e.kind == KIND_MACD_POS for e in events)


def test_vol_expansion_detected_on_vol_surge():
    closes = [100.0 + 0.01 * (i % 2) for i in range(240)] + \
             [100.0 + 2.0 * ((i % 2) * 2 - 1) for i in range(60)]
    _, events = _detect(closes)          # wide window covers the surge
    assert any(e.kind == KIND_VOL_EXPANSION for e in events)


def test_no_directional_directive_words_in_any_event():
    _, events = _detect(v_shape())
    assert events                       # sanity: fixture must produce events
    for ev in events:
        text = ev.human().lower()
        for word in FORBIDDEN_WORDS:
            assert word not in text, f"forbidden '{word}' in: {text}"


def test_short_data_returns_empty():
    # detect_signals guards n < 60 BEFORE touching `result`, so None is safe
    # here -- this tests the guard itself, not analyze()'s minimum.
    df = make_df(v_shape(50))
    assert detect_signals(df, None, window=10) == []