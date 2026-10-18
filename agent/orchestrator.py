import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import yaml

from agent.calc.breaks import jump_quarters
from agent.calc.funding import eight_quarter_change, funding_hhi, funding_mix_share
from agent.calc.metrics import (
    casa_ratio,
    credit_cost,
    gnpa_pct,
    loan_growth_yoy,
    pcr,
    stage3_pct,
    writeoff_adjusted_gnpa,
)
from agent.calc.timeseries import Provenance, quarterly_frame
from agent.reason.grade import grade
from agent.reason.hypothesize import deterministic_hypotheses
from agent.reason.investigate import investigate
from agent.reason.redteam import red_team
from agent.render.report import render_report
from agent.scan.novelty import score_novelty
from agent.scan.open_ended import (
    deduplicate,
    disclosure_drift,
    load_open_ended,
    mix_shift,
    peer_divergence,
    relationship_break,
    robust_outliers,
    stability,
    unexplained_change_points,
)
from agent.scan.rules import evaluate_rules, load_rules
from agent.scan.scoring import rank_anomalies
from schemas.models import Claim, ClaimEvidence, Run
from store.dao import EvidenceStore

STAGES = ("PROFILE", "COLLECT", "EXTRACT", "COMPUTE", "SCAN", "HYPOTHESIZE",
          "INVESTIGATE", "REDTEAM", "GRADE", "RENDER")


@dataclass
class PipelineResult:
    report: object
    events: list[dict] = field(default_factory=list)


