"""Scan working-tree text and git history for likely credentials."""
import subprocess
from pathlib import Path

from agent.security import scan_text

ROOT = Path(__file__).resolve().parents[1]
SKIP_PARTS = {".git", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache"}


def main() -> int:
    findings: list[str] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or any(part in SKIP_PARTS for part in path.parts):
            continue
        try:
            findings.extend(scan_text(str(path.relative_to(ROOT)), path.read_text(encoding="utf-8")))
        except (OSError, UnicodeDecodeError):
            continue
    history = subprocess.run(["git", "log", "-p", "--all", "--", "."], cwd=ROOT,
                             capture_output=True, check=True)
    findings.extend(scan_text("git-history", history.stdout.decode("utf-8", errors="replace")))
    if findings:
        print("\n".join(sorted(set(findings))))
        return 1
    print("no likely secrets found in working tree or git history")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
