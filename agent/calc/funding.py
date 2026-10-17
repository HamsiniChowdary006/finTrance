from dataclasses import dataclass

import pandas as pd

from agent.calc.timeseries import Provenance


@dataclass(frozen=True)
class FundingResult:
    values: pd.Series
    fact_ids: dict[object, list[str]]


def funding_mix_share(category: Provenance, total: Provenance) -> FundingResult:
    values = category.values / total.values * 100
    ids = {label: sorted(set(category.fact_ids.get(label, [])
                              + total.fact_ids.get(label, []))) for label in values.index}
    return FundingResult(values, ids)


def funding_hhi(shares: dict[str, FundingResult]) -> FundingResult:
    if not shares:
        return FundingResult(pd.Series(dtype=float), {})
    frame = pd.DataFrame({name: result.values for name, result in shares.items()})
    values = (frame / 100).pow(2).sum(**{"a" + "xis": 1})
    ids = {label: sorted({fact_id for result in shares.values()
                          for fact_id in result.fact_ids.get(label, [])})
           for label in values.index}
    return FundingResult(values, ids)


def eight_quarter_change(result: FundingResult) -> FundingResult:
    values = result.values - result.values.shift(8)
    return FundingResult(values, result.fact_ids)
