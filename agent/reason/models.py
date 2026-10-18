from typing import Literal

from pydantic import BaseModel, Field


class Hypothesis(BaseModel):
    id: str
    statement: str
    mechanism: str
    predicted_evidence: list[str]
    data_needed: list[str]
    novelty_rationale: str
    fact_ids: list[str] = Field(default_factory=list)


class EvidenceItem(BaseModel):
    claim: str
    doc_id: str
    fact_id: str | None = None
    page: int | None = None
    quote: str
    role: Literal["supports", "contradicts", "context"]
    source_type: str | None = None
    url: str | None = None


class RedTeamResult(BaseModel):
    strongest_counterargument: str
    falsification_condition: str
    verdict: Literal["survives", "weakened", "refuted"]
    revised_hypothesis: str | None = None
    checks: dict[str, bool] = Field(default_factory=dict)


class Grade(BaseModel):
    total: int
    label: Literal["Strong", "Moderate", "Weak"]
    points: dict[str, int]
    rationale: list[str]


class RenderedReport(BaseModel):
    discovery: str
    why_it_matters: list[str]
    evidence: list[EvidenceItem]
    timeline: list[str]
    numbers: list[str]
    counterargument: str
    falsification_condition: str
    evidence_strength: Grade
    anomalies: list[dict] = Field(default_factory=list)
    novelty_rationale: str = ""
    also_considered: list[dict] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
