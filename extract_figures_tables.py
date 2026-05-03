#!/usr/bin/env python3
"""
Extract figure and table captions from all PDFs in the material folder
and write a structured markdown reference file.

Usage:
    python3 extract_figures_tables.py [output.md]

Output defaults to: material/figures_tables_index.md
"""

import fitz  # PyMuPDF
import re
import sys
import pathlib
from collections import defaultdict

MATERIAL_DIR = pathlib.Path(__file__).parent
OUTPUT_FILE = MATERIAL_DIR / "figures_tables_index.md"

# Matches captions that start at the beginning of a text block and have a
# separator (. : – - —) after the label, distinguishing them from inline refs.
CAPTION_RE = re.compile(
    r'^(Fig(?:ure)?\.?\s*\d+[\w]*'
    r'|Table\s+\d+[\w]*'
    r'|Tabela\s+\d+[\w]*'
    r'|Figura\s+\d+[\w]*'
    r')'
    r'[.\s]*[:.–\-—]\s+'
    r'(.+)',
    re.IGNORECASE | re.MULTILINE,
)

SKIP_DIRS = {".git", "__pycache__", ".claude"}
CAPTION_MAX_CHARS = 350


def normalize_label(raw: str) -> str:
    label = re.sub(r'^Fig\.\s*', 'Figure ', raw.strip(), flags=re.IGNORECASE)
    label = re.sub(r'\s+', ' ', label).rstrip('.')
    # Capitalise first word
    return label[0].upper() + label[1:] if label else label


def extract_captions(pdf_path: pathlib.Path) -> list[dict]:
    """Return list of {label, caption, page} dicts for one PDF."""
    try:
        doc = fitz.open(str(pdf_path))
    except Exception:
        return []

    seen: set[str] = set()
    captions: list[dict] = []

    for page_num, page in enumerate(doc, start=1):
        blocks = page.get_text("blocks")
        for block in blocks:
            block_text = block[4].strip()
            m = CAPTION_RE.match(block_text)
            if not m:
                continue
            label = normalize_label(m.group(1))
            key = label.lower()
            if key in seen:
                continue
            seen.add(key)
            caption = block_text[m.start(2):].replace('\n', ' ').strip()
            caption = re.sub(r'\s+', ' ', caption)[:CAPTION_MAX_CHARS]
            kind = "table" if label.lower().startswith("tab") else "figure"
            captions.append({"label": label, "caption": caption, "page": page_num, "kind": kind})

    doc.close()
    return captions


def collect_all(material_dir: pathlib.Path) -> dict[str, list[dict]]:
    """Walk material_dir, extract captions from every PDF."""
    per_folder: dict[str, list[tuple[str, list[dict]]]] = defaultdict(list)

    pdf_paths = sorted(
        p for p in material_dir.rglob("*.pdf")
        if not any(part in SKIP_DIRS for part in p.parts)
    )

    total = len(pdf_paths)
    for i, pdf_path in enumerate(pdf_paths, start=1):
        folder = pdf_path.parent.name
        captions = extract_captions(pdf_path)
        if captions:
            per_folder[folder].append((pdf_path.name, captions))
        print(f"  [{i}/{total}] {pdf_path.name[:60]} — {len(captions)} captions", flush=True)

    return per_folder


def write_markdown(per_folder: dict, output_path: pathlib.Path) -> None:
    lines = [
        "# Figures and Tables Index",
        "",
        "Auto-generated index of figure and table captions extracted from PDFs in the `material/` folder.",
        "",
        f"**Generated:** 2026-05-03  ",
        f"**Source folder:** `material/`",
        "",
        "---",
        "",
    ]

    total_figures = total_tables = total_papers = 0

    for folder in sorted(per_folder.keys()):
        papers = per_folder[folder]
        if not papers:
            continue

        lines.append(f"## {folder}")
        lines.append("")

        for paper_name, captions in sorted(papers, key=lambda x: x[0]):
            figures = [c for c in captions if c["kind"] == "figure"]
            tables  = [c for c in captions if c["kind"] == "table"]

            lines.append(f"### {paper_name}")
            lines.append("")

            if figures:
                lines.append("**Figures**")
                lines.append("")
                for c in sorted(figures, key=lambda x: x["label"]):
                    lines.append(f"- **{c['label']}** (p. {c['page']}): {c['caption']}")
                lines.append("")

            if tables:
                lines.append("**Tables**")
                lines.append("")
                for c in sorted(tables, key=lambda x: x["label"]):
                    lines.append(f"- **{c['label']}** (p. {c['page']}): {c['caption']}")
                lines.append("")

            total_figures += len(figures)
            total_tables  += len(tables)
            total_papers  += 1

    # Summary at the top (insert after the header)
    summary = [
        f"**Summary:** {total_papers} papers · {total_figures} figures · {total_tables} tables",
        "",
    ]
    insert_at = lines.index("---") + 2
    for j, s in enumerate(summary):
        lines.insert(insert_at + j, s)

    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nWrote {output_path} ({total_papers} papers, {total_figures} figures, {total_tables} tables)")


def main() -> None:
    output = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else OUTPUT_FILE
    print(f"Scanning {MATERIAL_DIR} ...")
    per_folder = collect_all(MATERIAL_DIR)
    write_markdown(per_folder, output)


if __name__ == "__main__":
    main()
