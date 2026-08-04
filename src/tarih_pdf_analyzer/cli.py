from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .analyzer import analyze_book
from .chunking import build_discussion_question_chunks, chunk_pages
from .config import load_settings
from .db import Database
from .exporter import write_json_report, write_markdown_report, write_topics_csv
from .chat import FigureChatService
from .figures import load_figure_manifest, slugify
from .judge import GeminiTopicJudge, MockTopicJudge, judge_book_topics
from .llm import GeminiAnalyzer, MockAnalyzer
from .manual_text import ManualTextError, load_manual_text_book, load_standalone_text_file
from .metadata import (
    first_pages_sample,
    guess_from_filename,
    guess_from_pdf_metadata,
    merge_metadata_guesses,
)
from .pdf_reader import OCRRequiredError, extract_pdf


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tarih-analyze",
        description="Tarih kitabi PDF ve manuel metin analiz pipeline'i.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init-db", help="PostgreSQL semasini olusturur.")

    ingest = subparsers.add_parser("ingest", help="PDF ve TXT dosyalarini okur, chunk'lara ayirir.")
    ingest.add_argument("pdf_dir", type=Path)
    ingest.add_argument("--force", action="store_true", help="Ayni hash olsa bile yeniden isler.")
    ingest.add_argument("--llm-metadata", action="store_true", help="Dusuk guvenli metadata icin LLM kullanir.")

    ingest_text = subparsers.add_parser(
        "ingest-text",
        help="metadata.json ve TXT chunk'larindan kitaplari yukler.",
    )
    ingest_text.add_argument("text_dir", type=Path)
    ingest_text.add_argument("--force", action="store_true", help="Ayni hash olsa bile yeniden isler.")

    load_figures = subparsers.add_parser("load-figures", help="Tarihi sahsiyet manifestini PostgreSQL'e yukler.")
    load_figures.add_argument("manifest", type=Path)

    subparsers.add_parser("list-figures", help="PostgreSQL'deki tarihi sahsiyetleri listeler.")

    ask_figure = subparsers.add_parser("ask-figure", help="Secili sahsiyet hakkinda kaynakli soru sorar.")
    ask_figure.add_argument("--figure-id", type=int, required=True)
    ask_figure.add_argument("--question", required=True)
    ask_figure.add_argument("--mock", action="store_true", help="LLM cagirmadan kaynak onizlemesi dondurur.")

    review = subparsers.add_parser("review-metadata", help="Dusuk guvenli metadata kayitlarini CSV'ye aktarir.")
    review.add_argument("--output", type=Path, default=Path("exports/metadata_review.csv"))

    analyze = subparsers.add_parser("analyze", help="Chunk analizini ve kitap sentezini calistirir.")
    analyze_group = analyze.add_mutually_exclusive_group(required=True)
    analyze_group.add_argument("--book-id", type=int)
    analyze_group.add_argument("--all", action="store_true")
    analyze.add_argument("--mock", action="store_true", help="API anahtari olmadan deterministik analiz yapar.")

    judge = subparsers.add_parser("judge-topics", help="Chunk'lardan tartisma konusu adaylarini yargilar.")
    judge_group = judge.add_mutually_exclusive_group(required=True)
    judge_group.add_argument("--book-id", type=int)
    judge_group.add_argument("--all", action="store_true")
    judge.add_argument("--mock", action="store_true", help="Gemini cagirmadan deterministik judge calistirir.")
    judge.add_argument("--limit", type=int, help="Kitap basina degerlendirilecek kaynak chunk limiti.")

    export = subparsers.add_parser("export", help="Analiz raporlarini disari aktarir.")
    export_group = export.add_mutually_exclusive_group(required=True)
    export_group.add_argument("--book-id", type=int)
    export_group.add_argument("--all", action="store_true")
    export.add_argument(
        "--format",
        default="markdown",
        help="Virgulle ayrilmis format listesi: markdown,csv,json",
    )
    export.add_argument("--output-dir", type=Path, default=Path("exports"))
    return parser


def _make_analyzer(settings, mock: bool):
    if mock:
        return MockAnalyzer(), "mock"
    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY yok. Analiz icin anahtar verin veya --mock kullanin.")
    return GeminiAnalyzer(settings.gemini_api_key, settings.gemini_model), settings.gemini_model


def _make_topic_judge(settings, mock: bool):
    if mock:
        return MockTopicJudge(), "mock"
    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY yok. Judge icin anahtar verin veya --mock kullanin.")
    return GeminiTopicJudge(settings.gemini_api_key, settings.gemini_model), settings.gemini_model


