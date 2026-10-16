from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class PeerResult:
    median: pd.Series
    iqr: pd.Series
    gap: pd.Series
    zscore: pd.Series
    status: pd.Series


def compare_peers(company: pd.Series, peers: dict[str, pd.Series]) -> PeerResult:
    table = pd.DataFrame(peers)
    count = table.notna().T.sum()
    median = table.T.median()
    iqr = table.T.quantile(.75) - table.T.quantile(.25)
    gap = company - median
    std = table.T.std(ddof=0).replace(0, float("nan"))
    status = count.ge(3).map({True: "sufficient", False: "insufficient"})
    return PeerResult(median, iqr, gap, (company - median) / std, status)
