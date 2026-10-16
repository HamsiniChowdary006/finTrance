from pathlib import Path

from agent.collector.base import Cache


def test_cache_hit_avoids_second_request(tmp_path, monkeypatch):
    calls = []

    class Response:
        content = b"public filing"

        def raise_for_status(self):
            return None

    def fake_get(url, **kwargs):
        calls.append(url)
        return Response()

    monkeypatch.setattr("agent.collector.base.requests.get", fake_get)
    cache = Cache(tmp_path)
    first, digest = cache.download("https://example.invalid/filing.pdf", "T")
    second, second_digest = cache.download("https://example.invalid/filing.pdf", "T")
    assert first == second
    assert digest == second_digest
    assert calls == ["https://example.invalid/filing.pdf"]
    assert Path(first).read_bytes() == b"public filing"
