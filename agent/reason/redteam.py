from agent.reason.models import Hypothesis, RedTeamResult


def red_team(hypothesis: Hypothesis, evidence: list[dict], *, non_comparable: bool = False,
             peer_pattern: bool = False, low_confidence: bool = False) -> RedTeamResult:
    checks = {
        "sector_effect": peer_pattern,
        "structural_break": non_comparable,
        "data_quality": low_confidence,
        "evidence_present": bool(evidence),
    }
    if not evidence:
        return RedTeamResult(
            strongest_counterargument="No supporting evidence was available.",
            falsification_condition="Any verified supporting fact would be required before this can survive.",
            verdict="refuted", revised_hypothesis=None, checks=checks)
    if non_comparable:
        return RedTeamResult(
            strongest_counterargument="A structural break overlaps the anomaly window.",
            falsification_condition="Two consecutive comparable quarters must reproduce the pattern.",
            verdict="weakened", revised_hypothesis=hypothesis.statement, checks=checks)
    return RedTeamResult(
        strongest_counterargument="The pattern may reflect a sector-wide effect or denominator change.",
        falsification_condition="Two consecutive quarters below the rule threshold would refute this pattern.",
        verdict="survives", checks=checks)
