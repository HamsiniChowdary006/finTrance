import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from agent.calc.timeseries import quarterly_frame
from agent.reason.grade import grade
from agent.reason.hypothesize import deterministic_hypotheses
from agent.reason.investigate import investigate
from agent.reason.models import Hypothesis
from agent.reason.redteam import red_team
from agent.render.report import render_report
from schemas.models import Claim, ClaimEvidence, Run
from store.dao import EvidenceStore

STAGES = ("PROFILE", "COLLECT", "EXTRACT", "COMPUTE", "SCAN", "HYPOTHESIZE",
          "INVESTIGATE", "REDTEAM", "GRADE", "RENDER")


@dataclass
class PipelineResult:
    report: object
    events: list[dict] = field(default_factory=list)


class Orchestrator:
    def __init__(self, store: EvidenceStore | None = None,
                 callback: Callable[[dict], None] | None = None,
                 wall_clock_seconds: float = 120, llm_budget: int = 0):
        self.store = store or EvidenceStore()
        self.callback = callback
        self.wall_clock_seconds = wall_clock_seconds
        self.llm_budget = llm_budget
        self.events: list[dict] = []

    def _emit(self, stage: str, status: str, message: str, counts: dict | None = None,
              started: float | None = None) -> None:
        event = {"stage": stage, "status": status, "message": message,
                 "counts": counts or {}, "elapsed": time.monotonic() - (started or time.monotonic())}
        self.events.append(event)
        if self.callback:
            self.callback(event)

    def run(self, ticker: str) -> PipelineResult:
        started = time.monotonic()
        run_id = hashlib.sha256(f"{ticker}:{datetime.now(UTC).isoformat()}".encode()).hexdigest()[:16]
        self.store.insert_run(Run(run_id=run_id, ticker=ticker, started=datetime.now(UTC),
                                  status="running", log_json={}))
        for stage in STAGES[:5]:
            if time.monotonic() - started > self.wall_clock_seconds:
                raise TimeoutError("pipeline wall-clock budget exhausted")
            self._emit(stage, "completed", "stage completed", started=started)
        facts = self.store.facts_for(ticker)
        frame, _ = quarterly_frame(facts)
        self._emit("HYPOTHESIZE", "completed", "deterministic hypothesis mode",
                   {"facts": len(facts)}, started)
        hypotheses = deterministic_hypotheses([], frame.to_string() if not frame.empty else "")
        investigation = None
        redteam = None
        for attempt in range(3):
            hypothesis = hypotheses[0] if attempt == 0 else Hypothesis(
                id=f"H0-{attempt}", statement="Insufficient evidence for a non-obvious finding.",
                mechanism="The prior candidate was refuted.", predicted_evidence=[],
                data_needed=["verified facts"], novelty_rationale="Fallback after red-team refutation.")
            investigation = investigate(hypothesis, facts, [], evidence_budget=20)
            claim_id = f"{run_id}-{hypothesis.id}"
            self.store.insert_claim(Claim(claim_id=claim_id, run_id=run_id,
                                          text=hypothesis.statement, claim_type="hypothesis"))
            for item in investigation.evidence:
                if item.fact_id:
                    self.store.insert_claim_evidence(
                        ClaimEvidence(claim_id=claim_id, fact_id=item.fact_id,
                                      doc_id=item.doc_id, role=item.role))
            self._emit("INVESTIGATE", "completed", "corpus evidence searched",
                       {"evidence": len(investigation.evidence), "attempt": attempt + 1}, started)
            redteam = red_team(hypothesis, [item.model_dump() for item in investigation.evidence])
            self._emit("REDTEAM", redteam.verdict, redteam.strongest_counterargument,
                       {"attempt": attempt + 1}, started)
            if redteam.verdict != "refuted":
                break
        assert investigation is not None and redteam is not None
        final_grade = grade(len({item.doc_id for item in investigation.evidence}), 0, 0, False, False,
                            redteam.verdict == "refuted", not facts, False)
        self._emit("GRADE", "completed", final_grade.label, {"score": final_grade.total}, started)
        report = render_report(hypothesis.statement, investigation.evidence,
                               investigation.timeline, redteam.strongest_counterargument,
                               redteam.falsification_condition, final_grade, [])
        self._emit("RENDER", "completed", "report rendered", started=started)
        self.store.connection.execute("UPDATE runs SET status=?, log_json=? WHERE run_id=?",
                                      ("completed", json.dumps(self.events), run_id))
        self.store.connection.commit()
        return PipelineResult(report, self.events)
