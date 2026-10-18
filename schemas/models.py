from datetime import date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, HttpUrl


class CompanyType(StrEnum):
    BANK = "bank"
    NBFC = "nbfc"
    HOUSING_FIN = "housing_fin"
    OTHER_FIN = "other_fin"


class SourceType(StrEnum):
    EXCHANGE = "exchange"
    COMPANY_SITE = "company_site"
    RBI = "rbi"
    RATING = "rating"
    RATING_RATIONALE = "rating_rationale"
    SEARCH = "search"
    MANUAL = "manual"
    EVENT = "event"


class PeriodType(StrEnum):
    QUARTER = "quarter"
    FY = "fy"
    HALF_YEAR = "half_year"
    POINT_IN_TIME = "point_in_time"


class CompanyProfile(BaseModel):
    name: str
    symbol: str | None = None
    bse_scrip_code: str | None = None
    isin: str | None = None
    company_type: CompanyType = CompanyType.OTHER_FIN
    confidence: float = Field(ge=0, le=1)
    signals: list[str] = Field(default_factory=list)


class DocRef(BaseModel):
    ticker: str
    source_type: SourceType
    title: str
    url: HttpUrl | None = None
    published: date | None = None
    local_path: Path | None = None


class Document(BaseModel):
    doc_id: str
    ticker: str
    source_type: SourceType
    title: str
    url: str | None = None
    published: date | None = None
    sha256: str
    local_path: str


class Fact(BaseModel):
    fact_id: str
    ticker: str
    metric: str
    value: float
    unit: str
    period: str
    period_type: PeriodType
    doc_id: str
    page: int = Field(ge=1)
    quote: str = Field(min_length=1)
    extractor: str
    confidence: float = Field(ge=0, le=1)
    restated: bool = False
    normalized_value: float | None = None
    basis: str = "unknown"
    validator_status: dict[str, bool] = Field(default_factory=dict)
    conflict: bool = False
    suspect: bool = False


class Event(BaseModel):
    event_id: str
    ticker: str
    doc_id: str
    title: str
    period: str | None = None
    page: int = Field(ge=1)
    quote: str = Field(min_length=1)


class Claim(BaseModel):
    claim_id: str
    run_id: str
    text: str
    claim_type: str
    hypothesis_id: str | None = None


class ClaimEvidence(BaseModel):
    claim_id: str
    fact_id: str
    doc_id: str
    role: str


class Run(BaseModel):
    run_id: str
    ticker: str
    started: datetime
    status: str
    log_json: dict[str, Any] = Field(default_factory=dict)
