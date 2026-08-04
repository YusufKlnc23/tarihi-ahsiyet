from __future__ import annotations

import os
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
    --border: #d9e0e8;
    --ink: #172033;
    --muted: #667085;
    --surface: #ffffff;
    --surface-soft: #f6f8fb;
    --accent: #245f73;
}
.gradio-container {
    max-width: 100vw !important;
    min-height: 100vh !important;
    padding: 12px !important;
    background: var(--surface-soft);
}
.app-shell {
    min-height: calc(100vh - 24px);
    display: grid;
    grid-template-rows: auto 1fr;
    gap: 10px;
}
.app-header {
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 14px 16px;
    background: var(--surface);
}
.app-header h1 {
    margin: 0;
    font-size: 24px;
    line-height: 1.2;
    color: var(--ink);
}
.app-header p {
    margin: 4px 0 0;
    color: var(--muted);
    font-size: 14px;
}
.chat-grid {
    min-height: 0;
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    gap: 10px;
}
.admin-panel {
    max-width: 320px;
}
.chat-column {
    min-height: 0;
}
.chatbot-main {
    height: calc(100vh - 238px) !important;
    min-height: 430px !important;
}
.input-panel {
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 10px;
    background: var(--surface);
}
.status-box textarea {
    font-size: 13px !important;
}
.example-row button {
    min-height: 38px;
}
@media (max-width: 760px) {
    .gradio-container {
        padding: 8px !important;
    }
    .app-header h1 {
        font-size: 20px;
    }
    .chatbot-main {
        height: calc(100vh - 270px) !important;
        min-height: 360px !important;
    }
}
"""


settings = load_settings()
db = Database(settings.database_url)

SOURCE_DIR = Path("data/pdfs")
SHOW_ADMIN_PANEL = os.getenv("SHOW_ADMIN_PANEL", "").strip().lower() in {"1", "true", "yes", "on"}
PUBLIC_DEMO = not SHOW_ADMIN_PANEL
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


def demo_mode_note() -> str:
    if PUBLIC_DEMO:
        return (
            "Demo modu aktif. Kaynak yukleme ve dosya inceleme kontrolleri gizli; "
            "sohbet mevcut PostgreSQL chunk'lari ve Gemini uzerinden calisir."
        )
    return (
        "Yerel yonetim modu aktif. Kaynak yukleme ve dosya inceleme kontrolleri kullanilabilir."
    )


def parse_figure_id(value: str | None) -> int | None:
    if not value or value == "0" or value.startswith("0:"):
        return None
    try:
        if ":" in value:
            return int(value.split(":", 1)[0])
        return int(value)
    except ValueError:
        return None


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
        return history or [], ""
    try:
        service = FigureChatService(db, settings)
        answer = service.answer(message, figure_id=parse_figure_id(figure))
        return append_exchange(history, message, answer.answer), ""
    except Exception as exc:
        response = (
            "Uygulama cevap uretirken hata aldi. Database baglantisini, "
            "chunk yuklemesini ve GEMINI_API_KEY ayarini kontrol edin.\n\n"
            f"Hata: {exc}"
        )
        return append_exchange(history, message, response), ""


def set_question(prompt: str) -> str:
    return prompt


def launch_kwargs() -> dict:
    kwargs = {
        "server_name": os.getenv("GRADIO_SERVER_NAME", "127.0.0.1"),
        "server_port": int(os.getenv("PORT") or os.getenv("GRADIO_SERVER_PORT") or "7860"),
        "css": APP_CSS,
        "prevent_thread_lock": True,
        "share": os.getenv("GRADIO_SHARE", "").strip().lower() in {"1", "true", "yes", "on"},
    }
    username = os.getenv("DEMO_USERNAME")
    password = os.getenv("DEMO_PASSWORD")
    if username and password:
        kwargs["auth"] = (username, password)
    return kwargs

with gr.Blocks(title="Tarihi Sahsiyet Chat") as demo:
    with gr.Column(elem_classes=["app-shell"]):
        gr.Markdown(
            """
