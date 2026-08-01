from __future__ import annotations

from .db import Database
from .llm import AnalyzerClient
from .schemas import ChunkAnalysis


def analyze_book(db: Database, client: AnalyzerClient, book: dict, model_name: str) -> int:
    chunks = db.get_chunks(book["id"])
    if not chunks:
        raise RuntimeError(f"Book {book['id']} has no chunks. Run ingest first.")

    run_id = db.start_run(book["id"], model_name)
    chunk_analyses: list[ChunkAnalysis] = []
    try:
        for chunk in chunks:
            analysis = client.analyze_chunk(
                title=book["title"],
                author=book["author"],
                start_page=chunk["start_page"],
                end_page=chunk["end_page"],
                text=chunk["text"],
            )
            db.insert_chunk_analysis(chunk["id"], run_id, analysis)
            chunk_analyses.append(analysis)

        report = client.synthesize_book(book["title"], book["author"], chunk_analyses)
        db.insert_book_report(book["id"], run_id, report)
        db.finish_run(run_id, "completed")
        return run_id
    except Exception as exc:
        db.finish_run(run_id, "failed", str(exc))
        raise
