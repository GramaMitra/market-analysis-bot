"""Optional local-LLM narrative layer (Ollama), with strict safety rails.

Contract (spec §13/§14/§30):
* The model receives ONLY structured analysis JSON computed by the
  deterministic engine.
* After generation, every number in the model's text is verified against
  that JSON (1% relative tolerance for benign rounding). Any unmatched
  number => the whole narrative is discarded and the deterministic
  report is used. Invented numbers cannot reach Telegram.
* Any failure (no Ollama, timeout, bad shape) => deterministic fallback.
The core system never depends on this module.
"""
from __future__ import annotations

import logging
import re
import time

import requests

import config
from analysis.models import AnalysisResult
from reporting.formatter import format_report

import json

log = logging.getLogger("reporting.llm")

_TIMEOUT_S = (5, 90)           # (connect, read): read must tolerate CPU model load + slow generation
_LOG_THROTTLE_S = 300          # max one fallback-warning per 5 minutes
_last_fallback_log = 0.0

_NUM_RE = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?(?![\w.])")

_SYSTEM_PROMPT = """You write short market-analysis briefings for a retail user.
You receive JSON produced by deterministic analysis code. It is the ONLY
source of facts.

STRICT RULES:
1. Use ONLY numbers that appear in the JSON. Never invent, add, or
   extrapolate any number. No price targets, no probabilities, no forecasts.
2. Do not predict the future. Describe current conditions only.
3. If multi-timeframe trends conflict, say so explicitly.
4. No financial advice ("consider buying/selling" is forbidden).
5. Plain text, under 170 words. Three short paragraphs:
   current conditions / key observations / what to watch next.
"""


# ------------------------------------------------------------- payload ----

def build_payload(r: AnalysisResult) -> dict:
    """Structured facts only — exactly the spec's §13 shape, extended."""
    return {
        "symbol": r.symbol,
        "timeframe": r.timeframe,
        "close": round(r.close, r.digits),
        "regime": r.regime.value,
        "trend": r.trend.label.value,
        "trend_score": r.trend.score,
        "momentum": r.momentum.label.value,
        "rsi": round(r.momentum.rsi, 1) if r.momentum.rsi is not None else None,
        "atr": r.volatility.atr,
        "atr_percentile": round(r.volatility.atr_percentile),
        "volatility": r.volatility.label.value,
        "structure": r.structure.label.value,
        "structure_detail": r.structure.description,
        "support": round(r.structure.support, r.digits) if r.structure.support is not None else None,
        "resistance": round(r.structure.resistance, r.digits) if r.structure.resistance is not None else None,
        "score": r.score,
        "confidence": r.confidence,
        "mtf_trends": {tf: t.value for tf, t in r.mtf_trends.items()},
        "mtf_alignment": r.alignment.value,
        "candles_analyzed": r.candles_used,
        "ema200_available": r.has_ema200,
    }


# ---------------------------------------------------------- number guard ---

def _allowed_numbers(payload: dict) -> set[float]:
    found: set[float] = set()

    def walk(v):
        if isinstance(v, bool) or v is None:
            return
        if isinstance(v, (int, float)):
            found.add(float(v))
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, (list, tuple)):
            for x in v:
                walk(x)

    walk(payload)
    return found


def number_violations(text: str, payload: dict) -> list[float]:
    """Numbers in `text` that are NOT (within 1% of) payload numbers."""
    allowed = _allowed_numbers(payload)
    bad = []
    for tok in _NUM_RE.findall(text):
        n = float(tok)
        if not any(abs(n - a) <= max(1e-9, abs(a) * 0.01) for a in allowed):
            bad.append(n)
    return bad


# ------------------------------------------------------------- ollama ------

def _ollama_generate(prompt: str) -> str:
    resp = requests.post(
        f"{config.OLLAMA_HOST.rstrip('/')}/api/generate",
        json={"model": config.OLLAMA_MODEL, "prompt": prompt,
              "stream": False,
              "keep_alive": config.OLLAMA_KEEP_ALIVE,
              "options": {"temperature": 0.2, "num_predict": 300}},
        timeout=_TIMEOUT_S)
    resp.raise_for_status()
    text = resp.json().get("response", "").strip()
    if not text:
        raise ValueError("Ollama returned an empty response.")
    return text

# ----------------------------------------------------------- public API ----

def build_report(r: AnalysisResult, use_ai: bool | None = None) -> str:
    """Report sent to the user: AI narrative if healthy, else deterministic.

    `use_ai` overrides config for testing.
    """
    enabled = config.AI_ENABLED if use_ai is None else use_ai
    if not enabled or not config.OLLAMA_MODEL:
        return format_report(r)

    payload = build_payload(r)
    try:
        narrative = _ollama_generate(
            _SYSTEM_PROMPT + "\n\nJSON data:\n" + json.dumps(payload))  # type: ignore[attr-defined]
    except Exception as exc:
        _warn_fallback(f"LLM unavailable: {exc}")
        return format_report(r)

    bad = number_violations(narrative, payload)
    if bad:
        _warn_fallback(
            f"LLM invented numbers not present in the data {bad[:5]} - "
            "narrative discarded, deterministic report used.")
        return format_report(r)

    return (
        "📊 MARKET BRIEF — {sym} {tf}\n"
        "🤖 Narrative by local AI; all numbers verified against the "
        "deterministic engine.\n"
        "────────────────────\n\n"
        f"{narrative}\n\n"
        "────────────────────\n"
        f"Regime {r.regime.value} | Trend {r.trend.label.value} | "
        f"Momentum {r.momentum.label.value} | Volatility {r.volatility.label.value} | "
        f"Alignment {r.score}/100 ({r.confidence})\n"
        "⚠️ Educational market analysis. Not financial advice.").format(
            sym=r.symbol, tf=r.timeframe)


def _warn_fallback(msg: str) -> None:
    global _last_fallback_log
    now = time.monotonic()
    if now - _last_fallback_log > _LOG_THROTTLE_S:
        log.warning("%s", msg)
        _last_fallback_log = now