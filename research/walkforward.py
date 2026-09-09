"""Walk-forward research: run the live analysis engine over historical
candles and record forward outcomes.

For every `step`-th bar (after `warmup` bars of history), the exact live
`analyze()` runs on the window ending at that bar; the following
`measured in ATR units (excursions clamped at 0; net return signed):
  fwd_up_atr   = max(0, (max high  - close) / ATR)   0 = never rose above
  fwd_down_atr = max(0, (close - min low ) / ATR)    0 = never fell below
  fwd_ret_atr  = (last close - close) / ATR          signed

This is an association study between analytical states and subsequent
movement -- NOT a profitability backtest (no costs/execution/slippage).
"""
from __future__ import annotations

import csv
import logging
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd

from analysis.analyzer import analyze

log = logging.getLogger("research")

MAX_BARS = 20000


@dataclass
class ForwardOutcome:
    ts_utc: str
    regime: str
    trend: str
    momentum: str
    volatility: str
    structure: str
    score: int
    confidence: str
    close: float
    fwd_up_atr: float
    fwd_down_atr: float
    fwd_ret_atr: float


def run_walkforward(df: pd.DataFrame, symbol: str, timeframe: str,
                    warmup: int = 500, step: int = 1, forward: int = 12,
                    progress_every: int = 100) -> list[ForwardOutcome]:
    if len(df) < warmup + forward + 1:
        raise ValueError(
            f"Need at least warmup+forward+1={warmup + forward + 1} candles, "
            f"got {len(df)}. Fetch more with --bars.")
    rows: list[ForwardOutcome] = []
    t0 = time.monotonic()
    for end in range(warmup, len(df) - forward + 1, max(1, step)):
        window = df.iloc[:end]
        fwd = df.iloc[end:end + forward]
        res = analyze(window, symbol, timeframe)
        atr = res.volatility.atr
        c0 = res.close
        rows.append(ForwardOutcome(
            ts_utc=str(fwd["time"].iloc[0]),
            regime=res.regime.value, trend=res.trend.label.value,
            momentum=res.momentum.label.value,
            volatility=res.volatility.label.value,
            structure=res.structure.label.value,
            score=res.score, confidence=res.confidence, close=c0,
            fwd_up_atr=max(0.0, (float(fwd["high"].max()) - c0) / atr),
            fwd_down_atr=max(0.0, (c0 - float(fwd["low"].min())) / atr),
            fwd_ret_atr=(float(fwd["close"].iloc[-1]) - c0) / atr))
        if progress_every and (len(rows) % progress_every == 0):
            log.info("walk-forward: %d/%d steps (%.1fs)",
                     len(rows), (len(df) - forward - warmup) // max(1, step) + 1,
                     time.monotonic() - t0)
    return rows


def summarize(rows: list[ForwardOutcome]) -> str:
    if not rows:
        return "No outcomes recorded."
    lines = ["",
             "Forward-movement association by market regime",
             "(ATR units; association only — NOT a profitability backtest, "
             "no costs/execution modeled)",
             "-" * 74,
             f"{'regime':<18}{'n':>5}{'mean|ret|':>11}{'mean up':>10}"
             f"{'mean dn':>10}{'mean score':>12}"]
    by_regime: dict[str, list[ForwardOutcome]] = {}
    for r in rows:
        by_regime.setdefault(r.regime, []).append(r)
    for regime, group in sorted(by_regime.items(), key=lambda kv: -len(kv[1])):
        n = len(group)
        lines.append(
            f"{regime:<18}{n:>5}"
            f"{sum(abs(g.fwd_ret_atr) for g in group) / n:>11.2f}"
            f"{sum(g.fwd_up_atr for g in group) / n:>10.2f}"
            f"{sum(g.fwd_down_atr for g in group) / n:>10.2f}"
            f"{sum(g.score for g in group) / n:>12.1f}")
    lines.append("-" * 74)
    lines.append("Small samples (<30) are noise. Nothing here predicts the "
                 "market with certainty.")
    return "\n".join(lines)


def save_csv(rows: list[ForwardOutcome], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(asdict(rows[0])))
        w.writeheader()
        w.writerows(asdict(r) for r in rows)
    log.info("Saved %d rows -> %s", len(rows), path)