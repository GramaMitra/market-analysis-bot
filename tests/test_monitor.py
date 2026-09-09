"""Scheduling decision tests (pure logic, no network/DB)."""
from datetime import datetime, timezone

from monitoring.monitor import decide_send

NOW = datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc)
OLD = "2026-09-09T11:00:00+00:00"     # 60 min before NOW
RECENT = "2026-09-09T11:50:00+00:00"  # 10 min before NOW


def test_alert_on_regime_change():
    assert decide_send(RECENT, "RANGING", "TRENDING_UP", 30, NOW) == "alert"


def test_report_when_never_sent():
    assert decide_send(None, None, "RANGING", 30, NOW) == "report"


def test_report_when_interval_elapsed():
    assert decide_send(OLD, "RANGING", "RANGING", 30, NOW) == "report"


def test_none_when_recent_and_same():
    assert decide_send(RECENT, "RANGING", "RANGING", 30, NOW) is None


def test_alert_takes_priority_over_due():
    assert decide_send(OLD, "RANGING", "TRENDING_DOWN", 30, NOW) == "alert"