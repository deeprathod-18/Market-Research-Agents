"""Market data tool. Live backend: yfinance (Yahoo Finance). Mock backend: seeded synthetic series."""
from __future__ import annotations

import hashlib
import logging
import math
import random
from typing import List, Optional

from ..config import Settings
from ..state import EntityFinancials, ResearchRequest

log = logging.getLogger(__name__)

_INFO_KEYS = {
    "market_cap": "marketCap", "trailing_pe": "trailingPE", "forward_pe": "forwardPE",
    "profit_margin": "profitMargins", "operating_margin": "operatingMargins",
    "revenue_growth": "revenueGrowth", "total_revenue": "totalRevenue", "roe": "returnOnEquity",
    "debt_to_equity": "debtToEquity", "beta": "beta",
}


def _num(v) -> Optional[float]:
    try:
        f = float(v)
        return f if f == f and abs(f) != float("inf") else None
    except (TypeError, ValueError):
        return None


def resolve_ticker(name: str) -> Optional[str]:
    """Best-effort name -> ticker using Yahoo's search endpoint."""
    try:
        import yfinance as yf

        quotes = yf.Search(name, max_results=5).quotes
        for q in quotes:
            if q.get("quoteType") == "EQUITY" and q.get("symbol"):
                return q["symbol"]
    except Exception as e:
        log.warning("ticker resolution failed for %r: %s", name, e)
    return None


def _live_entity(name: str, ticker: str, is_target: bool) -> Optional[EntityFinancials]:
    try:
        import yfinance as yf

        t = yf.Ticker(ticker)
        hist = t.history(period="2y", interval="1d", auto_adjust=True)
        if hist is None or hist.empty:
            return None
        try:
            info = t.info or {}
        except Exception:
            info = {}
        metrics = {k: _num(info.get(v)) for k, v in _INFO_KEYS.items()}
        price_history = []
        for date, close in hist["Close"].items():
            price = _num(close)
            if price is not None and price > 0:
                price_history.append((date.strftime("%Y-%m-%d"), round(price, 4)))
        if not price_history:
            return None
        return EntityFinancials(
            name=name, ticker=ticker, currency=str(info.get("currency") or ""), is_target=is_target,
            metrics=metrics, dates=[date for date, _ in price_history],
            closes=[close for _, close in price_history],
        )
    except Exception as e:
        log.warning("yfinance failed for %s: %s", ticker, e)
        return None


def _mock_entity(name: str, ticker: str, is_target: bool) -> EntityFinancials:
    seed = int(hashlib.md5(name.encode()).hexdigest()[:8], 16)
    rng = random.Random(seed)
    price, closes, dates = 100.0, [], []
    import datetime as dt

    day = dt.date(2024, 1, 1)
    while len(closes) < 500:
        if day.weekday() < 5:
            price *= 1 + rng.gauss(0.0004, 0.016)
            closes.append(round(price, 2))
            dates.append(day.isoformat())
        day += dt.timedelta(days=1)
    metrics = {
        "market_cap": rng.uniform(5e9, 3e11), "trailing_pe": rng.uniform(12, 45), "forward_pe": rng.uniform(10, 40),
        "profit_margin": rng.uniform(0.05, 0.3), "operating_margin": rng.uniform(0.08, 0.35),
        "revenue_growth": rng.uniform(-0.02, 0.25), "total_revenue": rng.uniform(2e9, 1e11),
        "roe": rng.uniform(0.06, 0.3), "debt_to_equity": rng.uniform(5, 120), "beta": rng.uniform(0.6, 1.5),
    }
    return EntityFinancials(name=name, ticker=ticker or name[:4].upper(), currency="USD", is_target=is_target,
                            synthetic=True, metrics={k: round(v, 4) for k, v in metrics.items()}, dates=dates, closes=closes)


def fetch_entities(req: ResearchRequest, settings: Settings) -> List[EntityFinancials]:
    """Fetch the target plus competitors. Industry requests only use explicitly supplied peers."""
    pairs = []  # (name, ticker or None, is_target)
    if req.target_type == "company":
        pairs.append((req.target, req.ticker, True))
    for i, c in enumerate(req.competitors):
        tick = req.competitor_tickers[i] if i < len(req.competitor_tickers) else None
        pairs.append((c, tick, False))
    if req.target_type == "industry" and not req.competitor_tickers:
        pairs = [p for p in pairs if p[1]]  # industry mode: only entities with explicit tickers

    out: List[EntityFinancials] = []
    for name, ticker, is_target in pairs:
        if settings.finance_backend == "mock":
            out.append(_mock_entity(name, ticker or "", is_target))
            continue
        tick = ticker or resolve_ticker(name)
        if not tick:
            log.info("no ticker for %s; skipping quantitative data", name)
            continue
        ent = _live_entity(name, tick, is_target)
        if ent:
            out.append(ent)
    return out
