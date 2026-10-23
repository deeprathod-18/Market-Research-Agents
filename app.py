"""Streamlit web UI for the Automated Market and Competitor Research Team."""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent / "src"))

from marketresearch.config import PROVIDERS, get_settings  # noqa: E402
from marketresearch.orchestrator import Pipeline  # noqa: E402
from marketresearch.state import ResearchRequest  # noqa: E402

st.set_page_config(page_title="Market & Competitor Research Team", page_icon="📊", layout="wide")

MAX_RUNS = int(os.getenv("RUNS_PER_SESSION", "5"))
ACCESS_CODE = os.getenv("APP_ACCESS_CODE", "")
st.session_state.setdefault("runs", 0)

st.title("📊 Automated Market & Competitor Research Team")
st.caption("Four cooperating AI agents (Researcher, Data Analyst, Strategy Consultant, Report Writer) produce a consulting-style brief.")

# ------------------------------------------------------------------ optional access gate for public deployments
if ACCESS_CODE:
    if st.text_input("Access code", type="password") != ACCESS_CODE:
        st.info("Enter the access code to use this app.")
        st.stop()

# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.header("Model settings")
    default_provider = os.getenv("LLM_PROVIDER", "mock")
    providers = list(PROVIDERS)
    provider = st.selectbox("LLM provider", providers, index=providers.index(default_provider) if default_provider in providers else 0)
    model = st.text_input("Model (optional override)", value="")
    key = ""
    if provider not in ("mock", "ollama"):
        key = st.text_input(f"{provider} API key (kept in memory only)", type="password",
                            help="Leave blank to use the key from the server environment.")
    if provider == "mock":
        st.warning("Mock mode returns placeholder content for demos and tests. It is not real analysis.")
    st.markdown(f"Runs used this session: **{st.session_state['runs']} / {MAX_RUNS}**")

# ------------------------------------------------------------------ input form
with st.form("request"):
    c1, c2, c3 = st.columns([3, 1.3, 1.5])
    target = c1.text_input("Company or industry", placeholder="e.g. Infosys  or  Indian electric two-wheeler market")
    target_type = c2.selectbox("Type", ["company", "industry"])
    geography = c3.text_input("Geography", value="Global")
    focus = st.text_input("Focus (optional)", placeholder="e.g. generative AI services opportunity")
    c4, c5, c6 = st.columns(3)
    ticker = c4.text_input("Target ticker (optional)", placeholder="INFY.NS")
    competitors = c5.text_input("Competitors (comma separated)", placeholder="TCS, Wipro")
    comp_tickers = c6.text_input("Competitor tickers (same order)", placeholder="TCS.NS, WIPRO.NS")
    go = st.form_submit_button("Run research", type="primary")

csv = lambda s: [x.strip() for x in s.split(",") if x.strip()]

if go:
    if st.session_state["runs"] >= MAX_RUNS:
        st.error("Session run limit reached. Reload the page to start a new session.")
    elif len(target.strip()) < 2:
        st.error("Please enter a company or industry.")
    else:
        try:
            overrides = {"provider": provider}
            if model.strip():
                overrides["model"] = model.strip()
            if key.strip():
                overrides["api_key"] = key.strip()
            settings = get_settings(**overrides)
            req = ResearchRequest(target=target, target_type=target_type, geography=geography, focus=focus,
                                  ticker=ticker.strip() or None, competitors=csv(competitors), competitor_tickers=csv(comp_tickers))
            pipe = Pipeline(settings)
        except Exception as e:
            st.error(f"Configuration problem: {e}")
            st.stop()

        st.session_state["runs"] += 1
        with st.status("Research team at work...", expanded=True) as status:
            def on_event(ev):
                icon = {"running": "⏳", "done": "✅", "error": "❌"}[ev["status"]]
                st.write(f"{icon} **{ev['label']}** {ev.get('details') or ev.get('error') or ''}")

            result = pipe.run(req, on_event=on_event)
            status.update(label="Finished" if result.status == "success" else "Failed", state="complete" if result.status == "success" else "error")
        st.session_state["result"] = result

res = st.session_state.get("result")
if res is not None:
    if res.status != "success":
        st.error(f"The run failed: {res.error}")
    else:
        u = res.usage
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Duration", f"{res.duration_s}s")
        m2.metric("LLM calls", u["calls"])
        m3.metric("Tokens (in/out)", f"{u['prompt_tokens']:,} / {u['completion_tokens']:,}")
        m4.metric("Sources", len(res.state.get("sources", [])))

        t_report, t_charts, t_sources, t_trace = st.tabs(["Report", "Charts & data", "Sources", "Agent trace"])
        with t_report:
            st.markdown(re.sub(r"!\[.*?\]\(.*?\)", "", res.report_markdown))
            d1, d2 = st.columns(2)
            paths = res.report_paths
            if "docx" in paths:
                d1.download_button("⬇ Download Word report", Path(paths["docx"]).read_bytes(), file_name=Path(paths["docx"]).name,
                                   mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
            d2.download_button("⬇ Download Markdown", res.report_markdown, file_name="report.md", mime="text/markdown")
        with t_charts:
            analysis = res.state.get("analysis")
            if analysis and analysis.comparison_rows:
                st.dataframe(pd.DataFrame(analysis.comparison_rows).drop(columns=["Target"], errors="ignore"), use_container_width=True)
            for p in (analysis.chart_paths if analysis else []):
                st.image(p)
            if not (analysis and analysis.chart_paths):
                st.info("No market data charts for this request.")
        with t_sources:
            st.dataframe(pd.DataFrame([{"id": s.id, "title": s.title, "domain": s.domain, "url": s.url} for s in res.state.get("sources", [])]),
                         use_container_width=True)
        with t_trace:
            st.dataframe(pd.DataFrame([{k: v for k, v in t.items() if k != "details"} for t in res.trace]), use_container_width=True)
            st.json({t["node"] + f"#{i}": t.get("details") for i, t in enumerate(res.trace)})
