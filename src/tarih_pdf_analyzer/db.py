from __future__ import annotations

import csv
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .models import PdfDocument, TextChunk
from .schemas import BookMetadataGuess, BookReport, ChunkAnalysis, FigureSeed, JudgedDebateTopic


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS books (
    id BIGSERIAL PRIMARY KEY,
    file_path TEXT NOT NULL UNIQUE,
    file_sha256 CHAR(64) NOT NULL,
    title TEXT NOT NULL,
    author TEXT NOT NULL,
    year INTEGER,
    metadata_confidence NUMERIC(4,3) NOT NULL DEFAULT 0,
    metadata_status TEXT NOT NULL DEFAULT 'needs_review',
    pdf_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_books_file_sha256 ON books(file_sha256);
CREATE INDEX IF NOT EXISTS idx_books_metadata_status ON books(metadata_status);

CREATE TABLE IF NOT EXISTS pages (
    id BIGSERIAL PRIMARY KEY,
    book_id BIGINT NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    page_number INTEGER NOT NULL,
    text TEXT NOT NULL,
    token_count INTEGER NOT NULL,
    UNIQUE (book_id, page_number)
);

CREATE TABLE IF NOT EXISTS chunks (
    id BIGSERIAL PRIMARY KEY,
    book_id BIGINT NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    start_page INTEGER NOT NULL,
    end_page INTEGER NOT NULL,
    text TEXT NOT NULL,
    token_count INTEGER NOT NULL,
    page_numbers JSONB NOT NULL DEFAULT '[]'::jsonb,
    chunk_type TEXT NOT NULL DEFAULT 'source',
    UNIQUE (book_id, chunk_index)
);

ALTER TABLE chunks ADD COLUMN IF NOT EXISTS chunk_type TEXT NOT NULL DEFAULT 'source';
CREATE INDEX IF NOT EXISTS idx_chunks_chunk_type ON chunks(chunk_type);

CREATE TABLE IF NOT EXISTS analysis_runs (
    id BIGSERIAL PRIMARY KEY,
    book_id BIGINT NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    model TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    error TEXT
);

CREATE TABLE IF NOT EXISTS chunk_analyses (
    id BIGSERIAL PRIMARY KEY,
    chunk_id BIGINT NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
    run_id BIGINT NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
    summary TEXT NOT NULL,
    arguments JSONB NOT NULL DEFAULT '[]'::jsonb,
    people JSONB NOT NULL DEFAULT '[]'::jsonb,
    events JSONB NOT NULL DEFAULT '[]'::jsonb,
    periods JSONB NOT NULL DEFAULT '[]'::jsonb,
    concepts JSONB NOT NULL DEFAULT '[]'::jsonb,
    topics JSONB NOT NULL DEFAULT '[]'::jsonb,
    raw_response JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (chunk_id, run_id)
);

CREATE TABLE IF NOT EXISTS book_topics (
    id BIGSERIAL PRIMARY KEY,
    book_id BIGINT NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    run_id BIGINT NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    weight NUMERIC(6,3) NOT NULL,
    rationale TEXT NOT NULL,
    representative_pages JSONB NOT NULL DEFAULT '[]'::jsonb
);

CREATE TABLE IF NOT EXISTS book_summaries (
    id BIGSERIAL PRIMARY KEY,
    book_id BIGINT NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    run_id BIGINT NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
    detailed_summary TEXT NOT NULL,
    main_theses JSONB NOT NULL DEFAULT '[]'::jsonb,
    debate_map JSONB NOT NULL DEFAULT '[]'::jsonb,
    evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
    raw_response JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (book_id, run_id)
);

CREATE TABLE IF NOT EXISTS historical_figures (
    id BIGSERIAL PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    period TEXT,
    short_bio TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_historical_figures_name ON historical_figures(name);

CREATE TABLE IF NOT EXISTS figure_aliases (
    id BIGSERIAL PRIMARY KEY,
    figure_id BIGINT NOT NULL REFERENCES historical_figures(id) ON DELETE CASCADE,
    alias TEXT NOT NULL,
    UNIQUE (figure_id, alias)
);

CREATE INDEX IF NOT EXISTS idx_figure_aliases_alias ON figure_aliases(alias);

CREATE TABLE IF NOT EXISTS figure_mentions (
    id BIGSERIAL PRIMARY KEY,
    figure_id BIGINT NOT NULL REFERENCES historical_figures(id) ON DELETE CASCADE,
    book_id BIGINT NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    chunk_id BIGINT NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
    mention_text TEXT NOT NULL DEFAULT '',
    stance TEXT NOT NULL DEFAULT '',
    confidence NUMERIC(4,3) NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'manual',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (figure_id, chunk_id)
);

CREATE INDEX IF NOT EXISTS idx_figure_mentions_figure ON figure_mentions(figure_id);
CREATE INDEX IF NOT EXISTS idx_figure_mentions_chunk ON figure_mentions(chunk_id);

CREATE TABLE IF NOT EXISTS chat_sessions (
    id BIGSERIAL PRIMARY KEY,
    figure_id BIGINT REFERENCES historical_figures(id) ON DELETE SET NULL,
    title TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id BIGSERIAL PRIMARY KEY,
    session_id BIGINT NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    citations JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS topic_candidates (
    id BIGSERIAL PRIMARY KEY,
    chunk_id BIGINT NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
    topic_title TEXT NOT NULL,
    claim TEXT NOT NULL,
    people JSONB NOT NULL DEFAULT '[]'::jsonb,
    events JSONB NOT NULL DEFAULT '[]'::jsonb,
    periods JSONB NOT NULL DEFAULT '[]'::jsonb,
    evidence TEXT NOT NULL,
    confidence NUMERIC(5,4) NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_topic_candidates_chunk ON topic_candidates(chunk_id);
CREATE INDEX IF NOT EXISTS idx_topic_candidates_title ON topic_candidates(topic_title);

CREATE TABLE IF NOT EXISTS topic_judgements (
    id BIGSERIAL PRIMARY KEY,
    candidate_id BIGINT NOT NULL REFERENCES topic_candidates(id) ON DELETE CASCADE,
    approved BOOLEAN NOT NULL DEFAULT false,
    relevance_score NUMERIC(6,3) NOT NULL DEFAULT 0,
    evidence_score NUMERIC(6,3) NOT NULL DEFAULT 0,
    hallucination_risk NUMERIC(6,3) NOT NULL DEFAULT 0,
    debate_value NUMERIC(6,3) NOT NULL DEFAULT 0,
    action TEXT NOT NULL DEFAULT 'review',
    reason TEXT NOT NULL DEFAULT '',
    judge_model TEXT NOT NULL,
    raw_response JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_topic_judgements_candidate ON topic_judgements(candidate_id);
CREATE INDEX IF NOT EXISTS idx_topic_judgements_approved ON topic_judgements(approved);
CREATE INDEX IF NOT EXISTS idx_topic_judgements_scores
    ON topic_judgements(relevance_score DESC, evidence_score DESC, debate_value DESC);
"""

LEGACY_MIGRATION_SQL = """
ALTER TABLE IF EXISTS books
    ADD COLUMN IF NOT EXISTS file_path TEXT;
ALTER TABLE IF EXISTS books
    ADD COLUMN IF NOT EXISTS file_sha256 CHAR(64) NOT NULL
    DEFAULT '0000000000000000000000000000000000000000000000000000000000000000';
ALTER TABLE IF EXISTS books
    ADD COLUMN IF NOT EXISTS author TEXT NOT NULL DEFAULT 'Bilinmeyen';
ALTER TABLE IF EXISTS books
    ADD COLUMN IF NOT EXISTS year INTEGER;
ALTER TABLE IF EXISTS books
    ADD COLUMN IF NOT EXISTS metadata_confidence NUMERIC(4,3) NOT NULL DEFAULT 0;
ALTER TABLE IF EXISTS books
    ADD COLUMN IF NOT EXISTS metadata_status TEXT NOT NULL DEFAULT 'needs_review';
ALTER TABLE IF EXISTS books
    ADD COLUMN IF NOT EXISTS pdf_metadata JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE IF EXISTS books
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now();
ALTER TABLE IF EXISTS books
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

DO $$
BEGIN
    IF to_regclass('public.books') IS NOT NULL THEN
        IF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'books' AND column_name = 'pdf_path'
        ) THEN
            EXECUTE 'ALTER TABLE books ALTER COLUMN pdf_path DROP NOT NULL';
            EXECUTE 'UPDATE books SET file_path = pdf_path WHERE file_path IS NULL AND pdf_path IS NOT NULL';
        END IF;
        IF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'books' AND column_name = 'sha256'
        ) THEN
            EXECUTE 'UPDATE books SET file_sha256 = sha256 WHERE sha256 IS NOT NULL';
        END IF;
        IF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'books' AND column_name = 'publish_year'
        ) THEN
            EXECUTE 'UPDATE books SET year = publish_year WHERE year IS NULL AND publish_year IS NOT NULL';
        END IF;
        IF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'books' AND column_name = 'author_id'
        ) THEN
            EXECUTE 'UPDATE books SET author = author_id::text WHERE author = ''Bilinmeyen'' AND author_id IS NOT NULL';
        END IF;
    END IF;
END $$;

UPDATE books
SET file_path = 'legacy-book-' || id::text
WHERE file_path IS NULL OR file_path = '';

WITH ranked AS (
    SELECT id, row_number() OVER (PARTITION BY file_path ORDER BY id) AS rn
    FROM books
)
UPDATE books b
SET file_path = b.file_path || '#' || b.id::text
FROM ranked r
WHERE b.id = r.id AND r.rn > 1;

ALTER TABLE IF EXISTS books
    ALTER COLUMN file_path SET NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_books_file_path_unique ON books(file_path);

ALTER TABLE IF EXISTS pages
    ADD COLUMN IF NOT EXISTS token_count INTEGER NOT NULL DEFAULT 1;

ALTER TABLE IF EXISTS chunks
    ADD COLUMN IF NOT EXISTS book_id BIGINT;
ALTER TABLE IF EXISTS chunks
    ADD COLUMN IF NOT EXISTS start_page INTEGER NOT NULL DEFAULT 1;
ALTER TABLE IF EXISTS chunks
    ADD COLUMN IF NOT EXISTS end_page INTEGER NOT NULL DEFAULT 1;
ALTER TABLE IF EXISTS chunks
    ADD COLUMN IF NOT EXISTS text TEXT NOT NULL DEFAULT '';
ALTER TABLE IF EXISTS chunks
    ADD COLUMN IF NOT EXISTS token_count INTEGER NOT NULL DEFAULT 1;
ALTER TABLE IF EXISTS chunks
    ADD COLUMN IF NOT EXISTS page_numbers JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE IF EXISTS chunks
    ADD COLUMN IF NOT EXISTS chunk_type TEXT NOT NULL DEFAULT 'source';

DO $$
BEGIN
    IF to_regclass('public.chunks') IS NOT NULL
       AND EXISTS (
           SELECT 1 FROM information_schema.columns
           WHERE table_schema = 'public' AND table_name = 'chunks' AND column_name = 'page_id'
       ) THEN
        EXECUTE '
            UPDATE chunks c
            SET book_id = COALESCE(c.book_id, p.book_id),
                start_page = p.page_number,
                end_page = p.page_number,
                page_numbers = jsonb_build_array(p.page_number)
            FROM pages p
            WHERE c.page_id = p.id
              AND (c.book_id IS NULL OR c.page_numbers = ''[]''::jsonb)
        ';
    END IF;

    IF to_regclass('public.chunks') IS NOT NULL
       AND EXISTS (
           SELECT 1 FROM information_schema.columns
           WHERE table_schema = 'public' AND table_name = 'chunks' AND column_name = 'chunk_text'
       ) THEN
        EXECUTE 'ALTER TABLE chunks ALTER COLUMN chunk_text DROP NOT NULL';
        EXECUTE 'UPDATE chunks SET text = chunk_text WHERE text = '''' AND chunk_text IS NOT NULL';
    END IF;
END $$;

ALTER TABLE IF EXISTS historical_figures
    ADD COLUMN IF NOT EXISTS slug TEXT;
ALTER TABLE IF EXISTS historical_figures
    ADD COLUMN IF NOT EXISTS name TEXT;
ALTER TABLE IF EXISTS historical_figures
    ADD COLUMN IF NOT EXISTS period TEXT;
ALTER TABLE IF EXISTS historical_figures
    ADD COLUMN IF NOT EXISTS short_bio TEXT NOT NULL DEFAULT '';
ALTER TABLE IF EXISTS historical_figures
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now();
ALTER TABLE IF EXISTS historical_figures
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

DO $$
BEGIN
    IF to_regclass('public.historical_figures') IS NOT NULL THEN
        IF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'historical_figures' AND column_name = 'full_name'
        ) THEN
            EXECUTE 'ALTER TABLE historical_figures ALTER COLUMN full_name DROP NOT NULL';
            EXECUTE 'UPDATE historical_figures SET name = full_name WHERE name IS NULL AND full_name IS NOT NULL';
        END IF;
        IF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'historical_figures' AND column_name = 'description'
        ) THEN
            EXECUTE 'ALTER TABLE historical_figures ALTER COLUMN description DROP NOT NULL';
            EXECUTE 'UPDATE historical_figures SET short_bio = description WHERE short_bio = '''' AND description IS NOT NULL';
        END IF;
    END IF;
END $$;

UPDATE historical_figures
SET name = 'figure-' || id::text
WHERE name IS NULL OR name = '';

UPDATE historical_figures
SET slug = lower(regexp_replace(name, '[^a-zA-Z0-9]+', '-', 'g'))
WHERE slug IS NULL OR slug = '';

WITH ranked AS (
    SELECT id, row_number() OVER (PARTITION BY slug ORDER BY id) AS rn
    FROM historical_figures
)
UPDATE historical_figures f
SET slug = f.slug || '-' || f.id::text
FROM ranked r
WHERE f.id = r.id AND r.rn > 1;

ALTER TABLE IF EXISTS historical_figures
    ALTER COLUMN slug SET NOT NULL;
ALTER TABLE IF EXISTS historical_figures
    ALTER COLUMN name SET NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_historical_figures_slug_unique ON historical_figures(slug);
"""


def _json(value: Any) -> Any:
    from psycopg.types.json import Jsonb  # type: ignore[import-not-found]

    return Jsonb(value)


class Database:
    def __init__(self, url: str) -> None:
        self.url = url

    @contextmanager
    def connect(self) -> Iterator[Any]:
        try:
            import psycopg  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError("psycopg is required. Install with: pip install 'psycopg[binary]'") from exc
        with psycopg.connect(self.url, connect_timeout=5) as connection:
            yield connection

    def init_schema(self) -> None:
        with self.connect() as connection:
            connection.execute(LEGACY_MIGRATION_SQL)
            connection.execute(SCHEMA_SQL)

    def upsert_book(
        self,
        document: PdfDocument,
        metadata: BookMetadataGuess,
        metadata_status: str,
        force_update: bool = False,
    ) -> tuple[int, bool]:
        with self.connect() as connection:
            existing = connection.execute(
                "SELECT id, file_sha256 FROM books WHERE file_path = %s",
                (str(document.path),),
            ).fetchone()
            if existing and existing[1] == document.sha256 and not force_update:
                return int(existing[0]), False

            row = connection.execute(
                """
                INSERT INTO books (
                    file_path, file_sha256, title, author, year,
                    metadata_confidence, metadata_status, pdf_metadata
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (file_path) DO UPDATE SET
                    file_sha256 = EXCLUDED.file_sha256,
                    title = EXCLUDED.title,
                    author = EXCLUDED.author,
                    year = EXCLUDED.year,
                    metadata_confidence = EXCLUDED.metadata_confidence,
                    metadata_status = EXCLUDED.metadata_status,
                    pdf_metadata = EXCLUDED.pdf_metadata,
                    updated_at = now()
                RETURNING id
                """,
                (
                    str(document.path),
                    document.sha256,
                    metadata.title,
                    metadata.author,
                    metadata.year,
                    metadata.confidence,
                    metadata_status,
                    _json(document.metadata),
                ),
            ).fetchone()
            return int(row[0]), True

    def replace_pages_and_chunks(
        self,
        book_id: int,
        document: PdfDocument,
        chunks: list[TextChunk],
    ) -> None:
        from .chunking import estimate_tokens

        with self.connect() as connection:
            connection.execute("DELETE FROM pages WHERE book_id = %s", (book_id,))
            connection.execute("DELETE FROM chunks WHERE book_id = %s", (book_id,))
            for page in document.pages:
                connection.execute(
                    """
                    INSERT INTO pages (book_id, page_number, text, token_count)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (book_id, page.page_number, page.text, estimate_tokens(page.text)),
                )
            for chunk in chunks:
                connection.execute(
                    """
                    INSERT INTO chunks (
                        book_id, chunk_index, start_page, end_page, text, token_count, page_numbers, chunk_type
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        book_id,
                        chunk.chunk_index,
                        chunk.start_page,
                        chunk.end_page,
                        chunk.text,
                        chunk.token_count,
                        _json(chunk.page_numbers),
                        chunk.chunk_type,
                    ),
                )

    def export_metadata_review(self, output_path: Path) -> int:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, file_path, title, author, year, metadata_confidence
                FROM books
                WHERE metadata_status = 'needs_review'
                ORDER BY id
                """
            ).fetchall()

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["book_id", "file_path", "title", "author", "year", "confidence"])
            writer.writerows(rows)
        return len(rows)

    def get_books_for_analysis(self, book_id: int | None, all_books: bool) -> list[dict[str, Any]]:
        where = ""
        params: tuple[Any, ...] = ()
        if book_id is not None:
            where = "WHERE id = %s"
            params = (book_id,)
        elif not all_books:
            where = "WHERE metadata_status != 'needs_review'"
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT id, title, author, year
                FROM books
                {where}
                ORDER BY id
                """,
                params,
            ).fetchall()
        return [
            {"id": row[0], "title": row[1], "author": row[2], "year": row[3]}
            for row in rows
        ]

    def get_chunks(self, book_id: int) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, chunk_index, start_page, end_page, text, token_count, chunk_type
                FROM chunks
                WHERE book_id = %s
                ORDER BY chunk_index
                """,
                (book_id,),
            ).fetchall()
        return [
            {
                "id": row[0],
                "chunk_index": row[1],
                "start_page": row[2],
                "end_page": row[3],
                "text": row[4],
                "token_count": row[5],
                "chunk_type": row[6],
            }
            for row in rows
        ]

    def start_run(self, book_id: int, model: str) -> int:
        with self.connect() as connection:
            row = connection.execute(
                """
                INSERT INTO analysis_runs (book_id, model, status)
                VALUES (%s, %s, 'running')
                RETURNING id
                """,
                (book_id, model),
            ).fetchone()
            return int(row[0])

    def finish_run(self, run_id: int, status: str, error: str | None = None) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE analysis_runs
                SET status = %s, error = %s, finished_at = now()
                WHERE id = %s
                """,
                (status, error, run_id),
            )

    def insert_chunk_analysis(self, chunk_id: int, run_id: int, analysis: ChunkAnalysis) -> None:
        payload = analysis.model_dump()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO chunk_analyses (
                    chunk_id, run_id, summary, arguments, people, events,
                    periods, concepts, topics, raw_response
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (chunk_id, run_id) DO UPDATE SET
                    summary = EXCLUDED.summary,
                    arguments = EXCLUDED.arguments,
                    people = EXCLUDED.people,
                    events = EXCLUDED.events,
                    periods = EXCLUDED.periods,
                    concepts = EXCLUDED.concepts,
                    topics = EXCLUDED.topics,
                    raw_response = EXCLUDED.raw_response
                """,
                (
                    chunk_id,
                    run_id,
                    analysis.summary,
                    _json(analysis.arguments),
                    _json(analysis.people),
                    _json(analysis.events),
                    _json(analysis.periods),
                    _json(analysis.concepts),
                    _json(payload["topics"]),
                    _json(payload),
                ),
            )

    def insert_book_report(self, book_id: int, run_id: int, report: BookReport) -> None:
        payload = report.model_dump()
        with self.connect() as connection:
            connection.execute("DELETE FROM book_topics WHERE book_id = %s AND run_id = %s", (book_id, run_id))
            for topic in report.topics:
                connection.execute(
                    """
                    INSERT INTO book_topics (
                        book_id, run_id, name, weight, rationale, representative_pages
                    )
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        book_id,
                        run_id,
                        topic.name,
                        topic.weight,
                        topic.rationale,
                        _json(topic.representative_pages),
                    ),
                )
            connection.execute(
                """
                INSERT INTO book_summaries (
                    book_id, run_id, detailed_summary, main_theses,
                    debate_map, evidence, raw_response
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (book_id, run_id) DO UPDATE SET
                    detailed_summary = EXCLUDED.detailed_summary,
                    main_theses = EXCLUDED.main_theses,
                    debate_map = EXCLUDED.debate_map,
                    evidence = EXCLUDED.evidence,
                    raw_response = EXCLUDED.raw_response
                """,
                (
                    book_id,
                    run_id,
                    report.detailed_summary,
                    _json(report.main_theses),
                    _json(report.debate_map),
                    _json(report.evidence),
                    _json(payload),
                ),
            )

    def replace_topic_judgements_for_chunk(
        self,
        chunk_id: int,
        topics: list[JudgedDebateTopic],
        judge_model: str,
    ) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM topic_candidates WHERE chunk_id = %s", (chunk_id,))
            for topic in topics:
                candidate = topic.candidate
                judgement = topic.judgement
                raw_response = topic.model_dump()
                row = connection.execute(
                    """
                    INSERT INTO topic_candidates (
                        chunk_id, topic_title, claim, people, events, periods,
                        evidence, confidence
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        chunk_id,
                        candidate.topic_title,
                        candidate.claim,
                        _json(candidate.people),
                        _json(candidate.events),
                        _json(candidate.periods),
                        candidate.evidence,
                        candidate.confidence,
                    ),
                ).fetchone()
                candidate_id = int(row[0])
                connection.execute(
                    """
                    INSERT INTO topic_judgements (
                        candidate_id, approved, relevance_score, evidence_score,
                        hallucination_risk, debate_value, action, reason,
                        judge_model, raw_response
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        candidate_id,
                        judgement.approved,
                        judgement.relevance_score,
                        judgement.evidence_score,
                        judgement.hallucination_risk,
                        judgement.debate_value,
                        judgement.action,
                        judgement.reason,
                        judge_model,
                        _json(raw_response),
                    ),
                )

    def get_approved_topic_context(self, chunk_ids: list[int], limit: int = 12) -> list[dict[str, Any]]:
        if not chunk_ids:
            return []
        placeholders = ", ".join(["%s"] * len(chunk_ids))
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT
                    tc.chunk_id, tc.topic_title, tc.claim, tc.evidence,
                    tj.relevance_score, tj.evidence_score, tj.debate_value
                FROM topic_candidates tc
                JOIN topic_judgements tj ON tj.candidate_id = tc.id
                WHERE tc.chunk_id IN ({placeholders})
                  AND tj.approved = true
                  AND tj.action IN ('keep', 'revise')
                ORDER BY
                    tj.relevance_score DESC,
                    tj.evidence_score DESC,
                    tj.debate_value DESC
                LIMIT %s
                """,
                (*chunk_ids, limit),
            ).fetchall()
        return [
            {
                "chunk_id": row[0],
                "topic_title": row[1],
                "claim": row[2],
                "evidence": row[3],
                "relevance_score": float(row[4]),
                "evidence_score": float(row[5]),
                "debate_value": float(row[6]),
            }
            for row in rows
        ]

    def get_latest_reports(self, book_id: int | None = None) -> list[dict[str, Any]]:
        where = ""
        params: tuple[Any, ...] = ()
        if book_id is not None:
            where = "WHERE b.id = %s"
            params = (book_id,)
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT
                    b.id, b.title, b.author, b.year,
                    r.id AS run_id,
                    s.detailed_summary, s.main_theses, s.debate_map, s.evidence,
                    COALESCE(
                        jsonb_agg(
                            jsonb_build_object(
                                'name', t.name,
                                'weight', t.weight,
                                'rationale', t.rationale,
                                'representative_pages', t.representative_pages
                            )
                            ORDER BY t.weight DESC
                        ) FILTER (WHERE t.id IS NOT NULL),
                        '[]'::jsonb
                    ) AS topics
                FROM books b
                JOIN LATERAL (
                    SELECT id
                    FROM analysis_runs
                    WHERE book_id = b.id AND status = 'completed'
                    ORDER BY finished_at DESC NULLS LAST, id DESC
                    LIMIT 1
                ) r ON true
                JOIN book_summaries s ON s.book_id = b.id AND s.run_id = r.id
                LEFT JOIN book_topics t ON t.book_id = b.id AND t.run_id = r.id
                {where}
                GROUP BY b.id, b.title, b.author, b.year, r.id,
                         s.detailed_summary, s.main_theses, s.debate_map, s.evidence
                ORDER BY b.id
                """,
                params,
            ).fetchall()
        return [
            {
                "book_id": row[0],
                "title": row[1],
                "author": row[2],
                "year": row[3],
                "run_id": row[4],
                "detailed_summary": row[5],
                "main_theses": row[6],
                "debate_map": row[7],
                "evidence": row[8],
                "topics": row[9],
            }
            for row in rows
        ]

    def upsert_figure(self, figure: FigureSeed, slug: str) -> int:
        aliases = sorted({figure.name, *figure.aliases})
        with self.connect() as connection:
            row = connection.execute(
                """
                INSERT INTO historical_figures (slug, name, period, short_bio)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (slug) DO UPDATE SET
                    name = EXCLUDED.name,
                    period = EXCLUDED.period,
                    short_bio = EXCLUDED.short_bio,
                    updated_at = now()
                RETURNING id
                """,
                (slug, figure.name, figure.period, figure.short_bio),
            ).fetchone()
            figure_id = int(row[0])
            connection.execute(
                "DELETE FROM figure_aliases WHERE figure_id = %s",
                (figure_id,),
            )
            for alias in aliases:
                connection.execute(
                    """
                    INSERT INTO figure_aliases (figure_id, alias)
                    VALUES (%s, %s)
                    ON CONFLICT (figure_id, alias) DO NOTHING
                    """,
                    (figure_id, alias),
                )
            return figure_id

    def list_figures(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT f.id, f.slug, f.name, f.period, f.short_bio,
                       COALESCE(jsonb_agg(a.alias ORDER BY a.alias)
                                FILTER (WHERE a.id IS NOT NULL), '[]'::jsonb) AS aliases
                FROM historical_figures f
                LEFT JOIN figure_aliases a ON a.figure_id = f.id
                GROUP BY f.id, f.slug, f.name, f.period, f.short_bio
                ORDER BY f.name
                """
            ).fetchall()
        return [
            {
                "id": row[0],
                "slug": row[1],
                "name": row[2],
                "period": row[3],
                "short_bio": row[4],
                "aliases": row[5],
            }
            for row in rows
        ]

    def get_figure(self, figure_id: int) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT f.id, f.slug, f.name, f.period, f.short_bio,
                       COALESCE(jsonb_agg(a.alias ORDER BY a.alias)
                                FILTER (WHERE a.id IS NOT NULL), '[]'::jsonb) AS aliases
                FROM historical_figures f
                LEFT JOIN figure_aliases a ON a.figure_id = f.id
                WHERE f.id = %s
                GROUP BY f.id, f.slug, f.name, f.period, f.short_bio
                """,
                (figure_id,),
            ).fetchone()
        if not row:
            return None
        return {
            "id": row[0],
            "slug": row[1],
            "name": row[2],
            "period": row[3],
            "short_bio": row[4],
            "aliases": row[5],
        }

    def search_chunks(
        self,
        patterns: list[str],
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        cleaned_patterns = [pattern.strip() for pattern in patterns if pattern.strip()]
        if not cleaned_patterns:
            return []
        conditions = " OR ".join(["c.text ILIKE %s"] * len(cleaned_patterns))
        params = tuple(f"%{pattern}%" for pattern in cleaned_patterns)
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT c.id, c.book_id, b.title, b.author,
                       c.chunk_index, c.start_page, c.end_page, c.text, c.chunk_type
                FROM chunks c
                JOIN books b ON b.id = c.book_id
                WHERE {conditions}
                ORDER BY b.title, c.chunk_index
                LIMIT %s
                """,
                (*params, limit),
            ).fetchall()
        return [
            {
                "chunk_id": row[0],
                "book_id": row[1],
                "book_title": row[2],
                "author": row[3],
                "chunk_index": row[4],
                "start_page": row[5],
                "end_page": row[6],
                "text": row[7],
                "chunk_type": row[8],
            }
            for row in rows
        ]

    def source_stats(self) -> dict[str, int]:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT
                    (SELECT count(*) FROM books) AS books,
                    (SELECT count(*) FROM chunks) AS chunks,
                    (SELECT count(*) FROM historical_figures) AS figures
                """
            ).fetchone()
        return {"books": int(row[0]), "chunks": int(row[1]), "figures": int(row[2])}
