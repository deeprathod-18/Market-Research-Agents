"""Provider-agnostic LLM client with retries, JSON repair and per-agent usage tracking."""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .config import Settings, get_settings
from .mock_llm import mock_chat

log = logging.getLogger(__name__)


class LLMError(RuntimeError):
    """Raised when the provider cannot be reached or returns an unusable response."""


class LLMJSONError(LLMError):
    """Raised when the model never returns valid JSON."""


@dataclass
class LLMResponse:
    text: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_s: float = 0.0
    model: str = ""


@dataclass
class UsageTracker:
    records: List[Dict[str, Any]] = field(default_factory=list)

    def add(self, agent: str, task: str, resp: LLMResponse) -> None:
        self.records.append({"agent": agent, "task": task, "prompt_tokens": resp.prompt_tokens,
                             "completion_tokens": resp.completion_tokens, "latency_s": resp.latency_s})

    def snapshot(self) -> int:
        return len(self.records)

    def since(self, mark: int) -> Dict[str, float]:
        recs = self.records[mark:]
        return {"calls": len(recs), "prompt_tokens": sum(r["prompt_tokens"] for r in recs),
                "completion_tokens": sum(r["completion_tokens"] for r in recs),
                "llm_latency_s": round(sum(r["latency_s"] for r in recs), 3)}

    def summary(self, price_in: float = 0.0, price_out: float = 0.0) -> Dict[str, Any]:
        total = self.since(0)
        by_agent: Dict[str, Dict[str, float]] = {}
        for r in self.records:
            a = by_agent.setdefault(r["agent"], {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0})
            a["calls"] += 1
            a["prompt_tokens"] += r["prompt_tokens"]
            a["completion_tokens"] += r["completion_tokens"]
        total["est_cost_usd"] = round(total["prompt_tokens"] / 1e6 * price_in + total["completion_tokens"] / 1e6 * price_out, 5)
        total["by_agent"] = by_agent
        return total


# --------------------------------------------------------------------------- JSON helpers
def extract_json(text: str) -> Any:
    """Parse JSON from a model reply, tolerating code fences and surrounding prose."""
    if text is None:
        raise ValueError("empty response")
    s = text.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.I)
    s = re.sub(r"\s*```$", "", s)
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    starts = [i for i in (s.find("{"), s.find("[")) if i != -1]
    if not starts:
        raise ValueError("no JSON found")
    start = min(starts)
    closer = "}" if s[start] == "{" else "]"
    end = s.rfind(closer)
    if end <= start:
        raise ValueError("unterminated JSON")
    return json.loads(s[start : end + 1])


# --------------------------------------------------------------------------- backends
class _MockBackend:
    def chat(self, task: str, system: str, user: str, temperature: float, max_tokens: int) -> Tuple[str, int, int]:
        out = mock_chat(task, system, user)
        return out, (len(system) + len(user)) // 4, len(out) // 4


class _OpenAICompatBackend:
    def __init__(self, s: Settings):
        try:
            from openai import OpenAI
        except ImportError as e:  # pragma: no cover
            raise LLMError("The 'openai' package is required for this provider. pip install openai") from e
        if not s.api_key:
            raise LLMError(f"No API key found for provider '{s.provider}'. Set it in your .env file.")
        self.client = OpenAI(api_key=s.api_key, base_url=s.base_url, timeout=90)
        self.model = s.model

    def chat(self, task: str, system: str, user: str, temperature: float, max_tokens: int) -> Tuple[str, int, int]:
        msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        try:
            r = self.client.chat.completions.create(model=self.model, messages=msgs, temperature=temperature, max_tokens=max_tokens)
        except Exception as e:
            if "max_completion_tokens" in str(e):  # newer OpenAI reasoning-style models
                r = self.client.chat.completions.create(model=self.model, messages=msgs, max_completion_tokens=max_tokens)
            else:
                raise
        u = getattr(r, "usage", None)
        return (r.choices[0].message.content or ""), getattr(u, "prompt_tokens", 0) or 0, getattr(u, "completion_tokens", 0) or 0


class _AnthropicBackend:
    def __init__(self, s: Settings):
        try:
            import anthropic
        except ImportError as e:  # pragma: no cover
            raise LLMError("The 'anthropic' package is required for this provider. pip install anthropic") from e
        if not s.api_key:
            raise LLMError("No ANTHROPIC_API_KEY found. Set it in your .env file.")
        self.client = anthropic.Anthropic(api_key=s.api_key, timeout=90)
        self.model = s.model

    def chat(self, task: str, system: str, user: str, temperature: float, max_tokens: int) -> Tuple[str, int, int]:
        r = self.client.messages.create(model=self.model, max_tokens=max_tokens, temperature=temperature,
                                        system=system, messages=[{"role": "user", "content": user}])
        text = "".join(b.text for b in r.content if getattr(b, "type", "") == "text")
        return text, r.usage.input_tokens, r.usage.output_tokens


# --------------------------------------------------------------------------- client
class LLMClient:
    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self.usage = UsageTracker()
        sdk = self.settings.sdk
        self._backend = _MockBackend() if sdk == "mock" else _AnthropicBackend(self.settings) if sdk == "anthropic" else _OpenAICompatBackend(self.settings)

    def complete(self, *, agent: str, task: str, system: str, user: str,
                 temperature: Optional[float] = None, max_tokens: Optional[int] = None) -> LLMResponse:
        temp = self.settings.temperature if temperature is None else temperature
        mt = max_tokens or self.settings.max_tokens
        last: Optional[Exception] = None
        for attempt in range(3):
            t0 = time.perf_counter()
            try:
                text, pin, pout = self._backend.chat(task, system, user, temp, mt)
                resp = LLMResponse(text=text, prompt_tokens=pin, completion_tokens=pout,
                                   latency_s=round(time.perf_counter() - t0, 3), model=self.settings.model)
                self.usage.add(agent, task, resp)
                return resp
            except Exception as e:  # network, rate limit, auth...
                last = e
                log.warning("LLM call failed (%s, attempt %d/3): %s", task, attempt + 1, e)
                message = str(e).lower()
                if (getattr(e, "status_code", None) in (400, 401, 403, 404, 429)
                        or "resource_exhausted" in message or "quota exceeded" in message
                        or "api key" in message or "authentication" in message):
                    break  # invalid requests, credentials, and exhausted quotas will not improve on retry
                time.sleep(min(2 ** attempt, 4) if not self.settings.is_mock else 0)
        raise LLMError(f"LLM call '{task}' failed: {last}") from last

    def complete_json(self, *, agent: str, task: str, system: str, user: str,
                      temperature: Optional[float] = None, max_tokens: Optional[int] = None, repair_attempts: int = 2) -> Any:
        prompt = user
        for i in range(repair_attempts + 1):
            resp = self.complete(agent=agent, task=task, system=system, user=prompt, temperature=temperature, max_tokens=max_tokens)
            try:
                return extract_json(resp.text)
            except (ValueError, json.JSONDecodeError) as e:
                log.warning("Invalid JSON from model for task %s (try %d): %s", task, i + 1, e)
                prompt = (user + "\n\nYour previous reply was not valid JSON. Reply again with ONLY the JSON object, "
                          "no commentary and no markdown fences.")
        raise LLMJSONError(f"Model did not return valid JSON for task '{task}' after {repair_attempts + 1} tries")
