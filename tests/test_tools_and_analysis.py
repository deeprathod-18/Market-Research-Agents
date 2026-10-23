import sys
from types import SimpleNamespace

import pandas as pd

from marketresearch.agents.analyst import build_comparison_rows, performance_stats, ungrounded_numbers
from marketresearch.state import ResearchRequest
from marketresearch.tools import fetch_entities, search_web, wiki_lookup
from marketresearch.tools.charts import bar_chart, price_chart
from marketresearch.tools.financials import _live_entity


def test_mock_search_is_deterministic(settings):
    a, b = search_web("abc", settings, 3), search_web("abc", settings, 3)
    assert a == b and len(a) == 3 and all(r["url"].startswith("https://") for r in a)


def test_wiki_mock(settings):
    assert wiki_lookup("X", settings)["title"]


def test_performance_stats_known_values():
    closes = [100.0] * 10 + [100 + i for i in range(1, 31)]  # rises to 130
    p = performance_stats(closes)
    assert p["return_1y"] == 30.0
    assert p["max_drawdown"] == 0.0
    assert p["volatility"] > 0


def test_performance_stats_ignores_nonfinite_or_nonpositive_prices():
    closes = [100.0 + i for i in range(30)]
    dirty = closes[:15] + [float("nan"), 0.0, float("inf")] + closes[15:]
    assert performance_stats(dirty) == performance_stats(closes)


def test_live_entity_drops_invalid_close_prices(monkeypatch):
    dates = pd.date_range("2025-01-01", periods=4, freq="D")

    class FakeTicker:
        info = {"currency": "INR"}

        @staticmethod
        def history(**kwargs):
            return pd.DataFrame({"Close": [100.0, float("nan"), 101.0, 0.0]}, index=dates)

    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(Ticker=lambda ticker: FakeTicker()))
    entity = _live_entity("Acme", "ACME.NS", True)

    assert entity is not None
    assert entity.closes == [100.0, 101.0]
    assert entity.dates == ["2025-01-01", "2025-01-03"]


def test_performance_stats_drawdown():
    closes = [100.0] * 20 + [200.0, 100.0]
    assert performance_stats(closes)["max_drawdown"] == -50.0


def test_performance_stats_short_series():
    assert performance_stats([1.0, 2.0]) == {"return_1y": None, "volatility": None, "max_drawdown": None}


def test_company_request_includes_target_and_peers(settings):
    req = ResearchRequest(target="Acme", competitors=["B", "C"])
    ents = fetch_entities(req, settings)
    assert [e.name for e in ents] == ["Acme", "B", "C"] and ents[0].is_target


def test_industry_without_tickers_has_no_entities(settings):
    req = ResearchRequest(target="EV market", target_type="industry", competitors=["B"])
    assert fetch_entities(req, settings) == []


def test_comparison_rows_units(settings):
    ents = fetch_entities(ResearchRequest(target="Acme", competitors=["B"]), settings)
    rows = build_comparison_rows(ents)
    assert rows[0]["Company"] == "Acme" and 0 < rows[0]["Operating Margin (%)"] < 100


def test_ungrounded_number_detection():
    allowed = [12.3, 45.0]
    assert ungrounded_numbers("Margin is 12.3% versus peers", allowed) == []
    assert ungrounded_numbers("Margin is 99.9% which is huge", allowed) == ["99.9"]


def test_charts_written(settings, tmp_path):
    ents = fetch_entities(ResearchRequest(target="Acme", competitors=["B"]), settings)
    assert price_chart(ents, tmp_path / "p.png") and (tmp_path / "p.png").exists()
    rows = build_comparison_rows(ents)
    assert bar_chart(rows, "Company", "1Y Return (%)", tmp_path / "b.png", "t", pct=True)
    assert price_chart([], tmp_path / "x.png") is None
