"""One-command local launcher for the evidence dashboard."""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib
import os
import platform
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
MANUAL_ROOT = REPO_ROOT / "store" / "manual_drop"
OUT_ROOT = REPO_ROOT / "out"
REQUIRED_IMPORTS = ("pydantic", "pandas", "fitz", "pdfplumber", "requests", "yaml", "streamlit")
CORE_METRICS = ("gross_advances", "gross_npa", "gnpa_pct", "stage3_assets")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Run finTrance locally.")
    result.add_argument("--company")
    result.add_argument("--ticker")
    result.add_argument("--peers", default="")
    result.add_argument("--all", action="store_true")
    result.add_argument("--reingest", action="store_true")
    result.add_argument("--no-app", action="store_true")
    result.add_argument("--check", action="store_true")
    result.add_argument("--synthetic", action="store_true")
    result.add_argument("--dry-run", action="store_true")
    result.add_argument("--port", type=int, default=8501)
    result.add_argument("--time-budget", type=float, default=120)
    result.add_argument("--verbose", action="store_true")
    return result


def is_venv() -> bool:
    return sys.prefix != sys.base_prefix or bool(os.environ.get("VIRTUAL_ENV"))


def dependencies_ready() -> bool:
    try:
        for name in REQUIRED_IMPORTS:
            importlib.import_module(name)
    except ImportError:
        return False
    return True


def preflight(dry_run: bool = False) -> None:
    if sys.version_info < (3, 11):  # noqa: UP036
        raise RuntimeError("Python 3.11 or newer is required.")
    print(f"Preflight: Python {platform.python_version()} on {platform.system()}.")
    if not is_venv():
        print("Warning: no virtual environment is active; continuing with the current interpreter.")
    if dry_run:
        print("Dry run: dependency installation and all filesystem writes are disabled.")
        return
    if not dependencies_ready():
        print("Installing project dependencies with pip install -e . ...")
        subprocess.run([sys.executable, "-m", "pip", "install", "-e", str(REPO_ROOT)],
                       cwd=REPO_ROOT, check=True)
    else:
        print("Dependencies already available; skipping installation.")


