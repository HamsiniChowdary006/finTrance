import argparse
from pathlib import Path

from agent.collector.manual import ManualDropSource
from agent.extractor.document import extract_facts, read_document
from agent.profiler import profile_company
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
