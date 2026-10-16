"""SYNTHETIC fixtures only: hand-calculated calculator/scanner validation."""

import numpy as np
import pandas as pd
import pytest

from agent.calc.breaks import cusum, jump_quarters
from agent.calc.metrics import (
    casa_ratio,
    credit_deposit_ratio,
    gnpa_pct,
    pcr,
    stage2_pct,
    stage3_pct,
    stage_pct,
)
from agent.calc.peers import compare_peers
from agent.calc.timeseries import (
    Provenance,
    annualise,
    average_balance,
    qoq,
    quarterly_frame,
    trailing_sum,
    yoy,
)
from agent.scan.rules import (
    Anomaly,
    cosmetic_gnpa,
    coverage_erosion,
    growth_vs_stress,
    load_rules,
    provisioning_lag,
)
from agent.scan.scoring import rank_anomalies
from schemas.models import Fact, PeriodType


def series(values):
    labels = [f"Q{i}FY202{i // 4 + 1}" for i in range(len(values))]
    return Provenance(pd.Series(values, index=labels, dtype=float),
                      {label: [f"SYNTHETIC-{i}"] for i, label in enumerate(labels)})


def test_yoy_hand_calculation():
    result = yoy(series([100, 110, 120, 130, 150]).values, series([100, 110, 120, 130, 150]).fact_ids)
    assert result.values.iloc[4] == .5
    assert result.fact_ids[result.values.index[4]] == ["SYNTHETIC-4", "SYNTHETIC-0"]


def test_qoq_and_trailing_sum():
    source = series([10, 20, 30, 40, 50])
    assert qoq(source.values, source.fact_ids).values.iloc[1] == 1
    assert trailing_sum(source.values, 4, source.fact_ids).values.iloc[3] == 100


def test_average_balance():
    assert average_balance(series([100, 120]).values).values.iloc[1] == 110


def test_annualise_hand_calculation():
    assert annualise(series([25]).values).values.iloc[0] == 100


@pytest.mark.parametrize("numerator,denominator,expected", [(10, 100, 10), (25, 200, 12.5)])
def test_gnpa_formula(numerator, denominator, expected):
    assert gnpa_pct(series([numerator]), series([denominator])).values.iloc[0] == expected


def test_pcr_formula():
    assert pcr(series([30]), series([100])).values.iloc[0] == 30


def test_stage_formula():
    assert stage_pct(series([20]), series([100])).values.iloc[0] == 20
    assert stage2_pct(series([20]), series([100])).values.iloc[0] == 20
    assert stage3_pct(series([20]), series([100])).values.iloc[0] == 20


def test_casa_formula():
    assert casa_ratio(series([40]), series([100])).values.iloc[0] == 40


def test_credit_deposit_formula():
    assert credit_deposit_ratio(series([75]), series([100])).values.iloc[0] == 75


def test_missing_input_has_reason():
    result = gnpa_pct(series([10]), Provenance(pd.Series([np.nan], index=["Q1"]), {}))
    assert np.isnan(result.values.iloc[0])
    assert result.reasons["Q1"] == "missing required input"


def test_peer_insufficiency():
    result = compare_peers(pd.Series([10], index=["Q1"]), {"a": pd.Series([8], index=["Q1"])})
    assert result.status["Q1"] == "insufficient"


def test_peer_sufficiency_and_gap():
    result = compare_peers(pd.Series([10], index=["Q1"]), {
        "a": pd.Series([8], index=["Q1"]), "b": pd.Series([9], index=["Q1"]),
        "c": pd.Series([11], index=["Q1"])})
    assert result.status["Q1"] == "sufficient"
    assert result.gap["Q1"] == 1


def test_jump_detection():
    assert jump_quarters(pd.Series([100, 130], index=["Q1", "Q2"])) == ["Q2"]


def test_cusum_shift():
    points = cusum(pd.Series([1, 1, 1, 5, 5, 5], index=list("abcdef")), 2)
    assert points


