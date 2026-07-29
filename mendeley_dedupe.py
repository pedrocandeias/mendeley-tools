#!/usr/bin/env python3
"""
Mendeley Duplicate Remover
Groups documents whose normalised titles are identical, keeps the most
complete copy (attachments, DOI, abstract, authors, year, source), merges
missing fields from the duplicates into the keeper and moves the duplicates
to the Mendeley Trash (recoverable — nothing is permanently deleted).

Usage:
    python3 mendeley_dedupe.py            # dry run
    python3 mendeley_dedupe.py --apply    # merge + trash duplicates
"""

from __future__ import annotations

import asyncio
import re
import sys
from typing import Any

from mendeley_enrich import MendeleyAPI, load_credentials

FILE_ACCEPT = "application/vnd.mendeley-file.1+json"
DOC_ACCEPT = "application/vnd.mendeley-document.1+json"


def norm_title(title: str) -> str:
    """Aggressively normalise a title for exact-duplicate grouping."""
    t = title.lower()
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


async def file_counts(api: MendeleyAPI) -> dict[str, int]:
    """Return {document_id: number_of_attached_files}."""
    counts: dict[str, int] = {}
    params: dict[str, Any] = {"limit": 100}
    while True:
        r = await api._req("GET", "/files", accept=FILE_ACCEPT, params=params)
        batch = r.json()
        for f in batch:
            doc_id = f.get("document_id")
            if doc_id:
                counts[doc_id] = counts.get(doc_id, 0) + 1
        link = r.headers.get("Link", "")
        from mendeley_enrich import _parse_next_link
        next_url = _parse_next_link(link)
        if not next_url or not batch:
            break
        from urllib.parse import urlparse, parse_qs
        params = {k: v[0] for k, v in parse_qs(urlparse(next_url).query).items()}
    return counts


def completeness(doc: dict, n_files: int) -> tuple:
    """Sort key: higher = better keeper."""
    ids = doc.get("identifiers") or {}
    return (
        n_files,
        1 if ids.get("doi") else 0,
        1 if doc.get("abstract") else 0,
        1 if doc.get("authors") else 0,
        1 if doc.get("year") else 0,
        1 if doc.get("source") else 0,
    )


def merge_fields(keeper: dict, dupes: list[dict]) -> dict:
    """Fields present in a duplicate but missing from the keeper."""
    update: dict[str, Any] = {}
    for field in ("authors", "year", "abstract", "source"):
        if not keeper.get(field):
            for d in dupes:
                if d.get(field):
                    update[field] = d[field]
                    break
    keeper_ids = keeper.get("identifiers") or {}
    merged_ids = dict(keeper_ids)
    for d in dupes:
        for k, v in (d.get("identifiers") or {}).items():
            if not merged_ids.get(k):
                merged_ids[k] = v
    if merged_ids != keeper_ids:
        update["identifiers"] = merged_ids
    return update


async def trash_document(api: MendeleyAPI, doc_id: str) -> None:
    await api._req("POST", f"/documents/{doc_id}/trash", accept=DOC_ACCEPT)


async def main(dry_run: bool = True) -> None:
    print("=" * 60)
    print("Mendeley Duplicate Remover")
    print("=" * 60)
    if dry_run:
        print("DRY RUN — no changes will be made\n")

    api = MendeleyAPI(load_credentials())
    stats = {"groups": 0, "trashed": 0, "merged": 0, "errors": 0}
    try:
        print("[1/3] Fetching Mendeley library...")
        docs = await api.get_all_documents()
        print(f"  {len(docs)} documents loaded.")

        print("[2/3] Fetching file attachment counts...")
        counts = await file_counts(api)
        print(f"  {sum(counts.values())} files across {len(counts)} documents.")

        print("\n[3/3] Grouping by normalised title...\n")
        groups: dict[str, list[dict]] = {}
        for d in docs:
            key = norm_title(d.get("title") or "")
            if len(key) < 10:  # skip empty/degenerate titles
                continue
            groups.setdefault(key, []).append(d)

        for key, group in sorted(groups.items()):
            if len(group) < 2:
                continue
            stats["groups"] += 1
            group.sort(key=lambda d: completeness(d, counts.get(d["id"], 0)),
                       reverse=True)
            keeper, dupes = group[0], group[1:]
            title = " ".join((keeper.get("title") or "").split())[:70]
            print(f"  [{stats['groups']}] {title}")
            kf = counts.get(keeper["id"], 0)
            kdoi = (keeper.get("identifiers") or {}).get("doi", "—")
            print(f"      keep : {keeper['id']}  files={kf}  doi={kdoi}")

            update = merge_fields(keeper, dupes)
            if update:
                print(f"      merge: {', '.join(update.keys())}")
                if not dry_run:
                    try:
                        await api.patch_document(keeper["id"], update)
                        stats["merged"] += 1
                    except Exception as e:
                        print(f"      merge error: {e}")
                        stats["errors"] += 1
                else:
                    stats["merged"] += 1

            for d in dupes:
                df = counts.get(d["id"], 0)
                ddoi = (d.get("identifiers") or {}).get("doi", "—")
                print(f"      trash: {d['id']}  files={df}  doi={ddoi}")
                if not dry_run:
                    try:
                        await trash_document(api, d["id"])
                        stats["trashed"] += 1
                    except Exception as e:
                        print(f"      trash error: {e}")
                        stats["errors"] += 1
                else:
                    stats["trashed"] += 1

        print(f"\n{'=' * 60}")
        print("Summary:")
        print(f"  Duplicate groups : {stats['groups']}")
        print(f"  Keepers merged   : {stats['merged']}")
        print(f"  Docs to trash    : {stats['trashed']}")
        print(f"  Errors           : {stats['errors']}")
        if dry_run:
            print("\nDry run complete. Run with --apply to make changes.")
        else:
            print("\nDone! Trashed documents remain recoverable in Mendeley Trash.")
    finally:
        await api.close()


if __name__ == "__main__":
    dry_run = "--apply" not in sys.argv
    if not dry_run:
        print("Running in APPLY mode — duplicates will be moved to Trash.")
    else:
        print("Running in DRY RUN mode. Use --apply to make changes.")
    asyncio.run(main(dry_run=dry_run))
