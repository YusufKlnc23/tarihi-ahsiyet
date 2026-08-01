from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from .chunking import chunk_pages, estimate_tokens, split_oversized_text
from .metadata import guess_from_filename
from .models import PageText, PdfDocument, TextChunk
from .pdf_reader import hash_file
from .schemas import BookMetadataGuess, ManualBookManifest, ManualChunkSpec
from .text_cleaning import normalize_for_prompt


class ManualTextError(RuntimeError):
    """Raised when a manual text book directory is invalid."""


def _parse_page_range(spec: ManualChunkSpec, fallback: int) -> tuple[int, int]:
    if spec.start_page is not None:
        start_page = spec.start_page
        end_page = spec.end_page if spec.end_page is not None else start_page
    elif spec.end_page is not None:
        raise ManualTextError("end_page kullanmak icin start_page de verilmelidir.")
    elif isinstance(spec.pages, int):
        start_page = end_page = spec.pages
    elif isinstance(spec.pages, list) and spec.pages:
        if any(page < 1 for page in spec.pages):
            raise ManualTextError("Sayfa numaralari 1 veya daha buyuk olmalidir.")
        start_page, end_page = min(spec.pages), max(spec.pages)
    elif isinstance(spec.pages, str):
        if not re.fullmatch(r"\s*\d+\s*(?:-\s*\d+\s*)?", spec.pages):
            raise ManualTextError(f"Gecersiz sayfa araligi: {spec.pages}")
        numbers = [int(value) for value in re.findall(r"\d+", spec.pages)]
        start_page, end_page = min(numbers), max(numbers)
    else:
        start_page = end_page = fallback

    if start_page < 1:
        raise ManualTextError("Sayfa numaralari 1 veya daha buyuk olmalidir.")
    if end_page < start_page:
        raise ManualTextError(
            f"Bitis sayfasi baslangictan kucuk: {start_page}-{end_page}"
        )
    return start_page, end_page


def _resolve_chunk_path(book_dir: Path, relative_path: str) -> Path:
    root = book_dir.resolve()
    chunk_path = (book_dir / relative_path).resolve()
    if chunk_path != root and root not in chunk_path.parents:
        raise ManualTextError(f"Chunk kitap klasoru disinda olamaz: {relative_path}")
    if not chunk_path.is_file():
        raise ManualTextError(f"Chunk dosyasi bulunamadi: {relative_path}")
    return chunk_path


def _discover_chunk_specs(book_dir: Path) -> list[ManualChunkSpec]:
    files = sorted(book_dir.glob("*.txt"))
    return [ManualChunkSpec(file=path.name) for path in files]


def _bundle_hash(manifest_path: Path, chunk_paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in [manifest_path, *chunk_paths]:
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def load_manual_text_book(
    book_dir: str | Path,
    max_tokens: int = 1800,
) -> tuple[PdfDocument, BookMetadataGuess, list[TextChunk]]:
    if max_tokens < 1:
        raise ManualTextError("max_tokens 1 veya daha buyuk olmalidir.")
    directory = Path(book_dir)
    manifest_path = directory / "metadata.json"
    if not manifest_path.is_file():
        raise ManualTextError(f"metadata.json bulunamadi: {directory}")

    try:
        manifest_data = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        manifest = ManualBookManifest.model_validate(manifest_data)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ManualTextError(f"Gecersiz metadata.json: {manifest_path}: {exc}") from exc

    specs = manifest.chunks or _discover_chunk_specs(directory)
    if not specs:
        raise ManualTextError(f"Metin chunk dosyasi bulunamadi: {directory}")

    resolved_paths = [_resolve_chunk_path(directory, spec.file) for spec in specs]
    chunks: list[TextChunk] = []
    for source_index, (spec, chunk_path) in enumerate(
        zip(specs, resolved_paths, strict=True),
        start=1,
    ):
        text = normalize_for_prompt(chunk_path.read_text(encoding="utf-8-sig"))
        if not text:
            raise ManualTextError(f"Chunk dosyasi bos: {chunk_path}")
        start_page, end_page = _parse_page_range(spec, fallback=source_index)
        page_numbers = list(range(start_page, end_page + 1))

        for part in split_oversized_text(text, max_tokens=max_tokens):
            chunks.append(
                TextChunk(
                    chunk_index=len(chunks) + 1,
                    start_page=start_page,
                    end_page=end_page,
                    text=part,
                    token_count=estimate_tokens(part),
                    page_numbers=page_numbers,
                )
            )

    document = PdfDocument(
        path=directory.resolve(),
        sha256=_bundle_hash(manifest_path, resolved_paths),
        metadata={
            "source_type": "manual_text",
            "manifest": str(manifest_path.resolve()),
        },
        pages=[],
    )
    metadata = BookMetadataGuess(
        title=manifest.title,
        author=manifest.author,
        year=manifest.year,
        confidence=1.0,
        evidence=["Elle girilen metadata.json"],
    )
    return document, metadata, chunks


def load_standalone_text_file(
    path: str | Path,
    max_tokens: int = 1800,
    overlap_tokens: int = 160,
) -> tuple[PdfDocument, BookMetadataGuess, list[TextChunk]]:
    text_path = Path(path)
    text = normalize_for_prompt(text_path.read_text(encoding="utf-8-sig"))
    if not text:
        raise ManualTextError(f"Metin dosyasi bos: {text_path}")

    page = PageText(page_number=1, text=text)
    chunks = chunk_pages([page], max_tokens=max_tokens, overlap_tokens=overlap_tokens)
    metadata = guess_from_filename(text_path).model_copy(
        update={
            "confidence": 0.7,
            "evidence": [f"Standalone TXT dosyasi: {text_path.name}"],
        }
    )
    document = PdfDocument(
        path=text_path.resolve(),
        sha256=hash_file(text_path),
        metadata={
            "source_type": "standalone_text",
            "text_file": str(text_path.resolve()),
        },
        pages=[page],
    )
    return document, metadata, chunks
