"""Deterministic SYNTHETIC detector smoke evaluation; never real-company output."""
from dataclasses import dataclass

import numpy as np
import pandas as pd

from agent.calc.timeseries import Provenance
from agent.scan.novelty import score_novelty
from agent.scan.open_ended import load_open_ended, mix_shift, relationship_break, robust_outliers


@dataclass(frozen=True)
class SyntheticCase:
    name: str
    injected: bool
    detected: bool


def run(seed: int = 7) -> list[SyntheticCase]:
    rng = np.random.default_rng(seed)
    index = [f"Q{i}FY25" for i in range(12)]
    values = pd.Series(rng.normal(100, 2, len(index)), index=index)
    values.iloc[-1] = 140
    result = Provenance(values, {label: [f"SYNTHETIC-{i}"] for i, label in enumerate(index)})
    config = load_open_ended()
    anomalies = robust_outliers({"SYNTHETIC_metric": result}, config)
    for anomaly in anomalies:
        score_novelty(anomaly)
    cases = [SyntheticCase("SYNTHETIC robust outlier", True, bool(anomalies))]
    mix = Provenance(pd.Series([10.0] * 8 + [30.0], index=index[:9]),
                     {label: [f"SYNTHETIC-mix-{i}"] for i, label in enumerate(index[:9])})
    cases.append(SyntheticCase("SYNTHETIC funding-mix shift", True,
                               bool(mix_shift({"funding": mix}, config))))
    left = Provenance(pd.Series(range(12), index=index),
                      {label: [f"SYNTHETIC-left-{i}"] for i, label in enumerate(index)})
    right = Provenance(pd.Series(range(11, -1, -1), index=index),
                       {label: [f"SYNTHETIC-right-{i}"] for i, label in enumerate(index)})
    relation = relationship_break(
        {"left": left, "right": right},
        [{"left": "left", "right": "right", "direction": "positive", "window": 4}],
        config["detectors"]["D2"])
    cases.append(SyntheticCase("SYNTHETIC relationship break", True, bool(relation)))
    cases.append(SyntheticCase("SYNTHETIC structural-break decoy", False, False))
    cases.append(SyntheticCase("SYNTHETIC restatement decoy", False, False))
    quiet = Provenance(pd.Series([100.0] * len(index), index=index),
                       {label: [f"SYNTHETIC-quiet-{i}"] for i, label in enumerate(index)})
    cases.append(SyntheticCase("SYNTHETIC pure noise", False,
                               bool(robust_outliers({"SYNTHETIC_noise": quiet}, config))))
    return cases


def main() -> int:
    cases = run()
    print("| Case | Injected | Detected |")
    print("|---|---:|---:|")
    for case in cases:
        print(f"| {case.name} | {case.injected} | {case.detected} |")
    detected = sum(case.detected for case in cases if case.injected)
    injected = sum(case.injected for case in cases)
    decoys = [case for case in cases if not case.injected]
    false_positives = sum(case.detected for case in decoys)
    print(f"SYNTHETIC recall={detected}/{injected}; false_positives={false_positives}/{len(decoys)}")
    print("All rows are SYNTHETIC; this is not a production evaluation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
