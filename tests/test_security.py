"""SYNTHETIC security fixtures; no real credentials or external data."""
import logging

import pytest

from agent.security import RedactionFilter, SafeHTTP, safe_path, scan_text


def test_key_redaction(caplog):
    logger = logging.getLogger("synthetic-security")
    logger.addFilter(RedactionFilter())
    fake_key = "FAKE_" + "SYNTHETIC_" + "TOKEN_123456"
    with caplog.at_level(logging.INFO):
        logger.info("Authorization: Bearer %s", fake_key)
    assert fake_key not in caplog.text
    assert "[REDACTED]" in caplog.text
    logger.removeFilter(logger.filters[-1])


def test_path_traversal_block(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    with pytest.raises(ValueError):
        safe_path(root / ".." / "outside", root)


def test_safe_http_rejects_non_allowlisted_and_non_https():
    client = SafeHTTP({"example.com"})
    with pytest.raises(ValueError):
        client.get("http://example.com/")
    with pytest.raises(ValueError):
        client.get("https://127.0.0.1/")


def test_git_ref_is_not_secret():
    assert scan_text("synthetic-history",
                     "HamsiniChowdary006/copilot/fix-failing-github-actions-job") == []
