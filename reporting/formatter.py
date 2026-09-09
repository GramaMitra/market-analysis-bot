"""Render an AnalysisResult as the fixed-format market report."""
from __future__ import annotations

from analysis.models import AnalysisResult, Alignment
from data.data_processor import TF_MINUTES

LINE = "━" * 22


def format_report(r: AnalysisResult) -> str:
    f = lambda v: f"{v:.{r.digits}f}"          # noqa: E731
    regime = r.regime.value.replace("_", " ")

    lines = [
        LINE, "📊 MARKET ANALYSIS", LINE, "",
        f"Symbol: {r.symbol}",
        f"Timeframe: {r.timeframe}",
        f"Close: {f(r.close)}  ({r.generated_at.strftime('%Y-%m-%d %H:%M')} UTC)",
        f"Candles analyzed: {r.candles_used}",
        "",
        "Market regime:",
        regime,
        f"Reason: {r.regime_reason}",
        "",
        "Trend:",
        f"{r.trend.label.value} ({r.trend.detail})",
        "",
        "Momentum:",
        f"{r.momentum.label.value} — {r.momentum.detail}",
        "",
        "Volatility:",
        f"{r.volatility.label.value} — {r.volatility.detail}",
        "",
        "Structure:",
        f"{r.structure.description} [{r.structure.label.value}]",
        "",
        "Support / Resistance (algorithmic, not guaranteed):",
        f"  Nearest support:    {f(r.structure.support) if r.structure.support is not None else '—'}",
        f"  Nearest resistance: {f(r.structure.resistance) if r.structure.resistance is not None else '—'}",
    ]

    if r.mtf_trends:
        lines += ["", "Multi-timeframe:"]
        for tf in sorted(r.mtf_trends, key=lambda t: -TF_MINUTES[t]):
            lines.append(f"  {tf:<4} {r.mtf_trends[tf].value}")
        lines.append(f"  Alignment: {r.alignment.value}")
        if r.alignment == Alignment.CONFLICTING:
            lines.append("  ⚠ Timeframes disagree — no directional conclusion is forced.")

    lines += [
        "",
        f"Analytical alignment: {r.score}/100 ({r.confidence})",
        "This score measures agreement between indicators —",
        "it is NOT a probability of profit.",
        "",
        "⚠️ Educational market analysis. Not financial advice.",
        LINE,
    ]
    return "\n".join(lines)