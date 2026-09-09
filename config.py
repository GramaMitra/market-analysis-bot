"""
Central configuration.

Everything you may want to tune lives here (secrets live in .env).
Never put secrets directly in this file.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

try:
    import MetaTrader5 as mt5
except ImportError as _exc:  # pragma: no cover
    raise SystemExit(
        "The 'MetaTrader5' package is not installed.\n"
        "Fix:  pip install MetaTrader5\n"
        "(Windows + 64-bit Python only; the MT5 terminal must also be installed.)"
    ) from _exc

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# --------------------------------------------------------------- MT5 ------
# Optional path to terminal64.exe if the terminal is not running and
# MT5 cannot auto-locate it. Loaded from .env (MT5_PATH=...).
MT5_PATH: str | None = os.getenv("MT5_PATH", "").strip() or None

DEFAULT_SYMBOL = "EURUSD"
DEFAULT_TIMEFRAME = "M5"
LOOKBACK_CANDLES = 500  # max candles fetched per analysis request

TIMEFRAME_MAP = {
    "M1":  mt5.TIMEFRAME_M1,
    "M5":  mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "M30": mt5.TIMEFRAME_M30,
    "H1":  mt5.TIMEFRAME_H1,
    "H4":  mt5.TIMEFRAME_H4,
    "D1":  mt5.TIMEFRAME_D1,
}

# --------------------------------------------------------------- symbols --
# Brokers name symbols differently (suffixes like .a, .pro, m, i# are common).
# Map friendly names to this broker's EXACT symbol. Keys match case-insensitively.
SYMBOL_ALIASES: dict[str, str] = {
    "XAUUSD": "GOLD.i#",
    "GOLD":   "GOLD.i#",
}

# Used by later phases (automatic reports). Alias names are allowed here.
SYMBOLS: list[str] = ["EURUSD", "XAUUSD"]

# ----------------------------------------------------------- analysis -----
ANALYSIS_MIN_CANDLES = 60   # minimum validated candles required per analysis

# Multi-timeframe context sets: base timeframe -> [lower, middle, higher]
MTF_SETS: dict[str, list[str]] = {
    "M1":  ["M1", "M5", "M15"],
    "M5":  ["M5", "M15", "H1"],
    "M15": ["M15", "H1", "H4"],
    "M30": ["M30", "H1", "H4"],
    "H1":  ["H1", "H4", "D1"],
    "H4":  ["H4", "D1"],
    "D1":  ["D1"],
}

# ---------------------------------------------------------- storage -------
DB_PATH = BASE_DIR / os.getenv("DB_PATH", "bot_data.sqlite3")


# ---------------------------------------------------------- Telegram ------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

# --------------------------------------------------------------- AI -------
AI_ENABLED = os.getenv("AI_ENABLED", "false").strip().lower() == "true"
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434").strip()
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "").strip()
OLLAMA_KEEP_ALIVE = os.getenv("OLLAMA_KEEP_ALIVE", "15m").strip() or "15m"

# ---------------------------------------------------------- Logging -------
LOG_DIR = BASE_DIR / "logs"
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()


# --------------------------------------------------- .env-safe parsing ----
def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    if raw in ("true", "1", "yes", "on"):
        return True
    if raw in ("false", "0", "no", "off"):
        return False
    print(f"WARNING: {name}='{raw}' is not a boolean; using {default}.")
    return default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        print(f"WARNING: {name}='{raw}' is not an integer; using {default}.")
        return default


# --------------------------------------------------------- monitoring -----
MONITOR_ENABLED = _env_bool("MONITOR_ENABLED", True)
REPORT_INTERVAL_MINUTES = _env_int("REPORT_INTERVAL_MINUTES", 30)
MONITOR_TIMEFRAME = os.getenv("MONITOR_TIMEFRAME", "M15").strip().upper() or "M15"


# ----------------------------------------------------------- signals ------
SIGNALS_ENABLED = _env_bool("SIGNALS_ENABLED", True)
SIGNAL_WINDOW_BARS = _env_int("SIGNAL_WINDOW_BARS", 2)   # bars scanned per cycle
SIGNAL_COOLDOWN_MINUTES = _env_int("SIGNAL_COOLDOWN_MINUTES", 60)
SIGNAL_SR_PROXIMITY_ATR = 0.5   # "near level" distance in ATR units
SIGNAL_RSI_OVERBOUGHT = 70.0
SIGNAL_RSI_OVERSOLD = 30.0
SIGNAL_VOL_EXPANSION_PCTL = 85.0
SIGNAL_VOL_CONTRACTION_PCTL = 25.0