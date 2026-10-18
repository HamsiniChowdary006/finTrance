from dataclasses import dataclass

import pandas as pd

from .timeseries import Provenance, annualise, average_balance, trailing_sum, yoy


@dataclass(frozen=True)
class MetricResult:
    values: pd.Series
    fact_ids: dict[object, list[str]]
    reasons: dict[object, str]


def _result(values: pd.Series, *sources: Provenance) -> MetricResult:
    ids = {}
    for label in values.index:
        ids[label] = sorted({fid for source in sources for fid in source.fact_ids.get(label, [])})
    reasons = {label: "missing required input" for label, value in values.items() if pd.isna(value)}
    return MetricResult(values, ids, reasons)


def loan_growth_yoy(advances: Provenance) -> MetricResult:
    """Loan growth = current-quarter gross advances / prior-year quarter - 1."""
    return _result(yoy(advances.values, advances.fact_ids).values, advances)


def gnpa_pct(gross_npa: Provenance, advances: Provenance) -> MetricResult:
    """GNPA percentage = gross NPA / gross advances * 100."""
    return _result(gross_npa.values / advances.values * 100, gross_npa, advances)


def nnpa_pct(net_npa: Provenance, advances: Provenance) -> MetricResult:
    """NNPA percentage = net NPA / gross advances * 100."""
    return _result(net_npa.values / advances.values * 100, net_npa, advances)


def pcr(provisions: Provenance, gross_npa: Provenance) -> MetricResult:
    """PCR = provisions on NPA / gross NPA * 100."""
    return _result(provisions.values / gross_npa.values * 100, provisions, gross_npa)


def slippage_ratio(slippages: Provenance, opening_advances: Provenance) -> MetricResult:
    """Slippage ratio = annualised fresh slippages / opening advances * 100."""
    return _result(annualise(slippages.values, slippages.fact_ids).values
                   / opening_advances.values * 100, slippages, opening_advances)


def credit_cost(provisions: Provenance, write_offs: Provenance, advances: Provenance) -> MetricResult:
    """Credit cost = annualised provisions plus write-offs / average advances * 100."""
    avg = average_balance(advances.values, advances.fact_ids)
    numerator_values = provisions.values.add(write_offs.values, fill_value=0)
    numerator_ids = {
        label: sorted(set(provisions.fact_ids.get(label, []) +
                          write_offs.fact_ids.get(label, [])))
        for label in numerator_values.index
    }
    numerator = annualise(numerator_values, numerator_ids)
    return _result(numerator.values / avg.values * 100, provisions, write_offs, advances)


def writeoff_adjusted_gnpa(gross_npa: Provenance, advances: Provenance,
                           write_offs: Provenance) -> MetricResult:
    """Adjusted GNPA = (GNPA + trailing four-quarter write-offs) /
    (advances + trailing four-quarter write-offs) * 100."""
    trailing = trailing_sum(write_offs.values, 4, write_offs.fact_ids)
    values = (gross_npa.values + trailing.values) / (advances.values + trailing.values) * 100
    return _result(values, gross_npa, advances, trailing)


def stage_pct(stage: Provenance, advances: Provenance) -> MetricResult:
    """Stage percentage = stage balance / gross advances * 100."""
    return _result(stage.values / advances.values * 100, stage, advances)


def stage2_pct(stage2: Provenance, advances: Provenance) -> MetricResult:
    """Stage 2 percentage = Stage 2 assets / gross advances * 100."""
    return stage_pct(stage2, advances)


def stage3_pct(stage3: Provenance, advances: Provenance) -> MetricResult:
    """Stage 3 percentage = Stage 3 assets / gross advances * 100."""
    return stage_pct(stage3, advances)


def casa_ratio(casa: Provenance, deposits: Provenance) -> MetricResult:
    """CASA ratio = CASA deposits / total deposits * 100."""
    return _result(casa.values / deposits.values * 100, casa, deposits)


def credit_deposit_ratio(advances: Provenance, deposits: Provenance) -> MetricResult:
    """Credit-deposit ratio = gross advances / total deposits * 100."""
    return _result(advances.values / deposits.values * 100, advances, deposits)
