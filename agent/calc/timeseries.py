from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np
import pandas as pd

from schemas.models import Fact


@dataclass(frozen=True)
class Provenance:
    values: pd.Series
    fact_ids: dict[object, list[str]]


def quarterly_frame(facts: Iterable[Fact]) -> tuple[pd.DataFrame, dict[object, dict[str, list[str]]]]:
    rows = list(facts)
    selected: dict[tuple[str, str], Fact] = {}
    for fact in rows:
        key = (fact.period, fact.metric)
        current = selected.get(key)
        if current is None or fact.restated:
            selected[key] = fact
    periods = sorted({fact.period for fact in selected.values()})
    metrics = sorted({fact.metric for fact in selected.values()})
    frame = pd.DataFrame(index=pd.Index(periods, name="period"), columns=metrics, dtype=float)
    provenance: dict[object, dict[str, list[str]]] = {}
    for (period, metric), fact in selected.items():
        frame.loc[period, metric] = fact.value
        provenance.setdefault(period, {})[metric] = [fact.fact_id]
    return frame, provenance


def _provenance(index: pd.Index, source: dict[object, list[str]], positions: list[int]) -> dict[object, list[str]]:
    return {index[pos]: source.get(index[pos], []) for pos in positions}


def yoy(series: pd.Series, fact_ids: dict[object, list[str]] | None = None) -> Provenance:
    values = series / series.shift(4) - 1
    ids = fact_ids or {}
    provenance = {}
    for pos, label in enumerate(series.index):
        if pos >= 4:
            provenance[label] = ids.get(label, []) + ids.get(series.index[pos - 4], [])
    return Provenance(values, provenance)


def qoq(series: pd.Series, fact_ids: dict[object, list[str]] | None = None) -> Provenance:
    values = series / series.shift(1) - 1
    ids = fact_ids or {}
    return Provenance(values, {series.index[i]: ids.get(series.index[i], []) + ids.get(series.index[i - 1], [])
                               for i in range(1, len(series))})


def trailing_sum(series: pd.Series, n: int = 4, fact_ids: dict[object, list[str]] | None = None) -> Provenance:
    values = series.rolling(n, min_periods=n).sum()
    ids = fact_ids or {}
    provenance = {}
    for i in range(n - 1, len(series)):
        provenance[series.index[i]] = [fid for label in series.index[i - n + 1:i + 1]
                                       for fid in ids.get(label, [])]
    return Provenance(values, provenance)


def annualise(quarterly_value: pd.Series, fact_ids: dict[object, list[str]] | None = None) -> Provenance:
    return Provenance(quarterly_value * 4, fact_ids or {})


def rolling_zscore(series: pd.Series, window: int = 4) -> Provenance:
    mean = series.rolling(window, min_periods=window).mean()
    std = series.rolling(window, min_periods=window).std(ddof=0)
    return Provenance((series - mean) / std.replace(0, np.nan), {})


def average_balance(series: pd.Series, fact_ids: dict[object, list[str]] | None = None) -> Provenance:
    values = (series + series.shift(1)) / 2
    ids = fact_ids or {}
    return Provenance(values, {series.index[i]: ids.get(series.index[i], []) + ids.get(series.index[i - 1], [])
                               for i in range(1, len(series))})
