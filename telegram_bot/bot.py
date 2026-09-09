"""Telegram bot: read-only market analysis commands. No trading, ever."""
from __future__ import annotations

import asyncio
import functools
import logging

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

import config
from analysis.service import run_analysis
from data.mt5_client import MT5Client, MT5ConnectionError, SymbolNotFoundError
from monitoring.monitor import make_post_init
from reporting.formatter import format_report
from storage.database import Database

from reporting.llm_reporter import build_report

from datetime import datetime, timezone

log = logging.getLogger("telegram.bot")

HELP_TEXT = """Commands:
/status   — MT5 link, database stats, monitor state
/market [SYMBOL] — quick report, default timeframe
/analyze SYMBOL [TIMEFRAME] — full report, e.g. /analyze EURUSD M5
/signals  — recent indicator events (EMA cross, RSI zones, MACD flip, S/R)

Timeframes: M1 M5 M15 M30 H1 H4 D1
Automatic reports: every {iv} min on {tf} (symbols: {syms}).

All output is educational market analysis — not financial advice.
This bot is read-only: it cannot and will not place trades."""


def guard(handler):
    """Log any handler crash, tell the user, keep the bot alive (spec §21)."""
    @functools.wraps(handler)
    async def wrapper(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            await handler(self, update, context)
        except Exception:
            log.exception("Handler %s crashed", handler.__name__)
            self._db.save_error("telegram", f"handler {handler.__name__} crashed")
            try:
                await update.effective_message.reply_text(
                    "⚠️ Internal error. Details are in the application log.")
            except Exception:
                pass
    return wrapper


def _chunks(text: str, size: int = 3900):
    """Split long text on line boundaries (Telegram limit is 4096 chars)."""
    while text:
        if len(text) <= size:
            yield text
            break
        cut = text.rfind("\n", 0, size)
        cut = cut if cut > 1000 else size
        yield text[:cut]
        text = text[cut:].lstrip("\n")


class MarketBot:
    def __init__(self, db: Database):
        self._db = db
        self._client = MT5Client()
        self._app = None
        # Serializes all MT5-touching analysis runs (user commands + monitor).
        self.analysis_lock = asyncio.Lock()

    # ---- surface used by the monitor ------------------------------------
    @property
    def client(self) -> MT5Client:
        return self._client

    @property
    def db(self) -> Database:
        return self._db

    def attach(self, app: Application) -> None:
        self._app = app

    async def broadcast(self, text: str) -> bool:
        """Send to the configured chat. False = not sent (monitor retries)."""
        if self._app is None:
            log.warning("Broadcast before startup; message dropped.")
            return False
        if not config.TELEGRAM_CHAT_ID:
            log.info("TELEGRAM_CHAT_ID not set; monitor message suppressed:\n%s", text)
            return False
        try:
            await self._app.bot.send_message(
                chat_id=int(config.TELEGRAM_CHAT_ID), text=text[:4000])
            return True
        except Exception:
            log.exception("Broadcast failed")
            return False

    # ---- commands --------------------------------------------------------
    @guard
    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        cfg_note = ("✅ TELEGRAM_CHAT_ID is set — automatic reports active."
                    if config.TELEGRAM_CHAT_ID else
                    f"ℹ️ This chat's ID is {chat_id} — put it in .env as "
                    "TELEGRAM_CHAT_ID to receive automatic reports.")
        await update.effective_message.reply_text(
            "Market analysis bot online. Read-only; no trading.\n\n"
            f"{cfg_note}\n\n{HELP_TEXT.format(iv=config.REPORT_INTERVAL_MINUTES, tf=config.MONITOR_TIMEFRAME, syms=', '.join(config.SYMBOLS))}")

    @guard
    async def cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.effective_message.reply_text(
            HELP_TEXT.format(iv=config.REPORT_INTERVAL_MINUTES,
                             tf=config.MONITOR_TIMEFRAME,
                             syms=", ".join(config.SYMBOLS)))

    @guard
    async def cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        terminal = await asyncio.to_thread(self._client.terminal_summary)
        n, syms = await asyncio.to_thread(self._db.stats)
        await update.effective_message.reply_text(
            "🤖 Bot status\n"
            f"MT5: {terminal}\n"
            f"Stored analyses: {n} (symbols: {syms})\n"
            f"Configured symbols: {', '.join(config.SYMBOLS)}\n"
            f"Monitor: {'on' if config.MONITOR_ENABLED else 'off'} — "
            f"{config.MONITOR_TIMEFRAME} every {config.REPORT_INTERVAL_MINUTES} min\n"
            f"Default: {config.DEFAULT_SYMBOL} {config.DEFAULT_TIMEFRAME} | "
            f"AI layer: {'on' if config.AI_ENABLED else 'off'}")

    @guard
    async def cmd_market(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        symbol = context.args[0] if context.args else config.DEFAULT_SYMBOL
        await self._analyze_and_reply(update, symbol, config.DEFAULT_TIMEFRAME)

    @guard
    async def cmd_analyze(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args:
            await update.effective_message.reply_text(
                "Usage: /analyze SYMBOL [TIMEFRAME]\nExample: /analyze EURUSD M5")
            return
        symbol = context.args[0]
        timeframe = context.args[1].upper() if len(context.args) > 1 \
            else config.DEFAULT_TIMEFRAME
        if timeframe not in config.TIMEFRAME_MAP:
            await update.effective_message.reply_text(
                f"Unknown timeframe '{timeframe}'. Supported: "
                f"{', '.join(sorted(config.TIMEFRAME_MAP))}")
            return
        await self._analyze_and_reply(update, symbol, timeframe)

    @guard
    async def cmd_signals(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        rows = await asyncio.to_thread(self._db.recent_signals, 10)
        if not rows:
            await update.effective_message.reply_text(
                "No signal events recorded yet. Events appear when an "
                "indicator crosses a threshold (EMA cross, RSI zone exit, "
                "MACD flip, S/R proximity, volatility expansion).")
            return
        lines = ["🔔 Last signal events (newest first):\n"]
        for ts, sym, tf, kind, detail in rows:
            when = ts[:16].replace("T", " ") if ts else "?"
            lines.append(f"• {when} UTC — {sym} {tf}\n  {kind}: {detail or ''}")
        lines.append("\nFactual indicator events — not trade recommendations.")
        await update.effective_message.reply_text("\n".join(lines)[:4000])

    async def _analyze_and_reply(self, update: Update, symbol: str, timeframe: str):
        msg = await update.effective_message.reply_text(
            f"Analyzing {symbol} {timeframe}...")
        try:
            async with self.analysis_lock:
                result = await asyncio.to_thread(
                    run_analysis, self._client, symbol, timeframe)
        except SymbolNotFoundError as exc:
            await msg.edit_text(f"❌ {exc}")
            return
        except (MT5ConnectionError, ValueError) as exc:
            log.warning("Analysis failed for %s %s: %s", symbol, timeframe, exc)
            self._db.save_error("analysis", str(exc))
            await msg.edit_text(f"❌ Analysis failed: {exc}")
            return

        report = await asyncio.to_thread(build_report, result)
        for i, part in enumerate(_chunks(report)):
            if i == 0:
                await msg.edit_text(part)
            else:
                await update.effective_chat.send_message(part)
        await asyncio.to_thread(self._db.save_analysis, result, report)
        log.info("Telegram report sent: %s %s", result.symbol, result.timeframe)


def run_bot() -> int:
    if not config.TELEGRAM_BOT_TOKEN:
        print("TELEGRAM_BOT_TOKEN is not set. See .env.example.")
        return 1

    db = Database(config.DB_PATH)
    bot = MarketBot(db)

    app = (Application.builder()
           .token(config.TELEGRAM_BOT_TOKEN)
           .post_init(make_post_init(bot))
           .build())
    bot.attach(app)

    app.add_handler(CommandHandler("start", bot.cmd_start))
    app.add_handler(CommandHandler("help", bot.cmd_help))
    app.add_handler(CommandHandler("status", bot.cmd_status))
    app.add_handler(CommandHandler("market", bot.cmd_market))
    app.add_handler(CommandHandler("analyze", bot.cmd_analyze))
    app.add_handler(CommandHandler("signals", bot.cmd_signals))

    log.info("Telegram bot starting (long polling). Ctrl+C to stop.")
    app.run_polling()
    return 0