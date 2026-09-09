"""LLM-layer tests: payload shape and the numeric guard (no Ollama needed)."""
from analysis.analyzer import analyze
from reporting.llm_reporter import (build_payload, build_report,
                                    number_violations)
from reporting.formatter import format_report
from tests.test_analysis import make_df, ramp_up


def _result():
    return analyze(make_df(ramp_up()), "EURUSD", "M5", digits=5)


def test_payload_has_core_keys():
    p = build_payload(_result())
    for key in ("symbol", "timeframe", "regime", "rsi", "atr",
                "mtf_alignment", "score"):
        assert key in p


def test_guard_flags_invented_price_target():
    payload = build_payload(_result())
    assert number_violations("price could reach 1.99999 soon", payload)


def test_guard_allows_faithful_rounding():
    payload = {"close": 1.16301, "rsi": 51.7, "score": 57}
    assert number_violations("Close 1.1630 with RSI near 52 and score 57.",
                             payload) == []


def test_ai_disabled_returns_deterministic():
    r = _result()
    assert build_report(r, use_ai=False) == format_report(r)


def test_unreachable_ollama_falls_back(monkeypatch):
    import requests as _rq
    r = _result()
    monkeypatch.setattr("reporting.llm_reporter.config.AI_ENABLED", True)
    monkeypatch.setattr("reporting.llm_reporter.config.OLLAMA_MODEL", "test")
    monkeypatch.setattr(_rq, "post",
                        lambda *a, **k: (_ for _ in ()).throw(ConnectionError()))
    assert build_report(r) == format_report(r)