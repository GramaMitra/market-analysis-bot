"""
Market analysis bot — read-only MT5 analysis.

CLI:    python main.py --symbol EURUSD --timeframe M5 [--table] [--no-mtf]
        python main.py --symbol EURUSD --timeframe M5 --count 90 --resample M15
Telegram: python main.py --bot
"""
from __future__ import annotations

import argparse
import sys

import config
from analysis.service import run_analysis
from config import (ANALYSIS_MIN_CANDLES, DEFAULT_SYMBOL, DEFAULT_TIMEFRAME,
                    LOOKBACK_CANDLES)
from data.data_processor import resample_ohlcv
from data.mt5_client import MT5Client, MT5ConnectionError, SymbolNotFoundError
from reporting.formatter import format_report
from telegram_bot.bot import run_bot
from utils.logger import setup_logging

from research.walkforward import run_walkforward, save_csv, summarize


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Read-only MT5 market analysis bot.")
    p.add_argument("--bot", action="store_true", help="Run the Telegram bot")
    p.add_argument("--symbol", default=DEFAULT_SYMBOL)
    p.add_argument("--timeframe", default=DEFAULT_TIMEFRAME,
                   choices=sorted(config.TIMEFRAME_MAP))
    p.add_argument("--count", type=int, default=LOOKBACK_CANDLES)
    p.add_argument("--resample", default=None, metavar="TF")
    p.add_argument("--table", action="store_true")
    p.add_argument("--no-mtf", action="store_true")
    p.add_argument("--research", action="store_true",
                   help="Walk-forward research mode over historical candles")
    p.add_argument("--bars", type=int, default=3000,
                   help="History length for --research (max 20000)")
    p.add_argument("--warmup", type=int, default=500)
    p.add_argument("--forward", type=int, default=12,
                   help="Forward bars to measure after each analysis")
    p.add_argument("--step", type=int, default=1,
                   help="Analyze every Nth bar (use 5+ for long histories)")
    return p.parse_args()


def run_cli(args) -> int:
    client = MT5Client()
    try:
        print("Connecting to MetaTrader 5...")
        try:
            client.connect()
        except MT5ConnectionError as exc:
            print(f"Connection failed: {exc}\n"
                  "Hints: terminal running/logged in? MT5_PATH set in .env?")
            return 1
        print("Connected ✓")

        try:
            symbol = client.resolve_symbol(args.symbol.strip())
        except SymbolNotFoundError as exc:
            print(f"Symbol error: {exc}")
            return 1

        timeframe, count = args.timeframe.upper(), max(
            ANALYSIS_MIN_CANDLES, min(args.count, 5000))

        base_df = None
        if args.resample:
            try:
                base_df = resample_ohlcv(
                    client.get_candles(symbol, timeframe, count),
                    timeframe, args.resample.upper())
                timeframe = args.resample.upper()
            except (MT5ConnectionError, ValueError) as exc:
                print(f"Data/resample error: {exc}")
                return 1

        print(f"Fetching {symbol} {timeframe}...\nRunning analysis...")
        try:
            result = run_analysis(client, symbol, timeframe,
                                  count=count, do_mtf=not args.no_mtf,
                                  base_df=base_df)
        except (MT5ConnectionError, SymbolNotFoundError, ValueError) as exc:
            print(f"Analysis error: {exc}")
            return 1

        print()
        print(format_report(result))

        if args.table and base_df is not None:
            digits = result.digits
            view = base_df.tail(10).copy()
            view["time"] = view["time"].dt.strftime("%Y-%m-%d %H:%M")
            for col in ("open", "high", "low", "close"):
                view[col] = view[col].map(lambda v, d=digits: f"{v:.{d}f}")
            print("\n" + view[["time", "open", "high", "low", "close",
                               "tick_volume"]].to_string(index=False))
        print("\nDone ✓")
        return 0
    finally:
        client.shutdown()

def run_research(args) -> int:
    from pathlib import Path
    client = MT5Client()
    try:
        print("Connecting to MetaTrader 5...")
        client.connect()
        print("Connected ✓")
        symbol = client.resolve_symbol(args.symbol.strip())
        bars = max(args.warmup + args.forward + 1, min(args.bars, 20000))
        print(f"Fetching {bars} x {args.timeframe} candles for {symbol}...")
        df = client.get_candles(symbol, args.timeframe.upper(), bars)
    except (MT5ConnectionError, SymbolNotFoundError) as exc:
        print(f"Research setup failed: {exc}")
        return 1
    finally:
        client.shutdown()

    print(f"Running walk-forward: warmup={args.warmup} step={args.step} "
          f"forward={args.forward} ...")
    try:
        rows = run_walkforward(df, symbol, args.timeframe.upper(),
                               warmup=args.warmup, step=args.step,
                               forward=args.forward)
    except ValueError as exc:
        print(f"Research error: {exc}")
        return 1

    out = Path("research_out") / f"{symbol}_{args.timeframe}_walkforward.csv"
    save_csv(rows, out)
    print(summarize(rows))
    print(f"\nCSV written: {out}")
    print("Research complete ✓")
    return 0

def main() -> int:
    args = parse_args()
    setup_logging()
    if args.bot:
        return run_bot()
    if args.research:
        return run_research(args)
    return run_cli(args)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
        sys.exit(130)