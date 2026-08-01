from __future__ import annotations

import re
from collections import Counter

from .models import PageText


_PAGE_NUMBER_RE = re.compile(r"^\s*(?:-?\s*)?\d{1,4}(?:\s*-?)?\s*$")
_WHITESPACE_RE = re.compile(r"[ \t]+")


def clean_page_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    lines = []
    for raw_line in text.split("\n"):
        line = _WHITESPACE_RE.sub(" ", raw_line).strip()
        if not line:
            continue
        if _PAGE_NUMBER_RE.match(line):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def remove_repeated_headers_footers(pages: list[PageText]) -> list[PageText]:
    if len(pages) < 4:
        return pages

    candidates: Counter[str] = Counter()
    for page in pages:
        lines = [line.strip() for line in page.text.splitlines() if line.strip()]
        for line in (lines[:2] + lines[-2:]):
            if 3 <= len(line) <= 120:
                candidates[line] += 1

    threshold = max(3, int(len(pages) * 0.35))
    repeated = {line for line, count in candidates.items() if count >= threshold}
    if not repeated:
        return pages

    cleaned = []
    for page in pages:
        lines = [
            line
            for line in page.text.splitlines()
            if line.strip() and line.strip() not in repeated
        ]
        cleaned.append(PageText(page_number=page.page_number, text="\n".join(lines)))
    return cleaned


def normalize_for_prompt(text: str, max_chars: int | None = None) -> str:
    normalized = re.sub(r"\n{3,}", "\n\n", text.strip())
    if max_chars is not None and len(normalized) > max_chars:
        return normalized[:max_chars].rsplit(" ", 1)[0]
    return normalized
