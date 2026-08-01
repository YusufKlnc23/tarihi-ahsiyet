from __future__ import annotations

import re
from pathlib import Path

from .schemas import BookMetadataGuess
from .text_cleaning import normalize_for_prompt


_YEAR_RE = re.compile(r"(1[5-9]\d{2}|20\d{2}|21\d{2})")


def _clean_title_part(value: str) -> str:
    value = re.sub(r"[_]+", " ", value)
    value = re.sub(r"\s+", " ", value)
    value = re.sub(r"\b(pdf|epub|scan|ocr)\b", "", value, flags=re.IGNORECASE)
    return value.strip(" -_.,;")


def guess_from_filename(path: str | Path) -> BookMetadataGuess:
    stem = Path(path).stem
    year_match = _YEAR_RE.search(stem)
    year = int(year_match.group(1)) if year_match else None
    stem_without_year = _YEAR_RE.sub("", stem)
    parts = [_clean_title_part(part) for part in re.split(r"\s+-\s+|\s+--\s+", stem_without_year)]
    parts = [part for part in parts if part]

    if len(parts) >= 2:
        first, second = parts[0], " - ".join(parts[1:])
        author_first_hint = bool(re.search(r"\b(prof|dr|doc|halil|ilber|kemal|murat|ahmet|ittihat)\b", first, re.I))
        title, author = (second, first) if author_first_hint else (first, second)
        confidence = 0.62
    else:
        title = _clean_title_part(stem_without_year) or "Bilinmeyen kitap"
        author = "Bilinmeyen yazar"
        confidence = 0.35

    evidence = [f"Dosya adi: {Path(path).name}"]
    return BookMetadataGuess(
        title=title,
        author=author,
        year=year,
        confidence=confidence,
        evidence=evidence,
    )


def guess_from_pdf_metadata(pdf_metadata: dict[str, str]) -> BookMetadataGuess | None:
    title = (pdf_metadata.get("title") or pdf_metadata.get("Title") or "").strip()
    author = (pdf_metadata.get("author") or pdf_metadata.get("Author") or "").strip()
    if not title and not author:
        return None
    if not title:
        title = "Bilinmeyen kitap"
    if not author:
        author = "Bilinmeyen yazar"
    year = None
    for value in pdf_metadata.values():
        if match := _YEAR_RE.search(str(value)):
            year = int(match.group(1))
            break
    confidence = 0.82 if title != "Bilinmeyen kitap" and author != "Bilinmeyen yazar" else 0.55
    return BookMetadataGuess(
        title=title,
        author=author,
        year=year,
        confidence=confidence,
        evidence=["PDF metadata alanlari"],
    )


def merge_metadata_guesses(
    filename_guess: BookMetadataGuess,
    pdf_guess: BookMetadataGuess | None,
) -> BookMetadataGuess:
    if pdf_guess and pdf_guess.confidence >= filename_guess.confidence:
        evidence = [*pdf_guess.evidence, *filename_guess.evidence]
        return pdf_guess.model_copy(update={"evidence": evidence})
    if pdf_guess:
        evidence = [*filename_guess.evidence, *pdf_guess.evidence]
        return filename_guess.model_copy(update={"evidence": evidence})
    return filename_guess


def first_pages_sample(pages_text: list[str], max_chars: int = 7000) -> str:
    return normalize_for_prompt("\n\n".join(pages_text[:5]), max_chars=max_chars)
