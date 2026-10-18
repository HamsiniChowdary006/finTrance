from pathlib import Path

import pandas as pd
import yaml
from pydantic import BaseModel, Field

from agent.calc.funding import FundingResult
from agent.calc.metrics import MetricResult


class Anomaly(BaseModel):
    rule_id: str
    angle: str
    metrics: list[str]
    window: list[object]
    magnitude: float
    persistence_quarters: int
    peer_gap: float | None = None
    peer_check: str = "insufficient"
    non_comparable_overlap: bool = False
    fact_ids: list[str] = Field(default_factory=list)
    description: str
    score: float = 0.0
    novelty: float = 0.0
    novelty_rationale: str = ""
    novelty_components: dict[str, str] = Field(default_factory=dict)
    evidence_quotes: list[str] = Field(default_factory=list)
    doc_ids: list[str] = Field(default_factory=list)
    agreed_detectors: list[str] = Field(default_factory=list)
    stability: str = "unassessed"


def load_rules(path: str | Path = "config/anomaly_rules.yaml") -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def _runs(mask: pd.Series, minimum: int) -> list[list[object]]:
    runs, current = [], []
    for label, value in mask.fillna(False).items():
        if value:
            current.append(label)
        elif current:
            if len(current) >= minimum:
                runs.append(current)
            current = []
    if len(current) >= minimum:
        runs.append(current)
    return runs


def growth_vs_stress(growth: MetricResult, stress: MetricResult, config: dict) -> list[Anomaly]:
    rule = config["R1"]
    mask = (growth.values > rule["growth_min"]) & (stress.values > rule["multiple"] * growth.values)
    result = []
    for window in _runs(mask, rule["min_persistence"]):
        ids = [fid for label in window for fid in growth.fact_ids.get(label, []) + stress.fact_ids.get(label, [])]
        result.append(Anomaly(rule_id="R1", angle="growth-vs-stress",
                              metrics=["loan_growth_yoy", "stress"], window=window,
                              magnitude=float((stress.values[window] / growth.values[window]).mean()),
                              persistence_quarters=len(window), fact_ids=sorted(set(ids)),
                              description=f"Loan growth and stress diverged for {len(window)} quarters."))
    return result


def cosmetic_gnpa(gnpa: MetricResult, adjusted: MetricResult, writeoffs: MetricResult,
                  config: dict) -> list[Anomaly]:
    threshold = config["R2"]["writeoff_materiality"]
    mask = (gnpa.values.diff() < 0) & (adjusted.values.diff() >= 0) & (writeoffs.values.diff() > threshold)
    output = []
    for window in _runs(mask, 1):
        ids = [fid for label in window for result in (gnpa, adjusted, writeoffs)
               for fid in result.fact_ids.get(label, [])]
        output.append(Anomaly(rule_id="R2", angle="cosmetic-GNPA",
                              metrics=["gnpa_pct", "writeoff_adjusted_gnpa", "write_offs"],
                              window=window, magnitude=float(adjusted.values[window].mean()),
                              persistence_quarters=len(window), fact_ids=sorted(set(ids)),
                              description="Reported GNPA fell while write-off-adjusted GNPA did not."))
    return output


def provisioning_lag(credit_cost_result: MetricResult, stress: MetricResult,
                     config: dict) -> list[Anomaly]:
    mask = (credit_cost_result.values.diff() < 0) & (stress.values.diff() > 0)
    output = []
    for window in _runs(mask, config["R3"]["min_persistence"]):
        ids = [fid for label in window for result in (credit_cost_result, stress)
               for fid in result.fact_ids.get(label, [])]
        output.append(Anomaly(rule_id="R3", angle="provisioning-lag",
                              metrics=["credit_cost", "stress"], window=window,
                              magnitude=float(stress.values[window].mean()),
                              persistence_quarters=len(window), fact_ids=sorted(set(ids)),
                              description="Credit cost fell while stress indicators rose."))
    return output


def coverage_erosion(pcr_result: MetricResult, gnpa: MetricResult,
                     config: dict) -> list[Anomaly]:
    periods = config["R4"]["quarters"]
    values = pcr_result.values
    output = []
    for end in range(periods - 1, len(values)):
        start = end - periods + 1
        if values.iloc[end] - values.iloc[start] < -config["R4"]["pcr_drop"] and \
                gnpa.values.iloc[end] >= gnpa.values.iloc[start]:
            window = list(values.index[start:end + 1])
            ids = [fid for label in window for result in (pcr_result, gnpa)
                   for fid in result.fact_ids.get(label, [])]
            output.append(Anomaly(rule_id="R4", angle="coverage-erosion",
                                  metrics=["pcr", "gnpa_pct"], window=window,
                                  magnitude=float(values.iloc[start] - values.iloc[end]),
                                  persistence_quarters=periods, fact_ids=sorted(set(ids)),
                                  description="PCR fell materially while GNPA did not improve."))
    return output


