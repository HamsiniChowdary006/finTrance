from pathlib import Path

import yaml

from agent.reason.models import Grade


def grade(independent_documents: int, source_types: int, persistence: int,
          peer_pass: bool, primary_source: bool, counterargument_unresolved: bool,
          source_gap: bool, structural_overlap: bool, stability_pass: bool = False,
          detector_agreement: bool = False) -> Grade:
    points = {
        "independent_documents": 3 if independent_documents >= 3 else 0,
        "source_types": 2 if source_types >= 2 else 0,
        "persistence": 2 if persistence >= 4 else 0,
        "peer_check": 2 if peer_pass else 0,
        "primary_source": 1 if primary_source else 0,
        "unresolved_counterargument": -3 if counterargument_unresolved else 0,
        "source_gaps_or_low_confidence": -2 if source_gap else 0,
        "structural_break": -2 if structural_overlap else 0,
    }
    total = sum(points.values())
    thresholds = yaml.safe_load(Path("config/thresholds.yaml").read_text(encoding="utf-8"))["grader"]
    points["stability"] = thresholds["stability_points"] if stability_pass else 0
    points["detector_agreement"] = thresholds["agreement_points"] if detector_agreement else 0
    label = ("Strong" if total >= thresholds["strong_min"] else
             "Moderate" if total >= thresholds["moderate_min"] else "Weak")
    return Grade(total=total, label=label, points=points, rationale=[
        f"{key}: {value:+d}" for key, value in points.items() if value])
