from pathlib import Path

import yaml

from agent.scan.rules import Anomaly


def score_anomaly(anomaly: Anomaly, config: dict | None = None) -> Anomaly:
    config = config or yaml.safe_load(Path("config/open_ended.yaml").read_text(encoding="utf-8"))
    magnitude_cap = float(config["scoring"]["magnitude_cap"])
    magnitude = min(1.0, max(0.0, anomaly.magnitude / magnitude_cap))
    persistence = min(1.0, anomaly.persistence_quarters / 4)
    peer = min(1.0, abs(anomaly.peer_gap or 0.0) / magnitude_cap)
    penalty = 0.5 if anomaly.non_comparable_overlap else 1.0
    anomaly.score = (magnitude + persistence + peer + anomaly.novelty) / 4 * penalty
    return anomaly


def rank_anomalies(anomalies: list[Anomaly], limit: int = 3,
                   config: dict | None = None) -> list[Anomaly]:
    return sorted((score_anomaly(item, config) for item in anomalies),
                  key=lambda item: (item.score, item.novelty, item.stability == "pass"),
                  reverse=True)[:limit]
