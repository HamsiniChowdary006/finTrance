from pathlib import Path

import yaml

from agent.scan.rules import Anomaly


def score_novelty(anomaly: Anomaly, narrative: str = "", peer_check: str = "insufficient",
                  path: str | Path = "config/headline_metrics.yaml") -> Anomaly:
    config = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    topic = " ".join(anomaly.metrics).casefold()
    narrative_lower = narrative.casefold()
    management_value = (0.0 if topic in narrative_lower else
                        (0.5 if any(item in narrative_lower for item in topic.split()) else 1.0)
                        if narrative_lower else None)
    obviousness = 0.0 if set(anomaly.metrics) <= set(config["metrics"]) else 1.0
    peer_value = 0.5 if peer_check == "sufficient" else None
    weights = config["weights"]
    components = {"management": management_value, "headline_obviousness": obviousness,
                  "peer_uniqueness": peer_value}
    usable = [(key, value) for key, value in components.items() if value is not None]
    weight_map = {"management": weights["management"],
                  "headline_obviousness": weights["obviousness"],
                  "peer_uniqueness": weights["peer_uniqueness"]}
    denominator = sum(weight_map[key] for key, _ in usable)
    anomaly.novelty = (sum(value * weight_map[key] for key, value in usable) / denominator
                       if denominator else 0.0)
    anomaly.novelty_components = {
        key: "n/a" if value is None else f"{value:.1f}" for key, value in components.items()}
    anomaly.novelty_rationale = "; ".join(
        f"{key}={value}" for key, value in anomaly.novelty_components.items())
    return anomaly
