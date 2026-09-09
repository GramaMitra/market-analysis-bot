"""Walk-forward tests on synthetic data (no MT5)."""
import pytest

from research.walkforward import run_walkforward, summarize
from tests.test_analysis import make_df, ramp_down, ramp_up


def test_walkforward_row_count_and_fields():
    df = make_df(ramp_up(120))
    rows = run_walkforward(df, "EURUSD", "M5", warmup=60, step=1,
                           forward=2, progress_every=0)
    assert len(rows) == 59                    # end runs 60..118 inclusive
    r = rows[0]
    assert r.fwd_up_atr > 0                   # price rose above the close
    assert r.fwd_down_atr >= 0                # excursions are non-negative by definition
    assert r.fwd_ret_atr > 0                  # net forward move up in a rising fixture


def test_walkforward_forward_return_is_signed():
    df = make_df(ramp_down(120))
    rows = run_walkforward(df, "EURUSD", "M5", warmup=60, step=1,
                           forward=2, progress_every=0)
    assert rows[0].fwd_ret_atr < 0
    assert rows[0].fwd_up_atr >= 0


def test_walkforward_rejects_short_history():
    with pytest.raises(ValueError):
        run_walkforward(make_df(ramp_up(70)), "EURUSD", "M5",
                        warmup=60, forward=12)


def test_summarize_mentions_honesty_disclaimer():
    df = make_df(ramp_up(80))
    rows = run_walkforward(df, "EURUSD", "M5", warmup=60, forward=2,
                           progress_every=0)
    assert "NOT a profitability backtest" in summarize(rows)