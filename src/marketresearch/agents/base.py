"""Shared base class for all agents."""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List

from ..config import Settings
from ..llm import LLMClient

_CITE = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")


def clean_ids(ids: Any, valid: Iterable[int]) -> List[int]:
    """Keep only integer ids that exist in `valid` (guardrail against invented citations)."""
    valid_set = set(valid)
    out: List[int] = []
    for x in ids or []:
        try:
            i = int(x)
        except (TypeError, ValueError):
            continue
        if i in valid_set and i not in out:
            out.append(i)
    return out


def sanitize_citations(text: str, valid: Iterable[int]) -> str:
    """Remove citation numbers that do not match a real source id, e.g. [3, 99] -> [3]."""
    valid_set = set(valid)

    def repl(m: re.Match) -> str:
        keep = [n for n in re.findall(r"\d+", m.group(1)) if int(n) in valid_set]
        return f"[{', '.join(keep)}]" if keep else ""

    return _CITE.sub(repl, text)


class BaseAgent:
    name = "Agent"

    def __init__(self, llm: LLMClient, settings: Settings):
        self.llm = llm
        self.settings = settings
        self.stats: Dict[str, Any] = {}

    def _json(self, task: str, system: str, user: str, **kw: Any) -> Any:
        return self.llm.complete_json(agent=self.name, task=task, system=system, user=user, **kw)

    def _text(self, task: str, system: str, user: str, **kw: Any) -> str:
        return self.llm.complete(agent=self.name, task=task, system=system, user=user, **kw).text.strip()
