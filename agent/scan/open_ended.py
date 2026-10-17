from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from agent.calc.breaks import cusum
from agent.calc.timeseries import Provenance
from agent.scan.rules import Anomaly


def load_open_ended(path: str | Path = "config/open_ended.yaml") -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def _ids(result: Provenance, labels: list[object]) -> list[str]:
    return sorted({fact_id for label in labels for fact_id in result.fact_ids.get(label, [])})


def robust_outliers(series: dict[str, Provenance], config: dict) -> list[Anomaly]:
    rule = config["detectors"]["D1"]
    output = []
    for name, result in series.items():
        if len(result.values.dropna()) < rule["min_history"]:
            continue
        rolling = result.values.shift(1).rolling(
            rule["rolling_window"], min_periods=rule["rolling_window"])
        median = rolling.median()
        mad = rolling.apply(lambda values: float(np.median(np.abs(values - np.median(values)))))
        scale = mad * 1.4826
        difference = result.values - median
        zscore = difference / scale.replace(0, np.nan)
        zscore = zscore.mask(scale.eq(0) & difference.abs().gt(rule["min_delta"]), np.inf)
        labels = list(zscore.tail(rule["recent_quarters"])[
            zscore.tail(rule["recent_quarters"]).abs() > rule["mad_z"]].index)
        if labels:
            output.append(Anomaly(rule_id="D1", angle="robust-outlier", metrics=[name],
                                  window=labels, magnitude=float(zscore[labels].abs().max()),
                                  persistence_quarters=len(labels), fact_ids=_ids(result, labels),
                                  description=f"{name} was a robust rolling-MAD outlier.",
                                  agreed_detectors=["D1"]))
    return output


def relationship_break(data: dict[str, Provenance], relations: list[dict],
                       config: dict) -> list[Anomaly]:
    output = []
    for relation in relations:
        left, right = data.get(relation["left"]), data.get(relation["right"])
        if left is None or right is None or len(left.values.dropna()) < config["min_history"]:
            continue
        left_change = left.values.pct_change()
        right_change = right.values.pct_change()
        direction = relation.get("direction", "positive")
        divergence = ((left_change * right_change >= 0) if direction == "inverse"
                      else (left_change * right_change <= 0))
        labels = list(divergence.tail(relation["window"]).fillna(False)
                      [divergence.tail(relation["window"]).fillna(False)].index)
        if labels:
            output.append(Anomaly(rule_id="D2", angle="relationship-break",
                                  metrics=[relation["left"], relation["right"]], window=labels,
                                  magnitude=float((left_change[labels] - right_change[labels]).abs().max()),
                                  persistence_quarters=len(labels),
                                  fact_ids=sorted(set(_ids(left, labels) + _ids(right, labels))),
                                  description="A configured metric relationship decoupled.",
                                  agreed_detectors=["D2"]))
    return output


def peer_divergence(company: Provenance, peer_median: pd.Series | None,
                    config: dict) -> list[Anomaly]:
    if peer_median is None or len(peer_median.dropna()) < config["min_peers"]:
        return []
    window = int(config["window"])
    own = company.values.tail(window)
    peer = peer_median.reindex(own.index).dropna()
    if len(peer) < window:
        return []
    own_slope = np.polyfit(range(window), own.to_numpy(), 1)[0]
    peer_slope = np.polyfit(range(window), peer.to_numpy(), 1)[0]
    if abs(own_slope - peer_slope) <= config["slope_gap"]:
        return []
    labels = list(own.index)
    return [Anomaly(rule_id="D3", angle="peer-relative-divergence", metrics=["peer_metric"],
                    window=labels, magnitude=float(abs(own_slope - peer_slope)),
                    persistence_quarters=window, peer_check="sufficient",
                    fact_ids=_ids(company, labels),
                    description="Company trend diverged from the peer median.",
                    agreed_detectors=["D3"])]


def mix_shift(shares: dict[str, Provenance], config: dict) -> list[Anomaly]:
    rule = config["detectors"]["D4"]
    output = []
    for name, result in shares.items():
        change = result.values - result.values.shift(int(rule["window"]))
        labels = list(change.dropna()[change.dropna().abs() > rule["shift_points"]].index)
        if labels:
            output.append(Anomaly(rule_id="D4", angle="mix-shift", metrics=[name],
                                  window=labels, magnitude=float(change[labels].abs().max()),
                                  persistence_quarters=len(labels), fact_ids=_ids(result, labels),
                                  description=f"{name} share shifted materially.",
                                  agreed_detectors=["D4"]))
    return output


def unexplained_change_points(result: Provenance, event_periods: set[object],
                              config: dict) -> list[Anomaly]:
    points = [point.quarter for point in cusum(result.values.dropna())]
    points = [point for point in points if point not in event_periods]
    return [Anomaly(rule_id="D5", angle="unexplained-change-point", metrics=["series"],
                    window=[point], magnitude=1.0, persistence_quarters=1,
                    fact_ids=_ids(result, [point]),
                    description="A statistical change-point lacks a recorded event.",
                    agreed_detectors=["D5"]) for point in points]


def disclosure_drift(documents: list, config: dict) -> list[Anomaly]:
    from agent.extractor.document import read_document

    terms = config["detectors"]["D6"]["terms"]
    output = []
    for current, previous in zip(documents[1:], documents):
        try:
            current_text, previous_text = read_document(current.local_path), read_document(previous.local_path)
        except (OSError, ValueError, RuntimeError):
            continue
        newly_present = [term for term in terms if term.casefold() in current_text.casefold()
                         and term.casefold() not in previous_text.casefold()]
        for term in newly_present:
            sentence = next((line.strip() for line in current_text.splitlines()
                             if term.casefold() in line.casefold()), term)
            output.append(Anomaly(rule_id="D6", angle="disclosure-drift", metrics=[term],
                                  window=[current.title], magnitude=1.0, persistence_quarters=1,
                                  doc_ids=[current.doc_id], evidence_quotes=[sentence],
                                  description=f"Risk disclosure term appeared: {term}.",
                                  agreed_detectors=["D6"]))
    return output


def deduplicate(anomalies: list[Anomaly], config: dict) -> list[Anomaly]:
    merged: list[Anomaly] = []
    for anomaly in anomalies:
        match = next((item for item in merged if set(item.metrics) == set(anomaly.metrics)
                      and set(item.window) & set(anomaly.window)), None)
        if match:
            match.agreed_detectors = sorted(set(match.agreed_detectors
                                                + anomaly.agreed_detectors
                                                + [match.rule_id, anomaly.rule_id]))
            match.fact_ids = sorted(set(match.fact_ids + anomaly.fact_ids))
            match.doc_ids = sorted(set(match.doc_ids + anomaly.doc_ids))
            match.magnitude = max(match.magnitude, anomaly.magnitude)
        else:
            merged.append(anomaly)
    return merged[:config["guards"]["max_anomalies"]]


def stability(anomaly: Anomaly, detector, config: dict) -> Anomaly:
    perturbation = config["guards"]["stability_perturbation"]
    baseline = float(anomaly.magnitude)
    anomaly.stability = "pass" if baseline > perturbation else "fail"
    return anomaly
