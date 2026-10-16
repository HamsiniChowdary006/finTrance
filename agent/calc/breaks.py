from collections.abc import Iterable
from dataclasses import dataclass

import pandas as pd

from schemas.models import Document


@dataclass(frozen=True)
class Event:
    date: str | None
    keyword: str
    doc_id: str
    title: str


@dataclass(frozen=True)
class ChangePoint:
    quarter: object
    magnitude: float


def detect_events(documents: Iterable[Document], keywords: list[str]) -> list[Event]:
    events = []
    for doc in documents:
        for keyword in keywords:
            if keyword.casefold() in doc.title.casefold():
                events.append(Event(doc.published.isoformat() if doc.published else None,
                                     keyword, doc.doc_id, doc.title))
    return events


def jump_quarters(series: pd.Series, threshold: float = .15) -> list[object]:
    changes = series.pct_change()
    return list(changes.index[changes.abs() > threshold])


def cusum(series: pd.Series, sensitivity: float = 2.0) -> list[ChangePoint]:
    baseline = float(series.iloc[:max(2, len(series) // 3)].mean())
    scale = float(series.iloc[:max(2, len(series) // 3)].std(ddof=0)) or 1.0
    cumulative = 0.0
    points = []
    for label, value in series.items():
        cumulative = max(0.0, cumulative + (float(value) - baseline) / scale)
        if cumulative >= sensitivity:
            points.append(ChangePoint(label, cumulative))
            cumulative = 0.0
    return points


def non_comparable_windows(documents: Iterable[Document], keywords: list[str]) -> list[Event]:
    return detect_events(documents, keywords)
