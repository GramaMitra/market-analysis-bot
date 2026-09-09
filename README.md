# Market Analysis Bot

A local, read-only market-analysis bot: **MetaTrader 5 → Python → deterministic
technical analysis → Telegram**. Educational/analytical purposes only.

**This bot cannot trade.** It never calls `order_send()` or any execution API,
never places/modifies/closes orders, and never touches account functions. It
attaches to your MT5 terminal purely as a market-data observer.

---

## Purpose

- Monitor configured symbols and produce structured market-condition reports
  (trend, momentum, volatility, market structure, regime, multi-timeframe alignment).
- Announce factual indicator events (EMA crosses, RSI zone transitions, MACD
  flips, support/resistance proximity, volatility regime shifts) as they happen —
  descriptive events, never directives.
- Deliver reports via Telegram on demand and on a schedule, with alerts when
  the market regime changes.
- Optionally have a **local** LLM (Ollama) turn the structured analysis into a
  short narrative. The LLM only ever sees analysis results — never raw candles,
  never screenshots — and every number it writes is verified against the
  deterministic engine before sending.
- Provide a research mode that runs the *same* analysis code over historical
  data to study associations between analytical states and forward movement.

## What this bot is NOT

- Not a trading bot, not a signal seller, not a predictor.
- Its "analytical alignment" score measures **agreement between indicators**.
  It is **not** a probability of profit and must never be read as one.
- Signal events describe state transitions. They carry **no** direction or
  outcome claim.
- Research output shows **association**, not causal or predictive power.

---

## Architecture

```text
MetaTrader 5 (terminal, logged in)
        |  read-only rates
data/mt5_client.py        connect / reconnect / resolve symbols / fetch
data/data_processor.py    normalize / validate / resample (pure pandas)
        |  validated OHLCV DataFrames
analysis/                 indicators (EMA, RSI, MACD, ROC, ATR — Wilder math)
                          trend / momentum / volatility / structure
                          analyzer.py (regime, MTF alignment, score)
                          signals.py (deterministic event detection)
                          service.py (shared pipeline for CLI and Telegram)
        |  AnalysisResult (dataclass)
reporting/formatter.py    deterministic text report (always available)
reporting/llm_reporter.py optional Ollama narrative + numeric guard
        |
telegram_bot/bot.py       commands + broadcast
monitoring/monitor.py     scheduled reports, regime-change alerts, signal pushes
storage/database.py       SQLite persistence (analyses, errors, signals, monitor state)
research/walkforward.py   historical walk-forward studies
```

Key invariants:

- One analysis code path for live, CLI, Telegram, and research (no duplication).
- Analysis modules are pure (no MT5 imports) → fully unit-testable.
- Any failure in Telegram/LLM/monitor degrades gracefully; the core keeps running.

---

## Requirements

- Windows (the `MetaTrader5` Python package is Windows-only)
- **64-bit** Python 3.9+ (3.11+ recommended)
- MetaTrader 5 terminal, installed and **logged in to a broker account**
- ~200 MB free disk (venv + DB); local LLM models add ~2 GB. No GPU needed.

## Installation

```powershell
cd market-analysis-bot
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env      # then edit .env (see below)
python audit_environment.py # sanity check
python -m pytest -v         # all tests must pass
```

## MetaTrader 5 setup

1. Install MT5 from your broker; log in inside the terminal.
2. Keep the terminal running while the bot runs (it attaches to it).
3. Symbols differ per broker (suffixes like `.i#`, `.a`, `m`). If a symbol
   isn't found, the bot lists similar names — add a friendly alias in
   `config.py`:

```python
SYMBOL_ALIASES = {"XAUUSD": "GOLD.i#", "GOLD": "GOLD.i#"}
```

Symbol names are **case-sensitive**; quoted names like `"GOLD.i#"` are fine
in PowerShell.

## Environment variables (.env)

