import json

from tarih_pdf_analyzer.exporter import build_markdown_report, write_json_report, write_topics_csv


def sample_report():
    return {
        "book_id": 1,
        "title": "Modern Turkiye Tarihi",
        "author": "Feroz Ahmad",
        "year": 1993,
        "run_id": 7,
        "detailed_summary": "Ayrintili ozet.",
        "main_theses": ["Modernlesme tartismasi"],
        "debate_map": ["Devlet-toplum iliskisi"],
        "evidence": ["s. 12-18"],
        "topics": [
            {
                "name": "Modernlesme",
                "weight": 55.0,
                "rationale": "Metinde merkezi bir tartisma.",
                "representative_pages": [12, 13],
            }
        ],
    }


def test_build_markdown_report_contains_topics():
    markdown = build_markdown_report(sample_report())

    assert "# Modern Turkiye Tarihi" in markdown
    assert "Modernlesme" in markdown
    assert "%55.0" in markdown


def test_write_json_and_csv_reports(tmp_path):
    report = sample_report()

    json_path = write_json_report(report, tmp_path)
    csv_path = write_topics_csv([report], tmp_path)

    assert json.loads(json_path.read_text(encoding="utf-8"))["title"] == report["title"]
    assert "Modernlesme" in csv_path.read_text(encoding="utf-8")