def funding_shift(shares: dict[str, FundingResult], config: dict) -> list[Anomaly]:
    rule = config["R5"]
    output = []
    for category, result in shares.items():
        change = result.values - result.values.shift(int(rule["quarters"]))
        mask = change.abs() > rule["shift_points"]
        for window in _runs(mask, 1):
            ids = [fid for label in window for fid in result.fact_ids.get(label, [])]
            output.append(Anomaly(
                rule_id="R5", angle="funding-mix-shift", metrics=[category, "funding_mix_share"],
                window=window, magnitude=float(change[window].abs().max()),
                persistence_quarters=len(window), fact_ids=sorted(set(ids)),
                description=f"{category} funding share moved materially over the configured window."))
    return output


def casa_decline(casa: MetricResult, config: dict) -> list[Anomaly]:
    rule = config["R6"]
    change = casa.values - casa.values.shift(int(rule["quarters"]))
    windows = _runs(change < -rule["decline_points"], 1)
    return [Anomaly(rule_id="R6", angle="casa-decline", metrics=["casa_ratio"],
                    window=window, magnitude=float(-change[window].min()),
                    persistence_quarters=len(window),
                    fact_ids=sorted({fid for label in window for fid in casa.fact_ids.get(label, [])}),
                    description="CASA share declined over the configured comparison window.")
            for window in windows]


def concentration(hhi: FundingResult, top_lender: MetricResult | None,
                  config: dict) -> list[Anomaly]:
    rule = config["R7"]
    masks = [hhi.values > rule["hhi_threshold"]]
    if top_lender is not None:
        masks.append(top_lender.values > rule["top_lender_share"])
    mask = masks[0]
    for other in masks[1:]:
        mask = mask | other
    windows = _runs(mask, 1)
    return [Anomaly(rule_id="R7", angle="funder-concentration", metrics=["funding_hhi"],
                    window=window, magnitude=float(hhi.values[window].max()),
                    persistence_quarters=len(window),
                    fact_ids=sorted({fid for label in window for fid in hhi.fact_ids.get(label, [])}),
                    description="Funding concentration exceeded the configured threshold.")
            for window in windows]


def short_term_reliance(short_term: FundingResult, growth: MetricResult,
                        config: dict) -> list[Anomaly]:
    rule = config["R10"]
    change = short_term.values - short_term.values.shift(1)
    mask = (change > rule["short_term_share_rise"]) & (growth.values > rule["loan_growth_min"])
    windows = _runs(mask, 1)
    return [Anomaly(rule_id="R10", angle="short-term-funding-reliance",
                    metrics=["commercial_paper_share", "loan_growth_yoy"], window=window,
                    magnitude=float(change[window].max()), persistence_quarters=len(window),
                    fact_ids=sorted({fid for label in window
                                     for fid in short_term.fact_ids.get(label, [])
                                     + growth.fact_ids.get(label, [])}),
                    description="Short-term funding reliance rose while loan growth was high.")
            for window in windows]


def evaluate_rules(data: dict[str, MetricResult], config: dict) -> list[Anomaly]:
    anomalies = []
    if "loan_growth_yoy" in data and "stress" in data:
        anomalies.extend(growth_vs_stress(data["loan_growth_yoy"], data["stress"], config))
    if {"gnpa_pct", "writeoff_adjusted_gnpa", "write_offs"} <= data.keys():
        anomalies.extend(cosmetic_gnpa(data["gnpa_pct"], data["writeoff_adjusted_gnpa"],
                                       data["write_offs"], config))
    if {"credit_cost", "stress"} <= data.keys():
        anomalies.extend(provisioning_lag(data["credit_cost"], data["stress"], config))
    if {"pcr", "gnpa_pct"} <= data.keys():
        anomalies.extend(coverage_erosion(data["pcr"], data["gnpa_pct"], config))
    shares = data.get("funding_shares", {})
    if shares:
        anomalies.extend(funding_shift(shares, config))
    if "casa_ratio" in data:
        anomalies.extend(casa_decline(data["casa_ratio"], config))
    if "funding_hhi" in data:
        anomalies.extend(concentration(data["funding_hhi"], data.get("top_lender_share"), config))
    if {"commercial_paper_share", "loan_growth_yoy"} <= data.keys():
        anomalies.extend(short_term_reliance(data["commercial_paper_share"],
                                              data["loan_growth_yoy"], config))
    return anomalies