def test_rule_fires_after_four_quarters():
    labels = list("abcdefgh")
    growth = Provenance(pd.Series([0, 0, 0, 0, .3, .3, .3, .3], index=labels),
                        {x: [f"SYNTHETIC-G-{x}"] for x in labels})
    stress = Provenance(pd.Series([0, 0, 0, 0, .7, .7, .7, .7], index=labels),
                        {x: [f"SYNTHETIC-S-{x}"] for x in labels})
    result = growth_vs_stress(growth, stress, load_rules())
    assert result and len(result[0].fact_ids) == 8


def test_rule_near_miss_does_not_fire():
    labels = list("abcdefgh")
    growth = Provenance(pd.Series([.3] * 8, index=labels), {})
    stress = Provenance(pd.Series([.59] * 8, index=labels), {})
    assert not growth_vs_stress(growth, stress, load_rules())


def test_r2_fires_and_near_miss():
    labels = list("abcdef")
    gnpa = Provenance(pd.Series([5, 5, 5, 4, 4, 4], index=labels), {})
    adjusted = Provenance(pd.Series([5, 5, 5, 5, 5, 5], index=labels), {})
    writeoffs = Provenance(pd.Series([0, 0, 0, 1, 1, 1], index=labels), {})
    assert cosmetic_gnpa(gnpa, adjusted, writeoffs, load_rules())
    assert not cosmetic_gnpa(gnpa, adjusted, Provenance(pd.Series([0] * 6, index=labels), {}),
                              load_rules())


def test_r3_fires_and_near_miss():
    labels = list("abcdef")
    falling = Provenance(pd.Series([5, 4, 3, 2, 1, 0], index=labels), {})
    rising = Provenance(pd.Series([1, 1, 2, 3, 4, 5], index=labels), {})
    assert provisioning_lag(falling, rising, load_rules())
    assert not provisioning_lag(falling, Provenance(pd.Series([1] * 6, index=labels), {}),
                                 load_rules())


def test_r4_fires_after_six_quarters():
    labels = list("abcdef")
    pcr = Provenance(pd.Series([80, 79, 78, 77, 76, 70], index=labels), {})
    gnpa = Provenance(pd.Series([5, 5, 5, 5, 5, 5], index=labels), {})
    assert coverage_erosion(pcr, gnpa, load_rules())


def test_scoring_order_and_top_three():
    items = [Anomaly(rule_id=str(i), angle="x", metrics=["x"], window=["Q1"],
                     magnitude=i, persistence_quarters=4, fact_ids=[f"SYNTHETIC-{i}"],
                     description="synthetic") for i in (1, 3, 2, 4)]
    assert [item.rule_id for item in rank_anomalies(items)] == ["4", "3", "2"]


def test_non_comparable_score_penalty():
    item = Anomaly(rule_id="SYNTHETIC", angle="x", metrics=["x"], window=["Q1"],
                   magnitude=2, persistence_quarters=4, non_comparable_overlap=True,
                   fact_ids=["SYNTHETIC-1"], description="synthetic")
    assert rank_anomalies([item])[0].score < 0.5


def test_every_output_number_has_provenance():
    result = gnpa_pct(series([10]), series([100]))
    assert result.fact_ids["Q0FY2021"] == ["SYNTHETIC-0"]


def test_latest_restatement_wins():
    first = Fact(fact_id="SYNTHETIC-original", ticker="T", metric="gross_npa", value=10,
                 unit="INR crore", period="Q1FY2024", period_type=PeriodType.QUARTER,
                 doc_id="d1", page=1, quote="10", extractor="synthetic", confidence=.8)
    revised = first.model_copy(update={"fact_id": "SYNTHETIC-restated", "value": 8, "restated": True})
    frame, provenance = quarterly_frame([first, revised])
    assert frame.loc["Q1FY2024", "gross_npa"] == 8
    assert provenance["Q1FY2024"]["gross_npa"] == ["SYNTHETIC-restated"]