| Key | Default | Meaning |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | — | from @BotFather (required for `--bot`) |
| `TELEGRAM_CHAT_ID` | — | your chat id (required for automatic reports) |
| `MT5_PATH` | auto | path to `terminal64.exe` if not auto-detected |
| `MONITOR_ENABLED` | `true` | automatic reports on/off |
| `REPORT_INTERVAL_MINUTES` | `30` | full report cadence per symbol |
| `MONITOR_TIMEFRAME` | `M15` | timeframe used by the monitor |
| `SIGNALS_ENABLED` | `true` | signal-event pushes on/off |
| `SIGNAL_COOLDOWN_MINUTES` | `60` | minimum time between pushes of the same event kind |
| `AI_ENABLED` | `false` | local-LLM narrative layer |
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama endpoint |
| `OLLAMA_MODEL` | — | e.g. `llama3.2:3b` |
| `OLLAMA_KEEP_ALIVE` | `15m` | model stays in RAM between calls (avoids cold starts) |
| `LOG_LEVEL` | `INFO` | console/file log verbosity |
| `DB_PATH` | `bot_data.sqlite3` | SQLite location |

Never put secrets in `config.py`; never commit `.env`.

## Telegram setup (5 min)

1. Message **@BotFather** → `/newbot` → copy the token into `.env`.
2. `python main.py --bot`, send `/start` — the bot echoes your chat ID.
3. Put that ID in `.env` as `TELEGRAM_CHAT_ID`, restart. Automatic reports
   now arrive in your chat.

**If your token ever leaks** (pasted in a log or screenshot): @BotFather →
/mybots → your bot → API Token → **Revoke current token**, put the new one in
`.env`, restart. The app masks tokens in its own logs automatically.

## Running

```powershell
# CLI report (no Telegram needed)
python main.py --symbol EURUSD --timeframe M5
python main.py --symbol XAUUSD --timeframe M5 --table --no-mtf
python main.py --symbol EURUSD --timeframe M5 --count 90 --resample M15

# Telegram bot (commands + monitor + signals)
python main.py --bot

# Research (walk-forward over history; same analysis engine)
python main.py --research --symbol "GOLD.i#" --timeframe M15 --bars 3000 --step 5
```

## Telegram commands

| Command | Effect |
|---|---|
| `/start` | greeting + chat-id hint |
| `/help` | command list |
| `/status` | MT5 link, DB stats, monitor config |
| `/market [SYMBOL]` | quick report at the default timeframe |
| `/analyze SYMBOL [TF]` | full report, e.g. `/analyze EURUSD H1` |
| `/signals` | last 10 recorded indicator events |

## Signal events

The monitor scans each configured symbol every cycle and announces **factual
state transitions**:

- EMA20/EMA50 cross up / down
- RSI entering / leaving the overbought (70) and oversold (30) zones
- MACD histogram flipping positive / negative
- Price within 0.5 ATR of algorithmic support / resistance
- Volatility expanding / contracting (ATR percentile crossing 85 / 25)

Anti-spam: every event is deduplicated by bar time and additionally
throttled per event kind by `SIGNAL_COOLDOWN_MINUTES`. All events are stored
in SQLite (`signals` table) and browsable via `/signals`.

**These events are descriptions, not recommendations.** They say what changed,
never what to do. Whether any event type carries useful forward movement is a
question for the research mode on accumulated data — not an assumption.

## Ollama (optional, free, local)

Ollama is a **standalone Windows app** (not a pip package — the venv is
irrelevant to it). Install from https://ollama.com/download, then:

```powershell
ollama pull llama3.2:3b
# .env:  AI_ENABLED=true   OLLAMA_MODEL=llama3.2:3b
```

The LLM only receives structured analysis JSON. After generation, a numeric
guard verifies every number in the text against that JSON; any invented
number → the narrative is discarded and the deterministic report is sent.
With `AI_ENABLED=false` the bot is byte-identical to the non-AI build.

**Low disk on C:?** Move the models (not the app) to another drive:

```powershell
Get-Process ollama* -ErrorAction SilentlyContinue | Stop-Process -Force
New-Item -ItemType Directory -Force -Path D:\ollama\models
Move-Item "$env:USERPROFILE\.ollama\models\*" D:\ollama\models\
[Environment]::SetEnvironmentVariable("OLLAMA_MODELS", "D:\ollama\models", "User")
# start Ollama from the Start Menu, then verify:  ollama list
```

