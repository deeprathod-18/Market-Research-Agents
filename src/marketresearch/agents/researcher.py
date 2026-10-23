"""Agent 1: Researcher. Plans searches, calls the search tools, and extracts source-grounded findings."""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List

from ..llm import LLMError
from ..prompts import RESEARCHER_EXTRACT_SYSTEM, RESEARCHER_PLAN_SYSTEM
from ..state import FINDING_CATEGORIES, Finding, GraphState, ResearchRequest, Source
from ..tools import search_web, wiki_lookup
from .base import BaseAgent, clean_ids

log = logging.getLogger(__name__)
MAX_SOURCES = 40
BATCH = 10


def _norm_url(u: str) -> str:
    return re.sub(r"[#?].*$", "", u.lower().rstrip("/"))


def fallback_queries(req: ResearchRequest, attempt: int = 1) -> List[Dict[str, str]]:
    """Template queries used if the planning LLM call fails, or to broaden a retry."""
    t, geo = req.target, ("" if req.geography.lower() == "global" else f" {req.geography}")
    base = [
        (f"{t} overview business model{geo}", "overview"), (f"{t} market size growth{geo}", "market"),
        (f"{t} competitors market share{geo}", "competitors"), (f"{t} customers demand{geo}", "customers"),
        (f"{t} industry trends outlook{geo}", "trends"), (f"{t} financial performance revenue", "financials"),
        (f"{t} risks challenges", "risks"), (f"{t} regulation policy", "regulation"),
    ]
    if attempt > 1:
        base = [(f"{t} analysis report {c}{geo}", c) for c in ("market", "competitors", "trends", "risks", "financials")]
    return [{"query": q, "category": c} for q, c in base]


class ResearcherAgent(BaseAgent):
    name = "Researcher"

    def run(self, state: GraphState) -> Dict[str, Any]:
        req: ResearchRequest = state["request"]
        attempt = state.get("research_attempts", 0) + 1
        sources: List[Source] = list(state.get("sources", []))
        findings: List[Finding] = list(state.get("findings", []))

        queries = self._plan(req, attempt, sources)
        new_sources = self._gather(req, queries, sources, attempt)
        sources += new_sources
        dropped = 0
        if new_sources:
            new_findings, dropped = self._extract(req, new_sources)
            findings += new_findings
        self.stats = {"attempt": attempt, "queries": len(queries), "new_sources": len(new_sources),
                      "total_sources": len(sources), "total_findings": len(findings), "findings_dropped_ungrounded": dropped}
        return {"sources": sources, "findings": findings, "research_attempts": attempt}

    # ------------------------------------------------------------------ steps
    def _plan(self, req: ResearchRequest, attempt: int, existing: List[Source]) -> List[Dict[str, str]]:
        previous = sorted({s.query for s in existing if s.query})
        user = (f"TARGET: {req.target}\nTYPE: {req.target_type}\nGEOGRAPHY: {req.geography}\n"
                f"FOCUS: {req.focus or 'general strategic overview'}\n"
                f"KNOWN COMPETITORS: {', '.join(req.competitors) or 'none given'}\nATTEMPT: {attempt}\n")
        if previous:
            user += ("Earlier queries returned too little evidence. Write DIFFERENT, broader queries. "
                     "Do not repeat these:\n- " + "\n- ".join(previous[:12]) + "\n")
        try:
            data = self._json("plan_queries", RESEARCHER_PLAN_SYSTEM, user)
            qs = [{"query": str(q.get("query", "")).strip(), "category": str(q.get("category", "overview")).strip()}
                  for q in data.get("queries", []) if isinstance(q, dict) and str(q.get("query", "")).strip()]
        except (LLMError, AttributeError, TypeError) as e:
            log.warning("query planning failed, using template queries: %s", e)
            qs = []
        if len(qs) < 4:
            qs = fallback_queries(req, attempt)
        seen, out = set(previous), []
        for q in qs:
            if q["query"].lower() not in seen:
                seen.add(q["query"].lower())
                out.append(q)
        return out[:10] or fallback_queries(req, attempt)

    def _gather(self, req: ResearchRequest, queries: List[Dict[str, str]], existing: List[Source], attempt: int) -> List[Source]:
        seen = {_norm_url(s.url) for s in existing}
        next_id = max([s.id for s in existing], default=0) + 1
        new: List[Source] = []

        def add(item: Dict[str, str], query: str, origin: str) -> None:
            nonlocal next_id
            url = item.get("url", "")
            if not url or _norm_url(url) in seen or len(existing) + len(new) >= MAX_SOURCES:
                return
            if not (item.get("snippet") or "").strip():
                return
            seen.add(_norm_url(url))
            new.append(Source(id=next_id, title=item.get("title") or url, url=url,
                              snippet=item["snippet"][:900], query=query, origin=origin))
            next_id += 1

        if attempt == 1:
            wiki = wiki_lookup(req.target, self.settings)
            if wiki:
                add(wiki, "wikipedia", "wikipedia")
        for q in queries:
            for item in search_web(q["query"], self.settings):
                add(item, q["query"], "web")
        return new

    def _extract(self, req: ResearchRequest, new_sources: List[Source]) -> tuple[List[Finding], int]:
        out: List[Finding] = []
        dropped = 0
        for i in range(0, len(new_sources), BATCH):
            batch = new_sources[i : i + BATCH]
            valid = [s.id for s in batch]
            listing = "\n\n".join(f"[{s.id}] {s.title} | {s.url}\n{s.snippet}" for s in batch)
            user = f"TARGET: {req.target}\nFOCUS: {req.focus or 'general strategic overview'}\n\nSOURCES:\n{listing}"
            try:
                data = self._json("extract_findings", RESEARCHER_EXTRACT_SYSTEM, user)
            except LLMError as e:
                log.warning("finding extraction failed for a batch: %s", e)
                out.extend(self._snippet_findings(batch))
                continue
            batch_findings: List[Finding] = []
            for f in data.get("findings", []) if isinstance(data, dict) else []:
                try:
                    claim = str(f.get("claim", "")).strip()
                    ids = clean_ids(f.get("source_ids"), valid)
                    cat = str(f.get("category", "overview")).lower().strip()
                except AttributeError:
                    dropped += 1
                    continue
                if not claim or not ids:  # grounding guardrail: no valid source -> discard
                    dropped += 1
                    continue
                batch_findings.append(Finding(claim=claim, category=cat if cat in FINDING_CATEGORIES else "overview", source_ids=ids))
            if not batch_findings:
                log.warning("finding extraction returned no grounded findings; preserving source snippets")
                batch_findings = self._snippet_findings(batch)
            out.extend(batch_findings)
        return out, dropped

    @staticmethod
    def _snippet_findings(sources: List[Source]) -> List[Finding]:
        """Use verbatim search snippets when the LLM cannot extract claims."""
        categories = {
            "overview": ("overview", "business model", "company"),
            "market": ("market", "industry", "growth", "size"),
            "competitors": ("competitor", "peer", "rival"),
            "customers": ("customer", "client", "demand"),
            "trends": ("trend", "outlook", "forecast"),
            "financials": ("financial", "revenue", "profit", "earnings"),
            "risks": ("risk", "challenge", "threat"),
            "regulation": ("regulation", "policy", "government", "law"),
        }
        findings = []
        for source in sources:
            snippet = source.snippet.strip()
            if not snippet:
                continue
            query = source.query.lower()
            category = next(
                (name for name, terms in categories.items() if any(term in query for term in terms)),
                "overview",
            )
            findings.append(Finding(claim=snippet, category=category, source_ids=[source.id]))
        return findings
