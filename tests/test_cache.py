from pathlib import Path

from agent.collector.base import Cache


def test_cache_hit_avoids_second_request(tmp_path, monkeypatch):
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        return b"public filing"

    monkeypatch.setattr("agent.collector.base.SafeHTTP.get", lambda self, url: fake_get(url))
    cache = Cache(tmp_path, allowed_domains={"example.com"})
    first, digest = cache.download("https://example.com/filing.pdf", "T")
    second, second_digest = cache.download("https://example.com/filing.pdf", "T")
    assert first == second
    assert digest == second_digest
    assert calls == ["https://example.com/filing.pdf"]
    assert Path(first).read_bytes() == b"public filing"
