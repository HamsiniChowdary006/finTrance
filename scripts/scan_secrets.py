"""Scan working-tree text and git history for likely credentials."""
import math
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_PARTS = {".git", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache"}
PATTERNS = [
    re.compile(r"(?i)\b(?:api[_-]?key|secret|token|password)\s*[:=]\s*['\"]?[A-Za-z0-9_\-/.+=]{12,}"),
    re.compile(r"\bsk-[A-Za-z0-9]{16,}\b"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-+=]{16,}"),
    re.compile(r"-----BEGIN (?:RSA|OPENSSH|EC|PGP) PRIVATE KEY-----"),
]


def entropy(value: str) -> float:
    counts = {char: value.count(char) for char in set(value)}
    return -sum((count / len(value)) * math.log2(count / len(value))
                for count in counts.values())


def scan_text(label: str, text: str) -> list[str]:
    findings = [f"{label}: credential pattern {pattern.pattern[:40]}"
                for pattern in PATTERNS if pattern.search(text)]
    for token in re.findall(r"\b[A-Za-z0-9+/=_\-]{32,}\b", text):
        if entropy(token) >= 4.2 and not token.startswith(("SYNTHETIC", "sha")):
            findings.append(f"{label}: high-entropy token detected (length={len(token)})")
    return findings


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
                             capture_output=True, text=True, check=True)
    findings.extend(scan_text("git-history", history.stdout))
    if findings:
        print("\n".join(sorted(set(findings))))
        return 1
    print("no likely secrets found in working tree or git history")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
