# Data sources

## Verification status (2026-10-16)

Live checks from this environment used browser-like headers and a 30 second timeout:

* `https://www.bseindia.com/` returned HTTP 200 (`text/html`, 14,287 bytes). This verifies
  only the public landing page, not a filing/search API. No filing endpoint was enabled.
* `https://www.nseindia.com/` returned HTTP 403 Forbidden during homepage warm-up. After
  that failed warm-up, an explicitly requested `https://www.nseindia.com/api/allIndices`
  request with the warmed session, browser-like headers, and a one-second delay returned
  HTTP 200 JSON beginning `{"data":[{"key":"INDICES ELIGIBLE IN DERIVATIVES"...}`.
  This verifies only that index route and response shape; NSE filing/search routes remain
  **UNVERIFIED** and the homepage is blocked by bot protection in this environment.
* `https://www.crisil.com/` returned HTTP 200 (`text/html`, 171,270 bytes). This verifies
  only the rating-agency landing page; rating-search endpoints remain **UNVERIFIED**.

No quarterly-results, investor-presentation, transcript, annual-report, or symbol-search
endpoint is claimed as verified. The exchange adapter accepts an explicitly configured URL
and refuses to invent one. This is deliberate: endpoint paths, authentication headers, and
response shapes vary and must be checked with a real request before being enabled.

The P0-a3 prompt did not contain the promised captured BSE request block: it contained the
literal placeholder `[PASTE the captured URLs, headers and a sample JSON response here]`.
Consequently only the BSE landing page is verified; quarterly results, announcements, annual
reports, and BSE symbol-search endpoints remain **UNVERIFIED** pending those concrete captures.

The verified local source is `store/manual_drop/`: files are discovered locally and are not
network calls. Remote downloads, when supplied through a verified `DocRef`, use a clear
User-Agent, approximately one request per host per second, SHA-256 caching, and HTTP errors.

Before enabling an exchange source, record the exact URL pattern, parameters, response shape,
limits, and verification date here.

## Manual drop

Put public filings under `store/manual_drop/{ticker}/`. Supported extensions are `.pdf`,
`.html`, `.htm`, and `.xlsx`; filenames are retained as document titles. The deterministic
extractor reads PDF text, the first HTML table, or all XLSX sheets and stores only facts whose
quote appears verbatim in the source text. Unsupported or unreadable files are reported as
rejected rather than treated as empty coverage.
