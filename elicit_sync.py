#!/usr/bin/env python3
"""
Elicit Library Sync
Compares local PDFs with Elicit CSV exports and searches Elicit for missing papers.

Workflow:
  1. Load all local PDFs from configured folders
  2. Load all known Elicit papers from CSV exports
  3. Match local PDFs against Elicit entries by title
  4. For unmatched papers, search the Elicit API to find canonical metadata
  5. Report what's in sync, what's missing from Elicit, and what's in Elicit but not local
"""

from __future__ import annotations

import asyncio
import csv
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

import httpx

# ── Config ────────────────────────────────────────────────────────────────────

MATERIAL_DIR = Path(__file__).parent
ELICIT_API_BASE = "https://elicit.com"
CACHE_FILE = MATERIAL_DIR / ".elicit_cache.json"

# Same folder map as the other scripts
FOLDER_MAP = {
    "prosthetics-design":     "Design de Próteses",
    "3dprinting-prosthetics": "Impressão 3D em Próteses",
    "antropometria":          "Antropometria",
    "amputacao":              "Amputação",
    "reabilitacao":           "Reabilitação",
    "parametrico":            "Modelação Paramétrica",
    "prosthetics-user":       "Utilizador de Próteses",
    "colaboracao":            "Colaboração e Co-design",
    "prosthetics-control":    "Controlo de Próteses",
    "outros":                 "Outros",
    "lower-limb":             "Membro Inferior",
    "normas":                 "Normas",
}

# Elicit CSV exports to scan — relative to MATERIAL_DIR or absolute paths
# Add more paths here as you export additional notebooks from Elicit
ELICIT_CSV_PATHS: list[Path] = [
    MATERIAL_DIR / "Elicit - Papers Upper Limb Anthropometry for Prosthetic Design.csv",
    # Also look in the dev/mestrado sources directory
    Path.home() / "dev/mestrado/sources/capitulo2",
]

# ── Credentials ───────────────────────────────────────────────────────────────

ENV_SEARCH_PATHS = [
    MATERIAL_DIR / ".env",
    Path.home() / "dev/mestrado/.env.local",
    Path.home() / "dev/mestrado/.env",
]

def load_api_key() -> str:
    key = os.environ.get("ELICIT_API_KEY")
    if key:
        return key
    for env_file in ENV_SEARCH_PATHS:
        if not env_file.exists():
            continue
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("ELICIT_API_KEY="):
                value = line.split("=", 1)[1].strip().strip("'\"")
                if value:
                    return value
    print(
        "ERROR: ELICIT_API_KEY not found.\n"
        "Set it as an environment variable or in ~/dev/mestrado/.env.local"
    )
    sys.exit(1)

# ── Normalisation / Matching ──────────────────────────────────────────────────

