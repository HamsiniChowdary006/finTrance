import argparse
import csv
import sys

METRICS = {
    "bank": ["gross_advances", "gross_npa", "net_npa", "gnpa_pct", "nnpa_pct",
             "provisions_on_npa", "slippages", "write_offs", "credit_cost",
             "casa_deposits", "total_deposits"],
    "nbfc": ["gross_advances", "gross_npa", "net_npa", "gnpa_pct", "nnpa_pct",
             "provisions_on_npa", "slippages", "write_offs", "credit_cost",
             "stage1_assets", "stage2_assets", "stage3_assets", "ecl_provisions"],
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--company", required=True)
    parser.add_argument("--type", choices=tuple(METRICS), default="bank")
    args = parser.parse_args()
    writer = csv.writer(sys.stdout)
    writer.writerow(["ticker", "metric", "period", "value", "unit", "source_file", "page", "quote"])
    for metric in METRICS[args.type]:
        writer.writerow([args.company, metric, "", "", "INR crore", "", "1", ""])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
