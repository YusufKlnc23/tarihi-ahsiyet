from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class PageText:
    page_number: int
    text: str


@dataclass(frozen=True)
class PdfDocument:
    path: Path
    sha256: str
    metadata: dict[str, str]
    pages: list[PageText]


@dataclass(frozen=True)
class TextChunk:
    chunk_index: int
    start_page: int
    end_page: int
    text: str
    token_count: int
    page_numbers: list[int] = field(default_factory=list)
    chunk_type: str = "source"


