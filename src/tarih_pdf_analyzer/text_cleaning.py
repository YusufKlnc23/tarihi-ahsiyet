from __future__ import annotations

import re
from collections import Counter

from .models import PageText


_PAGE_NUMBER_RE = re.compile(r"^\s*(?:-?\s*)?\d{1,4}(?:\s*-?)?\s*$")
_WHITESPACE_RE = re.compile(r"[ \t]+")
_MOJIBAKE_MARKERS = ("\u00c3", "\u00c4", "\u00c5", "\u00e2\u20ac", "\u00c2")
_MOJIBAKE_REPLACEMENTS = {
    "\u00c3\u00a7": "\u00e7",
    "\u00c3\u2021": "\u00c7",
    "\u00c4\u0178": "\u011f",
    "\u00c4\u017e": "\u011e",
    "\u00c4\u00b1": "\u0131",
    "\u00c4\u00b0": "\u0130",
    "\u00c3\u00b6": "\u00f6",
    "\u00c3\u2013": "\u00d6",
    "\u00c5\u0178": "\u015f",
    "\u00c5\u017e": "\u015e",
    "\u00c3\u00bc": "\u00fc",
    "\u00c3\u0153": "\u00dc",
    "\u00e2\u20ac\u2122": "'",
    "\u00e2\u20ac\u02dc": "'",
    "\u00e2\u20ac\u0153": '"',
    "\u00e2\u20ac\u009d": '"',
    "\u00e2\u20ac\u201c": "-",
    "\u00e2\u20ac\u201d": "-",
    "\u00c2 ": " ",
    "\u00c2": "",
}


def repair_mojibake(text: str) -> str:
    if not text:
        return text

    repaired = text
    if any(marker in repaired for marker in _MOJIBAKE_MARKERS):
        try:
            repaired = repaired.encode("cp1252").decode("utf-8")
        except UnicodeError:
            pass
    for bad, good in _MOJIBAKE_REPLACEMENTS.items():
        repaired = repaired.replace(bad, good)
    return repaired


def clean_page_text(text: str) -> str:
    text = repair_mojibake(text)
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
    normalized = re.sub(r"\n{3,}", "\n\n", repair_mojibake(text).strip())
    if max_chars is not None and len(normalized) > max_chars:
        return normalized[:max_chars].rsplit(" ", 1)[0]
    return normalized