def normalize(text: str) -> str:
    text = text.lower()
    text = re.sub(r'[^\w\s]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def similarity(a: str, b: str) -> float:
    stop = {'a', 'an', 'the', 'of', 'in', 'on', 'for', 'and', 'with', 'to',
            'de', 'da', 'do', 'e', 'em', 'um', 'uma', 'para', 'is', 'are',
            'by', 'at', 'as', 'its', 'from', 'using', 'based', 'via'}
    ta = set(normalize(a).split()) - stop
    tb = set(normalize(b).split()) - stop
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / max(len(ta), len(tb))

def best_match(title: str, candidates: list[str], threshold: float = 0.45) -> tuple[str | None, float]:
    best_score = 0.0
    best = None
    for c in candidates:
        s = similarity(title, c)
        if s > best_score:
            best_score = s
            best = c
    return (best, best_score) if best_score >= threshold else (None, best_score)

# ── Local PDFs ────────────────────────────────────────────────────────────────

def collect_local_pdfs() -> dict[str, list[str]]:
    """Return {local_folder: [pdf_stem, ...]} for configured folders."""
    result: dict[str, list[str]] = {}
    for folder in FOLDER_MAP:
        folder_path = MATERIAL_DIR / folder
        if folder_path.is_dir():
            pdfs = [p.stem for p in sorted(folder_path.glob("*.pdf"))]
            if pdfs:
                result[folder] = pdfs
    return result

# ── Elicit CSV Exports ────────────────────────────────────────────────────────

def load_elicit_csvs() -> dict[str, dict]:
    """Load all Elicit CSV exports. Returns {normalised_title: row_dict}."""
    papers: dict[str, dict] = {}

    def load_csv(path: Path) -> None:
        try:
            with open(path, encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    title = (row.get("Title") or "").strip()
                    if title:
                        papers[normalize(title)] = {
                            "title": title,
                            "authors": row.get("Authors", ""),
                            "year": row.get("Year", ""),
                            "url": row.get("Url", ""),
                            "source": str(path.name),
                        }
        except Exception as e:
            print(f"  Warning: could not read {path.name}: {e}", file=sys.stderr)

    for entry in ELICIT_CSV_PATHS:
        if entry.is_file():
            load_csv(entry)
        elif entry.is_dir():
            for csv_path in sorted(entry.glob("*.csv")):
                load_csv(csv_path)

    return papers

# ── Elicit API ────────────────────────────────────────────────────────────────

class ElicitAPI:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.client = httpx.AsyncClient(base_url=ELICIT_API_BASE, timeout=30.0)
        self._last_request: float = 0.0

    async def close(self) -> None:
        await self.client.aclose()

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "elicit-sync/1.0",
        }

    async def _throttle(self) -> None:
        # Stay well within Elicit rate limits (~1 req/sec is safe)
        elapsed = time.monotonic() - self._last_request
        if elapsed < 1.1:
            await asyncio.sleep(1.1 - elapsed)
        self._last_request = time.monotonic()

    async def search(self, query: str, max_results: int = 5) -> list[dict]:
        await self._throttle()
        payload = {
            "query": query,
            "maxResults": max_results,
            "searchMode": "semantic",
            "corpus": "elicit",
        }
        r = await self.client.post("/api/v1/search", headers=self._headers(), json=payload)
        if r.status_code == 429:
            retry_after = int(r.headers.get("Retry-After", "60"))
            print(f"  Rate limited. Waiting {retry_after}s…", file=sys.stderr)
            await asyncio.sleep(retry_after)
            r = await self.client.post("/api/v1/search", headers=self._headers(), json=payload)
        r.raise_for_status()
        return r.json().get("papers", [])

# ── Cache ─────────────────────────────────────────────────────────────────────

def load_cache() -> dict[str, Any]:
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}

def save_cache(cache: dict[str, Any]) -> None:
    CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")

# ── Main ──────────────────────────────────────────────────────────────────────

