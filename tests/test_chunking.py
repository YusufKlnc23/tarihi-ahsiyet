from tarih_pdf_analyzer.chunking import build_discussion_question_chunks, chunk_pages, estimate_tokens
from tarih_pdf_analyzer.models import PageText, TextChunk


def test_chunk_pages_preserves_page_ranges_and_limits_size():
    pages = [
        PageText(1, "modernlesme " * 300),
        PageText(2, "devlet " * 300),
        PageText(3, "cumhuriyet " * 300),
        PageText(4, "inkilap " * 300),
        PageText(5, "republik " * 300),
        PageText(6, "demokrasi " * 300),
        PageText(7, "siyaset " * 300),
        PageText(8, "toplum " * 300),
        PageText(9, "ittihat " * 300),
    ]

    chunks = chunk_pages(pages, max_tokens=350, overlap_tokens=20)

    assert len(chunks) >= 3
    assert chunks[0].start_page == 1
    assert chunks[-1].end_page == 9
    assert all(chunk.token_count <= 380 for chunk in chunks)


def test_estimate_tokens_never_returns_zero():
    assert estimate_tokens("") == 1


def test_build_discussion_question_chunks_creates_question_entries():
    source_chunks = [
        TextChunk(
            chunk_index=1,
            start_page=1,
            end_page=2,
            text="İttihat ve Terakki çevreleri meşrutiyetin toplumsal tabanını genişletmek için reformlar önerdi.",
            token_count=20,
        )
    ]

    questions = build_discussion_question_chunks(source_chunks)

    assert len(questions) == 1
    assert questions[0].chunk_type == "discussion_question"
    assert "tartışma" in questions[0].text.lower() or "soru" in questions[0].text.lower()
    assert questions[0].start_page == 1
    assert questions[0].end_page == 2


