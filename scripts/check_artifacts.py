import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
blocked_suffixes = {".pyc", ".sqlite", ".sqlite3", ".db", ".pem", ".key"}
blocked_parts = {"__pycache__", ".venv", ".pytest_cache", ".ruff_cache", "store/cache",
                 "store/manual_drop", "store/llm_cache"}
bad: list[str] = []
tracked = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True)
for item in tracked.stdout.splitlines():
    path = Path(item)
    normalized = str(path).replace("\\", "/")
    if path.suffix in blocked_suffixes or any(
            normalized == part or normalized.startswith(part + "/") for part in blocked_parts):
        bad.append(item)
    if (ROOT / path).is_file() and (ROOT / path).stat().st_size > 5 * 1024 * 1024:
        bad.append(f"{item} (over 5MB)")
if bad:
    print("\n".join(bad))
    raise SystemExit(1)
print("tracked artifact checks passed")
