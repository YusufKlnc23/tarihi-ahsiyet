import pytest
from pydantic import ValidationError

from tarih_pdf_analyzer.schemas import BookMetadataGuess, BookTopic


def test_metadata_confidence_is_bounded():
    with pytest.raises(ValidationError):
        BookMetadataGuess(title="Kitap", author="Yazar", confidence=1.5)


def test_topic_weight_is_bounded():
    with pytest.raises(ValidationError):
        BookTopic(name="Konu", weight=101, rationale="fazla")
