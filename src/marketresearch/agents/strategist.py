"""Agent 3: Strategy Consultant. Turns findings and analysis into SWOT, Five Forces and recommendations."""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from ..llm import LLMError
from ..prompts import STRATEGIST_SYSTEM
from ..state import (Finding, ForceAssessment, GraphState, Recommendation, ResearchRequest, StrategyResult, SWOT, SWOTItem)
from .base import BaseAgent, clean_ids

log = logging.getLogger(__name__)
FORCES = ["Threat of New Entrants", "Bargaining Power of Suppliers", "Bargaining Power of Buyers",
          "Threat of Substitutes", "Competitive Rivalry"]


def _items(raw: Any, valid: List[int]) -> List[SWOTItem]:
    out = []
    for x in raw or []:
        if isinstance(x, str):
            x = {"text": x}
        if isinstance(x, dict) and str(x.get("text", "")).strip():
            out.append(SWOTItem(text=str(x["text"]).strip(), source_ids=clean_ids(x.get("source_ids"), valid)))
    return out[:6]


def parse_strategy(data: Any, valid: List[int]) -> StrategyResult:
    """Validate and clean raw model JSON into a StrategyResult. Invalid citations are stripped."""
    if not isinstance(data, dict):
        raise ValueError("strategy JSON must be an object")
    sw = data.get("swot") or {}
    swot = SWOT(**{q: _items(sw.get(q), valid) for q in ("strengths", "weaknesses", "opportunities", "threats")})
    forces: List[ForceAssessment] = []
    for f in data.get("five_forces") or []:
        if isinstance(f, dict) and f.get("force"):
            forces.append(ForceAssessment(force=str(f["force"]).strip(), rating=str(f.get("rating", "Medium")),
                                          rationale=str(f.get("rationale", "")).strip(), source_ids=clean_ids(f.get("source_ids"), valid)))
    recs: List[Recommendation] = []
    for r in data.get("recommendations") or []:
        if isinstance(r, dict) and str(r.get("title", "")).strip():
            recs.append(Recommendation(
                title=str(r["title"]).strip(), rationale=str(r.get("rationale", "")).strip(),
                priority=str(r.get("priority", "Medium")), timeframe=str(r.get("timeframe", "6-18 months")).strip(),
                expected_impact=str(r.get("expected_impact", "")).strip(), risks=str(r.get("risks", "")).strip(),
                source_ids=clean_ids(r.get("source_ids"), valid)))
    pts = [str(p).strip() for p in data.get("executive_points") or [] if str(p).strip()]
    return StrategyResult(executive_points=pts[:6], swot=swot, five_forces=forces[:5], recommendations=recs[:6])


def adequacy_problems(s: StrategyResult) -> List[str]:
    probs = []
    for q in ("strengths", "weaknesses", "opportunities", "threats"):
        if len(getattr(s.swot, q)) < 3:
            probs.append(f"SWOT '{q}' has fewer than 3 items")
    if len(s.five_forces) < 5:
        probs.append("Five Forces needs all 5 forces")
    if len(s.recommendations) < 3:
        probs.append("at least 3 recommendations are required")
    if not s.executive_points:
        probs.append("executive_points is empty")
    return probs


class StrategistAgent(BaseAgent):
    name = "Strategy Consultant"

    def run(self, state: GraphState) -> Dict[str, Any]:
        req: ResearchRequest = state["request"]
        findings: List[Finding] = state.get("findings", [])
        valid = [s.id for s in state.get("sources", [])]
        analysis = state.get("analysis")
        user = self._build_prompt(req, findings, valid, analysis)

        result, problems = None, []
        llm_error = None
        for attempt in range(2):
            prompt = user if not problems else user + "\n\nFIX THESE PROBLEMS FROM YOUR LAST ANSWER: " + "; ".join(problems)
            try:
                result = parse_strategy(self._json("strategy", STRATEGIST_SYSTEM, prompt, max_tokens=3500), valid)
            except (LLMError, ValueError, TypeError) as e:
                problems = [f"output was invalid ({e})"]
                if isinstance(e, LLMError):
                    llm_error = e
                    break
                continue
            problems = adequacy_problems(result)
            if not problems:
                break
        if result is None:
            result = StrategyResult(
                executive_points=["Strategic assessment unavailable because the language model could not be reached; no strategic conclusions were generated."],
                swot=SWOT(**{
                    quadrant: [SWOTItem(text="Not assessed: language model unavailable.")]
                    for quadrant in ("strengths", "weaknesses", "opportunities", "threats")
                }),
            )
            problems = ["language model unavailable; SWOT, Five Forces, and recommendations were not assessed"]

        all_items = [i for q in ("strengths", "weaknesses", "opportunities", "threats") for i in getattr(result.swot, q)]
        evidenced = sum(1 for i in all_items if i.source_ids) + sum(1 for r in result.recommendations if r.source_ids)
        total = len(all_items) + len(result.recommendations)
        self.stats = {"swot_items": len(all_items), "recommendations": len(result.recommendations),
                      "evidence_coverage": round(evidenced / total, 3) if total else 0.0,
                      "llm_unavailable": llm_error is not None, "unresolved_problems": problems}
        update: Dict[str, Any] = {"strategy": result}
        if problems:
            update["limitations"] = list(state.get("limitations", [])) + [
                "The strategic assessment is incomplete: " + "; ".join(problems) + "."]
        return update

    @staticmethod
    def _build_prompt(req: ResearchRequest, findings: List[Finding], valid: List[int], analysis: Any) -> str:
        lines = [f"TARGET: {req.target}", f"TYPE: {req.target_type}", f"GEOGRAPHY: {req.geography}",
                 f"FOCUS: {req.focus or 'general strategic overview'}",
                 f"VALID_SOURCE_IDS: {', '.join(map(str, valid))}", "", "RESEARCH FINDINGS:"]
        for i, f in enumerate(findings, 1):
            lines.append(f"F{i} [{f.category}] {f.claim} (sources: {', '.join(map(str, f.source_ids))})")
        if analysis is not None:
            lines += ["", "QUANTITATIVE INSIGHTS:"] + [f"- {x}" for x in analysis.insights]
            if analysis.comparison_rows:
                slim = [{k: v for k, v in r.items() if k in ("Company", "Operating Margin (%)", "Revenue Growth (%)", "1Y Return (%)", "P/E (TTM)")}
                        for r in analysis.comparison_rows]
                lines += ["PEER METRICS: " + json.dumps(slim)]
            if analysis.notes:
                lines += ["DATA NOTES: " + " | ".join(analysis.notes)]
        return "\n".join(lines)