def _provenance(frame: pd.DataFrame, provenance: dict, metric: str) -> Provenance:
    return Provenance(frame.get(metric, pd.Series(index=frame.index, dtype=float)),
                      {period: provenance.get(period, {}).get(metric, [])
                       for period in frame.index})


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

    def run(self, ticker: str, peers: list[str] | None = None) -> PipelineResult:
        started = time.monotonic()
        peers = peers or []
        run_id = hashlib.sha256(f"{ticker}:{datetime.now(UTC).isoformat()}".encode()).hexdigest()[:16]
        self.store.insert_run(Run(run_id=run_id, ticker=ticker, started=datetime.now(UTC),
                                  status="running", log_json={}))
        facts = self.store.facts_for(ticker)
        documents = self.store.documents_for(ticker)
        metric_errors: list[str] = []
        rule_errors: list[str] = []
        self._emit("PROFILE", "completed", "profile resolved from stored evidence",
                   {"facts": len(facts), "documents": len(documents)}, started)
        self._emit("COLLECT", "skipped" if not documents else "completed",
                   "manual corpus empty; no verified source was fetched" if not documents
                   else "stored corpus available", {"documents": len(documents)}, started)
        self._emit("EXTRACT", "skipped" if not facts else "completed",
                   "no unprocessed documents" if facts else "no documents to extract",
                   {"facts": len(facts), "processed_documents": len(documents)}, started)

        frame, provenance = quarterly_frame(facts)
        data: dict = {}
        if not frame.empty and "gross_advances" in frame:
            advances = _provenance(frame, provenance, "gross_advances")
            def compute(name, function, *args):
                try:
                    data[name] = function(*args)
                except (KeyError, TypeError, ValueError, ZeroDivisionError) as error:
                    metric_errors.append(f"{name}: {error}")

            compute("loan_growth_yoy", loan_growth_yoy, advances)
            if "stage3_assets" in frame:
                compute("stress", stage3_pct, _provenance(frame, provenance, "stage3_assets"), advances)
            elif "gnpa_pct" in frame:
                data["stress"] = _provenance(frame, provenance, "gnpa_pct")
            elif "gross_npa" in frame:
                compute("stress", gnpa_pct, _provenance(frame, provenance, "gross_npa"), advances)
            if {"gross_npa", "write_offs"} <= set(frame.columns):
                gnpa = (_provenance(frame, provenance, "gnpa_pct") if "gnpa_pct" in frame
                        else gnpa_pct(_provenance(frame, provenance, "gross_npa"), advances))
                data["gnpa_pct"] = gnpa
                data["writeoff_adjusted_gnpa"] = writeoff_adjusted_gnpa(
                    _provenance(frame, provenance, "gross_npa"), advances,
                    _provenance(frame, provenance, "write_offs"))
                data["write_offs"] = _provenance(frame, provenance, "write_offs")
            if {"provisions_expense", "write_offs"} <= set(frame.columns):
                compute("credit_cost", credit_cost,
                    _provenance(frame, provenance, "provisions_expense"),
                    _provenance(frame, provenance, "write_offs"), advances)
            if {"provisions_on_npa", "gross_npa"} <= set(frame.columns):
                compute("pcr", pcr, _provenance(frame, provenance, "provisions_on_npa"),
                        _provenance(frame, provenance, "gross_npa"))
            if {"casa_deposits", "total_deposits"} <= set(frame.columns):
                compute("casa_ratio", casa_ratio,
                        _provenance(frame, provenance, "casa_deposits"),
                        _provenance(frame, provenance, "total_deposits"))
        required_metrics = {"gross_advances", "gross_npa", "net_npa",
                            "write_offs", "provisions_expense", "provisions_on_npa"}
        missing_metrics = sorted(required_metrics - set(frame.columns))
        missing_quarters = sorted(set(frame.index) - {
            period for period in frame.index
            if all(pd.notna(frame.loc[period, metric]) for metric in required_metrics
                   if metric in frame.columns)
        })
        compute_message = ("computed provenance-carrying metric series" if data else
                           "insufficient facts for derived metrics; missing metrics=" +
                           ",".join(missing_metrics) + "; missing quarters=" +
                           ",".join(missing_quarters))
        self._emit("COMPUTE", "completed" if data else "skipped",
                   compute_message,
                   {"quarters": len(frame), "derived_metrics": len(data), "errors": len(metric_errors)}, started)
        if metric_errors:
            self._emit("COMPUTE", "warning", "; ".join(metric_errors), started=started)

        jump_candidates = set(jump_quarters(frame["gross_advances"])) if "gross_advances" in frame else set()
        break_terms = ("merger", "amalgamation", "demerger", "acquisition",
                       "scheme", "reclassification", "accounting policy", "rbi restriction")
        event_doc_ids = {doc.doc_id for doc in documents
                         if any(term in doc.title.casefold() for term in break_terms)}
        breaks = {fact.period for fact in facts
                  if fact.restated or fact.doc_id in event_doc_ids}
        total_metric = "total_borrowings" if "total_borrowings" in frame else "borrowings"
        if total_metric in frame:
            total = _provenance(frame, provenance, total_metric)
            categories = ("bank_loans", "ncd_bonds", "commercial_paper", "ecb",
                          "deposits", "securitisation", "term_deposits")
            shares = {category: funding_mix_share(_provenance(frame, provenance, category), total)
                      for category in categories if category in frame}
            if shares:
                data["funding_shares"] = shares
                data["funding_hhi"] = funding_hhi(shares)
                for category, result in shares.items():
                    data[f"{category}_share"] = result
                    if category == "commercial_paper":
                        data["commercial_paper_share"] = result
        if "casa_ratio" in data:
            data["casa_ratio_change"] = eight_quarter_change(data["casa_ratio"])
        if "top_lender_share" in frame:
            data["top_lender_share"] = _provenance(frame, provenance, "top_lender_share")
        if breaks:
            for result in data.values():
                if hasattr(result, "fact_ids") and hasattr(result.values, "loc"):
                    result.values.loc[result.values.index.isin(breaks)] = float("nan")
        rule_errors: list[str] = []
        try:
            anomalies = evaluate_rules(data, load_rules()) if data else []
        except (KeyError, TypeError, ValueError, ZeroDivisionError) as error:
            anomalies = []
            rule_errors.append(str(error))
            self._emit("SCAN", "warning", f"rules skipped: {error}", started=started)
        open_config = load_open_ended()
        series = {name: value for name, value in data.items()
                  if hasattr(value, "values") and hasattr(value, "fact_ids")}
        anomalies.extend(robust_outliers(series, open_config))
        relation_config = yaml.safe_load(
            Path("config/metric_relations.yaml").read_text(encoding="utf-8"))["relations"]
        anomalies.extend(relationship_break(series, relation_config,
                                            open_config["detectors"]["D2"]))
        if "funding_shares" in data:
            anomalies.extend(mix_shift(data["funding_shares"], open_config))
        if peers and "gross_advances" in series and len(peers) >= open_config["detectors"]["D3"]["min_peers"]:
            peer_values = []
            for peer in peers:
                peer_frame, _ = quarterly_frame(self.store.facts_for(peer))
                if "gross_advances" in peer_frame:
                    peer_values.append(peer_frame["gross_advances"])
            if len(peer_values) >= open_config["detectors"]["D3"]["min_peers"]:
                peer_median = pd.DataFrame(peer_values).T.median()
                anomalies.extend(peer_divergence(
                    series["gross_advances"], peer_median, open_config["detectors"]["D3"]))
        if "gross_advances" in series:
            anomalies.extend(unexplained_change_points(
                series["gross_advances"], breaks, open_config))
        anomalies.extend(disclosure_drift(documents, open_config))
        anomalies = deduplicate(anomalies, open_config)
        for anomaly in anomalies:
            anomaly.peer_check = "sufficient" if len(peers) >= 3 else "insufficient"
            score_novelty(anomaly, frame.to_string() if not frame.empty else "",
                          anomaly.peer_check)
            stability(anomaly, None, open_config)
        ranked = rank_anomalies(anomalies, limit=open_config["guards"]["max_anomalies"],
                                config=open_config)
        for anomaly in ranked:
            anomaly.peer_check = "sufficient" if len(peers) >= 3 else "insufficient"
        self._emit("SCAN", "completed" if ranked else "skipped",
                   "ranked rule anomalies" if ranked else "no rule anomaly met configured thresholds",
                   {"anomalies": len(anomalies), "ranked": len(ranked),
                    "masked_quarters": len(breaks), "jump_candidates": len(jump_candidates)}, started)

        hypotheses = deterministic_hypotheses([item.model_dump() for item in ranked],
                                              frame.to_string() if not frame.empty else "")
        if not ranked:
            base = hypotheses[0]
            hypotheses.extend(base.model_copy(update={"id": f"H0-{index}",
                                                      "mechanism": "No detector-backed candidate survived."})
                              for index in (1, 2))
        self._emit("HYPOTHESIZE", "completed", "deterministic evidence-bound hypothesis mode",
                   {"hypotheses": len(hypotheses), "anomaly_inputs": len(ranked)}, started)
        candidate_results = []
        for attempt, candidate in enumerate(hypotheses[:open_config["guards"]["max_anomalies"]]):
            if time.monotonic() - started > self.wall_clock_seconds:
                self._emit("HYPOTHESIZE", "stopped", "wall-clock budget exhausted",
                           {"evaluated": len(candidate_results)}, started)
                break
            hypothesis = candidate
            investigation = investigate(hypothesis, facts, documents, evidence_budget=20)
            claim_id = f"{run_id}-{hypothesis.id}"
            self.store.insert_claim(Claim(claim_id=claim_id, run_id=run_id,
                                          text=hypothesis.statement, claim_type="hypothesis",
                                          hypothesis_id=hypothesis.id))
            for item in investigation.evidence:
                if item.fact_id:
                    self.store.insert_claim_evidence(
                        ClaimEvidence(claim_id=claim_id, fact_id=item.fact_id,
                                      doc_id=item.doc_id, role=item.role))
            self._emit("INVESTIGATE", "completed", "searched stored document corpus",
                       {"evidence": len(investigation.evidence), "attempt": attempt + 1}, started)
            low_confidence = any(f.confidence < 0.6 or f.restated
                                 for f in facts if f.fact_id in hypothesis.fact_ids)
            redteam = red_team(hypothesis, [item.model_dump() for item in investigation.evidence],
                               non_comparable=bool(set(hypothesis.fact_ids) and breaks),
                               peer_pattern=len(peers) >= 3, low_confidence=low_confidence)
            self._emit("REDTEAM", redteam.verdict, redteam.strongest_counterargument,
                       {"attempt": attempt + 1, "checks": len(redteam.checks)}, started)
            evidence_facts = [item for item in facts if item.fact_id in hypothesis.fact_ids]
            evidence_doc_ids = {item.doc_id for item in investigation.evidence}
            source_types = len({doc.source_type for doc in documents if doc.doc_id in evidence_doc_ids})
            primary = any(doc.source_type.value in {"exchange", "rbi", "manual"}
                          for doc in documents if doc.doc_id in evidence_doc_ids)
            anomaly = next((item for item in ranked if item.rule_id == candidate.id.removeprefix("H-")), None)
            final_grade = grade(len(evidence_doc_ids), source_types,
                                anomaly.persistence_quarters if anomaly else 0,
                                len(peers) >= 3, primary, redteam.verdict == "weakened",
                                not evidence_facts or any(f.confidence < 0.6 for f in evidence_facts),
                                bool(breaks), anomaly.stability == "pass" if anomaly else False,
                                len(anomaly.agreed_detectors) >= 2 if anomaly else False)
            candidate_results.append((candidate, investigation, redteam, final_grade, anomaly))
        if not candidate_results:
            fallback = deterministic_hypotheses([], "")[0]
            investigation = investigate(fallback, facts, documents, evidence_budget=20)
            redteam = red_team(fallback, [])
            final_grade = grade(0, 0, 0, False, False, True, True, False)
            hypothesis = fallback
            chosen = (fallback, investigation, redteam, final_grade, None)
        else:
            rank = {"survives": 2, "weakened": 1, "refuted": 0}
            chosen = max(candidate_results,
                         key=lambda item: (rank[item[2].verdict], item[3].total,
                                            item[4].novelty if item[4] else 0,
                                            item[4].stability == "pass" if item[4] else False))
            hypothesis, investigation, redteam, final_grade, _chosen_anomaly = chosen
        evidence_facts = [item for item in facts if item.fact_id in hypothesis.fact_ids]
        also_considered = [{"hypothesis": item[0].id, "grade": item[3].label,
                            "reason": item[2].strongest_counterargument}
                           for item in candidate_results if item[0].id != hypothesis.id]
        self._emit("GRADE", "completed", final_grade.label,
                   {"score": final_grade.total, "evidence_facts": len(evidence_facts)}, started)
        report = render_report(hypothesis.statement, investigation.evidence,
                               investigation.timeline, redteam.strongest_counterargument,
                               redteam.falsification_condition, final_grade,
                               [item.model_dump() for item in ranked],
                               hypothesis.novelty_rationale, also_considered,
                               metric_errors + rule_errors)
        self._emit("RENDER", "completed", "report rendered with evidence filter",
                   {"evidence": len(report.evidence), "anomalies": len(report.anomalies)}, started)
        self.store.connection.execute("UPDATE runs SET status=?, log_json=? WHERE run_id=?",
                                      ("completed", json.dumps(self.events), run_id))
        self.store.connection.commit()
        return PipelineResult(report, self.events)
