"""Shared analysis pipeline used by the CLI, the Telegram bot and the monitor."""
from __future__ import annotations

import logging

import config
from analysis.analyzer import add_mtf, analyze
from analysis.models import AnalysisResult
from data.mt5_client import MT5Client

log = logging.getLogger("analysis.service")


def run_analysis(client: MT5Client, symbol: str, timeframe: str, *,
                 count: int | None = None, do_mtf: bool = True,
                 base_df=None, return_df: bool = False):
    """Resolve -> fetch -> analyze -> (optional) MTF context.

    Returns AnalysisResult, or (AnalysisResult, df) when return_df=True.
    """
    count = count or config.LOOKBACK_CANDLES
    client.ensure_connected()
    symbol = client.resolve_symbol(symbol)
    df = base_df if base_df is not None else client.get_candles(symbol, timeframe, count)
    digits = client.get_symbol_digits(symbol)
    result = analyze(df, symbol, timeframe, digits=digits)

    if do_mtf:
        mtf = {}
        for tf in config.MTF_SETS.get(timeframe, [timeframe]):
            if tf == timeframe:
                mtf[tf] = result
                continue
            try:
                mdf = client.get_candles(symbol, tf, count)
                mtf[tf] = analyze(mdf, symbol, tf, digits=digits)
            except Exception as exc:
                log.warning("MTF %s skipped: %s", tf, exc)
        if mtf:
            result = add_mtf(result, mtf)
    return (result, df) if return_df else result