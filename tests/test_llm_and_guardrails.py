import pytest

from marketresearch.agents.base import clean_ids, sanitize_citations
from marketresearch.config import get_settings
from marketresearch.llm import LLMClient, LLMJSONError, extract_json
from marketresearch.state import ResearchRequest


def test_gemini_default_uses_available_model(monkeypatch):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    assert get_settings(provider="gemini").model == "gemini-3.8-flash"


def test_extract_json_handles_fences_and_prose():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('Sure! Here you go: {"a": [1, 2]} hope that helps') == {"a": [1, 2]}
    assert extract_json("[1, 2, 3]") == [1, 2, 3]


def test_extract_json_rejects_garbage():
    with pytest.raises(ValueError):
        extract_json("no json here")


def test_clean_ids_drops_invalid_and_duplicates():
    assert clean_ids([1, "2", 99, 2, "x", None], valid=[1, 2, 3]) == [1, 2]


def test_sanitize_citations_removes_invented_ids():
    assert sanitize_citations("Revenue grew [1, 99].", [1, 2]) == "Revenue grew [1]."
    assert sanitize_citations("Invented claim [42].", [1, 2]) == "Invented claim ."


def test_complete_json_raises_after_repair_attempts(settings):
    llm = LLMClient(settings)
    llm._backend.chat = lambda *a, **k: ("definitely not json", 1, 1)
    with pytest.raises(LLMJSONError):
        llm.complete_json(agent="t", task="x", system="s", user="u", repair_attempts=1)
    assert len(llm.usage.records) == 2  # initial try + one repair


def test_complete_does_not_retry_exhausted_quota(settings):
    llm = LLMClient(settings)
    calls = []

    class QuotaError(Exception):
        status_code = 429

    def fail(*args, **kwargs):
        calls.append(1)
        raise QuotaError("quota exceeded")

    llm._backend.chat = fail
    with pytest.raises(Exception, match="quota exceeded"):
        llm.complete(agent="t", task="x", system="s", user="u")
    assert len(calls) == 1


def test_usage_tracker_summary(settings):
    llm = LLMClient(settings)
    llm.complete(agent="A", task="plan_queries", system="s", user="TARGET: X")
    s = llm.usage.summary(price_in=1.0, price_out=2.0)
    assert s["calls"] == 1 and "A" in s["by_agent"] and s["est_cost_usd"] >= 0


def test_request_validation():
    with pytest.raises(ValueError):
        ResearchRequest(target="x")
    with pytest.raises(ValueError):
        ResearchRequest(target="Valid Name", target_type="planet")
    assert ResearchRequest(target="  Infosys ").target == "Infosys"
