# Capturing public endpoints

Configured collection is intentionally disabled until an endpoint is verified.

1. Open the public site in a browser and open DevTools.
2. Select **Network**, then **Fetch/XHR**, and perform the public search or filing
   action.
3. Inspect the request URL, method, query parameters, response format, and JSON
   fields. Verify it succeeds without an account.
4. Copy only the URL pattern, non-sensitive query parameters, required non-secret
   headers, and JSON paths into `config/sources.yaml`.
5. Run the collector against a test ticker and document the observed response shape.

Never paste cookies, authorization headers, API keys, bearer tokens, personal data,
or browser session identifiers. The collector accepts only HTTPS allowlisted domains,
uses the existing SSRF and response-size guards, and records a `source_gap` instead
of guessing when a configured source fails. The checked-in configuration contains
no endpoints, so collection currently reports “no sources configured”.
