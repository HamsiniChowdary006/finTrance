import json
import sqlite3
from pathlib import Path

from schemas.models import Claim, ClaimEvidence, Document, Event, Fact, Run

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
 doc_id TEXT PRIMARY KEY, ticker TEXT NOT NULL, source_type TEXT NOT NULL,
 title TEXT NOT NULL, url TEXT, published TEXT, sha256 TEXT NOT NULL, local_path TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS facts (
 fact_id TEXT PRIMARY KEY, ticker TEXT NOT NULL, metric TEXT NOT NULL, value REAL NOT NULL,
 unit TEXT NOT NULL, period TEXT NOT NULL, period_type TEXT NOT NULL, doc_id TEXT NOT NULL,
 page INTEGER NOT NULL, quote TEXT NOT NULL, extractor TEXT NOT NULL,
 confidence REAL NOT NULL, restated INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS claims (
 claim_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, text TEXT NOT NULL,
 claim_type TEXT NOT NULL, hypothesis_id TEXT
);
CREATE TABLE IF NOT EXISTS claim_evidence (
 claim_id TEXT NOT NULL, fact_id TEXT NOT NULL, doc_id TEXT NOT NULL,
 role TEXT NOT NULL CHECK(role IN ('supports','contradicts','context')),
 PRIMARY KEY (claim_id, fact_id, doc_id)
);
CREATE TABLE IF NOT EXISTS runs (
 run_id TEXT PRIMARY KEY, ticker TEXT NOT NULL, started TEXT NOT NULL,
 status TEXT NOT NULL, log_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS source_gaps (
 gap_id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT NOT NULL, source TEXT NOT NULL,
 reason TEXT NOT NULL, created TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
 event_id TEXT PRIMARY KEY, ticker TEXT NOT NULL, doc_id TEXT NOT NULL,
 title TEXT NOT NULL, period TEXT, page INTEGER NOT NULL, quote TEXT NOT NULL
);
"""


class EvidenceStore:
    def __init__(self, path: str | Path = "store/evidence.sqlite") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(SCHEMA)
        self.connection.commit()

    def insert_document(self, document: Document) -> None:
        self.connection.execute(
            "INSERT OR REPLACE INTO documents VALUES (?,?,?,?,?,?,?,?)",
            (document.doc_id, document.ticker, document.source_type.value, document.title,
             document.url, document.published.isoformat() if document.published else None,
             document.sha256, document.local_path),
        )
        self.connection.commit()

    def insert_fact(self, fact: Fact) -> None:
        self.connection.execute(
            "INSERT OR REPLACE INTO facts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (fact.fact_id, fact.ticker, fact.metric, fact.value, fact.unit, fact.period,
             fact.period_type.value, fact.doc_id, fact.page, fact.quote, fact.extractor,
             fact.confidence, int(fact.restated)),
        )
        self.connection.commit()

    def insert_run(self, run: Run) -> None:
        self.connection.execute(
            "INSERT OR REPLACE INTO runs VALUES (?,?,?,?,?)",
            (run.run_id, run.ticker, run.started.isoformat(), run.status,
             json.dumps(run.log_json)),
        )
        self.connection.commit()

    def insert_claim(self, claim: Claim) -> None:
        self.connection.execute("INSERT OR REPLACE INTO claims VALUES (?,?,?,?,?)",
                                (claim.claim_id, claim.run_id, claim.text, claim.claim_type,
                                 claim.hypothesis_id))
        self.connection.commit()

    def insert_claim_evidence(self, evidence: ClaimEvidence) -> None:
        self.connection.execute("INSERT OR REPLACE INTO claim_evidence VALUES (?,?,?,?)",
                                (evidence.claim_id, evidence.fact_id, evidence.doc_id,
                                 evidence.role))
        self.connection.commit()

    def insert_source_gap(self, ticker: str, source: str, reason: str, created: str) -> None:
        self.connection.execute(
            "INSERT INTO source_gaps (ticker, source, reason, created) VALUES (?,?,?,?)",
            (ticker, source, reason, created),
        )
        self.connection.commit()

    def insert_event(self, event: Event) -> None:
        self.connection.execute(
            "INSERT OR REPLACE INTO events VALUES (?,?,?,?,?,?,?)",
            (event.event_id, event.ticker, event.doc_id, event.title, event.period,
             event.page, event.quote),
        )
        self.connection.commit()

    def delete_document_evidence(self, doc_id: str) -> None:
        self.connection.execute("DELETE FROM facts WHERE doc_id=?", (doc_id,))
        self.connection.execute("DELETE FROM events WHERE doc_id=?", (doc_id,))
        self.connection.commit()

    def events_for(self, ticker: str) -> list[Event]:
        rows = self.connection.execute(
            "SELECT * FROM events WHERE ticker=? ORDER BY page, event_id", (ticker,)
        ).fetchall()
        return [Event(event_id=row["event_id"], ticker=row["ticker"], doc_id=row["doc_id"],
                      title=row["title"], period=row["period"], page=row["page"],
                      quote=row["quote"]) for row in rows]

    def facts_for(self, ticker: str, metric: str | None = None) -> list[Fact]:
        query = "SELECT * FROM facts WHERE ticker = ?"
        params: list[str] = [ticker]
        if metric:
            query += " AND metric = ?"
            params.append(metric)
        rows = self.connection.execute(query, params).fetchall()
        return [Fact(fact_id=r["fact_id"], ticker=r["ticker"], metric=r["metric"],
                     value=r["value"], unit=r["unit"], period=r["period"],
                     period_type=r["period_type"], doc_id=r["doc_id"], page=r["page"],
                     quote=r["quote"], extractor=r["extractor"], confidence=r["confidence"],
                     restated=bool(r["restated"])) for r in rows]

    def documents_for(self, ticker: str) -> list[Document]:
        rows = self.connection.execute(
            "SELECT * FROM documents WHERE ticker = ? ORDER BY published, doc_id", (ticker,)
        ).fetchall()
        return [Document(doc_id=row["doc_id"], ticker=row["ticker"],
                         source_type=row["source_type"], title=row["title"], url=row["url"],
                         published=row["published"], sha256=row["sha256"],
                         local_path=row["local_path"]) for row in rows]

    def flag_restatements(self, ticker: str, metric: str, period: str) -> int:
        rows = self.connection.execute(
            "SELECT fact_id, value FROM facts WHERE ticker=? AND metric=? AND period=?",
            (ticker, metric, period),
        ).fetchall()
        if len({row["value"] for row in rows}) < 2:
            return 0
        self.connection.executemany("UPDATE facts SET restated=1 WHERE fact_id=?",
                                    [(row["fact_id"],) for row in rows])
        self.connection.commit()
        return len(rows)

    def close(self) -> None:
        self.connection.close()
