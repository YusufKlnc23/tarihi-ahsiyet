from __future__ import annotations

import time
import re
import unicodedata
from collections import Counter, defaultdict
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

try:
    import gradio as gr  # type: ignore[import-not-found]

except ImportError as exc:
    raise ImportError(
        "gradio package is required to run this app. Install it with 'pip install gradio'."
    ) from exc

from tarih_pdf_analyzer.chat import FigureChatService
from tarih_pdf_analyzer.cli import command_ingest, command_load_figures
from tarih_pdf_analyzer.config import load_settings
from tarih_pdf_analyzer.db import Database


APP_CSS = """
:root {
    --panel-border: #d7dde8;
    --panel-bg: #f7f9fc;
    --ink: #1f2937;
}
.top-panel {
    border: 1px solid var(--panel-border);
    border-radius: 8px;
    padding: 18px 20px;
    background: var(--panel-bg);
}
.top-panel h1 {
    margin-bottom: 10px;
}
.status-box textarea {
    font-size: 13px !important;
}
.source-box {
    border-left: 4px solid #476582;
    padding-left: 12px;
}
.command-box {
    border: 1px solid var(--panel-border);
    border-radius: 8px;
    padding: 12px;
    background: #ffffff;
}
"""


settings = load_settings()
db = Database(settings.database_url)

SOURCE_DIR = Path("data/pdfs")
_TR_MAP = str.maketrans(
    {
        "ç": "c",
        "Ç": "c",
        "ğ": "g",
        "Ğ": "g",
        "ı": "i",
        "I": "i",
        "İ": "i",
        "ö": "o",
        "Ö": "o",
        "ş": "s",
        "Ş": "s",
        "ü": "u",
        "Ü": "u",
    }
)


FigureChoice = tuple[str, str]


def figure_choices() -> list[FigureChoice]:
    try:
        db.init_schema()
        figures = db.list_figures()
    except Exception:
        return [("0: Tum kaynaklar", "0")]
    return [
        ("0: Tum kaynaklar", "0"),
        *[
            (f"{index}: {figure['name']}", str(figure["id"]))
            for index, figure in enumerate(figures, start=1)
        ],
    ]


def source_choices() -> list[str]:
    if not SOURCE_DIR.is_dir():
        return []
    paths = sorted(
        [
            path
            for path in SOURCE_DIR.iterdir()
            if path.is_file() and path.suffix.lower() in {".pdf", ".txt"}
        ],
        key=lambda item: item.name.lower(),
    )
    return [path.name for path in paths]


def refresh_figure_choices():
    choices = figure_choices()
    return gr.update(choices=choices, value=choices[0][1] if choices else None)


def refresh_source_choices():
    choices = source_choices()
    return gr.update(choices=choices, value=choices[0] if choices else None)


def parse_figure_id(value: str | None) -> int | None:
    if not value or value == "0" or value.startswith("0:"):
        return None
    try:
        if ":" in value:
            return int(value.split(":", 1)[0])
        return int(value)
    except ValueError:
        return None


def source_markdown(answer) -> str:
    if not answer.citations:
        return "### Kaynaklar\nKaynak eslesmesi bulunamadi."
    lines = ["### Kaynaklar"]
    for citation in answer.citations:
        lines.append(
            (
                f"- **{citation.book_title}** / {citation.author}, "
                f"chunk {citation.chunk_index}, sayfa {citation.pages}"
            )
        )
    return "\n".join(lines)


def source_status() -> str:
    try:
        db.init_schema()
        stats = db.source_stats()
        return (
            "Database hazir.\n"
            f"Kitap/kaynak: {stats['books']}\n"
            f"Chunk: {stats['chunks']}\n"
            f"Sahsiyet: {stats['figures']}"
        )
    except Exception as exc:
        return (
            "Database baglantisi kurulamadi.\n"
            "DATABASE_URL degerini .env dosyasinda veya PowerShell ortaminda kontrol edin.\n\n"
            f"Hata: {exc}"
        )


def normalize_match(value: str) -> str:
    value = value.translate(_TR_MAP)
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    return ascii_value.casefold()


def count_figure_mentions(text: str, figures: list[dict]) -> tuple[Counter, dict[str, set[str]]]:
    normalized_text = normalize_match(text)
    counts: Counter = Counter()
    matched_aliases: dict[str, set[str]] = defaultdict(set)
    for figure in figures:
        aliases = [figure["name"], *(figure.get("aliases") or [])]
        normalized_aliases = sorted(
            {normalize_match(alias).strip() for alias in aliases if alias.strip()},
            key=len,
            reverse=True,
        )
        for alias in normalized_aliases:
            if len(alias) < 3:
                continue
            hits = len(re.findall(rf"\b{re.escape(alias)}\b", normalized_text))
            if hits:
                counts[figure["name"]] += hits
                matched_aliases[figure["name"]].add(alias)
    return counts, matched_aliases


