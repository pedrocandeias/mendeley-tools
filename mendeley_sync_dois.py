#!/usr/bin/env python3
"""Sincroniza DOIs entre a bibliografia do manuscrito e a biblioteca Mendeley.

O DOCX canónico é gerido pelo Mendeley Cite (Word): a bibliografia
regenera-se a partir da biblioteca na nuvem em cada Refresh. Este script
garante que os registos da nuvem têm os DOIs corretos antes do Refresh:

  1. Entradas do manuscrito COM DOI (auditadas à mão) — o registo Mendeley
     correspondente recebe esse DOI se estiver em falta ou divergente.
  2. Entradas SEM DOI com DOI verificado externamente (CrossRef, com
     confirmação de autor e ano) — fornecidas num JSON via --dois.
  3. Registos com DOI comprovadamente errado — limpos via --clear.

Uso:
    mendeley_sync_dois.py [--apply] [--dois novos.json] [--clear ref-x ...]

O ficheiro --dois é um JSON {"ref-slug": "10.xxxx/...", ...}. Os slugs
são as âncoras <a id="ref-..."> da secção Bibliografia do Markdown.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
import unicodedata
from pathlib import Path

from mendeley_enrich import MendeleyAPI, load_credentials, similarity
from mendeley_paths import resolve_manuscript

MATCH_THRESHOLD = 0.70


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


def bare_doi(doi: str) -> str:
    return re.sub(r"^https?://(dx\.)?doi\.org/", "", doi.strip())


def parse_bibliography(md: Path) -> list[dict]:
    """Extrai (slug, texto, título, ano, doi) da secção Bibliografia."""
    lines = md.read_text(encoding="utf-8").split("\n")
    try:
        start = next(i for i, l in enumerate(lines) if l.strip() == "## Bibliografia")
        end = next(i for i in range(start + 1, len(lines))
                   if lines[i].startswith("## "))
    except StopIteration:
        raise RuntimeError("Secção '## Bibliografia' não encontrada")
    entries = []
    for line in lines[start:end]:
        m = re.match(r'<a id="(ref-[^"]+)"></a> (.*)', line)
        if not m:
            continue
        slug, text = m.group(1), m.group(2).rstrip()
        y = re.search(r"\((\d{4})", text)
        t = re.search(r"\(\d{4}[^)]*\)\.\s*\*?([^*.]+(?:\.[^ .][^.]*)*?)[.*]", text)
        d = re.search(r"https?://doi\.org/(\S+?)\.?$", text)
        entries.append({
            "slug": slug, "text": text,
            "year": int(y.group(1)) if y else None,
            "title": t.group(1).strip() if t else "",
            "md_doi": d.group(1) if d else None,
        })
    return entries


def match_record(entry: dict, docs: list[dict]):
    best, score = None, 0.0
    for d in docs:
        s = similarity(entry["title"] or entry["text"][:80], d.get("title", ""))
        if s > score:
            best, score = d, s
    if best is None or score < MATCH_THRESHOLD:
        return None, score
    ry, ey = best.get("year"), entry["year"]
    if ry is not None and ey is not None and abs(ry - ey) > 1:
        return None, score
    return best, score


async def main() -> None:
    apply = "--apply" in sys.argv
    md_arg = None
    if "--md" in sys.argv:
        md_arg = Path(sys.argv[sys.argv.index("--md") + 1])
    md = resolve_manuscript(md_arg, required=True)
    new_dois: dict[str, str] = {}
    if "--dois" in sys.argv:
        path = sys.argv[sys.argv.index("--dois") + 1]
        new_dois = {k: bare_doi(v) for k, v in json.load(open(path)).items()}
    clear_slugs = set()
    if "--clear" in sys.argv:
        idx = sys.argv.index("--clear") + 1
        while idx < len(sys.argv) and not sys.argv[idx].startswith("--"):
            clear_slugs.add(sys.argv[idx])
            idx += 1
    skip_slugs = set()
    if "--skip" in sys.argv:
        idx = sys.argv.index("--skip") + 1
        while idx < len(sys.argv) and not sys.argv[idx].startswith("--"):
            skip_slugs.add(sys.argv[idx])
            idx += 1

    print("Modo:", "APPLY" if apply else "DRY RUN")
    print(f"Manuscrito: {md}")
    entries = parse_bibliography(md)
    print(f"{len(entries)} entradas na bibliografia do manuscrito.")

    api = MendeleyAPI(load_credentials())
    stats = {"set": 0, "fix": 0, "clear": 0, "ok": 0,
             "sem_registo": 0, "sem_doi": 0, "erros": 0}
    try:
        docs = await api.get_all_documents()
        print(f"{len(docs)} registos na biblioteca Mendeley.\n")

        for e in entries:
            slug = e["slug"]
            if slug in skip_slugs:
                continue
            want = e["md_doi"] or new_dois.get(slug)
            rec, score = match_record(e, docs)
            if rec is None:
                if want or slug in clear_slugs:
                    print(f"  SEM REGISTO ({score:.2f}) {slug}")
                    stats["sem_registo"] += 1
                continue
            ids = dict(rec.get("identifiers") or {})
            have = ids.get("doi")
            have_b = bare_doi(have) if have else None

            if slug in clear_slugs:
                if have:
                    print(f"  CLEAR {slug}: remove doi errado {have}")
                    ids.pop("doi", None)
                    if apply:
                        try:
                            await api.patch_document(rec["id"],
                                                     {"identifiers": ids})
                        except Exception as ex:
                            print(f"    erro: {ex}")
                            stats["erros"] += 1
                            continue
                    stats["clear"] += 1
                continue

            if not want:
                stats["sem_doi"] += 1
                continue
            want = bare_doi(want)
            if have_b and norm(have_b) == norm(want):
                stats["ok"] += 1
                continue
            action = "FIX " if have_b else "SET "
            print(f"  {action}{slug}: {have_b or '—'} -> {want}"
                  f"  [{rec['title'][:50]}]")
            ids["doi"] = want
            if apply:
                try:
                    await api.patch_document(rec["id"], {"identifiers": ids})
                except Exception as ex:
                    print(f"    erro: {ex}")
                    stats["erros"] += 1
                    continue
            stats["fix" if have_b else "set"] += 1

        print("\nResumo:")
        for k, v in stats.items():
            print(f"  {k:12}: {v}")
        if not apply:
            print("\nDry run. Use --apply para gravar na biblioteca Mendeley.")
    finally:
        await api.close()


if __name__ == "__main__":
    asyncio.run(main())
