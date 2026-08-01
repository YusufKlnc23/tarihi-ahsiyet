from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

from .schemas import FigureManifest, FigureSeed


def slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_value).strip("-").lower()
    return slug or "figure"


def load_figure_manifest(path: str | Path) -> list[FigureSeed]:
    manifest_path = Path(path)
    if not manifest_path.is_file():
        return []
    data = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    manifest = FigureManifest.model_validate(data)
    return manifest.figures