def inspect_selected_source(source_name: str | None) -> str:
    if not source_name:
        return "### Kaynak inceleme\nKaynak secilmedi."
    source_path = (SOURCE_DIR / source_name).resolve()
    if SOURCE_DIR.resolve() not in source_path.parents:
        return "### Kaynak inceleme\nGecersiz kaynak yolu."
    if not source_path.is_file():
        return f"### Kaynak inceleme\nDosya bulunamadi: `{source_name}`"

    try:
        db.init_schema()
        figures = db.list_figures()
    except Exception as exc:
        return f"### Kaynak inceleme\nDatabase baglantisi kurulamadi.\n\nHata: `{exc}`"

    total_chars = 0
    page_count = 1
    counts: Counter = Counter()
    matched_aliases: dict[str, set[str]] = defaultdict(set)

    try:
        if source_path.suffix.lower() == ".pdf":
            import fitz  # type: ignore[import-not-found]

            document = fitz.open(source_path)
            page_count = document.page_count
            for page in document:
                text = page.get_text("text") or ""
                total_chars += len(text.strip())
                page_counts, page_aliases = count_figure_mentions(text, figures)
                counts.update(page_counts)
                for figure_name, aliases in page_aliases.items():
                    matched_aliases[figure_name].update(aliases)
            document.close()
        else:
            text = source_path.read_text(encoding="utf-8-sig")
            total_chars = len(text.strip())
            page_count = 1
            counts, matched_aliases = count_figure_mentions(text, figures)
    except Exception as exc:
        return f"### Kaynak inceleme\nDosya okunamadi: `{source_name}`\n\nHata: `{exc}`"

    lines = [
        "### Kaynak inceleme",
        f"**Dosya:** `{source_name}`",
        f"**Sayfa:** {page_count}",
        f"**Cikarilabilen metin karakteri:** {total_chars}",
    ]

    if total_chars < 1000 and source_path.suffix.lower() == ".pdf":
        lines.extend(
            [
                "",
                "**Sonuc:** Bu PDF secilebilir metin icermiyor veya metin cok az.",
                "Bu nedenle tarihi sahsiyet bilgisi guvenilir sekilde cikarilamaz.",
                "",
                "**Gereken islem:** OCR uygulanmis yeni bir PDF olusturup tekrar ingest et.",
                "",
                "```powershell",
                f"ocrmypdf -l tur+eng data/pdfs/{source_name} data/pdfs/{source_path.stem}_ocr.pdf",
                ".\\.venv\\Scripts\\python.exe -m tarih_pdf_analyzer ingest data/pdfs --force",
                "```",
            ]
        )
        return "\n".join(lines)

    if not figures:
        lines.append("\nSahsiyet listesi bos. Once `load-figures` calistir.")
        return "\n".join(lines)

    if not counts:
        lines.append("\nYuklu sahsiyet adlariyla eslesen kayit bulunamadi.")
        return "\n".join(lines)

    lines.append("\n**Bulunan sahsiyetler:**")
    for figure_name, hit_count in counts.most_common(15):
        aliases = ", ".join(sorted(matched_aliases.get(figure_name, [])))
        lines.append(f"- **{figure_name}**: {hit_count} eslesme" + (f" ({aliases})" if aliases else ""))
    return "\n".join(lines)


def ingest_sources() -> str:
    output = StringIO()
    try:
        db.init_schema()
        args = SimpleNamespace(
            pdf_dir=Path("data/pdfs"),
            force=True,
            llm_metadata=False,
        )
        with redirect_stdout(output):
            manifest = Path("data/figures.example.json")
            if manifest.is_file():
                command_load_figures(SimpleNamespace(manifest=manifest), db)
            command_ingest(args, db, settings)
        log = output.getvalue().strip()
        return f"{source_status()}\n\nIslem logu:\n{log[-3500:]}"
    except Exception as exc:
        log = output.getvalue().strip()
        return (
            "Kaynak islemesi basarisiz.\n"
            "DATABASE_URL ayarini ve PostgreSQL servisinin calistigini kontrol edin.\n\n"
            f"Hata: {exc}\n\n"
            f"Islem logu:\n{log[-2500:] if log else '-'}"
        )


def append_exchange(history: list | None, message: str, response: str) -> list[dict[str, str]]:
    messages = list(history or [])
    messages.append({"role": "user", "content": message})
    messages.append({"role": "assistant", "content": response})
    return messages


