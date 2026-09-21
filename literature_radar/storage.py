from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path

from literature_radar.models import Paper, PaperAnalysis
from literature_radar.identity import normalize_doi, publication_kind
from literature_radar.backup import snapshot, SCHEMA_VERSION


LIBRARY_SORTS = {
    "recommended": "favorite DESC, score DESC, published DESC, id DESC",
    "published": "published DESC, id DESC",
    "added": "created_at DESC, id DESC",
    "score": "score DESC, published DESC, id DESC",
    "title": "title COLLATE NOCASE ASC, id ASC",
}


class PaperStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        version=0
        if self.db_path.exists():
            with self._connect() as check:
                version=check.execute('PRAGMA user_version').fetchone()[0]
                populated=check.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='papers'").fetchone()[0]
            if version>SCHEMA_VERSION:raise ValueError('Database requires a newer Paper Orbit version')
            if populated and version<SCHEMA_VERSION:
                snapshot(self.db_path,self.db_path.parent/'migration-backups','before-v1')
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS papers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL,
                    external_id TEXT NOT NULL,
                    doi TEXT,
                    title TEXT NOT NULL,
                    abstract TEXT,
                    authors_json TEXT,
                    url TEXT,
                    published TEXT,
                    journal TEXT,
                    score INTEGER NOT NULL DEFAULT 0,
                    tags_json TEXT,
                    analysis_json TEXT,
                    raw_json TEXT,
                    favorite INTEGER NOT NULL DEFAULT 0,
                    read_status TEXT NOT NULL DEFAULT 'new',
                    user_note TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(source, external_id)
                )
                """
            )
            self._ensure_user_columns(conn)
            columns={r['name'] for r in conn.execute('PRAGMA table_info(papers)')}
            if 'doi_key' not in columns:
                conn.execute("ALTER TABLE papers ADD COLUMN doi_key TEXT NOT NULL DEFAULT ''")
                for row in conn.execute('SELECT id,doi FROM papers').fetchall():
                    conn.execute('UPDATE papers SET doi_key=? WHERE id=?',(normalize_doi(row['doi']),row['id']))
            conn.execute('CREATE INDEX IF NOT EXISTS idx_papers_doi_key ON papers(doi_key)')
            conn.execute("CREATE TABLE IF NOT EXISTS paper_sources (source TEXT, external_id TEXT, paper_id INTEGER, url TEXT, PRIMARY KEY(source,external_id))")
            if version<SCHEMA_VERSION:conn.execute("INSERT OR IGNORE INTO paper_sources SELECT source,external_id,id,url FROM papers")
            conn.execute(f'PRAGMA user_version={SCHEMA_VERSION}')
            conn.execute("CREATE INDEX IF NOT EXISTS idx_papers_published ON papers(published)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_papers_score ON papers(score)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_papers_favorite ON papers(favorite)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_papers_read_status ON papers(read_status)")

    def upsert_paper(self, paper: Paper) -> None:
        now = datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds")
        analysis = {
            "provider": paper.analysis.provider,
            "score": paper.analysis.score,
            "tags": paper.analysis.tags,
            "summary": paper.analysis.summary,
            "detailed_summary": paper.analysis.detailed_summary,
            "method_clues": paper.analysis.method_clues,
            "data_task_clues": paper.analysis.data_task_clues,
            "method_flow": paper.analysis.method_flow,
            "follow_up_prompts": paper.analysis.follow_up_prompts,
            "evaluation": paper.analysis.evaluation,
            "why_read": paper.analysis.why_read,
            "rating_dimensions": paper.analysis.rating_dimensions,
            "rating_provenance": paper.analysis.rating_provenance,
            "publication_kind": "preprint" if paper.raw.get("type")=="preprint" else publication_kind(paper.source),
            "retraction_status": paper.raw.get("retraction_status", "retracted" if paper.raw.get("is_retracted") else "not_flagged_by_source" if "is_retracted" in paper.raw else "not_checked"),
        }
        with self._connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            source,external=paper.source,paper.external_id
            existing=conn.execute('SELECT id,source,external_id,analysis_json FROM papers WHERE source=? AND external_id=?',(source,external)).fetchone()
            doi_key=normalize_doi(paper.doi)
            if existing is None and doi_key:
                existing=conn.execute('SELECT id,source,external_id,analysis_json FROM papers WHERE doi_key=? ORDER BY id LIMIT 1',(doi_key,)).fetchone()
                if existing: source,external=existing['source'],existing['external_id']
            if existing:
                previous = json.loads(existing['analysis_json'] or '{}')
                if previous.get('retraction_status') in {'retracted', 'retraction_notice'}:
                    analysis['retraction_status'] = previous['retraction_status']
            conn.execute(
                """
                INSERT INTO papers (
                    source, external_id, doi, title, abstract, authors_json, url,
                    published, journal, score, tags_json, analysis_json, raw_json,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source, external_id) DO UPDATE SET
                    doi=excluded.doi,
                    title=excluded.title,
                    abstract=excluded.abstract,
                    authors_json=excluded.authors_json,
                    url=excluded.url,
                    published=excluded.published,
                    journal=excluded.journal,
                    score=excluded.score,
                    tags_json=excluded.tags_json,
                    analysis_json=excluded.analysis_json,
                    raw_json=excluded.raw_json,
                    updated_at=excluded.updated_at
                """,
                (
                    source,
                    external,
                    paper.doi,
                    paper.title,
                    paper.abstract,
                    json.dumps(paper.authors, ensure_ascii=False),
                    paper.url,
                    paper.published.isoformat() if paper.published else None,
                    paper.journal,
                    paper.analysis.score,
                    json.dumps(paper.analysis.tags, ensure_ascii=False),
                    json.dumps(analysis, ensure_ascii=False),
                    json.dumps(paper.raw, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            row=conn.execute('SELECT id FROM papers WHERE source=? AND external_id=?',(source,external)).fetchone()
            conn.execute('UPDATE papers SET doi_key=? WHERE id=?',(doi_key,row['id']))
            conn.execute('INSERT OR REPLACE INTO paper_sources VALUES (?,?,?,?)',(paper.source,paper.external_id,row['id'],paper.url))


    def list_recent(self, start_date: date, min_score: int = 0) -> list[Paper]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT source, external_id, doi, title, abstract, authors_json, url,
                       published, journal, analysis_json, raw_json
                FROM papers
                WHERE (published IS NULL OR published >= ?) AND score >= ?
                ORDER BY score DESC, published DESC, title ASC
                """,
                (start_date.isoformat(), min_score),
            ).fetchall()

        papers = []
        for row in rows:
            analysis_data = json.loads(row["analysis_json"] or "{}")
            published = date.fromisoformat(row["published"]) if row["published"] else None
            papers.append(
                Paper(
                    source=row["source"],
                    external_id=row["external_id"],
                    doi=row["doi"],
                    title=row["title"],
                    abstract=row["abstract"] or "",
                    authors=json.loads(row["authors_json"] or "[]"),
                    url=row["url"] or "",
                    published=published,
                    journal=row["journal"],
                    raw=json.loads(row["raw_json"] or "{}"),
                    analysis=PaperAnalysis(
                        score=int(analysis_data.get("score", 0)),
                        provider=analysis_data.get("provider", "heuristic"),
                        tags=list(analysis_data.get("tags", [])),
                        summary=analysis_data.get("summary", ""),
                        detailed_summary=analysis_data.get("detailed_summary", ""),
                        method_clues=list(analysis_data.get("method_clues", [])),
                        data_task_clues=list(analysis_data.get("data_task_clues", [])),
                        method_flow=list(analysis_data.get("method_flow", [])),
                        follow_up_prompts=list(analysis_data.get("follow_up_prompts", [])),
                        evaluation=analysis_data.get("evaluation", ""),
                        why_read=analysis_data.get("why_read", ""),
                        rating_dimensions=analysis_data.get("rating_dimensions", {}),
                        rating_provenance=analysis_data.get("rating_provenance", {}),
                    ),
                )
            )
        return papers

    def list_for_library(
        self,
        query: str = "",
        favorite: bool = False,
        status: str = "",
        min_score: int = 0,
        limit: int = 100,
        offset: int = 0,
        source: str = "",
        sort: str = "recommended",
    ) -> list[sqlite3.Row]:
        where, params = self._library_filters(query, favorite, status, min_score, source)
        params.extend([max(1, min(limit, 500)), max(0, offset)])
        order = LIBRARY_SORTS.get(sort, LIBRARY_SORTS["recommended"])
        with self._connect() as conn:
            return conn.execute(
                f"SELECT * FROM papers WHERE {where} ORDER BY {order} LIMIT ? OFFSET ?",
                params,
            ).fetchall()

    def count_for_library(
        self, query: str = "", favorite: bool = False, status: str = "",
        min_score: int = 0, source: str = "",
    ) -> int:
        where, params = self._library_filters(query, favorite, status, min_score, source)
        with self._connect() as conn:
            return conn.execute(f"SELECT COUNT(*) FROM papers WHERE {where}", params).fetchone()[0]

    def library_sources(self) -> list[str]:
        with self._connect() as conn:
            return [row[0] for row in conn.execute("SELECT DISTINCT source FROM papers ORDER BY source")]

    @staticmethod
    def _library_filters(
        query: str, favorite: bool, status: str, min_score: int, source: str,
    ) -> tuple[str, list[object]]:
        clauses = ["score >= ?"]
        params: list[object] = [min_score]
        fields = ("title", "abstract", "journal", "tags_json", "analysis_json",
                  "doi", "authors_json", "user_note")
        # Words can match different fields. LIKE wildcards are literal search text.
        for word in query.split():
            like = "%" + word.replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%"
            clauses.append("(" + " OR ".join(f"{field} LIKE ? ESCAPE '!'" for field in fields) + ")")
            params.extend([like] * len(fields))
        if favorite:
            clauses.append("favorite = 1")
        if status:
            clauses.append("read_status = ?")
            params.append(status)
        if source:
            clauses.append("source = ?")
            params.append(source)
        return " AND ".join(clauses), params

    def update_user_fields(
        self,
        paper_id: int,
        favorite: bool | None = None,
        read_status: str | None = None,
        user_note: str | None = None,
    ) -> None:
        allowed_status = {"new", "to_read", "reading", "read", "ignore", "reproduce"}
        updates = []
        params: list[object] = []
        if favorite is not None:
            updates.append("favorite = ?")
            params.append(1 if favorite else 0)
        if read_status is not None:
            if read_status not in allowed_status:
                raise ValueError(f"Invalid status: {read_status}")
            updates.append("read_status = ?")
            params.append(read_status)
        if user_note is not None:
            updates.append("user_note = ?")
            params.append(user_note)
        if not updates:
            return
        updates.append("updated_at = ?")
        params.append(datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds"))
        params.append(paper_id)

        with self._connect() as conn:
            result = conn.execute(f"UPDATE papers SET {', '.join(updates)} WHERE id = ?", params)
            if result.rowcount == 0:
                raise LookupError("Paper not found")

    def dashboard_stats(self) -> dict[str, int]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN favorite = 1 THEN 1 ELSE 0 END) AS favorites,
                    SUM(CASE WHEN read_status = 'to_read' THEN 1 ELSE 0 END) AS to_read,
                    SUM(CASE WHEN read_status = 'reproduce' THEN 1 ELSE 0 END) AS reproduce,
                    SUM(CASE WHEN score >= 18 THEN 1 ELSE 0 END) AS high_score
                FROM papers
                """
            ).fetchone()
        return {key: int(row[key] or 0) for key in row.keys()}

    def _ensure_user_columns(self, conn: sqlite3.Connection) -> None:
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(papers)").fetchall()}
        migrations = {
            "favorite": "ALTER TABLE papers ADD COLUMN favorite INTEGER NOT NULL DEFAULT 0",
            "read_status": "ALTER TABLE papers ADD COLUMN read_status TEXT NOT NULL DEFAULT 'new'",
            "user_note": "ALTER TABLE papers ADD COLUMN user_note TEXT NOT NULL DEFAULT ''",
        }
        for column, sql in migrations.items():
            if column not in existing:
                conn.execute(sql)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=15)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()
