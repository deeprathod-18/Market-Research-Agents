"""Objective, reproducible report-quality metrics. Applied identically to both systems (multi-agent and single-agent)."""
from __future__ import annotations

import re
from typing import Any, Dict, List

REQUIRED_SECTIONS = {
    "executive_summary": ("executive summary",), "landscape": ("competitive", "landscape", "market"),
    "swot": ("swot",), "recommendations": ("recommendation",), "risks": ("risk", "limitation"), "references": ("reference", "source"),
}
_CITE = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")


def headings(md: str) -> List[str]:
    return [ln.lstrip("#").strip().lower() for ln in md.splitlines() if ln.startswith("#")]


def section_completeness(md: str) -> float:
    hs = headings(md)
    hit = sum(1 for keys in REQUIRED_SECTIONS.values() if any(any(k in h for k in keys) for h in hs))
    return round(hit / len(REQUIRED_SECTIONS), 3)


def citation_stats(md: str, valid_ids: List[int]) -> Dict[str, Any]:
    body = md.split("## References")[0]
    ids = [int(n) for grp in _CITE.findall(body) for n in re.findall(r"\d+", grp)]
    valid = set(valid_ids)
    good = [i for i in ids if i in valid]
    words = max(len(body.split()), 1)
    return {"citations_total": len(ids), "citation_validity": round(len(good) / len(ids), 3) if ids else 0.0,
            "citations_per_1k_words": round(len(ids) / words * 1000, 1), "unique_sources_cited": len(set(good))}


def numeric_facts(md: str) -> int:
    body = md.split("## References")[0]
    return len(re.findall(r"\d+(?:\.\d+)?\s?%|[$₹€£]\s?\d[\d,.]*|\b\d+(?:\.\d+)?\s?(?:bn|billion|million|crore|lakh)\b", body, flags=re.I))


def report_metrics(md: str, valid_ids: List[int]) -> Dict[str, Any]:
    out = {"words": len(md.split()), "section_completeness": section_completeness(md), "numeric_facts": numeric_facts(md)}
    out.update(citation_stats(md, valid_ids))
    return out


def mean(vals: List[float]) -> float:
    vals = [v for v in vals if v is not None]
    return round(sum(vals) / len(vals), 3) if vals else 0.0
