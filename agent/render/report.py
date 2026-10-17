from pathlib import Path

from agent.reason.models import EvidenceItem, Grade, RenderedReport


def render_report(hypothesis: str, evidence: list[EvidenceItem], timeline: list[str],
                  counterargument: str, falsification: str, grade: Grade,
                  anomalies: list[dict], novelty_rationale: str = "",
                  also_considered: list[dict] | None = None) -> RenderedReport:
    safe_evidence = [item for item in evidence if item.doc_id and item.quote]
    return RenderedReport(
        discovery=hypothesis,
        why_it_matters=["This is a research signal, not an investment recommendation.",
                        "The evidence window and limitations are shown explicitly."],
        evidence=safe_evidence, timeline=timeline,
        numbers=[item.claim for item in safe_evidence],
        counterargument=counterargument,
        falsification_condition=falsification,
        evidence_strength=grade, anomalies=anomalies,
        novelty_rationale=novelty_rationale,
        also_considered=also_considered or [])


def markdown(report: RenderedReport) -> str:
    lines = [f"# Discovery\n\n{report.discovery}", "\n## Why it matters"]
    lines.extend(f"- {item}" for item in report.why_it_matters)
    lines.append("\n## Evidence\n\n| Document | Page | Quote |\n|---|---:|---|")
    for item in report.evidence:
        quote = item.quote.replace("|", "\\|")
        lines.append(f"| {item.doc_id} | {item.page or ''} | {quote} |")
    lines.extend(["\n## Timeline", *[f"- {item}" for item in report.timeline],
                  "\n## Numbers", *[f"- {item}" for item in report.numbers],
                  f"\n## Counterargument\n\n{report.counterargument}",
                  f"\n## Falsification condition\n\n{report.falsification_condition}",
                  f"\n## Why this is not obvious\n\n{report.novelty_rationale}",
                  "\n## Also considered",
                  *[f"- {item}" for item in report.also_considered],
                  (f"\n## Evidence strength\n\n{report.evidence_strength.label} "
                   f"({report.evidence_strength.total}/10)")])
    return "\n".join(lines)


def write_report(report: RenderedReport, path: str | Path, fmt: str = "md") -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "json":
        target.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    else:
        target.write_text(markdown(report), encoding="utf-8")
