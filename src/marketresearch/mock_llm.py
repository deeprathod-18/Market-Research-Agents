"""Deterministic offline stand-in for an LLM.

Used ONLY for demos, unit tests and CI. It returns structurally valid but generic text so the whole
pipeline can be exercised without network access. Reports produced in mock mode carry a visible
"DEMO MODE" banner and must never be used as real analysis.
"""
from __future__ import annotations

import json
import re
from typing import List

CATEGORIES = ["overview", "market", "competitors", "customers", "trends", "financials", "risks", "regulation"]


def _target(user: str) -> str:
    m = re.search(r"TARGET:\s*(.+)", user)
    return m.group(1).strip() if m else "the target"


def _valid_ids(user: str) -> List[int]:
    m = re.search(r"VALID_SOURCE_IDS:\s*([0-9,\s]+)", user)
    if m:
        ids = [int(x) for x in re.findall(r"\d+", m.group(1))]
        if ids:
            return ids
    return [1]


def _cite(ids: List[int], k: int, n: int = 2) -> List[int]:
    return [ids[(k + j) % len(ids)] for j in range(min(n, len(ids)))]


def mock_chat(task: str, system: str, user: str) -> str:
    t = _target(user)
    ids = _valid_ids(user)

    if task == "plan_queries":
        qs = [
            (f"{t} company overview business model", "overview"),
            (f"{t} market size growth", "market"),
            (f"{t} main competitors market share", "competitors"),
            (f"{t} customer segments demand", "customers"),
            (f"{t} industry trends outlook", "trends"),
            (f"{t} revenue profit financial performance", "financials"),
            (f"{t} risks challenges", "risks"),
            (f"{t} regulation policy impact", "regulation"),
        ]
        return json.dumps({"queries": [{"query": q, "category": c} for q, c in qs]})

    if task == "extract_findings":
        src = [int(x) for x in re.findall(r"^\[(\d+)\]", user, re.M)] or [1]
        out = []
        for i, sid in enumerate(src):
            cat = CATEGORIES[i % len(CATEGORIES)]
            out.append({"claim": f"Demo finding {i + 1} about {t} ({cat}): placeholder statement supported by the cited source.",
                        "category": cat, "source_ids": [sid]})
        return json.dumps({"findings": out})

    if task == "analyst_insights":
        return json.dumps({"insights": [
            f"Demo insight 1: {t} shows a mixed profitability profile relative to peers in the synthetic dataset.",
            "Demo insight 2: valuation multiples differ materially across the peer group.",
            "Demo insight 3: price volatility and drawdown vary, indicating different risk profiles.",
            "Demo insight 4: all figures here are synthetic and exist only to test the pipeline.",
        ]})

    if task == "strategy":
        def items(prefix: str, n: int = 4):
            return [{"text": f"{prefix} point {i + 1} for {t} (demo content).", "source_ids": _cite(ids, i)} for i in range(n)]
        forces = ["Threat of New Entrants", "Bargaining Power of Suppliers", "Bargaining Power of Buyers",
                  "Threat of Substitutes", "Competitive Rivalry"]
        ratings = ["Medium", "Low", "High", "Medium", "High"]
        return json.dumps({
            "executive_points": [f"Demo executive point {i + 1} about {t}." for i in range(4)],
            "swot": {"strengths": items("Strength"), "weaknesses": items("Weakness"),
                     "opportunities": items("Opportunity"), "threats": items("Threat")},
            "five_forces": [{"force": f, "rating": r, "rationale": f"Demo rationale for {f.lower()}.",
                             "source_ids": _cite(ids, i)} for i, (f, r) in enumerate(zip(forces, ratings))],
            "recommendations": [{
                "title": f"Demo recommendation {i + 1}", "rationale": f"Demo rationale {i + 1} for {t}.",
                "priority": ["High", "High", "Medium", "Low"][i], "timeframe": ["0-6 months", "6-18 months", "6-18 months", "18+ months"][i],
                "expected_impact": "Illustrative impact (demo).", "risks": "Illustrative risk (demo).",
                "source_ids": _cite(ids, i)} for i in range(4)],
        })

    if task.startswith("write_section"):
        name = task.split(":", 1)[1] if ":" in task else "section"
        c = _cite(ids, 0, 2)
        cite = "[" + ", ".join(str(x) for x in c) + "]"
        return (f"- Demo prose for the {name} section on {t}, generated offline for pipeline testing {cite}.\n"
                f"- A second supporting point is included so formatting can be checked {cite}.\n"
                f"- This text is not real analysis.")

    if task == "judge":
        return json.dumps({"relevance": 4, "depth": 3, "actionability": 3, "grounding": 4, "clarity": 4,
                           "comment": "Mock judge: scores are placeholders."})

    if task == "baseline_single":
        c = "[" + ", ".join(str(x) for x in _cite(ids, 0, 2)) + "]"
        return (f"# Market Brief: {t}\n\n## Executive Summary\n- Demo single-agent summary {c}.\n\n"
                f"## Competitive Landscape\n- Demo landscape paragraph {c}.\n\n## SWOT Analysis\n"
                f"- Strengths: demo {c}\n- Weaknesses: demo\n- Opportunities: demo\n- Threats: demo\n\n"
                f"## Recommendations\n1. Demo recommendation {c}\n2. Demo recommendation\n\n"
                f"## Risks and Limitations\n- Demo risk.\n\n## References\n- See sources.\n")

    return json.dumps({"note": "mock backend has no handler for this task", "task": task})
