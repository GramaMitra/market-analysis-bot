"""Automatic monitor: scheduled reports, regime-change alerts and
deterministic signal-event notifications.

Anti-spam contract:
* Identical consecutive states never produce messages.
* Signals are de-duplicated by (symbol, timeframe, kind, bar_time) and
  additionally throttled per kind by SIGNAL_COOLDOWN_MINUTES.
* Interval due -> one full report. Failed sends retry next cycle.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import config
from analysis.models import AnalysisResult
from analysis.service import run_analysis
from analysis.signals import SignalEvent, detect_signals
from reporting.formatter import format_report
from reporting.llm_reporter import build_report

log = logging.getLogger("monitor")

_EMOJI = {"TRENDING_UP": "📈", "TRENDING_DOWN": "📉", "RANGING": "↔️",
          "HIGH_VOLATILITY": "🌩", "LOW_VOLATILITY": "💤", "UNCERTAIN": "❓"}


def _minutes_since(iso_ts: str, now: datetime | None = None) -> float:
    then = datetime.fromisoformat(iso_ts)
    now = now or datetime.now(timezone.utc)
    return (now - then).total_seconds() / 60.0


def decide_send(last_sent_ts: str | None, last_sent_regime: str | None,
                regime_now: str, interval_min: float,
                now: datetime | None = None) -> str | None:
    """Pure scheduling decision: 'alert' | 'report' | None. Unit-tested."""
    if last_sent_regime is not None and last_sent_regime != regime_now:
        return "alert"
    if last_sent_ts is None or _minutes_since(last_sent_ts, now) >= interval_min:
        return "report"
    return None


def _change_text(prev_regime: str, r: AnalysisResult) -> str:
    return (
        f"{_EMOJI.get(r.regime.value, '⚠️')} Market condition changed\n\n"
        f"Symbol: {r.symbol} {r.timeframe}\n"
        f"Previous: {prev_regime}\n"
        f"Current: {r.regime.value}\n\n"
        f"Reason:\n{r.regime_reason}\n\n"
        f"Trend: {r.trend.label.value} | Momentum: {r.momentum.label.value} | "
        f"Volatility: {r.volatility.label.value}\n"
        f"Analytical alignment: {r.score}/100 ({r.confidence})\n\n"
        "Use /analyze for the full report. Educational analysis, not advice.")


def _signal_text(symbol: str, tf: str, ev: SignalEvent,
                 r: AnalysisResult) -> str:
    return (f"🔔 Signal — {symbol} {tf}\n"
            f"{ev.bar_time.strftime('%Y-%m-%d %H:%M')} UTC — {ev.human()}\n\n"
            f"Close: {r.close:.{r.digits}f} | Regime: {r.regime.value}\n\n"
            "Factual indicator event — not a trade recommendation.")


def make_post_init(bot):
    """Returns the PTB post_init hook that starts the monitor task."""
    async def post_init(app):
        if not config.MONITOR_ENABLED:
            log.info("Monitor disabled (MONITOR_ENABLED=false).")
            return
        app.create_task(Monitor(bot).run())
    return post_init


class Monitor:
    def __init__(self, bot):
        self._bot = bot

    async def run(self) -> None:
        interval_s = max(1, config.REPORT_INTERVAL_MINUTES) * 60
        await asyncio.sleep(10)   # let PTB and the MT5 link settle
        log.info("Monitor started: symbols=%s tf=%s interval=%dmin signals=%s",
                 config.SYMBOLS, config.MONITOR_TIMEFRAME,
                 config.REPORT_INTERVAL_MINUTES, config.SIGNALS_ENABLED)
        while True:
            try:
                await self._cycle()
            except asyncio.CancelledError:
                log.info("Monitor stopped.")
                raise
            except Exception:
                log.exception("Monitor cycle failed")
            await asyncio.sleep(interval_s)

    async def _cycle(self) -> None:
        now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
        for symbol in config.SYMBOLS:
            tf = config.MONITOR_TIMEFRAME
            try:
                async with self._bot.analysis_lock:
                    result, df = await asyncio.to_thread(
                        run_analysis, self._bot.client, symbol, tf,
                        return_df=True)
            except Exception as exc:
                log.warning("Monitor %s failed: %s", symbol, exc)
                self._bot.db.save_error("monitor", f"{symbol}: {exc}")
                continue

            action = decide_send(*self._bot.db.get_monitor_state(symbol, tf),
                                 result.regime.value,
                                 config.REPORT_INTERVAL_MINUTES)
            if action == "alert":
                state = self._bot.db.get_monitor_state(symbol, tf)
                text = _change_text(state[1], result)
                sent = await self._bot.broadcast(text)
            elif action == "report":
                # AI narrative if enabled+healthy, else deterministic.
                text = await asyncio.to_thread(build_report, result)
                sent = await self._bot.broadcast(text)
            else:
                text = format_report(result)   # history-only snapshot
                sent = False
                log.info("Monitor %s: %s (no change, not due)",
                         symbol, result.regime.value)

            if sent:
                self._bot.db.set_monitor_state(symbol, tf, now_iso,
                                               result.regime.value)
            await asyncio.to_thread(self._bot.db.save_analysis,
                                    result, text)

            if config.SIGNALS_ENABLED:
                await self._check_signals(symbol, tf, df, result)

    async def _check_signals(self, symbol: str, tf: str, df,
                             result: AnalysisResult) -> None:
        try:
            events = await asyncio.to_thread(
                detect_signals, df, result, config.SIGNAL_WINDOW_BARS,
                config.SIGNAL_RSI_OVERBOUGHT, config.SIGNAL_RSI_OVERSOLD,
                config.SIGNAL_VOL_EXPANSION_PCTL,
                config.SIGNAL_VOL_CONTRACTION_PCTL,
                config.SIGNAL_SR_PROXIMITY_ATR)
        except Exception:
            log.exception("Signal detection failed for %s %s", symbol, tf)
            return

        for ev in events:
            if self._bot.db.signal_exists(symbol, tf, ev.kind, str(ev.bar_time)):
                continue
            last = self._bot.db.last_signal_ts_of_kind(symbol, tf, ev.kind)
            if last:
                try:
                    if _minutes_since(last) < config.SIGNAL_COOLDOWN_MINUTES:
                        log.info("Signal %s %s %s suppressed (cooldown)",
                                 symbol, tf, ev.kind)
                        continue
                except ValueError:
                    pass
            self._bot.db.save_signal(symbol, tf, ev.kind,
                                     str(ev.bar_time), ev.human())
            await self._bot.broadcast(_signal_text(symbol, tf, ev, result))
            log.info("Signal announced: %s %s %s @ %s",
                     symbol, tf, ev.kind, ev.bar_time)