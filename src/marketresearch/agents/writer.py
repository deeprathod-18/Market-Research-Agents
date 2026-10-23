"""Agent 4: Report Writer. Assembles the final brief (LLM prose + deterministic tables) and exports files."""
from __future__ import annotations

import datetime as dt
import logging
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from ..llm import LLMError
from ..prompts import WRITER_SYSTEM
from ..report.exporter import markdown_to_docx
from ..state import Finding, GraphState, ResearchRequest, Source, StrategyResult, SWOTItem
from .base import BaseAgent, sanitize_citations

log = logging.getLogger(__name__)


def md_table(headers: List[str], rows: Iterable[List[str]]) -> str:
    esc = lambda s: str(s).replace("|", "/").replace("\n", " ")
    out = ["| " + " | ".join(esc(h) for h in headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    out += ["| " + " | ".join(esc(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def cite(ids: List[int]) -> str:
    return f" [{', '.join(map(str, ids))}]" if ids else ""


def fmt(v: Any, suffix: str = "", nd: int = 1) -> str:
    return "n/a" if v is None else f"{v:,.{nd}f}{suffix}"


def swot_table(a_name: str, a: List[SWOTItem], b_name: str, b: List[SWOTItem]) -> str:
    n = max(len(a), len(b))
    cell = lambda lst, i: (lst[i].text + cite(lst[i].source_ids)) if i < len(lst) else ""
    return md_table([a_name, b_name], [[cell(a, i), cell(b, i)] for i in range(n)])


class WriterAgent(BaseAgent):
    name = "Report Writer"

    def run(self, state: GraphState) -> Dict[str, Any]:
        req: ResearchRequest = state["request"]
        sources: List[Source] = state.get("sources", [])
        findings: List[Finding] = state.get("findings", [])
        strategy: StrategyResult = state["strategy"]
        analysis = state["analysis"]
        run_dir = Path(state.get("run_dir") or self.settings.output_dir)
        valid = [s.id for s in sources]
        limitations = list(state.get("limitations", []))

        sections = {
            "executive_summary": self._prose("executive_summary", req, valid, findings, strategy, analysis,
                                             "Write 5 to 6 bullets. First bullet states the overall conclusion. Cover market position, key risk and top recommendation."),
            "overview": self._prose("overview", req, valid, [f for f in findings if f.category in ("overview", "customers", "financials")],
                                    strategy, analysis, f"Write 4 to 5 bullets describing what {req.target} is, how it operates and who it serves."),
            "landscape": self._prose("landscape", req, valid,
                                     [f for f in findings if f.category in ("market", "competitors", "trends", "regulation")],
                                     strategy, analysis, "Write 5 to 7 bullets on market size/growth, competitors, trends and regulation."),
            "roadmap": self._prose("roadmap", req, valid, [], strategy, analysis,
                                   "Write 4 to 6 bullets forming a phased implementation roadmap (0-6, 6-18, 18+ months) with one KPI per phase."),
        }
        md = self._assemble(req, sources, findings, strategy, analysis, sections, limitations, run_dir)

        run_dir.mkdir(parents=True, exist_ok=True)
        md_path, docx_path = run_dir / "report.md", run_dir / "report.docx"
        md_path.write_text(md, encoding="utf-8")
        try:
            markdown_to_docx(md, docx_path, base_dir=run_dir)
        except Exception as e:  # keep the markdown even if docx export fails
            log.error("DOCX export failed: %s", e)
            limitations.append(f"DOCX export failed: {e}")
            docx_path = None
        paths = {"markdown": str(md_path)}
        if docx_path:
            paths["docx"] = str(docx_path)
        words = len(md.split())
        self.stats = {"words": words, "sections_llm": len(sections), "citations": len(re.findall(r"\[\d+(?:,\s*\d+)*\]", md))}
        return {"report_markdown": md, "report_paths": paths, "limitations": limitations}

    # ------------------------------------------------------------------ LLM prose sections
    def _prose(self, name: str, req: ResearchRequest, valid: List[int], findings: List[Finding],
               strategy: StrategyResult, analysis: Any, instruction: str) -> str:
        lines = [f"TARGET: {req.target}", f"FOCUS: {req.focus or 'general strategic overview'}",
                 f"VALID_SOURCE_IDS: {', '.join(map(str, valid))}", f"TASK: {instruction}", ""]
        if findings:
            lines += ["FACTS:"] + [f"- {f.claim} [{', '.join(map(str, f.source_ids))}]" for f in findings]
        if name == "executive_summary":
            lines += ["KEY POINTS:"] + [f"- {p}" for p in strategy.executive_points]
            lines += ["TOP RECOMMENDATIONS:"] + [f"- {r.title}: {r.rationale}" for r in strategy.recommendations[:3]]
            lines += ["INSIGHTS:"] + [f"- {i}" for i in analysis.insights[:4]]
        if name == "roadmap":
            lines += ["RECOMMENDATIONS:"] + [f"- {r.title} ({r.priority}, {r.timeframe}): {r.expected_impact}" for r in strategy.recommendations]
        try:
            text = self._text(f"write_section:{name}", WRITER_SYSTEM, "\n".join(lines))
        except LLMError as e:
            log.warning("writer section %s failed: %s", name, e)
            return "- This section could not be generated because the language model call failed."
        text = sanitize_citations(text, valid)
        # normalise to bullet lines
        out = []
        for ln in text.splitlines():
            ln = ln.strip()
            if not ln:
                continue
            out.append(ln if ln.startswith(("- ", "* ")) else "- " + re.sub(r"^\d+[.)]\s*", "", ln))
        return "\n".join(out)

    # ------------------------------------------------------------------ assembly
    def _assemble(self, req: ResearchRequest, sources: List[Source], findings: List[Finding], st: StrategyResult,
                  analysis: Any, sec: Dict[str, str], limitations: List[str], run_dir: Path) -> str:
        today = dt.date.today().strftime("%d %B %Y")
        domains = sorted({s.domain for s in sources})
        kind = "Company" if req.target_type == "company" else "Industry"
        P: List[str] = [f"# {req.target}: Market and Competitor Brief", "",
                        f"**Scope:** {kind} analysis | **Geography:** {req.geography} | **Focus:** {req.focus or 'General strategic overview'} | **Date:** {today}", ""]
        if self.settings.is_mock or analysis.synthetic:
            P += ["> **DEMO MODE.** This brief was generated with the offline mock language model and/or synthetic market data. "
                  "It contains placeholder content for pipeline testing only and is NOT real analysis.", ""]

        P += ["## 1. Executive Summary", "", sec["executive_summary"], ""]
        P += [f"## 2. {kind} Overview", "", sec["overview"], ""]
        P += ["## 3. Market and Competitive Landscape", "", sec["landscape"], ""]

        P += ["## 4. Quantitative Benchmarking", ""]
        if analysis.has_quantitative_data and analysis.comparison_rows:
            cols = [("Company", "Company", ""), ("Market Cap (bn)", "Mkt Cap (bn)", ""), ("P/E (TTM)", "P/E", ""),
                    ("Operating Margin (%)", "Op. Margin", "%"), ("Revenue Growth (%)", "Rev. Growth", "%"),
                    ("1Y Return (%)", "1Y Return", "%"), ("Volatility (%)", "Volatility", "%")]
            rows = [[r["Company"] if k == "Company" else fmt(r.get(k), suf) for k, _, suf in cols] for r in analysis.comparison_rows]
            P += [md_table([h for _, h, _ in cols], rows), ""]
            src = "SYNTHETIC demo data (not real market data)" if analysis.synthetic else f"Yahoo Finance via yfinance, retrieved {today}"
            P += [f"*Source: {src}. Margins and growth are as reported by the data provider; return and volatility are computed from daily closing prices.*", ""]
            for p in analysis.chart_paths:
                rel = Path(p).relative_to(run_dir) if Path(p).is_relative_to(run_dir) else Path(p)
                cap = {"price_performance": "Indexed share price performance", "operating_margin": "Operating margin comparison",
                       "one_year_return": "One-year share price return"}.get(Path(p).stem, Path(p).stem)
                P += [f"![{cap}]({rel.as_posix()})", ""]
        else:
            P += ["No listed-company market data was available for this request, so benchmarking relies on the research findings below.", ""]
        if analysis.insights:
            P += ["**Key insights**", ""] + [f"- {i}" for i in analysis.insights] + [""]

        P += ["## 5. Strategic Assessment", "", "### 5.1 SWOT Analysis", "",
              swot_table("Strengths", st.swot.strengths, "Weaknesses", st.swot.weaknesses), "",
              swot_table("Opportunities", st.swot.opportunities, "Threats", st.swot.threats), "",
              "### 5.2 Porter's Five Forces", "",
              md_table(["Force", "Intensity", "Rationale"],
                       [[f.force, f.rating, f.rationale + cite(f.source_ids)] for f in st.five_forces]), ""]

        P += ["## 6. Strategic Recommendations", "",
              md_table(["#", "Recommendation", "Priority", "Timeframe", "Expected impact"],
                       [[str(i), r.title, r.priority, r.timeframe, r.expected_impact] for i, r in enumerate(st.recommendations, 1)]), ""]
        for i, r in enumerate(st.recommendations, 1):
            P += [f"**{i}. {r.title}**", "", f"- **Rationale:** {r.rationale}{cite(r.source_ids)}",
                  f"- **Key risk:** {r.risks or 'Not specified.'}", ""]
        P += ["### Implementation roadmap", "", sec["roadmap"], ""]

        P += ["## 7. Risks and Limitations", ""]
        lim = ["Findings are extracted from search-result snippets, not from full page reading, and may omit context.",
               "Source quality varies; claims should be verified against primary documents before decisions are made.",
               "This brief is analysis for discussion and is not investment, legal or financial advice."]
        if len(sources) < 8:
            lim.append(f"Evidence base is thin: only {len(sources)} sources were found.")
        lim += limitations + list(analysis.notes)
        P += [f"- {x}" for x in dict.fromkeys(lim)] + [""]

        P += ["## 8. Methodology", "",
              f"- Four cooperating agents (Researcher, Data Analyst, Strategy Consultant, Report Writer) coordinated by a LangGraph workflow.",
              f"- Evidence base: {len(sources)} sources from {len(domains)} domains and {len(findings)} extracted findings.",
              "- Every citation [n] refers to the reference list below; citation numbers not matching a real source are removed automatically.", ""]

        P += ["## References", ""]
        for s in sources:
            P.append(f"- [{s.id}] {s.title}. {s.domain}. {s.url}")
        P.append("")
        return "\n".join(P)
