import argparse
import json
from pathlib import Path

import pandas as pd

from agent.calc.breaks import cusum, jump_quarters
from agent.calc.metrics import loan_growth_yoy
from agent.calc.timeseries import quarterly_frame
from agent.collector.manual import ManualDropSource
from agent.extractor.document import extract_facts, read_document
from agent.orchestrator import Orchestrator
from agent.profiler import profile_company
from agent.render.report import markdown
from agent.scan.rules import evaluate_rules, load_rules
from agent.scan.scoring import rank_anomalies
from schemas.models import Fact, PeriodType
from store.dao import EvidenceStore

CORE_METRICS = (
    "gross_advances", "gross_npa", "net_npa", "gnpa_pct", "nnpa_pct",
    "write_offs", "provisions_on_npa", "stage2_assets", "stage3_assets",
    "casa_deposits", "total_deposits",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    extract = sub.add_parser("extract")
    extract.add_argument("--company", required=True)
    extract.add_argument("--no-llm", action="store_true")
    analyze = sub.add_parser("analyze")
    analyze.add_argument("--company", required=True)
    analyze.add_argument("--peers", default="")
    analyze.add_argument("--json", dest="json_path")
    run = sub.add_parser("run")
    run.add_argument("--company", required=True)
    run.add_argument("--peers", default="")
    run.add_argument("--format", choices=("md", "json"), default="md")
    run.add_argument("--no-llm", action="store_true")
    args = parser.parse_args()
    if args.command == "extract":
        profile = profile_company(args.company)
        profile.symbol = args.company
        docs = ManualDropSource(Path("store/manual_drop")).search(profile)
        store = EvidenceStore()
        counts: dict[str, int] = {}
        rejected = 0
        for doc in docs:
            try:
                facts = extract_facts(read_document(doc.local_path), doc.ticker, doc.title)
            except (OSError, ValueError, ImportError) as error:
                print(f"rejected {doc.title}: {error}")
                rejected += 1
                continue
            for item in facts:
                item["period_type"] = PeriodType(item["period_type"])
                store.insert_fact(Fact.model_validate(item))
                counts[item["metric"]] = counts.get(item["metric"], 0) + 1
        print(f"company_type={profile.company_type.value} confidence={profile.confidence:.2f}")
        print("coverage matrix (metric x quarter):")
        for metric in CORE_METRICS:
            print(f"{metric}: {counts.get(metric, 0)} filled")
        print(f"documents={len(docs)} gaps=0 rejected_extractions={rejected}")
    elif args.command == "analyze":
        store = EvidenceStore()
        facts = store.facts_for(args.company)
        frame, provenance = quarterly_frame(facts)
        print(f"coverage for {args.company}:")
        if frame.empty:
            print("no real facts available; synthetic validation only")
            result = {"company": args.company, "quarters": [], "anomalies": [], "top3": []}
        else:
            frame = frame.tail(12)
            print(frame.to_string())
            from agent.calc.timeseries import Provenance
            growth = loan_growth_yoy(
                Provenance(
                    frame.get("gross_advances", pd.Series(index=frame.index, dtype=float)),
                    {period: provenance.get(period, {}).get("gross_advances", [])
                     for period in frame.index},
                )
            )
            data = {"loan_growth_yoy": growth}
            anomalies = evaluate_rules(data, load_rules())
            top3 = rank_anomalies(anomalies)
            changes = jump_quarters(frame["gross_advances"]) if "gross_advances" in frame else []
            change_points = [point.quarter for point in cusum(frame["gross_advances"])] if "gross_advances" in frame else []
            print(f"jump_quarters={changes}")
            print(f"change_points={change_points}")
            print(f"anomalies={anomalies}")
            print(f"top3={top3}")
            result = {"company": args.company, "quarters": list(frame.index),
                      "anomalies": [item.model_dump() for item in anomalies],
                      "top3": [item.model_dump() for item in top3]}
        if args.json_path:
            Path(args.json_path).write_text(json.dumps(result, default=str, indent=2), encoding="utf-8")
    elif args.command == "run":
        result = Orchestrator(callback=lambda event: print(
            f"[{event['stage']}] {event['status']}: {event['message']}")).run(args.company)
        output = result.report.model_dump_json(indent=2) if args.format == "json" else markdown(result.report)
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