def command_init_db(db: Database) -> None:
    db.init_schema()
    print("PostgreSQL semasi hazir.")


def command_ingest(args, db: Database, settings) -> None:
    db.init_schema()
    analyzer = None
    if args.llm_metadata:
        analyzer, _ = _make_analyzer(settings, mock=False)

    pdf_paths = sorted(args.pdf_dir.rglob("*.pdf"))
    txt_paths = sorted(args.pdf_dir.rglob("*.txt"))
    if not pdf_paths and not txt_paths:
        print(f"PDF/TXT bulunamadi: {args.pdf_dir}")
        return

    ingested = skipped = failed = 0
    for pdf_path in pdf_paths:
        try:
            document = extract_pdf(pdf_path)
            filename_guess = guess_from_filename(pdf_path)
            pdf_guess = guess_from_pdf_metadata(document.metadata)
            metadata = merge_metadata_guesses(filename_guess, pdf_guess)

            if (
                analyzer
                and metadata.confidence < settings.metadata_confidence_threshold
            ):
                sample = first_pages_sample([page.text for page in document.pages])
                metadata = analyzer.guess_metadata(pdf_path.name, document.metadata, sample)

            status = (
                "needs_review"
                if metadata.confidence < settings.metadata_confidence_threshold
                else "auto"
            )
            book_id, changed = db.upsert_book(
                document,
                metadata,
                status,
                force_update=args.force,
            )
            if not changed and not args.force:
                skipped += 1
                print(f"SKIP book_id={book_id} {pdf_path.name}")
                continue

            source_chunks = chunk_pages(
                document.pages,
                max_tokens=settings.chunk_max_tokens,
                overlap_tokens=settings.chunk_overlap_tokens,
            )
            discussion_chunks = build_discussion_question_chunks(source_chunks)
            db.replace_pages_and_chunks(
                book_id,
                document,
                [*source_chunks, *discussion_chunks],
            )
            ingested += 1
            print(
                f"OK book_id={book_id} pages={len(document.pages)} chunks={len(source_chunks) + len(discussion_chunks)} "
                f"metadata={metadata.title} / {metadata.author} ({metadata.confidence:.2f})"
            )
        except OCRRequiredError as exc:
            skipped += 1
            print(f"OCR_SKIPPED {pdf_path.name}: {exc}")
        except Exception as exc:
            failed += 1
            print(f"FAILED {pdf_path.name}: {exc}")
    for text_path in txt_paths:
        try:
            document, metadata, chunks = load_standalone_text_file(
                text_path,
                max_tokens=settings.chunk_max_tokens,
                overlap_tokens=settings.chunk_overlap_tokens,
            )
            book_id, changed = db.upsert_book(
                document,
                metadata,
                "manual",
                force_update=args.force,
            )
            if not changed and not args.force:
                skipped += 1
                print(f"SKIP book_id={book_id} {text_path.name}")
                continue
            discussion_chunks = build_discussion_question_chunks(chunks)
            db.replace_pages_and_chunks(book_id, document, [*chunks, *discussion_chunks])
            ingested += 1
            print(
                f"OK book_id={book_id} chunks={len(chunks) + len(discussion_chunks)} "
                f"metadata={metadata.title} / {metadata.author}"
            )
        except Exception as exc:
            failed += 1
            print(f"FAILED {text_path.name}: {exc}")
    print(f"Tamamlandi. ingested={ingested} skipped={skipped} failed={failed}")


def command_review_metadata(args, db: Database) -> None:
    count = db.export_metadata_review(args.output)
    print(f"{count} kayit yazildi: {args.output}")


def command_ingest_text(args, db: Database, settings) -> None:
    db.init_schema()
    manifest_paths = sorted(args.text_dir.rglob("metadata.json"))
    if not manifest_paths:
        print(f"metadata.json bulunamadi: {args.text_dir}")
        return

    ingested = skipped = failed = 0
    for manifest_path in manifest_paths:
        book_dir = manifest_path.parent
        try:
            document, metadata, chunks = load_manual_text_book(
                book_dir,
                max_tokens=settings.chunk_max_tokens,
            )
            book_id, changed = db.upsert_book(
                document,
                metadata,
                metadata_status="manual",
                force_update=args.force,
            )
            if not changed and not args.force:
                skipped += 1
                print(f"SKIP book_id={book_id} {metadata.title}")
                continue

            discussion_chunks = build_discussion_question_chunks(chunks)
            db.replace_pages_and_chunks(book_id, document, [*chunks, *discussion_chunks])
            ingested += 1
            print(
                f"OK book_id={book_id} chunks={len(chunks) + len(discussion_chunks)} "
                f"metadata={metadata.title} / {metadata.author}"
            )
        except ManualTextError as exc:
            failed += 1
            print(f"FAILED {book_dir}: {exc}")
        except Exception as exc:
            failed += 1
            print(f"FAILED {book_dir}: {exc}")
    print(f"Tamamlandi. ingested={ingested} skipped={skipped} failed={failed}")


