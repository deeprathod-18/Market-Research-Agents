"""LangGraph workflow that coordinates the four agents, with a supervisor-style quality gate.

    START -> researcher -> quality_gate -+-> (retry)   -> researcher
                                         +-> (proceed) -> analyst -> strategist -> writer -> END
                                         +-> (abort)   -> END
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

from langgraph.graph import END, START, StateGraph

from .agents import AnalystAgent, ResearcherAgent, StrategistAgent, WriterAgent
from .config import Settings, get_settings
from .llm import LLMClient
from .state import GraphState, ResearchRequest

log = logging.getLogger(__name__)
EventCb = Optional[Callable[[Dict[str, Any]], None]]


class PipelineError(RuntimeError):
    pass


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:40] or "run"


@dataclass
class ResearchResult:
    status: str  # success | failed
    state: Dict[str, Any]
    run_dir: str
    trace: List[Dict[str, Any]] = field(default_factory=list)
    usage: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    duration_s: float = 0.0

    @property
    def report_markdown(self) -> str:
        return self.state.get("report_markdown", "")

    @property
    def report_paths(self) -> Dict[str, str]:
        return self.state.get("report_paths", {})


def evaluate_gate(state: GraphState, s: Settings) -> Dict[str, Any]:
    """Pure decision function for the quality gate (unit tested)."""
    sources, findings = state.get("sources", []), state.get("findings", [])
    attempts = state.get("research_attempts", 0)
    cats = {f.category for f in findings}
    ok = len(sources) >= s.min_sources and len(findings) >= s.min_findings and len(cats) >= 4
    reason = f"{len(sources)} sources, {len(findings)} findings, {len(cats)} categories (need {s.min_sources}/{s.min_findings}/4)"
    if ok:
        return {"gate_decision": "proceed", "gate_reason": reason}
    if attempts < s.max_research_attempts:
        return {"gate_decision": "retry", "gate_reason": "Insufficient evidence: " + reason}
    if not sources or not findings:
        return {"gate_decision": "abort", "gate_reason": "No usable evidence after all attempts: " + reason}
    lims = list(state.get("limitations", [])) + [
        f"Research quality gate not fully met after {attempts} attempts ({reason}); conclusions rest on a limited evidence base."]
    return {"gate_decision": "proceed", "gate_reason": "Proceeding with limitations: " + reason, "limitations": lims}


class Pipeline:
    def __init__(self, settings: Optional[Settings] = None, llm: Optional[LLMClient] = None):
        self.settings = settings or get_settings()
        self.llm = llm or LLMClient(self.settings)
        self.agents = {
            "researcher": ResearcherAgent(self.llm, self.settings),
            "analyst": AnalystAgent(self.llm, self.settings),
            "strategist": StrategistAgent(self.llm, self.settings),
            "writer": WriterAgent(self.llm, self.settings),
        }
        self.trace: List[Dict[str, Any]] = []
        self._cb: EventCb = None
        self.graph = self._build()

    # ------------------------------------------------------------------ graph
    def _emit(self, **ev: Any) -> None:
        if self._cb:
            try:
                self._cb(ev)
            except Exception:  # UI callbacks must never break the pipeline
                log.exception("event callback failed")

    def _wrap(self, key: str, label: str, fn: Callable[[GraphState], Dict[str, Any]], stats_from: Optional[Any] = None):
        def node(state: GraphState) -> Dict[str, Any]:
            mark, t0 = self.llm.usage.snapshot(), time.perf_counter()
            self._emit(node=key, label=label, status="running")
            try:
                update = fn(state)
            except Exception as e:
                self.trace.append({"node": key, "agent": label, "status": "error", "error": str(e),
                                   "duration_s": round(time.perf_counter() - t0, 2), **self.llm.usage.since(mark)})
                self._emit(node=key, label=label, status="error", error=str(e))
                raise
            entry = {"node": key, "agent": label, "status": "ok", "duration_s": round(time.perf_counter() - t0, 2),
                     **self.llm.usage.since(mark), "details": dict(getattr(stats_from, "stats", {}) or {})}
            if key == "quality_gate":
                entry["details"] = {"decision": update.get("gate_decision"), "reason": update.get("gate_reason")}
            self.trace.append(entry)
            self._emit(node=key, label=label, status="done", details=entry["details"])
            return update
        return node

    def _build(self):
        a = self.agents
        g = StateGraph(GraphState)
        g.add_node("researcher", self._wrap("researcher", "Researcher", a["researcher"].run, a["researcher"]))
        g.add_node("quality_gate", self._wrap("quality_gate", "Orchestrator quality gate", lambda st: evaluate_gate(st, self.settings)))
        g.add_node("analyst", self._wrap("analyst", "Data Analyst", a["analyst"].run, a["analyst"]))
        g.add_node("strategist", self._wrap("strategist", "Strategy Consultant", a["strategist"].run, a["strategist"]))
        g.add_node("writer", self._wrap("writer", "Report Writer", a["writer"].run, a["writer"]))
        g.add_edge(START, "researcher")
        g.add_edge("researcher", "quality_gate")
        g.add_conditional_edges("quality_gate", lambda st: st["gate_decision"],
                                {"retry": "researcher", "proceed": "analyst", "abort": END})
        g.add_edge("analyst", "strategist")
        g.add_edge("strategist", "writer")
        g.add_edge("writer", END)
        return g.compile()

    # ------------------------------------------------------------------ run
    def run(self, request: Union[ResearchRequest, Dict[str, Any]], on_event: EventCb = None) -> ResearchResult:
        req = request if isinstance(request, ResearchRequest) else ResearchRequest(**request)
        self._cb, self.trace = on_event, []
        self.llm.usage.records.clear()
        run_dir = self.settings.output_dir / f"{slugify(req.target)}_{dt.datetime.now():%Y%m%d_%H%M%S}"
        run_dir.mkdir(parents=True, exist_ok=True)
        state: Dict[str, Any] = {"request": req, "run_dir": str(run_dir), "sources": [], "findings": [],
                                 "research_attempts": 0, "limitations": [], "errors": []}
        t0, status, error = time.perf_counter(), "success", None
        try:
            for chunk in self.graph.stream(dict(state), config={"recursion_limit": 30}, stream_mode="updates"):
                for _node, upd in chunk.items():
                    state.update(upd or {})
            if state.get("gate_decision") == "abort":
                status, error = "failed", state.get("gate_reason", "research produced no usable evidence")
            elif "report_markdown" not in state:
                status, error = "failed", "pipeline ended without producing a report"
        except Exception as e:
            log.exception("pipeline failed")
            status, error = "failed", f"{type(e).__name__}: {e}"
        res = ResearchResult(status=status, state=state, run_dir=str(run_dir), trace=list(self.trace),
                             usage=self.llm.usage.summary(self.settings.price_per_1m_input, self.settings.price_per_1m_output),
                             error=error, duration_s=round(time.perf_counter() - t0, 2))
        self._save_summary(res)
        return res

    @staticmethod
    def _save_summary(res: ResearchResult) -> None:
        st = res.state

        def dump(x: Any) -> Any:
            if hasattr(x, "model_dump"):
                return x.model_dump()
            if isinstance(x, list):
                return [dump(i) for i in x]
            return x

        analysis = dump(st.get("analysis"))
        summary = {"status": res.status, "error": res.error, "duration_s": res.duration_s, "usage": res.usage, "trace": res.trace,
                   "request": dump(st.get("request")), "sources": dump(st.get("sources", [])), "findings": dump(st.get("findings", [])),
                   "analysis": analysis, "strategy": dump(st.get("strategy")), "limitations": st.get("limitations", []),
                   "gate": {"decision": st.get("gate_decision"), "reason": st.get("gate_reason")},
                   "report_paths": st.get("report_paths", {})}
        try:
            (Path(res.run_dir) / "run_summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
        except OSError as e:  # pragma: no cover
            log.warning("could not write run summary: %s", e)


def run_research(request: Union[ResearchRequest, Dict[str, Any]], settings: Optional[Settings] = None,
                 on_event: EventCb = None) -> ResearchResult:
    """One-call convenience wrapper used by the CLI, the UI and the evaluation harness."""
    return Pipeline(settings).run(request, on_event=on_event)
