from __future__ import annotations

from .config import Settings
from .db import Database
from .retrieval import FigureRetriever, alias_hits
from .schemas import ChatAnswer, Citation, RetrievedChunk
from .text_cleaning import normalize_for_prompt


def citation_from_chunk(chunk: RetrievedChunk) -> Citation:
    pages = (
        str(chunk.start_page)
        if chunk.start_page == chunk.end_page
        else f"{chunk.start_page}-{chunk.end_page}"
    )
    return Citation(
        book_title=chunk.book_title,
        author=chunk.author,
        chunk_id=chunk.chunk_id,
        chunk_index=chunk.chunk_index,
        pages=pages,
    )


def format_sources(chunks: list[RetrievedChunk], max_chars: int = 9000) -> str:
    blocks: list[str] = []
    used = 0
    for chunk in chunks:
        header = (
            f"[chunk_id={chunk.chunk_id}; kitap={chunk.book_title}; "
            f"yazar={chunk.author}; sayfa={chunk.start_page}-{chunk.end_page}; tip={chunk.chunk_type}]"
        )
        body = normalize_for_prompt(chunk.text, max_chars=1800)
        block = f"{header}\n{body}"
        if used + len(block) > max_chars:
            break
        blocks.append(block)
        used += len(block)
    return "\n\n---\n\n".join(blocks)


def build_local_source_answer(
    scope_name: str,
    chunks: list[RetrievedChunk],
    api_unavailable: bool = False,
) -> str:
    lines = [f"{scope_name} icin kaynaklarda su bilgiler one cikiyor:"]
    for index, chunk in enumerate(chunks[:3], start=1):
        preview = normalize_for_prompt(chunk.text, max_chars=650)
        lines.append(
            f"\n{index}. {chunk.book_title}, sayfa {chunk.start_page}-{chunk.end_page}:\n"
            f"{preview}"
        )
    lines.append(f"\nToplam {len(chunks)} kaynak chunk bulundu.")
    if api_unavailable:
        lines.append(
            "\nNot: OpenAI API su an kullanilamadigi icin cevap dogrudan "
            "kaynak chunk'lardan yerel olarak hazirlandi."
        )
    return "\n".join(lines)


class FigureChatService:
    def __init__(self, db: Database, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self.retriever = FigureRetriever(db)

    def infer_figure_from_question(self, question: str) -> dict | None:
        if self.db is None:
            return None
        candidates: list[tuple[int, dict]] = []
        for figure in self.db.list_figures():
            aliases = [figure["name"], *(figure.get("aliases") or [])]
            hits = alias_hits(question, aliases)
            if hits:
                candidates.append((hits, figure))
        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0], reverse=True)
        if len(candidates) > 1 and candidates[0][0] == candidates[1][0]:
            return None
        return candidates[0][1]

    def answer(
        self,
        question: str,
        figure_id: int | None = None,
        use_llm: bool = True,
    ) -> ChatAnswer:
        figure = self.db.get_figure(figure_id) if figure_id is not None else None
        if figure_id is None:
            figure = self.infer_figure_from_question(question)
            if figure:
                figure_id = int(figure["id"])
        if figure_id is not None and not figure:
            return ChatAnswer(answer="Secilen sahsiyet veritabaninda bulunamadi.")

        if figure:
            chunks = self.retriever.retrieve(figure_id=figure_id, question=question)
            scope_name = figure["name"]
            scope_period = figure.get("period") or "Bilinmiyor"
        else:
            chunks = self.retriever.retrieve_general(question=question)
            scope_name = "Tum kaynaklar"
            scope_period = "Genel arama"

        if not chunks:
            return ChatAnswer(
                answer=(
                    "Bu veri icinde soruyu cevaplayacak kaynak chunk bulunamadi. "
                    "Once `python -m tarih_pdf_analyzer ingest data/pdfs --force` "
                    "komutuyla PDF/TXT kaynaklarini yukleyin."
                )
            )

        citations = [citation_from_chunk(chunk) for chunk in chunks]
        if not use_llm or not self.settings.openai_api_key:
            return ChatAnswer(
                answer=build_local_source_answer(scope_name, chunks),
                citations=citations,
            )

        try:
            from .openai_client import load_openai_client, create_chat_completion
        except ImportError:
            return ChatAnswer(
                answer="OpenAI baglayici modul bulunamadi. `pip install openai` veya proje baglantilarini kontrol edin.",
                citations=citations,
            )

        client = load_openai_client(self.settings.openai_api_key)
        system = (
            "Turk tarihi kaynaklari uzerinden cevap veren bir arastirma asistanisin. "
            "Sadece verilen kaynak chunk'lara dayan. Kaynaklarda yoksa bunu acikca soyle. "
            "Secili sahsiyet kaynaklarda acikca gecmiyorsa tahmin yurutme. "
            "Kisi adlari benzerse veya kanit zayifsa belirsiz oldugunu soyle. "
            "Cevabin sonunda kaynak numarasi uydurma; kaynak listesi uygulama tarafindan eklenecek."
        )
        user = (
            f"Kapsam: {scope_name}\n"
            f"Donem: {scope_period}\n"
            f"Soru: {question}\n\n"
            f"Kaynak chunk'lar:\n{format_sources(chunks)}"
        )
        try:
            response = create_chat_completion(
                client,
                model=self.settings.openai_model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0.2,
            )
            content = getattr(response.choices[0], "message", None)
            if isinstance(content, dict):
                answer = content.get("content") or "Cevap uretilemedi."
            else:
                answer = getattr(content, "content", None) or "Cevap uretilemedi."
        except Exception as exc:
            answer = build_local_source_answer(
                scope_name,
                chunks,
                api_unavailable=True,
            )
        return ChatAnswer(answer=answer, citations=citations)
