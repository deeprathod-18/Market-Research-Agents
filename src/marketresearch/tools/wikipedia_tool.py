"""Wikipedia lookup via the public REST API (no key). Gives a reliable, citable background source."""
from __future__ import annotations

import logging
from typing import Dict, Optional

import requests

from ..config import Settings

log = logging.getLogger(__name__)
_HEADERS = {"User-Agent": "MarketResearchAgents/1.0 (academic project; contact: student)"}


def wiki_lookup(term: str, settings: Settings) -> Optional[Dict[str, str]]:
    """Return {title, url, snippet} for the best matching article, or None."""
    if settings.search_backend == "mock":
        return {"title": f"Demo Wikipedia entry: {term}", "url": "https://en.wikipedia.example.com/wiki/Demo",
                "snippet": f"Placeholder encyclopedia summary for {term}. Offline fixture."}
    try:
        s = requests.get("https://en.wikipedia.org/w/api.php", headers=_HEADERS, timeout=10,
                         params={"action": "opensearch", "search": term, "limit": 1, "format": "json"})
        s.raise_for_status()
        data = s.json()
        if not data[1]:
            return None
        title = data[1][0]
        r = requests.get(f"https://en.wikipedia.org/api/rest_v1/page/summary/{requests.utils.quote(title.replace(' ', '_'))}",
                         headers=_HEADERS, timeout=10)
        r.raise_for_status()
        j = r.json()
        extract = (j.get("extract") or "").strip()
        if not extract:
            return None
        return {"title": f"{j.get('title', title)} (Wikipedia)", "url": j.get("content_urls", {}).get("desktop", {}).get("page", data[3][0]),
                "snippet": extract[:900]}
    except Exception as e:
        log.warning("wikipedia lookup failed for %r: %s", term, e)
        return None