def command_load_figures(args, db: Database) -> None:
    db.init_schema()
    figures = load_figure_manifest(args.manifest)
    for figure in figures:
        db.upsert_figure(figure, slug=figure.slug or slugify(figure.name))
    print(f"{len(figures)} sahsiyet yuklendi: {args.manifest}")


def command_list_figures(db: Database) -> None:
    db.init_schema()
    figures = db.list_figures()
    if not figures:
        print("Sahsiyet bulunamadi. Once `tarih-analyze load-figures data/figures.example.json` calistirin.")
        return
    for figure in figures:
        period = f" ({figure['period']})" if figure.get("period") else ""
        print(f"{figure['id']}: {figure['name']}{period}")


def command_ask_figure(args, db: Database, settings) -> None:
    db.init_schema()
    service = FigureChatService(db, settings)
    answer = service.answer(
        question=args.question,
        figure_id=args.figure_id,
        use_llm=not args.mock,
    )
    print(answer.answer)
    if answer.citations:
        print("\nKaynaklar:")
        for citation in answer.citations:
            print(
                f"- {citation.book_title} / {citation.author}, "
                f"chunk {citation.chunk_index}, sayfa {citation.pages}"
            )


def command_analyze(args, db: Database, settings) -> None:
    db.init_schema()
    client, model_name = _make_analyzer(settings, mock=args.mock)
    books = db.get_books_for_analysis(args.book_id, args.all)
    if not books:
        print("Analiz edilecek kitap bulunamadi.")
        return
    for book in books:
        print(f"Analiz basladi book_id={book['id']} {book['title']}")
        run_id = analyze_book(db, client, book, model_name)
        print(f"Analiz tamamlandi book_id={book['id']} run_id={run_id}")


def command_judge_topics(args, db: Database, settings) -> None:
    db.init_schema()
    client, model_name = _make_topic_judge(settings, mock=args.mock)
    books = db.get_books_for_analysis(args.book_id, args.all)
    if not books:
        print("Judge calistirilacak kitap bulunamadi.")
        return
    for book in books:
        print(f"Judge basladi book_id={book['id']} {book['title']}")
        written = judge_book_topics(
            db=db,
            client=client,
            book=book,
            model_name=model_name,
            limit=args.limit,
        )
        print(f"Judge tamamlandi book_id={book['id']} topic_adayi={written}")


def command_export(args, db: Database) -> None:
    formats = {item.strip().lower() for item in args.format.split(",") if item.strip()}
    unknown = formats - {"markdown", "md", "json", "csv"}
    if unknown:
        raise RuntimeError(f"Bilinmeyen format: {', '.join(sorted(unknown))}")

    reports = db.get_latest_reports(book_id=args.book_id if not args.all else None)
    if not reports:
        print("Disari aktarilacak tamamlanmis analiz bulunamadi.")
        return

    written = []
    for report in reports:
        if "markdown" in formats or "md" in formats:
            written.append(write_markdown_report(report, args.output_dir))
        if "json" in formats:
            written.append(write_json_report(report, args.output_dir))
    if "csv" in formats:
        written.append(write_topics_csv(reports, args.output_dir))

    for path in written:
        print(f"WROTE {path}")


def main(argv: list[str] | None = None) -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    parser = build_parser()
    args = parser.parse_args(argv)
    settings = load_settings()
    db = Database(settings.database_url)

    if args.command == "init-db":
        command_init_db(db)
    elif args.command == "ingest":
        command_ingest(args, db, settings)
    elif args.command == "ingest-text":
        command_ingest_text(args, db, settings)
    elif args.command == "load-figures":
        command_load_figures(args, db)
    elif args.command == "list-figures":
        command_list_figures(db)
    elif args.command == "ask-figure":
        command_ask_figure(args, db, settings)
    elif args.command == "review-metadata":
        command_review_metadata(args, db)
    elif args.command == "analyze":
        command_analyze(args, db, settings)
    elif args.command == "judge-topics":
        command_judge_topics(args, db, settings)
    elif args.command == "export":
        command_export(args, db)
    else:
        parser.error(f"Unknown command: {args.command}")
