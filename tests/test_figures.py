import json

from tarih_pdf_analyzer.chat import clean_generated_answer, citation_from_chunk, format_sources
from tarih_pdf_analyzer.chat import FigureChatService
from tarih_pdf_analyzer.config import Settings
from tarih_pdf_analyzer.figures import load_figure_manifest, slugify
from tarih_pdf_analyzer.retrieval import focused_question_terms, question_terms, score_text
from tarih_pdf_analyzer.schemas import RetrievedChunk
from tarih_pdf_analyzer.text_cleaning import repair_mojibake


def test_slugify_normalizes_turkish_names():
    assert slugify("II. Abdulhamid") == "ii-abdulhamid"
    assert slugify("Mustafa Kemal Ataturk") == "mustafa-kemal-ataturk"


def test_load_figure_manifest_handles_missing_file(tmp_path):
    missing_path = tmp_path / "missing.json"
    figures = load_figure_manifest(missing_path)
    assert figures == []

def test_load_figure_manifest(tmp_path):
    path = tmp_path / "figures.json"
    path.write_text(
        json.dumps(
            {
                "figures": [
                    {
                        "name": "Enver Pasa",
                        "aliases": ["Enver Bey"],
                        "period": "1881-1922",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    figures = load_figure_manifest(path)

    assert figures[0].name == "Enver Pasa"
    assert figures[0].aliases == ["Enver Bey"]


def test_question_terms_deduplicates_words():
    assert question_terms("Mehmet Reşad") == ["mehmet", "resad"]
    assert question_terms("Enver Pasa siyasi siyasi rolu nedir?") == [
        "enver",
        "pasa",
        "siyasi",
    ]
def test_question_terms_handles_empty_string():
    assert question_terms("") == []     

def test_score_text_prioritizes_aliases():
    score = score_text(
        "Enver Pasa ve Ittihat tartismasi.",
        aliases=["Enver Pasa"],
        terms=["ittihat", "devlet"],
    )

    assert score == 31.0


def test_score_text_requires_alias_when_requested():
    score = score_text(
        "Ittihat ve devlet tartismasi.",
        aliases=["Enver Pasa"],
        terms=["ittihat", "devlet"],
        require_alias=True,
    )

    assert score == 0.0


def test_focused_question_terms_removes_figure_name():
    terms = focused_question_terms(
        "Enver Paşa Babıali Baskını'nda ne yapti?",
        aliases=["Enver Pasa", "Enver Paşa"],
    )

    assert terms == ["babiali", "baskini", "yapti"]


def test_chat_service_answers_from_all_sources_without_figure():
    chunk = RetrievedChunk(
        chunk_id=10,
        book_id=2,
        book_title="Ornek Kitap",
        author="Ornek Yazar",
        chunk_index=3,
        start_page=12,
        end_page=15,
        text="Enver Pasa hakkinda kaynak metin.",
        score=5,
    )

    class FakeRetriever:
        def retrieve_general(self, question, limit=5):
            return [chunk]

    service = FigureChatService(
        db=None,
        settings=Settings(
            database_url="postgresql://localhost",
            llm_provider="gemini",
            gemini_api_key=None,
            gemini_model="test-model",
            metadata_confidence_threshold=0.75,
            chunk_max_tokens=1800,
            chunk_overlap_tokens=160,
        ),
    )
    service.retriever = FakeRetriever()

    answer = service.answer("Enver Pasa kimdir?", figure_id=None, use_llm=False)

    assert "Tum kaynaklar" in answer.answer
    assert answer.citations[0].chunk_id == 10


def test_citation_and_source_formatting():
    chunk = RetrievedChunk(
        chunk_id=10,
        book_id=2,
        book_title="Ornek Kitap",
        author="Ornek Yazar",
        chunk_index=3,
        start_page=12,
        end_page=15,
        text="Enver Pasa hakkinda kaynak metin.",
        score=11,
    
    )

    citation = citation_from_chunk(chunk)
    sources = format_sources([chunk])

    assert citation.pages == "12-15"
    assert "[parca 1]" in sources
    assert "chunk_id=10" not in sources
    assert "Ornek Kitap" not in sources


def test_text_cleanup_repairs_mojibake_and_strips_source_lines():
    assert repair_mojibake("ReÅŸad PaÅŸa") == "Reşad Paşa"
    answer = clean_generated_answer(
        "Verilen kaynaklara gore, Enver Paşa onemliydi.\nSayfa 89: ayrinti"
    )

    assert answer == "Enver Paşa onemliydi."
