from __future__ import annotations

from typing import Any

from .chat import FigureChatService
from .config import load_settings
from .db import Database


def _citation_payload(citation: Any) -> dict[str, Any]:
    if hasattr(citation, "model_dump"):
        return citation.model_dump()
    return {
        "book_title": getattr(citation, "book_title", ""),
        "author": getattr(citation, "author", ""),
        "chunk_id": getattr(citation, "chunk_id", None),
        "chunk_index": getattr(citation, "chunk_index", None),
        "pages": getattr(citation, "pages", ""),
    }


def build_server() -> Any:
    try:
        from mcp.server.fastmcp import FastMCP  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError(
            "MCP server icin `mcp` paketi gerekli. Kurulum: pip install -e .[mcp]"
        ) from exc

    settings = load_settings()
    db = Database(settings.database_url)
    server = FastMCP("tarih-sahsiyet-chat")

    @server.tool()
    def list_figures() -> list[dict[str, Any]]:
        """PostgreSQL'deki tarihi sahsiyetleri listeler."""
        db.init_schema()
        return [
            {
                "id": figure["id"],
                "name": figure["name"],
                "period": figure.get("period"),
                "aliases": figure.get("aliases") or [],
            }
            for figure in db.list_figures()
        ]

    @server.tool()
    def ask_figure(figure_id: int, question: str) -> dict[str, Any]:
        """Secili tarihi sahsiyet hakkinda kaynakli cevap uretir."""
        db.init_schema()
        answer = FigureChatService(db, settings).answer(
            question=question,
            figure_id=figure_id,
            use_llm=True,
        )
        return {
            "answer": answer.answer,
            "citations": [_citation_payload(citation) for citation in answer.citations],
        }

    @server.tool()
    def search_sources(question: str) -> dict[str, Any]:
        """Tum kaynak chunk'lari icinde soru ile ilgili kaynaklari arar."""
        db.init_schema()
        answer = FigureChatService(db, settings).answer(
            question=question,
            figure_id=None,
            use_llm=False,
        )
        return {
            "answer": answer.answer,
            "citations": [_citation_payload(citation) for citation in answer.citations],
        }

    return server


def main() -> None:
    build_server().run()


if __name__ == "__main__":
    main()