def chat_turn(message: str, history: list | None, figure: str | None):
    if not message.strip():
        return history or [], "### Kaynaklar\nSoru girilmedi.", ""
    try:
        service = FigureChatService(db, settings)
        answer = service.answer(message, figure_id=parse_figure_id(figure))
        return append_exchange(history, message, answer.answer), source_markdown(answer), ""
    except Exception as exc:
        response = (
            "Uygulama cevap uretirken hata aldi. Database baglantisini, "
            "chunk yuklemesini ve OPENAI_API_KEY ayarini kontrol edin.\n\n"
            f"Hata: {exc}"
        )
        return (
            append_exchange(history, message, response),
            "### Kaynaklar\nHata nedeniyle kaynak listesi uretilemedi.",
            "",
        )

with gr.Blocks(title="Tarihi Sahsiyet Chat") as demo:
    with gr.Column(elem_classes=["top-panel"]):
        gr.Markdown(
            """
# Tarihi Sahsiyet Chat

PDF ve TXT kaynaklardan uretilen chunk'lara dayanarak cevap verir. Sahsiyet secmeden sorarsan tum kaynaklarda arama yapar.
"""
        )

    with gr.Row():
        with gr.Column(scale=1, min_width=280):
            status = gr.Textbox(
                value="Kaynak durumunu gormek icin 'Kaynaklari yenile' butonuna basin.",
                label="Kaynak durumu",
                lines=5,
                interactive=False,
                elem_classes=["status-box"],
            )
            figure_dropdown = gr.Dropdown(
                choices=[("0: Tum kaynaklar", "0")],
                value="0",
                label="Soru kapsami",
                interactive=True,
            )
            refresh_button = gr.Button("Kaynaklari yenile")
            refresh_button.click(fn=source_status, outputs=status)
            refresh_button.click(fn=refresh_figure_choices, outputs=figure_dropdown)
            ingest_button = gr.Button("PDF/TXT chunk olustur", variant="secondary")
            ingest_button.click(fn=ingest_sources, outputs=status)
            ingest_button.click(fn=refresh_figure_choices, outputs=figure_dropdown)

            source_dropdown = gr.Dropdown(
                choices=source_choices(),
                value=source_choices()[0] if source_choices() else None,
                label="Kaynak incele",
                interactive=True,
            )
            inspect_button = gr.Button("Sahsiyetleri tara", variant="secondary")
            source_report = gr.Markdown("### Kaynak inceleme\nKaynak secip tarama baslat.")
            refresh_button.click(fn=refresh_source_choices, outputs=source_dropdown)
            ingest_button.click(fn=refresh_source_choices, outputs=source_dropdown)
            inspect_button.click(
                fn=inspect_selected_source,
                inputs=source_dropdown,
                outputs=source_report,
            )

            gr.Markdown(

                """
<div class="command-box">

**Veri hazirlama**

```powershell
uv --cache-dir .uv-cache run python -m tarih_pdf_analyzer init-db
uv --cache-dir .uv-cache run python -m tarih_pdf_analyzer load-figures data/figures.example.json
uv --cache-dir .uv-cache run python -m tarih_pdf_analyzer ingest data/pdfs --force
```

</div>
"""
            )

        with gr.Column(scale=3):
            chatbot = gr.Chatbot(label="Sohbet", height=520)
            question = gr.Textbox(
                label="Soru",
                placeholder="Ornek: Enver Pasa bu kaynaklarda nasil degerlendiriliyor?",
                lines=3,
            )
            with gr.Row():
                send = gr.Button("Sor", variant="primary")
                clear = gr.Button("Temizle")
            sources = gr.Markdown(
                "### Kaynaklar\nHenuz soru sorulmadi.",
                elem_classes=["source-box"],
            )

            send.click(
                fn=chat_turn,
                inputs=[question, chatbot, figure_dropdown],
                outputs=[chatbot, sources, question],
            )
            question.submit(
                fn=chat_turn,
                inputs=[question, chatbot, figure_dropdown],
                outputs=[chatbot, sources, question],
            )
            clear.click(
                fn=lambda: ([], "### Kaynaklar\nHenuz soru sorulmadi.", ""),
                outputs=[chatbot, sources, question],
            )

    demo.load(fn=source_status, outputs=status)
    demo.load(fn=refresh_figure_choices, outputs=figure_dropdown)
     
     


if __name__ == "__main__":
    demo.launch(
        server_name="127.0.0.1",
        server_port=7860,
        css=APP_CSS,
        prevent_thread_lock=True,
    )
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
