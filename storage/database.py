"""SQLite persistence: analyses, errors, monitor state, signals, stats.

Design: short-lived connections + a threading.Lock (the Telegram bot's
event loop and worker threads share this). WAL mode for safe concurrent
reads. Only exception messages are stored -- never tokens or credentials.
"""
from __future__ import annotations

import logging
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from analysis.models import AnalysisResult

logger = logging.getLogger("storage.database")

SCHEMA = """
CREATE TABLE IF NOT EXISTS analyses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_utc TEXT NOT NULL,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    close REAL,
    rsi REAL, atr REAL, macd_hist REAL, roc REAL,
    ema20 REAL, ema50 REAL, ema200 REAL,
    atr_percentile REAL,
    trend TEXT, momentum TEXT, volatility TEXT, structure TEXT,
    regime TEXT, alignment TEXT,
    score INTEGER, confidence TEXT,
    support REAL, resistance REAL,
    report TEXT
);
CREATE INDEX IF NOT EXISTS idx_analyses_sym_tf
    ON analyses(symbol, timeframe, ts_utc);

CREATE TABLE IF NOT EXISTS errors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_utc TEXT NOT NULL,
    component TEXT NOT NULL,
    message TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS monitor_state (
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    last_sent_ts TEXT,
    last_sent_regime TEXT,
    PRIMARY KEY (symbol, timeframe)
);

CREATE TABLE IF NOT EXISTS signals (
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    kind TEXT NOT NULL,
    bar_time TEXT NOT NULL,
    detail TEXT,
    announced_ts TEXT,
    PRIMARY KEY (symbol, timeframe, kind, bar_time)
);
"""


class Database:
    def __init__(self, path: str | Path):
        self._path = str(path)
        self._lock = threading.Lock()
        with self._lock, self._connect() as conn:
            conn.executescript(SCHEMA)
        logger.info("Database ready: %s", self._path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    # ------------------------------------------------------------ analyses --

    def save_analysis(self, r: AnalysisResult, report: str) -> int:
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO analyses
                   (ts_utc, symbol, timeframe, close, rsi, atr, macd_hist, roc,
                    ema20, ema50, ema200, atr_percentile,
                    trend, momentum, volatility, structure, regime, alignment,
                    score, confidence, support, resistance, report)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (ts, r.symbol, r.timeframe, r.close,
                 r.momentum.rsi, r.volatility.atr, r.momentum.macd_hist,
                 r.momentum.roc, r.trend.ema20, r.trend.ema50, r.trend.ema200,
                 r.volatility.atr_percentile,
                 r.trend.label.value, r.momentum.label.value,
                 r.volatility.label.value, r.structure.label.value,
                 r.regime.value, r.alignment.value, r.score, r.confidence,
                 r.structure.support, r.structure.resistance, report))
            conn.commit()
            return int(cur.lastrowid)

    def last_analysis(self, symbol: str, timeframe: str) -> tuple | None:
        with self._lock, self._connect() as conn:
            return conn.execute(
                """SELECT ts_utc, regime, trend, score FROM analyses
                   WHERE symbol=? AND timeframe=? ORDER BY id DESC LIMIT 1""",
                (symbol.upper(), timeframe.upper())).fetchone()

    def save_error(self, component: str, message: str) -> None:
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._lock, self._connect() as conn:
            conn.execute("INSERT INTO errors (ts_utc, component, message) VALUES (?,?,?)",
                         (ts, component, message[:2000]))
            conn.commit()

    def stats(self) -> tuple[int, str]:
        with self._lock, self._connect() as conn:
            n = conn.execute("SELECT COUNT(*) FROM analyses").fetchone()[0]
            syms = [row[0] for row in conn.execute("SELECT DISTINCT symbol FROM analyses")]
        return n, ", ".join(syms) if syms else "—"

    # ------------------------------------------------------- monitor state --

    def get_monitor_state(self, symbol: str, timeframe: str) -> tuple:
        with self._lock, self._connect() as conn:
            return conn.execute(
                "SELECT last_sent_ts, last_sent_regime FROM monitor_state "
                "WHERE symbol=? AND timeframe=?",
                (symbol.upper(), timeframe.upper())).fetchone() or (None, None)

    def set_monitor_state(self, symbol: str, timeframe: str,
                          ts: str, regime: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """INSERT INTO monitor_state (symbol, timeframe, last_sent_ts, last_sent_regime)
                   VALUES (?,?,?,?)
                   ON CONFLICT(symbol, timeframe) DO UPDATE SET
                     last_sent_ts=excluded.last_sent_ts,
                     last_sent_regime=excluded.last_sent_regime""",
                (symbol.upper(), timeframe.upper(), ts, regime))
            conn.commit()

    # -------------------------------------------------------------- signals --

    def signal_exists(self, symbol: str, timeframe: str, kind: str,
                      bar_time: str) -> bool:
        with self._lock, self._connect() as conn:
            return conn.execute(
                "SELECT 1 FROM signals WHERE symbol=? AND timeframe=? "
                "AND kind=? AND bar_time=?",
                (symbol.upper(), timeframe.upper(), kind, bar_time)
            ).fetchone() is not None

    def save_signal(self, symbol: str, timeframe: str, kind: str,
                    bar_time: str, detail: str) -> None:
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._lock, self._connect() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO signals
                   (symbol, timeframe, kind, bar_time, detail, announced_ts)
                   VALUES (?,?,?,?,?,?)""",
                (symbol.upper(), timeframe.upper(), kind, bar_time,
                 detail[:500], ts))
            conn.commit()

    def last_signal_ts_of_kind(self, symbol: str, timeframe: str,
                               kind: str) -> str | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT announced_ts FROM signals WHERE symbol=? AND "
                "timeframe=? AND kind=? ORDER BY announced_ts DESC LIMIT 1",
                (symbol.upper(), timeframe.upper(), kind)).fetchone()
        return row[0] if row else None

    def recent_signals(self, limit: int = 10) -> list[tuple]:
        with self._lock, self._connect() as conn:
            return conn.execute(
                "SELECT announced_ts, symbol, timeframe, kind, detail "
                "FROM signals ORDER BY announced_ts DESC LIMIT ?", (limit,)
            ).fetchall()