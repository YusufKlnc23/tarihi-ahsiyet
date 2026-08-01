from tarih_pdf_analyzer.metadata import (
    guess_from_filename,
    guess_from_pdf_metadata,
    merge_metadata_guesses,
)


def test_guess_from_filename_extracts_title_author_and_year():
    guess = guess_from_filename("Modern Turkiye Tarihi - Feroz Ahmad 1993.pdf")

    assert guess.title == "Modern Turkiye Tarihi"
    assert guess.author == "Feroz Ahmad"
    assert guess.year == 1993


def test_pdf_metadata_wins_when_more_confident():
    filename_guess = guess_from_filename("Bilinmeyen.pdf")
    pdf_guess = guess_from_pdf_metadata({"title": "Osmanli Tarihi", "author": "Halil Inalcik"})

    merged = merge_metadata_guesses(filename_guess, pdf_guess)

    assert merged.title == "Osmanli Tarihi"
    assert merged.author == "Halil Inalcik"
    assert merged.confidence > filename_guess.confidence