async def main(search_missing: bool = False) -> None:
    print("=" * 60)
    print("Elicit Library Sync")
    print("=" * 60)

    api_key = load_api_key()

    # 1. Collect local PDFs
    print("\n[1/4] Scanning local PDFs…")
    local_by_folder = collect_local_pdfs()
    all_local: list[tuple[str, str]] = []  # (folder, stem)
    for folder, stems in sorted(local_by_folder.items()):
        all_local.extend((folder, s) for s in stems)
    print(f"  {len(all_local)} PDFs across {len(local_by_folder)} folders.")

    # 2. Load Elicit CSV exports
    print("\n[2/4] Loading Elicit CSV exports…")
    elicit_papers = load_elicit_csvs()
    elicit_titles = list(elicit_papers.keys())  # normalised
    print(f"  {len(elicit_papers)} papers found in CSV exports.")

    # 3. Match local PDFs against CSV exports
    print("\n[3/4] Matching local PDFs against Elicit CSVs…")
    matched: list[dict] = []
    unmatched: list[tuple[str, str]] = []

    for folder, stem in all_local:
        match_title, score = best_match(stem, elicit_titles)
        if match_title:
            entry = elicit_papers[match_title]
            matched.append({
                "local_folder": folder,
                "local_stem": stem,
                "elicit_title": entry["title"],
                "score": round(score, 2),
                "year": entry["year"],
                "url": entry["url"],
                "csv_source": entry["source"],
            })
        else:
            unmatched.append((folder, stem))

    print(f"  Matched:   {len(matched)}")
    print(f"  Unmatched: {len(unmatched)}")

    # 4. Search Elicit API for unmatched papers
    api_results: dict[str, Any] = {}
    cache = load_cache()

    if unmatched and search_missing:
        print(f"\n[4/4] Searching Elicit API for {len(unmatched)} unmatched papers…")
        api = ElicitAPI(api_key)
        try:
            for i, (folder, stem) in enumerate(unmatched, 1):
                cache_key = normalize(stem)
                if cache_key in cache:
                    api_results[stem] = cache[cache_key]
                    print(f"  [{i}/{len(unmatched)}] (cached) {stem[:60]}")
                    continue

                print(f"  [{i}/{len(unmatched)}] {stem[:60]}")
                try:
                    papers = await api.search(stem, max_results=3)
                    if papers:
                        best = papers[0]
                        result = {
                            "found": True,
                            "title": best.get("title", ""),
                            "year": best.get("year"),
                            "doi": best.get("doi", ""),
                            "authors": best.get("authors", []),
                            "abstract": (best.get("abstract") or "")[:200],
                        }
                        score = similarity(stem, best.get("title", ""))
                        result["match_score"] = round(score, 2)
                        if score < 0.3:
                            result["found"] = False
                            result["note"] = "low confidence match"
                    else:
                        result = {"found": False, "title": "", "doi": ""}
                    api_results[stem] = result
                    cache[cache_key] = result
                except httpx.HTTPStatusError as e:
                    print(f"    ✗ API error: {e}", file=sys.stderr)
                    api_results[stem] = {"found": False, "error": str(e)}
        finally:
            await api.close()
            save_cache(cache)
    elif unmatched:
        print(f"\n[4/4] Skipping Elicit API search (run with --search to enable).")
        print(f"  {len(unmatched)} papers need manual verification in Elicit.")

    # ── Report ────────────────────────────────────────────────────────────────

    print(f"\n{'='*60}")
    print("SYNC REPORT")
    print(f"{'='*60}")

    # Papers matched in Elicit CSVs
    if matched:
        print(f"\n✓ In Elicit CSV exports ({len(matched)} papers):")
        prev_folder = None
        for m in sorted(matched, key=lambda x: x["local_folder"]):
            if m["local_folder"] != prev_folder:
                print(f"\n  [{FOLDER_MAP[m['local_folder']]}]")
                prev_folder = m["local_folder"]
            year = f" ({m['year']})" if m["year"] else ""
            print(f"    ✓ {m['local_stem'][:55]}{year}  [{m['score']:.2f}]")

    # Papers not in any Elicit CSV
    if unmatched:
        print(f"\n✗ Not found in Elicit CSVs ({len(unmatched)} papers):")
        prev_folder = None
        for folder, stem in sorted(unmatched):
            if folder != prev_folder:
                print(f"\n  [{FOLDER_MAP[folder]}]")
                prev_folder = folder

            if stem in api_results:
                result = api_results[stem]
                if result.get("found"):
                    doi_str = f"  doi:{result['doi']}" if result.get("doi") else ""
                    print(f"    ? {stem[:55]}{doi_str}  (found via API, add to Elicit manually)")
                else:
                    note = result.get("note", "not found in Elicit")
                    print(f"    ✗ {stem[:55]}  ({note})")
            else:
                print(f"    · {stem[:55]}")

    # Papers in Elicit CSV exports but not local
    local_normalised = {normalize(stem) for _, stem in all_local}
    elicit_only = [
        entry for norm_title, entry in elicit_papers.items()
        if best_match(entry["title"], list(local_normalised))[0] is None
    ]
    if elicit_only:
        print(f"\n~ In Elicit CSVs but no matching local PDF ({len(elicit_only)} papers):")
        for entry in sorted(elicit_only, key=lambda x: x["title"]):
            year = f" ({entry['year']})" if entry["year"] else ""
            print(f"    ~ {entry['title'][:60]}{year}")

    # Summary
    total = len(all_local)
    in_elicit_api = sum(1 for r in api_results.values() if r.get("found"))
    fully_synced = len(matched) + in_elicit_api
    print(f"\n{'─'*60}")
    print(f"Total local PDFs:          {total}")
    print(f"In Elicit CSV exports:     {len(matched)}")
    if search_missing:
        print(f"Found via Elicit API:      {in_elicit_api}")
    print(f"Not found in Elicit:       {total - fully_synced}")
    print(f"In Elicit but not local:   {len(elicit_only)}")
    print(f"{'─'*60}")
    print()
    if not search_missing and unmatched:
        print("Tip: run with --search to query the Elicit API for unmatched papers.")
    print("To add missing papers to your Elicit library, open elicit.com and search by title.")


if __name__ == "__main__":
    search_missing = "--search" in sys.argv
    if search_missing:
        print("Search mode enabled — will query Elicit API for unmatched papers.")
    asyncio.run(main(search_missing=search_missing))
