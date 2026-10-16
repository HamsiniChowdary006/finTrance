from dataclasses import dataclass

from agent.reason.models import EvidenceItem, Hypothesis
from schemas.models import Document, Fact


@dataclass(frozen=True)
class Investigation:
    evidence: list[EvidenceItem]
    timeline: list[str]
    source_gaps: list[str]


def investigate(hypothesis: Hypothesis, facts: list[Fact], documents: list[Document],
                evidence_budget: int = 20) -> Investigation:
    fact_map = {fact.fact_id: fact for fact in facts}
    evidence = []
    for fact_id in hypothesis.fact_ids[:evidence_budget]:
        fact = fact_map.get(fact_id)
        if not fact:
            continue
        document = next((item for item in documents if item.doc_id == fact.doc_id), None)
        evidence.append(EvidenceItem(claim=f"{fact.metric}={fact.value} {fact.unit}",
                                     doc_id=fact.doc_id, fact_id=fact.fact_id, page=fact.page,
                                     quote=fact.quote, role="supports",
                                     source_type=document.source_type.value if document else None,
                                     url=document.url if document else None))
    return Investigation(evidence=evidence, timeline=[], source_gaps=[])
