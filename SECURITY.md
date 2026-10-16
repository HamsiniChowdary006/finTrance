# Security

* Credentials are read only from environment variables or a local `.env` file and are never
  written to cache, SQLite, logs, prompts, or serialized outputs. `.env` is ignored; commit
  only `.env.example` with placeholders.
* Rotate any exposed credential immediately at its provider, then inspect history. History
  rewriting with `git filter-repo` requires explicit operator approval and is not automatic.
* Network access is HTTPS-only, allowlisted, timeout-bounded, size-bounded, redirect-limited,
  and rejects private/loopback destinations.
* Manual files and cache paths must remain inside their configured roots. Documents are
  untrusted evidence, not instructions.
* Before every push:
  1. `pytest`
  2. `ruff check .`
  3. `python scripts/check_no_company_names.py`
  4. `python scripts/scan_secrets.py`
  5. `git diff --check && git ls-files`
