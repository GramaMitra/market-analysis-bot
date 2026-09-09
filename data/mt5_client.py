"""
Read-only MetaTrader 5 market-data client.

SAFETY
------
This module is strictly read-only. It must NEVER contain order or
execution calls (mt5.order_send() or equivalents). It only:
  - attaches to the running MT5 terminal,
  - reads symbol/candle information,
  - validates and normalizes the returned data.

We deliberately never pass login credentials to mt5.initialize():
the terminal itself is logged in by the user; we only attach to it.
"""
from __future__ import annotations
from data.data_processor import prepare_ohlcv, validate_ohlc

import logging
import time

import MetaTrader5 as mt5
import pandas as pd

import config

logger = logging.getLogger("data.mt5_client")


class MT5ConnectionError(RuntimeError):
    """Terminal cannot be reached or returned no data."""


class SymbolNotFoundError(RuntimeError):
    """Symbol does not exist on this broker."""


class MT5Client:
    """Attach to a running MetaTrader 5 terminal and read market data."""

    def __init__(self, mt5_path: str | None = None,
                 max_reconnect_attempts: int = 3):
        self._mt5_path = mt5_path or config.MT5_PATH
        self._max_reconnect_attempts = max_reconnect_attempts
        self._resolved_symbols: dict[str, str] = {}

    # ------------------------------------------------------- connection --

    def connect(self) -> None:
        """Attach to (or start) the MetaTrader 5 terminal."""
        self._resolved_symbols.clear()  # symbol list may differ after restart
        kwargs = {"path": self._mt5_path} if self._mt5_path else {}
        if not mt5.initialize(**kwargs):
            code, msg = mt5.last_error()
            raise MT5ConnectionError(
                f"mt5.initialize() failed (error {code}: {msg}). "
                "Is the MetaTrader 5 terminal running and logged in?"
            )

        terminal = mt5.terminal_info()
        if terminal is None:
            mt5.shutdown()
            raise MT5ConnectionError("Terminal info unavailable after initialize().")

        logger.info("Connected to MT5: %s build %s | broker link: %s",
                    terminal.name, terminal.build, terminal.connected)

        if mt5.account_info() is None:
            logger.warning("No account logged in inside the terminal; "
                           "market data may be unavailable.")

    def ensure_connected(self) -> None:
        """Transparently reconnect if the terminal link dropped."""
        if mt5.terminal_info() is not None:
            return
        logger.warning("MT5 link lost - trying to reconnect (%d attempts)...",
                       self._max_reconnect_attempts)
        mt5.shutdown()
        last_exc: Exception | None = None
        for attempt in range(1, self._max_reconnect_attempts + 1):
            try:
                self.connect()
                logger.info("Reconnected on attempt %d.", attempt)
                return
            except MT5ConnectionError as exc:
                last_exc = exc
                logger.warning("Reconnect attempt %d/%d failed: %s",
                               attempt, self._max_reconnect_attempts, exc)
                time.sleep(min(2 * attempt, 10))
        raise MT5ConnectionError(f"Unable to reconnect to MetaTrader 5: {last_exc}")

    def shutdown(self) -> None:
        mt5.shutdown()
        logger.info("MT5 connection closed.")

    # ----------------------------------------------------------- symbol --

    def resolve_symbol(self, symbol: str) -> str:
        """Map user input to this broker's exact, case-sensitive symbol name.

        MT5 names ARE case-sensitive ('GOLD.i#' != 'GOLD.I#'), so naive
        .upper() breaks mixed-case broker suffixes. Resolution order:
          1. explicit alias from config.SYMBOL_ALIASES
          2. exactly as typed
          3. upper-cased          (helps 'eurusd' -> 'EURUSD')
          4. unique case-insensitive match across all broker symbols
        Otherwise raises SymbolNotFoundError with concrete suggestions.
        """
        key = symbol.strip()
        if key in self._resolved_symbols:
            return self._resolved_symbols[key]

        alias = config.SYMBOL_ALIASES.get(key.upper())
        if alias:
            if mt5.symbol_info(alias) is None:
                raise SymbolNotFoundError(
                    f"Alias '{key}' -> '{alias}', but '{alias}' does not exist "
                    "on this broker. Check SYMBOL_ALIASES in config.py.")
            self._resolved_symbols[key] = alias
            return alias

        for candidate in dict.fromkeys([key, key.upper()]):
            if mt5.symbol_info(candidate) is not None:
                self._resolved_symbols[key] = candidate
                if candidate != key:
                    logger.info("Symbol '%s' resolved to '%s'", key, candidate)
                return candidate

        names = [s.name for s in (mt5.symbols_get() or [])]
        matches = [n for n in names if n.lower() == key.lower()]
        if len(matches) == 1:
            logger.info("Symbol '%s' resolved to '%s' (case-insensitive match)",
                        key, matches[0])
            self._resolved_symbols[key] = matches[0]
            return matches[0]

        raise SymbolNotFoundError(self._symbol_error_with_suggestions(key))

    # ------------------------------------------------------------- data --

    def get_candles(self, symbol: str, timeframe: str, count: int) -> pd.DataFrame:
        """Fetch the most recent `count` candles as a validated DataFrame.

        The final row is the currently forming candle.
        """
        self.ensure_connected()

        tf = config.TIMEFRAME_MAP.get(timeframe.upper())
        if tf is None:
            raise ValueError(
                f"Unsupported timeframe '{timeframe}'. "
                f"Supported: {sorted(config.TIMEFRAME_MAP)}")

        symbol = self.resolve_symbol(symbol)
        if not self._select_symbol(symbol):
            raise SymbolNotFoundError(
                f"Symbol '{symbol}' exists but could not be enabled "
                "in Market Watch.")

        rates = mt5.copy_rates_from_pos(symbol, tf, 0, count)
        if rates is None or len(rates) == 0:
            code, msg = mt5.last_error()
            raise MT5ConnectionError(
                f"No rate data returned for {symbol} {timeframe.upper()} "
                f"(error {code}: {msg}).")

        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")  # MT5 returns UTC seconds
        df = prepare_ohlcv(df)
        df = validate_ohlc(df, symbol)
        logger.info("Fetched %d candles for %s %s", len(df), symbol, timeframe.upper())
        return df

    def get_symbol_digits(self, symbol: str) -> int:
        """Price precision for this symbol (used for display formatting)."""
        try:
            canonical = self.resolve_symbol(symbol)
        except SymbolNotFoundError:
            return 5
        info = mt5.symbol_info(canonical)
        return info.digits if info else 5

    # -------------------------------------------------------- internals --

    def _select_symbol(self, symbol: str) -> bool:
        """Ensure the symbol exists and is visible in Market Watch."""
        info = mt5.symbol_info(symbol)
        if info is None:
            return False
        if not info.visible:
            return bool(mt5.symbol_select(symbol, True))
        return True

    def _symbol_error_with_suggestions(self, symbol: str) -> str:
        """Case-tolerant fuzzy search so the hint survives suffix/case quirks."""
        found: dict[str, None] = {}
        for pattern in (f"*{symbol}*", f"*{symbol.upper()}*"):
            try:
                for s in (mt5.symbols_get(pattern) or []):
                    found.setdefault(s.name)
            except Exception:
                pass
        hint = (f" Similar symbols on this broker: "
                f"{', '.join(list(found)[:10])}.") if found else ""
        return f"Symbol '{symbol}' not found on this broker.{hint}"

    def terminal_summary(self) -> str:
        """Human-readable link state; probes/reconnects lazily."""
        try:
            self.ensure_connected()
        except MT5ConnectionError as exc:
            return f"NOT connected ({exc})"
        t = mt5.terminal_info()
        return (f"{t.name} build {t.build}, link "
                f"{'up' if t.connected else 'DOWN'}") if t else "unknown"