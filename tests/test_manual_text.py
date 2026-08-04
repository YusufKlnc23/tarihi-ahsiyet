import json

import pytest  # type: ignore

from tarih_pdf_analyzer.manual_text import (
    ManualTextError,
    load_manual_text_book,
    load_standalone_text_file,
)


def test_load_manual_text_book_with_explicit_page_ranges(tmp_path):
    book_dir = tmp_path / "kitap"
    book_dir.mkdir()
    (book_dir / "chunk-001.txt").write_text("Devlet ve toplum tartismasi.", encoding="utf-8")
    (book_dir / "chunk-002.txt").write_text("Modernlesme ve reform tartismasi.", encoding="utf-8")
    (book_dir / "chunk-003.txt").write_text("Cumhuriyet ve demokrasi tartismasi.", encoding="utf-8")
    (book_dir / "metadata.json").write_text(
        json.dumps(
            {
                "title": "Ornek Tarih",
                "author": "Ornek Yazar",
                "year": 2020,
                "chunks": [
                    {"file": "chunk-001.txt", "pages": "10-12"},
                    {"file": "chunk-002.txt", "start_page": 20, "end_page": 22},
                    {"file": "chunk-003.txt", "start_page": 30, "end_page": 32},
                ],
            }
        ),
        encoding="utf-8",
    )

    document, metadata, chunks = load_manual_text_book(book_dir)

    assert document.metadata["source_type"] == "manual_text"
    assert metadata.title == "Ornek Tarih"
    assert metadata.confidence == 1.0
    assert [(chunk.start_page, chunk.end_page) for chunk in chunks] == [(10, 12), (20, 22), (30, 32)]


def test_load_manual_text_book_auto_discovers_txt_files(tmp_path):
    book_dir = tmp_path / "kitap"
    book_dir.mkdir()
    (book_dir / "b.txt").write_text("Ikinci metin.", encoding="utf-8")
    (book_dir / "a.txt").write_text("Birinci metin.", encoding="utf-8")
    (book_dir / "metadata.json").write_text(
        json.dumps({"title": "Kitap", "author": "Yazar"}),
        encoding="utf-8",
    )

    _, _, chunks = load_manual_text_book(book_dir)

    assert chunks[0].text == "Birinci metin."
    assert chunks[1].text == "Ikinci metin."
    assert [chunk.start_page for chunk in chunks] == [1, 2]


def test_manual_text_rejects_paths_outside_book_directory(tmp_path):
    book_dir = tmp_path / "kitap"
    book_dir.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("Disaridaki metin", encoding="utf-8")
    (book_dir / "metadata.json").write_text(
        json.dumps(
            {
                "title": "Kitap",
                "author": "Yazar",
                "chunks": [{"file": "../outside.txt"}],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ManualTextError):
        load_manual_text_book(book_dir)


def test_manual_text_splits_oversized_chunk(tmp_path):
    book_dir = tmp_path / "kitap"
    book_dir.mkdir()
    (book_dir / "chunk.txt").write_text("devlet " * 200, encoding="utf-8")
    (book_dir / "metadata.json").write_text(
        json.dumps(
            {
                "title": "Kitap",
                "author": "Yazar",
                "chunks": [{"file": "chunk.txt", "pages": "5-7"}],
            }
        ),
        encoding="utf-8",
    )

    _, _, chunks = load_manual_text_book(book_dir, max_tokens=80)

    assert len(chunks) > 1
    assert all(chunk.start_page == 5 and chunk.end_page == 7 for chunk in chunks)
    assert all(chunk.token_count <= 80 for chunk in chunks)


def test_load_standalone_text_file_creates_document_and_chunks(tmp_path):
    path = tmp_path / "referans-notu.txt"
    path.write_text("Enver Pasa ve Ittihat tartismasi. " * 80, encoding="utf-8")

    document, metadata, chunks = load_standalone_text_file(path, max_tokens=150)

    assert document.metadata["source_type"] == "standalone_text"
    assert metadata.title == "referans-notu"
    assert chunks
