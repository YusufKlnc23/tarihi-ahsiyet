from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any


def slugify(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9ığüşöçİĞÜŞÖÇ]+", "-", value, flags=re.IGNORECASE)
    value = value.strip("-").lower()
    replacements = str.maketrans("ığüşöç", "igusoc")
    return value.translate(replacements) or "rapor"


def build_markdown_report(report: dict[str, Any]) -> str:
    title = report["title"]
    author = report["author"]
    year = f" ({report['year']})" if report.get("year") else ""
    lines = [
        f"# {title}",
        "",
        f"**Yazar:** {author}{year}",
        f"**Analiz run:** {report['run_id']}",
        "",
        "## Ayrintili Ozet",
        "",
        report["detailed_summary"],
        "",
        "## Ana Tezler",
        "",
    ]
    lines.extend(f"- {item}" for item in report.get("main_theses") or [])
    lines.extend(["", "## Tartisma Konulari", ""])
    for topic in report.get("topics") or []:
        pages = ", ".join(str(page) for page in topic.get("representative_pages", []))
        lines.append(f"### {topic['name']} - %{float(topic['weight']):.1f}")
        lines.append("")
        lines.append(topic["rationale"])
        if pages:
            lines.append("")
            lines.append(f"Temsili sayfalar: {pages}")
        lines.append("")
    lines.extend(["## Tartisma Haritasi", ""])
    lines.extend(f"- {item}" for item in report.get("debate_map") or [])
    lines.extend(["", "## Kanitlar", ""])
    lines.extend(f"- {item}" for item in report.get("evidence") or [])
    lines.append("")
    return "\n".join(lines)


def write_json_report(report: dict[str, Any], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{report['book_id']:04d}-{slugify(report['title'])}.json"
    with path.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2, default=str)
    return path


def write_markdown_report(report: dict[str, Any], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{report['book_id']:04d}-{slugify(report['title'])}.md"
    path.write_text(build_markdown_report(report), encoding="utf-8")
    return path


def write_topics_csv(reports: list[dict[str, Any]], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "book_topics.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "book_id",
                "title",
                "author",
                "run_id",
                "topic",
                "weight",
                "representative_pages",
                "rationale",
            ]
        )
        for report in reports:
            for topic in report.get("topics") or []:
                writer.writerow(
                    [
                        report["book_id"],
                        report["title"],
                        report["author"],
                        report["run_id"],
                        topic["name"],
                        topic["weight"],
                        ",".join(str(page) for page in topic.get("representative_pages", [])),
                        topic["rationale"],
                    ]
                )
    return path
