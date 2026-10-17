import re
from pathlib import Path

root = Path(__file__).resolve().parents[1]
names = {line.strip().casefold() for line in (root / "config/denylist.txt").read_text().splitlines()
         if line.strip()}
violations = []
for base in (root / "agent", root / "config"):
    for path in base.rglob("*"):
        if (path.is_file() and path.name != "denylist.txt"
                and path.suffix not in {".pyc", ".pyo"}
                and "__pycache__" not in path.parts):
            text = path.read_text(encoding="utf-8", errors="ignore").casefold()
            for name in names:
                if re.search(rf"\b{re.escape(name)}\b", text):
                    violations.append(f"{path.relative_to(root)} contains {name}")
if violations:
    raise SystemExit("\n".join(violations))
print("no company names found")
