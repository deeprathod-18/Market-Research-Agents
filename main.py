#!/usr/bin/env python3
"""Command-line entry point.

Examples
  python main.py "Infosys" --type company --ticker INFY.NS --competitors "TCS,Wipro" --competitor-tickers "TCS.NS,WIPRO.NS"
  python main.py "Indian electric two-wheeler market" --type industry --geography India
  python main.py "Demo Corp" --provider mock      # offline demo, no API key needed
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from marketresearch.config import get_settings  # noqa: E402
from marketresearch.orchestrator import Pipeline  # noqa: E402
from marketresearch.state import ResearchRequest  # noqa: E402


def _csv(v: str) -> list:
    return [x.strip() for x in (v or "").split(",") if x.strip()]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Automated Market and Competitor Research Team")
    ap.add_argument("target", help="Company or industry to research")
    ap.add_argument("--type", dest="target_type", choices=["company", "industry"], default="company")
    ap.add_argument("--focus", default="", help="Optional question or angle, e.g. 'expansion into tier-2 cities'")
    ap.add_argument("--geography", default="Global")
    ap.add_argument("--ticker", default=None, help="Yahoo Finance ticker of the target, e.g. INFY.NS")
    ap.add_argument("--competitors", default="", help="Comma-separated competitor names")
    ap.add_argument("--competitor-tickers", default="", help="Comma-separated tickers, same order as competitors")
    ap.add_argument("--provider", default=None, help="mock | openai | anthropic | groq | gemini | openrouter | ollama")
    ap.add_argument("--model", default=None)
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO if a.verbose else logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    overrides = {k: v for k, v in (("provider", a.provider), ("model", a.model)) if v}
    settings = get_settings(**overrides)
    req = ResearchRequest(target=a.target, target_type=a.target_type, focus=a.focus, geography=a.geography, ticker=a.ticker,
                          competitors=_csv(a.competitors), competitor_tickers=_csv(a.competitor_tickers))

    print(f"Provider: {settings.provider} ({settings.model}) | search: {settings.search_backend} | finance: {settings.finance_backend}")

    def show(ev):
        if ev["status"] == "running":
            print(f"  -> {ev['label']} ...", flush=True)
        elif ev["status"] == "done":
            print(f"     done {ev.get('details') or ''}", flush=True)

    res = Pipeline(settings).run(req, on_event=show)
    if res.status != "success":
        print(f"\nFAILED: {res.error}", file=sys.stderr)
        return 1
    u = res.usage
    print(f"\nFinished in {res.duration_s}s | LLM calls: {u['calls']} | tokens: {u['prompt_tokens']} in / {u['completion_tokens']} out")
    for k, p in res.report_paths.items():
        print(f"  {k}: {p}")
    print(f"  run folder: {res.run_dir}")
    print("\nAgent trace (proof that each agent ran):")
    print(f"  {'Agent':<28}{'Status':<8}{'Time(s)':>8}{'LLM calls':>11}{'Tokens in/out':>16}")
    for t in res.trace:
        print(f"  {t['agent']:<28}{t['status']:<8}{t['duration_s']:>8}{t['calls']:>11}{str(t['prompt_tokens']) + '/' + str(t['completion_tokens']):>16}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
