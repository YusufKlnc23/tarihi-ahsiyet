from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    database_url: str
    openai_api_key: str | None
    openai_model: str
    metadata_confidence_threshold: float
    chunk_max_tokens: int
    chunk_overlap_tokens: int


def load_settings() -> Settings:
    load_env_file()
    return Settings(
        database_url=os.getenv(
            "DATABASE_URL",
            "postgresql://postgres:postgres@127.0.0.1:5432/tarih_figures",
        ),
        openai_api_key=os.getenv("OPENAI_API_KEY") or None,
        openai_model=os.getenv("OPENAI_MODEL", "gpt-5.6-terra"),
        metadata_confidence_threshold=float(
            os.getenv("METADATA_CONFIDENCE_THRESHOLD", "0.75")
        ),
        chunk_max_tokens=int(os.getenv("CHUNK_MAX_TOKENS", "1800")),
        chunk_overlap_tokens=int(os.getenv("CHUNK_OVERLAP_TOKENS", "160")),
    )


def load_env_file(path: str | Path = ".env", override: bool = True) -> None:
    env_path = Path(path)
    if not env_path.is_file():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if override or key not in os.environ:
            os.environ[key] = value
