from __future__ import annotations

import hashlib
from pathlib import Path

from .models import PageText, PdfDocument
from .text_cleaning import clean_page_text, remove_repeated_headers_footers


class OCRRequiredError(RuntimeError):
    """Raised when a PDF does not contain enough selectable text."""


def hash_file(path: Path, block_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(block_size):
            digest.update(chunk)
    return digest.hexdigest()


def extract_pdf(path: str | Path, min_total_chars: int = 1000) -> PdfDocument:
    pdf_path = Path(path)
    try:
        import fitz  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError("PyMuPDF is required. Install with: pip install PyMuPDF") from exc

    document = fitz.open(pdf_path)
    pages: list[PageText] = []
    for index, page in enumerate(document, start=1):
        text = clean_page_text(page.get_text("text") or "")
        pages.append(PageText(page_number=index, text=text))

    pages = remove_repeated_headers_footers(pages)
    total_chars = sum(len(page.text) for page in pages)
    if total_chars < min_total_chars:
        raise OCRRequiredError(
            f"{pdf_path.name} secilebilir metin icermiyor veya metin cok az; OCR gerekli."
        )

    metadata = {
        key: str(value)
        for key, value in (document.metadata or {}).items()
        if value is not None and str(value).strip()
    }
    document.close()
    return PdfDocument(
        path=pdf_path,
        sha256=hash_file(pdf_path),
        metadata=metadata,
        pages=pages,
    )
