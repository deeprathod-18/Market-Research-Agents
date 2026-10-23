#!/usr/bin/env python3
"""Evaluate the multi-agent system against a single-agent baseline on a fixed set of test cases.

  python evaluation/run_eval.py --provider groq --judge
  python evaluation/run_eval.py --provider mock --limit 2        # pipeline smoke test only; numbers are meaningless
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from evaluation.baseline import run_baseline  # noqa: E402
from evaluation.metrics import mean, report_metrics  # noqa: E402
from marketresearch.config import get_settings  # noqa: E402
from marketresearch.llm import LLMClient, LLMError  # noqa: E402
from marketresearch.orchestrator import Pipeline  # noqa: E402
from marketresearch.prompts import JUDGE_SYSTEM  # noqa: E402
from marketresearch.state import ResearchRequest  # noqa: E402

CRITERIA = ["relevance", "depth", "actionability", "grounding", "clarity"]


def judge(llm: LLMClient, md: str, req: ResearchRequest) -> dict:
    user = f"TARGET: {req.target}\nFOCUS: {req.focus}\n\nBRIEF TO REVIEW:\n{md[:14000]}"
    try:
        d = llm.complete_json(agent="Judge", task="judge", system=JUDGE_SYSTEM, user=user, temperature=0.0)
        return {k: int(d[k]) for k in CRITERIA if k in d} | {"comment": str(d.get("comment", ""))[:300]}
    except (LLMError, ValueError, TypeError, KeyError) as e:
        return {"error": str(e)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", default=str(ROOT / "evaluation" / "test_cases.json"))
    ap.add_argument("--provider", default=None)
    ap.add_argument("--model", default=None)
    ap.add_argument("--judge", action="store_true", help="add an LLM-as-judge rubric score (costs extra calls)")
    ap.add_argument("--judge-provider", default=None, help="use a different provider for judging to reduce self-preference bias")
    ap.add_argument("--limit", type=int, default=None)
    a = ap.parse_args()

    overrides = {k: v for k, v in (("provider", a.provider), ("model", a.model)) if v}
    settings = get_settings(**overrides)
    judge_llm = LLMClient(get_settings(provider=a.judge_provider)) if (a.judge and a.judge_provider) else None
    cases = json.loads(Path(a.cases).read_text())[: a.limit]
    print(f"Evaluating {len(cases)} cases | provider={settings.provider} model={settings.model}")

    rows = []
    for c in cases:
        cid = c.pop("id")
        req = ResearchRequest(**c)
        print(f"[{cid}] {req.target}")
        pipe = Pipeline(settings)
        multi = pipe.run(req)
        rec = {"id": cid, "target": req.target, "type": req.target_type, "multi": {"ok": multi.status == "success"}, "single": {"ok": False}}
        if multi.status == "success":
            valid = [s.id for s in multi.state["sources"]]
            m = report_metrics(multi.report_markdown, valid)
            st = multi.state["strategy"]
            m.update({"latency_s": multi.duration_s, "llm_calls": multi.usage["calls"],
                      "tokens": multi.usage["prompt_tokens"] + multi.usage["completion_tokens"], "cost_usd": multi.usage["est_cost_usd"],
                      "evidence_coverage": next((t["details"].get("evidence_coverage") for t in multi.trace if t["node"] == "strategist"), None),
                      "findings_dropped": next((t["details"].get("findings_dropped_ungrounded") for t in multi.trace if t["node"] == "researcher"), None),
                      "swot_items": sum(len(getattr(st.swot, q)) for q in ("strengths", "weaknesses", "opportunities", "threats"))})
            if a.judge:
                m["judge"] = judge(judge_llm or pipe.llm, multi.report_markdown, req)
            rec["multi"].update(m)
            # baseline: same sources and market data, one prompt
            bllm = LLMClient(settings)
            try:
                text, lat = run_baseline(bllm, req, multi.state["sources"], multi.state["analysis"].comparison_rows)
                bm = report_metrics(text, valid)
                u = bllm.usage.summary(settings.price_per_1m_input, settings.price_per_1m_output)
                bm.update({"latency_s": lat, "llm_calls": u["calls"], "tokens": u["prompt_tokens"] + u["completion_tokens"], "cost_usd": u["est_cost_usd"]})
                if a.judge:
                    bm["judge"] = judge(judge_llm or bllm, text, req)
                rec["single"].update({"ok": True, **bm})
            except LLMError as e:
                rec["single"]["error"] = str(e)
        else:
            rec["multi"]["error"] = multi.error
        rows.append(rec)

    # ------------------------------------------------------------------ aggregate
    def agg(system: str, key: str):
        return mean([r[system].get(key) for r in rows if r[system].get("ok")])

    keys = [("section_completeness", "Section completeness (0-1)"), ("citation_validity", "Citation validity (0-1)"),
            ("citations_per_1k_words", "Citations per 1k words"), ("unique_sources_cited", "Unique sources cited"),
            ("numeric_facts", "Numeric facts in report"), ("words", "Report length (words)"), ("latency_s", "Latency (s)"),
            ("llm_calls", "LLM calls"), ("tokens", "Total tokens"), ("cost_usd", "Est. cost (USD)")]
    out = [f"# Evaluation results\n\nProvider: `{settings.provider}` / `{settings.model}` | cases: {len(rows)} | date: {dt.date.today()}\n"]
    if settings.is_mock:
        out.append("> **MOCK MODE: these numbers come from the offline stub and must NOT be reported as results.**\n")
    out.append(f"Success rate: multi-agent {sum(r['multi']['ok'] for r in rows)}/{len(rows)}, single-agent {sum(r['single']['ok'] for r in rows)}/{len(rows)}\n")
    out += ["## Mean metrics", "", "| Metric | Multi-agent | Single-agent |", "|---|---|---|"]
    out += [f"| {label} | {agg('multi', k)} | {agg('single', k)} |" for k, label in keys]
    if a.judge:
        out += ["", "## LLM-as-judge (1-5)", "", "| Criterion | Multi-agent | Single-agent |", "|---|---|---|"]
        for cr in CRITERIA:
            mv = mean([r["multi"].get("judge", {}).get(cr) for r in rows if r["multi"].get("ok")])
            sv = mean([r["single"].get("judge", {}).get(cr) for r in rows if r["single"].get("ok")])
            out.append(f"| {cr.capitalize()} | {mv} | {sv} |")
    out += ["", "## Multi-agent guardrail statistics", "",
            f"- Mean evidence coverage of SWOT items and recommendations: {agg('multi', 'evidence_coverage')}",
            f"- Mean ungrounded findings dropped per run: {agg('multi', 'findings_dropped')}", "",
            "## Per-case detail", "", "| Case | Target | Multi OK | Multi latency (s) | Multi cites valid | Single cites valid |", "|---|---|---|---|---|---|"]
    out += [f"| {r['id']} | {r['target']} | {r['multi']['ok']} | {r['multi'].get('latency_s', '-')} | {r['multi'].get('citation_validity', '-')} | {r['single'].get('citation_validity', '-')} |" for r in rows]

    res_dir = ROOT / "evaluation" / "results"
    res_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    (res_dir / f"eval_{stamp}.json").write_text(json.dumps(rows, indent=2, default=str))
    (res_dir / f"eval_{stamp}.md").write_text("\n".join(out), encoding="utf-8")

    labels = ["Section\ncompleteness", "Citation\nvalidity"]
    mv = [agg("multi", "section_completeness"), agg("multi", "citation_validity")]
    sv = [agg("single", "section_completeness"), agg("single", "citation_validity")]
    fig, ax = plt.subplots(figsize=(5.5, 3.2))
    x = range(len(labels))
    ax.bar([i - 0.18 for i in x], mv, 0.36, label="Multi-agent", color="#1F4E79")
    ax.bar([i + 0.18 for i in x], sv, 0.36, label="Single-agent", color="#C55A11")
    ax.set_xticks(list(x), labels)
    ax.set_ylim(0, 1.05)
    ax.legend(frameon=False)
    ax.set_title("Mean quality metrics", fontsize=10, fontweight="bold")
    fig.tight_layout()
    fig.savefig(res_dir / f"eval_{stamp}.png", dpi=160)
    print("\n".join(out))
    print(f"\nSaved to {res_dir}/eval_{stamp}.(md|json|png)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