<div class="app-header">
  <h1>Tarihi Sahsiyet Chat</h1>
  <p>Turk tarihi sahsiyetleri uzerine kaynaklara dayali sohbet.</p>
</div>
"""
        )

        with gr.Row(elem_classes=["chat-grid"]):
            if SHOW_ADMIN_PANEL:
                with gr.Column(scale=1, min_width=260, elem_classes=["admin-panel"]):
                    status = gr.Textbox(
                        value="Kaynak durumunu gormek icin 'Kaynaklari yenile' butonuna basin.",
                        label="Kaynak durumu",
                        lines=5,
                        interactive=False,
                        elem_classes=["status-box"],
                    )
                    refresh_button = gr.Button("Kaynaklari yenile")
                    ingest_button = gr.Button("PDF/TXT chunk olustur", variant="secondary")

                    source_dropdown = gr.Dropdown(
                        choices=source_choices(),
                        value=source_choices()[0] if source_choices() else None,
                        label="Kaynak incele",
                        interactive=True,
                    )
                    inspect_button = gr.Button("Sahsiyetleri tara", variant="secondary")
                    source_report = gr.Markdown("### Kaynak inceleme\nKaynak secip tarama baslat.")

            with gr.Column(scale=4, elem_classes=["chat-column"]):
                figure_dropdown = gr.Dropdown(
                    choices=[("Tum kaynaklar", "0")],
                    value="0",
                    label="Soru kapsami",
                    interactive=True,
                )
                chatbot = gr.Chatbot(label="Sohbet", height=620, elem_classes=["chatbot-main"])
                with gr.Column(elem_classes=["input-panel"]):
                    question = gr.Textbox(
                        label="Soru",
                        placeholder="Ornek: Enver Pasa Babiali Baskini'nda ne yapti?",
                        lines=2,
                    )
                    with gr.Row(elem_classes=["example-row"]):
                        example_one = gr.Button("Babiali Baskini")
                        example_two = gr.Button("II. Mesrutiyet")
                        example_three = gr.Button("Mehmed Resad")
                    with gr.Row():
                        send = gr.Button("Sor", variant="primary")
                        clear = gr.Button("Temizle")

                example_one.click(
                    fn=lambda: set_question("Enver Pasa Babiali Baskini'nda ne yapti?"),
                    outputs=question,
                )
                example_two.click(
                    fn=lambda: set_question("II. Mesrutiyet surecinde one cikan sahsiyetler kimlerdi?"),
                    outputs=question,
                )
                example_three.click(
                    fn=lambda: set_question("Mehmed Resad Ittihat ve Terakki doneminde nasil bir roldeydi?"),
                    outputs=question,
                )
                send.click(
                    fn=chat_turn,
                    inputs=[question, chatbot, figure_dropdown],
                    outputs=[chatbot, question],
                )
                question.submit(
                    fn=chat_turn,
                    inputs=[question, chatbot, figure_dropdown],
                    outputs=[chatbot, question],
                )
                clear.click(
                    fn=lambda: ([], ""),
                    outputs=[chatbot, question],
                )

    if SHOW_ADMIN_PANEL:
        refresh_button.click(fn=source_status, outputs=status)
        refresh_button.click(fn=refresh_figure_choices, outputs=figure_dropdown)
        ingest_button.click(fn=ingest_sources, outputs=status)
        ingest_button.click(fn=refresh_figure_choices, outputs=figure_dropdown)
        refresh_button.click(fn=refresh_source_choices, outputs=source_dropdown)
        ingest_button.click(fn=refresh_source_choices, outputs=source_dropdown)
        inspect_button.click(
            fn=inspect_selected_source,
            inputs=source_dropdown,
            outputs=source_report,
        )
        demo.load(fn=source_status, outputs=status)
    demo.load(fn=refresh_figure_choices, outputs=figure_dropdown)


if __name__ == "__main__":
    demo.queue(max_size=16).launch(**launch_kwargs())
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
