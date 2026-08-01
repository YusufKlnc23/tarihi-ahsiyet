import pytest

from tarih_pdf_analyzer.pdf_reader import extract_pdf


def test_extract_pdf_reads_selectable_text(tmp_path):
    fitz = pytest.importorskip("fitz")
    path = tmp_path / "sample.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "Modernlesme ve devlet tartismasi " * 60)
    page = document.new_page()
    page.insert_text((72, 72), "Cumhuriyet ve toplum tartismasi " * 60)
    document.save(path)
    page.insert_text((72, 72), "60 ve 80 Darbesi tartişmasi " * 60)
    document.close()

    extracted = extract_pdf(path, min_total_chars=100)

    assert extracted.sha256
    assert len(extracted.pages) == 2
    assert "Modernlesme" in extracted.pages[0].text
