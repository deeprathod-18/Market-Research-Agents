"""Web search tool. Live backend: DuckDuckGo via the `ddgs` package (no API key needed)."""
from __future__ import annotations

import hashlib
import logging
import re
import time
from typing import Dict, List

from ..config import Settings

log = logging.getLogger(__name__)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "q"


def _mock_results(query: str, n: int) -> List[Dict[str, str]]:
    """Deterministic fixtures so tests and demos run offline. Clearly marked as demo sources."""
    h = hashlib.md5(query.encode()).hexdigest()[:6]
    return [{
        "title": f"Demo source {i + 1}: {query}",
        "url": f"https://demo{i % 3 + 1}.example.com/{_slug(query)}-{h}-{i + 1}",
        "snippet": f"Placeholder snippet {i + 1} for the query '{query}'. Offline fixture, not real content.",
    } for i in range(n)]


def search_web(query: str, settings: Settings, max_results: int | None = None) -> List[Dict[str, str]]:
    """Return a list of {title, url, snippet}. Never raises: returns [] if the backend fails."""
    n = max_results or settings.max_results_per_query
    if settings.search_backend == "mock":
        return _mock_results(query, n)
    try:
        from ddgs import DDGS
    except ImportError:  # pragma: no cover
        log.error("ddgs is not installed. pip install ddgs")
        return []
    for attempt in range(3):
        try:
            raw = list(DDGS().text(query, max_results=n))
            return [{"title": (r.get("title") or "").strip(), "url": (r.get("href") or r.get("url") or "").strip(),
                     "snippet": (r.get("body") or "").strip()} for r in raw if (r.get("href") or r.get("url"))]
        except Exception as e:
            log.warning("web search failed for %r (attempt %d): %s", query, attempt + 1, e)
            time.sleep(1.5 * (attempt + 1))
    return []
