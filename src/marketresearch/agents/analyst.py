"""Agent 2: Data Analyst. Deterministic metric computation (pandas/numpy-free) plus grounded LLM commentary."""
from __future__ import annotations

import logging
import math
import re
import statistics
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..llm import LLMError
from ..prompts import ANALYST_QUAL_SYSTEM, ANALYST_QUANT_SYSTEM
from ..state import AnalysisResult, EntityFinancials, GraphState, ResearchRequest
from ..tools import bar_chart, fetch_entities, price_chart
from .base import BaseAgent, sanitize_citations

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------- pure functions (unit tested)
def performance_stats(closes: List[float]) -> Dict[str, Optional[float]]:
    """1-year return, annualised volatility and max drawdown from daily closes (percent values)."""
    closes = [price for price in closes if math.isfinite(price) and price > 0]
    n = len(closes)
    if n < 20:
        return {"return_1y": None, "volatility": None, "max_drawdown": None}
    window = closes[-(min(252, n - 1) + 1):]
    ret = (window[-1] / window[0] - 1) * 100
    daily = [window[i] / window[i - 1] - 1 for i in range(1, len(window)) if window[i - 1]]
    vol = statistics.pstdev(daily) * math.sqrt(252) * 100 if len(daily) > 1 else None
    peak, mdd = window[0], 0.0
    for p in window:
        peak = max(peak, p)
        mdd = min(mdd, (p / peak - 1) * 100)
    return {"return_1y": round(ret, 2), "volatility": round(vol, 2) if vol is not None else None, "max_drawdown": round(mdd, 2)}


def _pct(v: Optional[float]) -> Optional[float]:
    return None if v is None else round(v * 100, 2)


def build_comparison_rows(entities: List[EntityFinancials]) -> List[Dict[str, Any]]:
    rows = []
    for e in entities:
        m, perf = e.metrics, performance_stats(e.closes)
        rows.append({
            "Company": e.name, "Ticker": e.ticker, "Target": e.is_target,
            "Market Cap (bn)": None if m.get("market_cap") is None else round(m["market_cap"] / 1e9, 2),
            "P/E (TTM)": None if m.get("trailing_pe") is None else round(m["trailing_pe"], 1),
            "Fwd P/E": None if m.get("forward_pe") is None else round(m["forward_pe"], 1),
            "Operating Margin (%)": _pct(m.get("operating_margin")), "Net Margin (%)": _pct(m.get("profit_margin")),
            "Revenue Growth (%)": _pct(m.get("revenue_growth")), "ROE (%)": _pct(m.get("roe")),
            "Debt/Equity": None if m.get("debt_to_equity") is None else round(m["debt_to_equity"], 1),
            "Beta": None if m.get("beta") is None else round(m["beta"], 2),
            "1Y Return (%)": perf["return_1y"], "Volatility (%)": perf["volatility"], "Max Drawdown (%)": perf["max_drawdown"],
        })
    return rows


def _table_numbers(rows: List[Dict[str, Any]]) -> List[float]:
    return [float(v) for r in rows for v in r.values() if isinstance(v, (int, float)) and not isinstance(v, bool)]


def ungrounded_numbers(text: str, allowed: List[float], tol: float = 0.06) -> List[str]:
    """Return decimal/percent numbers in `text` that do not appear in `allowed` (hallucination check)."""
    bad = []
    for tok in re.findall(r"-?\d+\.\d+|-?\d+(?=\s?%)", text):
        x = abs(float(tok))
        if not any(abs(x - abs(a)) <= max(tol, 0.005 * abs(a)) for a in allowed):
            bad.append(tok)
    return bad


# ---------------------------------------------------------------------- agent
class AnalystAgent(BaseAgent):
    name = "Data Analyst"

    def run(self, state: GraphState) -> Dict[str, Any]:
        req: ResearchRequest = state["request"]
        run_dir = Path(state.get("run_dir") or self.settings.output_dir)
        entities = fetch_entities(req, self.settings)
        notes: List[str] = []
        result = AnalysisResult(has_quantitative_data=bool(entities), synthetic=any(e.synthetic for e in entities))

        if entities:
            result.comparison_rows = build_comparison_rows(entities)
            chart_dir = run_dir / "charts"
            for path in (
                price_chart(entities, chart_dir / "price_performance.png"),
                bar_chart(result.comparison_rows, "Company", "Operating Margin (%)", chart_dir / "operating_margin.png",
                          "Operating margin (%)", pct=True),
                bar_chart(result.comparison_rows, "Company", "1Y Return (%)", chart_dir / "one_year_return.png",
                          "1-year share price return (%)", pct=True),
            ):
                if path:
                    result.chart_paths.append(path)
            if len(entities) == 1:
                notes.append("Only one entity had market data, so no peer comparison was possible.")
            missing = [n for n in [req.target] + req.competitors if n not in {e.name for e in entities}]
            if missing and req.target_type == "company":
                notes.append("No market data found for: " + ", ".join(missing) + " (unlisted, unrecognised ticker, or data source unavailable).")
            result.insights = self._quant_insights(req, result, notes)
        else:
            notes.append("No listed-company market data was used for this request (industry-level scope or no tickers resolved).")
            result.insights = self._qual_insights(req, state, notes)
        result.notes = notes
        self.stats = {"entities": len(entities), "charts": len(result.chart_paths), "insights": len(result.insights),
                      "synthetic_data": result.synthetic}
        return {"analysis": result, "financials": entities}

    def _quant_insights(self, req: ResearchRequest, result: AnalysisResult, notes: List[str]) -> List[str]:
        slim = [{k: v for k, v in r.items() if k not in ("Target",)} for r in result.comparison_rows]
        import json

        user = f"TARGET: {req.target}\nPEER TABLE (JSON):\n{json.dumps(slim, indent=1)}"
        try:
            data = self._json("analyst_insights", ANALYST_QUANT_SYSTEM, user)
            raw = [str(x).strip() for x in data.get("insights", []) if str(x).strip()]
        except (LLMError, AttributeError) as e:
            notes.append(f"Insight generation failed ({e}); showing computed metrics only.")
            return []
        allowed, kept = _table_numbers(result.comparison_rows), []
        for ins in raw:
            bad = ungrounded_numbers(ins, allowed)
            if bad:
                notes.append(f"An insight was removed because it cited figures not in the data table ({', '.join(bad[:3])}).")
            else:
                kept.append(ins)
        return kept

    def _qual_insights(self, req: ResearchRequest, state: GraphState, notes: List[str]) -> List[str]:
        findings, sources = state.get("findings", []), state.get("sources", [])
        valid = [s.id for s in sources]
        listing = "\n".join(f"- {f.claim} [sources: {', '.join(map(str, f.source_ids))}]" for f in findings)
        user = f"TARGET: {req.target}\nVALID_SOURCE_IDS: {', '.join(map(str, valid))}\nFINDINGS:\n{listing}"
        try:
            data = self._json("analyst_insights", ANALYST_QUAL_SYSTEM, user)
            return [sanitize_citations(str(x).strip(), valid) for x in data.get("insights", []) if str(x).strip()]
        except (LLMError, AttributeError) as e:
            notes.append(f"Insight generation failed ({e}).")
            return []
