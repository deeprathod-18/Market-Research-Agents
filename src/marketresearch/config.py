"""Central configuration. All values come from environment variables (or a .env file)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

try:  # python-dotenv is optional at runtime
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover
    pass

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# provider -> (base_url, api-key env var, default model, sdk)
PROVIDERS: Dict[str, dict] = {
    "openai": {"base_url": None, "key_env": "OPENAI_API_KEY", "model": "gpt-4o-mini", "sdk": "openai"},
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "key_env": "GROQ_API_KEY",
        "model": "llama-3.3-70b-versatile",
        "sdk": "openai",
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "key_env": "GEMINI_API_KEY",
        "model": "gemini-3.8-flash",
        "sdk": "openai",
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "key_env": "OPENROUTER_API_KEY",
        "model": "meta-llama/llama-3.3-70b-instruct",
        "sdk": "openai",
    },
    "ollama": {
        "base_url": os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
        "key_env": "",
        "model": "llama3.1",
        "sdk": "openai",
    },
    "anthropic": {"base_url": None, "key_env": "ANTHROPIC_API_KEY", "model": "claude-sonnet-5-5", "sdk": "anthropic"},
    "mock": {"base_url": None, "key_env": "", "model": "mock-llm", "sdk": "mock"},
}


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


@dataclass
class Settings:
    provider: str = "mock"
    model: str = "mock-llm"
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    sdk: str = "mock"
    search_backend: str = "mock"
    finance_backend: str = "mock"
    max_results_per_query: int = 5
    min_sources: int = 8
    min_findings: int = 8
    max_research_attempts: int = 2
    temperature: float = 0.2
    max_tokens: int = 2500
    output_dir: Path = PROJECT_ROOT / "outputs"
    price_per_1m_input: float = 0.0
    price_per_1m_output: float = 0.0

    @property
    def is_mock(self) -> bool:
        return self.provider == "mock"


def get_settings(**overrides) -> Settings:
    """Build Settings from the environment; keyword overrides win (used by tests and the UI)."""
    provider = str(overrides.pop("provider", None) or os.getenv("LLM_PROVIDER", "mock")).lower().strip()
    if provider not in PROVIDERS:
        raise ValueError(f"Unknown LLM_PROVIDER '{provider}'. Choose from: {', '.join(PROVIDERS)}")
    spec = PROVIDERS[provider]
    key_env = spec["key_env"]
    api_key = overrides.pop("api_key", None) or (os.getenv(key_env) if key_env else ("ollama" if provider == "ollama" else None))

    default_search = "mock" if provider == "mock" else "ddgs"
    default_fin = "mock" if provider == "mock" else "yfinance"
    out_dir = Path(os.getenv("OUTPUT_DIR", "outputs"))
    if not out_dir.is_absolute():
        out_dir = PROJECT_ROOT / out_dir

    s = Settings(
        provider=provider,
        model=overrides.pop("model", None) or os.getenv("LLM_MODEL") or spec["model"],
        api_key=api_key,
        base_url=spec["base_url"],
        sdk=spec["sdk"],
        search_backend=os.getenv("SEARCH_BACKEND", default_search).lower(),
        finance_backend=os.getenv("FINANCE_BACKEND", default_fin).lower(),
        max_results_per_query=_int("MAX_RESULTS_PER_QUERY", 5),
        min_sources=_int("MIN_SOURCES", 8),
        min_findings=_int("MIN_FINDINGS", 8),
        max_research_attempts=_int("MAX_RESEARCH_ATTEMPTS", 2),
        temperature=_float("LLM_TEMPERATURE", 0.2),
        max_tokens=_int("LLM_MAX_TOKENS", 2500),
        output_dir=out_dir,
        price_per_1m_input=_float("PRICE_PER_1M_INPUT", 0.0),
        price_per_1m_output=_float("PRICE_PER_1M_OUTPUT", 0.0),
    )
    # In mock mode never touch the network, regardless of what the environment says.
    if provider == "mock":
        s.search_backend, s.finance_backend = "mock", "mock"
    for k, v in overrides.items():
        if not hasattr(s, k):
            raise TypeError(f"Unknown setting '{k}'")
        setattr(s, k, v)
    return s