def load_environment() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv(REPO_ROOT / ".env")
    except ImportError:
        pass
    if not any(os.environ.get(name) for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY")):
        os.environ["FINTRANCE_NO_LLM"] = "1"
        print("No LLM key configured; using --no-llm deterministic mode.")


def discover_folders() -> list[str]:
    if not MANUAL_ROOT.exists():
        return []
    return sorted(path.name for path in MANUAL_ROOT.iterdir() if path.is_dir())


def read_universe() -> dict[str, dict[str, object]]:
    path = REPO_ROOT / "data" / "universe.csv"
    if not path.exists():
        return {}
    output: dict[str, dict[str, object]] = {}
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            ticker = (row.get("ticker") or "").strip()
            if ticker:
                output[ticker] = {"name": row.get("name") or ticker,
                                  "type": row.get("type") or "other_fin",
                                  "peers": [item.strip() for item in (row.get("peers") or "").split(",")
                                            if item.strip()]}
    return output


def choose_companies(args: argparse.Namespace) -> list[tuple[str, str, list[str], str]]:
    universe = read_universe()
    folders = discover_folders()
    if args.ticker:
        tickers = [args.ticker]
    elif args.company and not args.all:
        tickers = [next((ticker for ticker, item in universe.items()
                         if item["name"] == args.company), args.company)]
    else:
        tickers = folders
    if not tickers:
        return []
    result = []
    for ticker in tickers:
        metadata = universe.get(ticker, {"name": ticker, "type": "other_fin", "peers": []})
        peers = [item.strip() for item in args.peers.split(",") if item.strip()] or metadata["peers"]
        if not peers:
            peers = [other for other in tickers if other != ticker
                     and universe.get(other, {}).get("type") == metadata["type"]]
        result.append((ticker, str(metadata["name"]), peers, str(metadata["type"])))
    return result


def coverage_summary(store, ticker: str) -> tuple[int, int, list[str]]:
    facts = store.facts_for(ticker)
    periods = sorted({fact.period for fact in facts})
    warnings = []
    for metric in CORE_METRICS:
        covered = {fact.period for fact in facts if fact.metric == metric}
        if len(covered) < 8:
            warnings.append(f"{metric} has {len(covered)} quarters; fewer than 8.")
    return len(facts), len(periods), warnings


def create_synthetic(store, ticker: str = "SYNTHETIC") -> None:
    from schemas.models import Document, Fact, PeriodType, SourceType
    document_id = hashlib.sha256(b"SYNTHETIC fixture document").hexdigest()[:16]
    store.insert_document(Document(doc_id=document_id, ticker=ticker, source_type=SourceType.MANUAL,
                                    title="SYNTHETIC fixture (not real data)", sha256=document_id,
                                    local_path="SYNTHETIC fixture (not a downloaded file)"))
    for index in range(12):
        period = f"Q{index % 4 + 1}FY{23 + index // 4}"
        advances = 1000 * (1.25 ** index)
        values = {"gross_advances": advances, "stage3_assets": advances * 0.08,
                  "gross_npa": advances * 0.08, "gnpa_pct": 8.0}
        for metric, value in values.items():
            fact_id = hashlib.sha256(f"SYNTHETIC:{metric}:{period}".encode()).hexdigest()[:16]
            store.insert_fact(Fact(fact_id=fact_id, ticker=ticker, metric=metric, value=value,
                                   unit="%" if metric == "gnpa_pct" else "INR crore",
                                   period=period, period_type=PeriodType.QUARTER,
                                   doc_id=document_id, page=1,
                                   quote=f"SYNTHETIC {metric} {value}", extractor="synthetic_fixture",
                                   confidence=1.0))


def run_company(ticker: str, name: str, peers: list[str], args: argparse.Namespace,
                synthetic: bool = False) -> dict[str, object]:
    from agent.ingest import coverage, ingest_company
    from agent.orchestrator import Orchestrator
    from agent.render.report import write_report
    from store.dao import EvidenceStore

    store = EvidenceStore()
    if synthetic:
        create_synthetic(store, ticker)
        ingest_result = {"documents": 1, "facts": len(store.facts_for(ticker))}
    else:
        ingest_result = ingest_company(ticker, MANUAL_ROOT, ticker, store, args.reingest)
        print(f"{ticker} coverage matrix:")
        for metric, periods in coverage(store, ticker).items():
            print(f"  {metric}: " + " ".join(period for period, filled in periods.items() if filled))
    facts, quarters, warnings = coverage_summary(store, ticker)
    if warnings:
        for warning in warnings:
            print(f"WARNING {ticker}: {warning}")
    started = time.monotonic()
    result = Orchestrator(store=store, wall_clock_seconds=args.time_budget).run(ticker, peers)
    target = OUT_ROOT / ticker
    target.mkdir(parents=True, exist_ok=True)
    write_report(result.report, target / "report.md", "md")
    write_report(result.report, target / "report.json", "json")
    (target / "run_log.json").write_text(
        __import__("json").dumps(result.events, indent=2), encoding="utf-8")
    return {"company": name, "ticker": ticker, "type": "synthetic" if synthetic else "configured",
            "facts": facts, "quarters": quarters, "discovery": result.report.discovery.splitlines()[0],
            "strength": result.report.evidence_strength.label, "runtime": time.monotonic() - started,
            "warnings": warnings, "ingest": ingest_result}


def free_port(start: int) -> int:
    port = start
    while True:
        with socket.socket() as sock:
            try:
                sock.bind(("127.0.0.1", port))
                return port
            except OSError:
                port += 1


def run_checks() -> int:
    commands = [
        [sys.executable, "-m", "pytest"],
        [sys.executable, "-m", "ruff", "check", "."],
        [sys.executable, "scripts/check_no_company_names.py"],
        [sys.executable, "scripts/scan_secrets.py"],
        [sys.executable, "scripts/check_artifacts.py"],
    ]
    for command in commands:
        print(f"CHECK: {' '.join(command[1:])}")
        completed = subprocess.run(command, cwd=REPO_ROOT, check=False)
        if completed.returncode:
            return completed.returncode
    return 0


def launch_app(port: int, synthetic: bool) -> int:
    selected_port = free_port(port)
    if selected_port != port:
        print(f"Port {port} is busy; using port {selected_port}.")
    environment = os.environ.copy()
    if synthetic:
        environment["FINTRANCE_SYNTHETIC"] = "1"
    process = subprocess.Popen([sys.executable, "-m", "streamlit", "run", "app/main.py",
                                "--server.headless", "true", "--server.port", str(selected_port)],
                               cwd=REPO_ROOT, env=environment)
    url = f"http://localhost:{selected_port}"
    print(f"Dashboard: {url} (Ctrl+C stops it)")
    webbrowser.open(url)
    try:
        return process.wait()
    except KeyboardInterrupt:
        print("Stopping dashboard...")
        process.terminate()
        try:
            return process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            return process.wait()


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.dry_run:
        print("Plan: preflight, discover manual-drop folders, ingest, run reports, launch dashboard.")
        return 0
    preflight()
    load_environment()
    if args.check:
        return run_checks()
    if args.synthetic and not discover_folders():
        companies = [("SYNTHETIC", "SYNTHETIC demo (not real data)", [], "synthetic")]
    else:
        companies = choose_companies(args)
    if not companies:
        print("No company folders found under store/manual_drop/. Download public filings and place")
        print("them in store/manual_drop/<ticker>/, then rerun; see README.md. Use --synthetic for demo.")
        return 1
    failures = []
    summaries = []
    for ticker, name, peers, _company_type in companies:
        try:
            summaries.append(run_company(ticker, name, peers, args, ticker == "SYNTHETIC"))
        except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
            failures.append((ticker, str(error)))
            print(f"ERROR {ticker}: {error}")
    print("\nSummary")
    for summary in summaries:
        print(f"{summary['company']} | {summary['type']} | facts={summary['facts']} | "
              f"quarters={summary['quarters']} | {summary['strength']} | {summary['discovery']} | "
              f"runtime={summary['runtime']:.2f}s | warnings={len(summary['warnings'])}")
    if failures:
        print("Failures:", failures)
        return 1
    if args.no_app:
        return 0
    return launch_app(args.port, args.synthetic)


if __name__ == "__main__":
    raise SystemExit(main())
