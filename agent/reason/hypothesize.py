import re

from agent.reason.models import Hypothesis


def wrap_document_text(text: str) -> str:
    return f"<DOCUMENT_EVIDENCE>\n{text}\n</DOCUMENT_EVIDENCE>"


def contains_prompt_injection(text: str) -> bool:
    markers = ("ignore previous instructions", "system prompt", "call a tool",
               "reveal the api key", "follow these instructions")
    lowered = text.casefold()
    return any(marker in lowered for marker in markers)


def _numbers(text: str) -> set[str]:
    return set(re.findall(r"(?<![A-Za-z])\d+(?:\.\d+)?%?", text))


def validate_numbers(hypothesis: Hypothesis, supplied_text: str) -> bool:
    return _numbers(hypothesis.statement) <= _numbers(supplied_text)


def deterministic_hypotheses(anomalies: list[dict], metrics: str = "") -> list[Hypothesis]:
    if not anomalies:
        return [Hypothesis(id="H0", statement="Insufficient evidence for a non-obvious finding.",
                           mechanism="The available evidence does not establish a rule-backed pattern.",
                           predicted_evidence=[], data_needed=["quarterly facts and source evidence"],
                           novelty_rationale="No anomaly passed the minimum evidence threshold.")]
    first = anomalies[0]
    return [Hypothesis(
        id=f"H-{first.get('rule_id', '0')}",
        statement=f"{first.get('description', 'The observed metric pattern warrants investigation.')}",
        mechanism="The rule-linked metrics moved together across the reported window.",
        predicted_evidence=[f"Verify {metric}" for metric in first.get("metrics", [])],
        data_needed=list(first.get("metrics", [])),
        novelty_rationale="Generated from a deterministic anomaly rule, not an LLM.",
        fact_ids=list(first.get("fact_ids", [])),
    )]
