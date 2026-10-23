import json
from pathlib import Path

import pytest

from marketresearch.agents.strategist import adequacy_problems, parse_strategy
from marketresearch.orchestrator import Pipeline, evaluate_gate, slugify
from marketresearch.state import Finding, ResearchRequest, Source


def req(**kw):
    return ResearchRequest(**{"target": "Acme Robotics", "competitors": ["Beta", "Gamma"], **kw})


def test_parse_strategy_strips_invalid_citations():
    data = {"executive_points": ["a"], "swot": {"strengths": [{"text": "s", "source_ids": [1, 99]}, "plain string"]},
            "five_forces": [{"force": "Competitive Rivalry", "rating": "high"}],
            "recommendations": [{"title": "t", "rationale": "r", "priority": "urgent", "source_ids": [2]}]}
    s = parse_strategy(data, valid=[1, 2])
    assert s.swot.strengths[0].source_ids == [1] and s.swot.strengths[1].source_ids == []
    assert s.five_forces[0].rating == "High"
    assert s.recommendations[0].priority == "Medium"  # invalid value normalised


def test_adequacy_flags_thin_output():
    s = parse_strategy({"executive_points": ["x"]}, valid=[1])
    problems = adequacy_problems(s)
    assert any("SWOT" in p for p in problems) and any("recommendations" in p for p in problems)


def test_parse_strategy_rejects_non_object():
    with pytest.raises(ValueError):
        parse_strategy([1, 2], valid=[1])


def _state(n_sources, n_findings, cats, attempts):
    srcs = [Source(id=i, title="t", url=f"https://x.com/{i}") for i in range(1, n_sources + 1)]
    fnd = [Finding(claim="c", category=cats[i % len(cats)], source_ids=[1]) for i in range(n_findings)]
    return {"sources": srcs, "findings": fnd, "research_attempts": attempts, "limitations": []}


def test_gate_proceeds_when_evidence_sufficient(settings):
    d = evaluate_gate(_state(10, 10, ["a", "b", "c", "d"], 1), settings)
    assert d["gate_decision"] == "proceed"


def test_gate_retries_then_proceeds_with_limitation(settings):
    thin = _state(3, 3, ["a"], 1)
    assert evaluate_gate(thin, settings)["gate_decision"] == "retry"
    final = evaluate_gate(_state(3, 3, ["a"], settings.max_research_attempts), settings)
    assert final["gate_decision"] == "proceed" and final["limitations"]


def test_gate_aborts_without_any_evidence(settings):
    assert evaluate_gate(_state(0, 0, ["a"], settings.max_research_attempts), settings)["gate_decision"] == "abort"


def test_end_to_end_company(settings):
    res = Pipeline(settings).run(req())
    assert res.status == "success", res.error
    md = res.report_markdown
    for heading in ("Executive Summary", "SWOT Analysis", "Porter's Five Forces", "Strategic Recommendations", "References", "DEMO MODE"):
        assert heading in md
    assert Path(res.report_paths["docx"]).stat().st_size > 10_000
    assert [t["node"] for t in res.trace][:2] == ["researcher", "quality_gate"]
    summary = json.loads((Path(res.run_dir) / "run_summary.json").read_text())
    assert summary["status"] == "success" and summary["usage"]["calls"] >= 8


def test_end_to_end_industry_without_market_data(settings):
    res = Pipeline(settings).run(ResearchRequest(target="Indian EV two-wheeler market", target_type="industry", geography="India"))
    assert res.status == "success"
    assert "No listed-company market data" in res.report_markdown


def test_all_report_citations_are_valid(settings):
    import re

    res = Pipeline(settings).run(req())
    ids = {s.id for s in res.state["sources"]}
    cited = {int(n) for grp in re.findall(r"\[(\d+(?:,\s*\d+)*)\]", res.report_markdown) for n in re.findall(r"\d+", grp)}
    assert cited and cited <= ids


def test_pipeline_retries_when_evidence_thin(settings):
    settings.min_sources = 60  # impossible with the 40-source cap, forces the retry loop
    res = Pipeline(settings).run(req())
    gates = [t for t in res.trace if t["node"] == "quality_gate"]
    assert len(gates) == settings.max_research_attempts
    assert res.status == "success" and any("quality gate" in x.lower() for x in res.state["limitations"])


def test_pipeline_fails_cleanly_when_search_returns_nothing(settings, monkeypatch):
    import marketresearch.agents.researcher as r

    monkeypatch.setattr(r, "search_web", lambda *a, **k: [])
    monkeypatch.setattr(r, "wiki_lookup", lambda *a, **k: None)
    res = Pipeline(settings).run(req())
    assert res.status == "failed" and "No usable evidence" in res.error
    assert (Path(res.run_dir) / "run_summary.json").exists()


def test_pipeline_writes_limited_report_when_llm_is_unavailable(settings, monkeypatch):
    from marketresearch.llm import LLMClient, LLMError

    llm = LLMClient(settings)

    def unavailable(**kwargs):
        raise LLMError("provider quota exhausted")

    monkeypatch.setattr(llm, "complete_json", unavailable)
    monkeypatch.setattr(llm, "complete", unavailable)
    res = Pipeline(settings, llm=llm).run(req())

    assert res.status == "success", res.error
    assert Path(res.report_paths["docx"]).is_file()
    assert "Not assessed: language model unavailable." in res.report_markdown
    assert res.state["findings"] and all(f.source_ids for f in res.state["findings"])
    assert any("language model unavailable" in item for item in res.state["limitations"])


def test_ungrounded_findings_are_dropped(settings, monkeypatch):
    from marketresearch.agents.researcher import ResearcherAgent
    from marketresearch.llm import LLMClient

    llm = LLMClient(settings)
    real = llm._backend.chat

    def fake(task, system, user, t, m):
        if task == "extract_findings":
            return json.dumps({"findings": [{"claim": "ok", "category": "market", "source_ids": [1]},
                                            {"claim": "invented", "category": "market", "source_ids": [999]},
                                            {"claim": "uncited", "category": "market", "source_ids": []}]}), 1, 1
        return real(task, system, user, t, m)

    llm._backend.chat = fake
    agent = ResearcherAgent(llm, settings)
    out = agent.run({"request": req(), "sources": [], "findings": [], "research_attempts": 0})
    assert agent.stats["findings_dropped_ungrounded"] >= 2
    assert all(f.source_ids for f in out["findings"])


def test_slugify():
    assert slugify("Tata Motors (EV)!") == "tata_motors_ev"
