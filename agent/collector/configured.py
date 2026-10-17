import json
import time
from datetime import date
from pathlib import Path
from urllib.parse import urlencode

import requests
import yaml

from agent.collector.base import Cache, Source
from agent.security import SafeHTTP
from schemas.models import CompanyProfile, DocRef, SourceType


def _json_value(payload: object, path: str | None) -> object:
    value = payload
    for part in (path or "").strip(".").split("."):
        if not part:
            continue
        if isinstance(value, dict):
            value = value.get(part)
        elif isinstance(value, list) and part.isdigit():
            value = value[int(part)]
        else:
            return None
    return value


class ConfiguredSource(Source):
    def __init__(self, config_path: str | Path = "config/sources.yaml",
                 cache: Cache | None = None, gap_store=None):
        self.path = Path(config_path)
        payload = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
        self.definitions = payload.get("sources", [])
        domains = {definition["domain"] for definition in self.definitions if definition.get("domain")}
        self.http = SafeHTTP(domains)
        self.cache = cache or Cache(allowed_domains=domains)
        self.gap_store = gap_store

    def search(self, profile: CompanyProfile) -> list[DocRef]:
        results: list[DocRef] = []
        for definition in self.definitions:
            try:
                base = definition["base_url"].rstrip("/")
                path = definition.get("path_pattern", "").format(
                    name=profile.name, symbol=profile.symbol or profile.name)
                query = {key: str(value).format(name=profile.name, symbol=profile.symbol or profile.name)
                         for key, value in definition.get("query_params", {}).items()}
                url = f"{base}/{path.lstrip('/')}"
                if query:
                    url = f"{url}?{urlencode(query)}"
                body = self.http.get(url)
                payload = json.loads(body) if definition.get("response_format") == "json" else {}
                items = payload if isinstance(payload, list) else (
                    _json_value(payload, definition.get("items_path")) or [payload])
                for item in items:
                    title = str(_json_value(item, definition.get("title_path")) or definition["name"])
                    href = _json_value(item, definition.get("url_path")) or url
                    published_raw = _json_value(item, definition.get("date_path"))
                    published = date.fromisoformat(str(published_raw)[:10]) if published_raw else None
                    results.append(DocRef(ticker=profile.symbol or profile.name,
                                          source_type=SourceType(definition.get("source_type", "search")),
                                          title=title, url=href, published=published))
            except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError,
                    requests.RequestException) as error:
                if self.gap_store:
                    self.gap_store.insert_source_gap(profile.symbol or profile.name,
                                                     definition.get("name", "configured"),
                                                     str(error), time.strftime("%Y-%m-%dT%H:%M:%SZ"))
        return results

    def fetch(self, doc: DocRef) -> Path:
        if not doc.url:
            raise ValueError("configured document has no URL")
        path, _ = self.cache.download(str(doc.url), doc.ticker)
        return path
