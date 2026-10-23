"""Single-agent baseline: ONE prompt that sees the same sources and market data as the multi-agent system."""
from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Tuple

from marketresearch.llm import LLMClient
from marketresearch.prompts import BASELINE_SYSTEM
from marketresearch.state import ResearchRequest, Source


def run_baseline(llm: LLMClient, req: ResearchRequest, sources: List[Source], rows: List[Dict[str, Any]]) -> Tuple[str, float]:
    listing = "\n\n".join(f"[{s.id}] {s.title} | {s.url}\n{s.snippet}" for s in sources)
    user = (f"TARGET: {req.target}\nTYPE: {req.target_type}\nGEOGRAPHY: {req.geography}\nFOCUS: {req.focus or 'general'}\n"
            f"VALID_SOURCE_IDS: {', '.join(str(s.id) for s in sources)}\n\nSOURCES:\n{listing}\n")
    if rows:
        slim = [{k: v for k, v in r.items() if k != "Target"} for r in rows]
        user += f"\nMARKET DATA (JSON):\n{json.dumps(slim)}\n"
    t0 = time.perf_counter()
    text = llm.complete(agent="Single Agent", task="baseline_single", system=BASELINE_SYSTEM, user=user, max_tokens=4000).text
    return text, round(time.perf_counter() - t0, 2)
