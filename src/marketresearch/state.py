"""Typed data models shared by every agent plus the LangGraph state definition."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator

TARGET_TYPES = ("company", "industry")
FINDING_CATEGORIES = (
    "overview", "market", "competitors", "customers", "trends", "financials", "risks", "regulation",
)


class ResearchRequest(BaseModel):
    """What the user asks the team to research."""

    target: str
    target_type: str = "company"
    focus: str = ""
    geography: str = "Global"
    competitors: List[str] = Field(default_factory=list)
    ticker: Optional[str] = None
    competitor_tickers: List[str] = Field(default_factory=list)

    @field_validator("target")
    @classmethod
    def _target_ok(cls, v: str) -> str:
        v = (v or "").strip()
        if len(v) < 2:
            raise ValueError("target must be at least 2 characters")
        if len(v) > 120:
            raise ValueError("target must be at most 120 characters")
        return v

    @field_validator("target_type")
    @classmethod
    def _type_ok(cls, v: str) -> str:
        v = (v or "company").lower().strip()
        if v not in TARGET_TYPES:
            raise ValueError(f"target_type must be one of {TARGET_TYPES}")
        return v


class Source(BaseModel):
    id: int
    title: str
    url: str
    snippet: str = ""
    query: str = ""
    origin: str = "web"  # web | wikipedia

    @property
    def domain(self) -> str:
        return urlparse(self.url).netloc.lower().replace("www.", "")


class Finding(BaseModel):
    claim: str
    category: str = "overview"
    source_ids: List[int] = Field(default_factory=list)


class EntityFinancials(BaseModel):
    name: str
    ticker: str
    currency: str = ""
    is_target: bool = False
    synthetic: bool = False
    metrics: Dict[str, Optional[float]] = Field(default_factory=dict)
    dates: List[str] = Field(default_factory=list)
    closes: List[float] = Field(default_factory=list)


class AnalysisResult(BaseModel):
    has_quantitative_data: bool = False
    comparison_rows: List[Dict[str, Any]] = Field(default_factory=list)
    insights: List[str] = Field(default_factory=list)
    chart_paths: List[str] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)
    synthetic: bool = False


class SWOTItem(BaseModel):
    text: str
    source_ids: List[int] = Field(default_factory=list)


class SWOT(BaseModel):
    strengths: List[SWOTItem] = Field(default_factory=list)
    weaknesses: List[SWOTItem] = Field(default_factory=list)
    opportunities: List[SWOTItem] = Field(default_factory=list)
    threats: List[SWOTItem] = Field(default_factory=list)


class ForceAssessment(BaseModel):
    force: str
    rating: str = "Medium"
    rationale: str = ""
    source_ids: List[int] = Field(default_factory=list)

    @field_validator("rating")
    @classmethod
    def _rating(cls, v: str) -> str:
        v = (v or "Medium").strip().capitalize()
        return v if v in ("Low", "Medium", "High") else "Medium"


class Recommendation(BaseModel):
    title: str
    rationale: str
    priority: str = "Medium"
    timeframe: str = "6-18 months"
    expected_impact: str = ""
    risks: str = ""
    source_ids: List[int] = Field(default_factory=list)

    @field_validator("priority")
    @classmethod
    def _priority(cls, v: str) -> str:
        v = (v or "Medium").strip().capitalize()
        return v if v in ("Low", "Medium", "High") else "Medium"


class StrategyResult(BaseModel):
    executive_points: List[str] = Field(default_factory=list)
    swot: SWOT = Field(default_factory=SWOT)
    five_forces: List[ForceAssessment] = Field(default_factory=list)
    recommendations: List[Recommendation] = Field(default_factory=list)


class GraphState(TypedDict, total=False):
    """State passed between LangGraph nodes. Each node returns only the keys it changes."""

    request: ResearchRequest
    run_dir: str
    sources: List[Source]
    findings: List[Finding]
    research_attempts: int
    gate_decision: str  # retry | proceed | abort
    gate_reason: str
    financials: List[EntityFinancials]
    analysis: AnalysisResult
    strategy: StrategyResult
    report_markdown: str
    report_paths: Dict[str, str]
    limitations: List[str]
    trace: List[Dict[str, Any]]
    errors: List[str]