All future pulls land on D: automatically. The bot needs no changes.

## Backup to GitHub (private repo)

The repo must be **Private** — it is a personal archive, not a publication.
Secrets are never committed by design (`.env` is git-ignored).

```powershell
# one-time on github.com: New repository -> Private -> do NOT add a README
git init
git add -A
git status                      # MUST NOT list .env, *.sqlite3, logs/
git commit -m "v1.1: read-only MT5 analysis bot with signals"
git branch -M main
git remote add origin https://github.com/<username>/market-analysis-bot.git
git push -u origin main         # first push opens a browser login
```

Later updates: `git add -A && git commit -m "..." && git push`.
Restore on a new machine: `git clone <url>`, then `python -m venv .venv`,
`pip install -r requirements.txt`, and recreate `.env` from `.env.example`
(services like Telegram/Ollama config are local-only by design).

## Troubleshooting

| Symptom | Fix |
|---|---|
| `mt5.initialize() failed` | Start MT5 and log in. Custom install folder? Set `MT5_PATH` in `.env`. |
| `MetaTrader5` package won't install | You're on 32-bit Python or non-Windows. Install 64-bit Python. |
| `Symbol 'X' not found` | Check the bot's similar-names hint; add an alias in `config.py`. Quote `#` names in PowerShell. |
| No rate data | Market closed, or symbol not enabled (bot auto-selects in Market Watch). |
| Telegram 409 conflict | Another instance is polling the same token — close it. |
| Times look shifted | MT5 returns **UTC**; broker charts may show server/local time. |
| Support & resistance very close together | Normal in low-volatility regimes; levels are nearest printed swings, in ATR terms. |
| Too many signal notifications | Raise `SIGNAL_COOLDOWN_MINUTES` (e.g. 180) or set `SIGNALS_ENABLED=false`. |
| LLM times out | First call after idle = model load (CPU). Keep `OLLAMA_KEEP_ALIVE=15m`, or use a 1B model. Fallback to the deterministic report is automatic. |
| Bad .env values crash at startup | Invalid values warn and fall back to defaults (hardened parser). |

Logs: `logs/application.log`, `logs/errors.log`. Secrets are never logged.

## Project structure

```text
market-analysis-bot/
├── main.py                  CLI / bot / research entry points
├── config.py                all tunables; secrets live in .env
├── audit_environment.py     read-only environment check
├── data/                    mt5_client, data_processor (validation/resample)
├── analysis/                indicators, models, trend, momentum, volatility,
│                            structure, analyzer, signals, service
├── reporting/               formatter, llm_reporter
├── telegram_bot/            bot + commands
├── monitoring/              scheduled reports, alerts, signal pushes
├── storage/                 SQLite database
├── research/                walk-forward engine
├── utils/                   logging (token-masking filter included)
├── tests/                   59 tests (pure, no MT5/Telegram/Ollama needed)
├── logs/                    runtime logs (not committed)
└── research_out/            walk-forward CSVs (not committed)
```

## Limitations (read this)

- **Swing detection lags** by `SWING_RIGHT` bars by construction; structure
  labels confirm late and can repaint.
- **S/R levels are algorithmic clusters of past swings** — statistical
  reference points, not barriers.
- **The score is agreement, not probability.** 90/100 means components agree,
  not that anything will "work."
- **Signal events fire on the newest, still-forming bar** — an intrabar
  transition can occur and partially reverse before the bar closes.
- **Indicator conventions** (Wilder RSI/ATR, EMA seeding) match MT5/TradingView
  for identical input, but different tools may differ slightly.
- FX `tick_volume` is tick counts, not real volume.
- Research mode models **no costs, execution, or slippage**; it measures
  association only. Small samples are noise.
- D1 data should be fetched natively; resampling to D1 uses calendar
  boundaries and is approximate.
- The LLM layer can only rephrase verified facts; it adds no information and
  is optional by design.

---

*Market Analysis Bot v1.1 — educational software. Not financial advice.*