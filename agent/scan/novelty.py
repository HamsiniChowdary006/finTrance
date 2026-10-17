from pathlib import Path

import yaml

from agent.scan.rules import Anomaly


def score_novelty(anomaly: Anomaly, narrative: str = "", peer_check: str = "insufficient",
                  path: str | Path = "config/headline_metrics.yaml") -> Anomaly:
    config = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    topic = " ".join(anomaly.metrics).casefold()
    narrative_lower = narrative.casefold()
    management = 0.0 if topic in narrative_lower else (0.5 if any(item in narrative_lower for item in topic.split()) else 1.0)
    obviousness = 0.0 if set(anomaly.metrics) <= set(config["metrics"]) else 1.0
    peer = 1.0 if peer_check != "sufficient" else 0.5
    weights = config["weights"]
    anomaly.novelty = max(0.0, min(1.0, management * weights["management"]
                                     + obviousness * weights["obviousness"]
                                     + peer * weights["peer_uniqueness"]))
    anomaly.novelty_rationale = (
        f"Management mention={management:.1f}; headline obviousness={obviousness:.1f}; "
        f"peer uniqueness={peer:.1f}.")
    return anomaly
