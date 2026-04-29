#!/usr/bin/env python3
"""
Mendeley Metadata Enricher
For each organized PDF:
  1. Extract DOI from PDF text
  2. Query CrossRef for full metadata
  3. Update Mendeley document (skip existing fields)
  4. Write metadata back to PDF file
"""

from __future__ import annotations

import asyncio
import base64
import json
import re
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import fitz  # pymupdf
import httpx

# ── Config ────────────────────────────────────────────────────────────────────

MATERIAL_DIR = Path(__file__).parent
CROSSREF_BASE = "https://api.crossref.org"
CROSSREF_HEADERS = {
    "User-Agent": "MendeleyEnricher/1.0 (mailto:pedrocandeias+claude@gmail.com)"
}
MENDELEY_API_BASE = "https://api.mendeley.com"

# Same folder map as organizer — only process these
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

# Similarity threshold for title matching (same as organizer)
MATCH_THRESHOLD = 0.45
# CrossRef title-search confidence threshold (0–1 score from CrossRef)
CROSSREF_SCORE_THRESHOLD = 50.0

# ── Credentials ───────────────────────────────────────────────────────────────

def load_credentials() -> dict[str, str]:
    config_file = Path.home() / ".config" / "mendeley-mcp" / "credentials.json"
    if not config_file.exists():
        print("ERROR: Run 'mendeley-auth login' first.")
        sys.exit(1)
    with open(config_file) as f:
        config = json.load(f)
    if config.get("use_keyring"):
        import keyring
        config["client_secret"] = keyring.get_password("mendeley-mcp", "client_secret")
        config["access_token"]  = keyring.get_password("mendeley-mcp", "access_token")
        config["refresh_token"] = keyring.get_password("mendeley-mcp", "refresh_token")
    return config

# ── Mendeley API ──────────────────────────────────────────────────────────────

class MendeleyAPI:
    def __init__(self, creds: dict) -> None:
        self.creds = creds
        self.client = httpx.AsyncClient(base_url=MENDELEY_API_BASE, timeout=30.0)

    async def close(self) -> None:
        await self.client.aclose()

    def _headers(self, content_type: str | None = None,
                 accept: str = "application/json") -> dict:
        h = {"Authorization": f"Bearer {self.creds['access_token']}", "Accept": accept}
        if content_type:
            h["Content-Type"] = content_type
        return h

    async def _refresh(self) -> None:
        auth = base64.b64encode(
            f"{self.creds['client_id']}:{self.creds['client_secret']}".encode()
        ).decode()
        r = await self.client.post(
            "https://api.mendeley.com/oauth/token",
            data={"grant_type": "refresh_token", "refresh_token": self.creds["refresh_token"]},
            headers={"Authorization": f"Basic {auth}",
                     "Content-Type": "application/x-www-form-urlencoded"},
        )
        r.raise_for_status()
        self.creds["access_token"] = r.json()["access_token"]

    async def _req(self, method: str, path: str, accept: str,
                   content_type: str | None = None, **kwargs: Any) -> httpx.Response:
        r = await self.client.request(
            method, path, headers=self._headers(content_type, accept), **kwargs)
        if r.status_code == 401:
            await self._refresh()
            r = await self.client.request(
                method, path, headers=self._headers(content_type, accept), **kwargs)
        r.raise_for_status()
        return r

    async def get_all_documents(self) -> list[dict]:
        docs: list[dict] = []
        params: dict[str, Any] = {"limit": 100, "sort": "title", "order": "asc", "view": "all"}
        accept = "application/vnd.mendeley-document.1+json"
        while True:
            r = await self._req("GET", "/documents", accept=accept, params=params)
            batch = r.json()
            docs.extend(batch)
            link = r.headers.get("Link", "")
            next_url = _parse_next_link(link)
            if not next_url or not batch:
                break
            from urllib.parse import urlparse, parse_qs
            parsed = urlparse(next_url)
            params = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        return docs

    async def patch_document(self, doc_id: str, fields: dict) -> dict:
        accept = "application/vnd.mendeley-document.1+json"
        ct = "application/vnd.mendeley-document.1+json"
        r = await self._req("PATCH", f"/documents/{doc_id}", accept=accept,
                            content_type=ct, json=fields)
        return r.json()

# ── CrossRef ──────────────────────────────────────────────────────────────────

async def crossref_by_doi(client: httpx.AsyncClient, doi: str) -> dict | None:
    try:
        r = await client.get(f"{CROSSREF_BASE}/works/{doi}",
                             headers=CROSSREF_HEADERS, timeout=15.0)
        if r.status_code == 200:
            return r.json().get("message")
    except Exception:
        pass
    return None

async def crossref_by_title(client: httpx.AsyncClient, title: str) -> dict | None:
    try:
        r = await client.get(
            f"{CROSSREF_BASE}/works",
            params={"query.bibliographic": title, "rows": 1,
                    "select": "title,author,published,abstract,DOI,container-title,ISSN,score"},
            headers=CROSSREF_HEADERS, timeout=15.0,
        )
        if r.status_code == 200:
            items = r.json().get("message", {}).get("items", [])
            if items and items[0].get("score", 0) >= CROSSREF_SCORE_THRESHOLD:
                return items[0]
    except Exception:
        pass
    return None

def strip_jats(text: str) -> str:
    """Remove JATS XML tags from CrossRef abstracts."""
    return re.sub(r"<[^>]+>", "", text).strip()

def parse_crossref(data: dict) -> dict:
    """Extract clean fields from a CrossRef work record."""
    result: dict[str, Any] = {}

    titles = data.get("title", [])
    if titles:
        result["title"] = titles[0]

    authors = []
    for a in data.get("author", []):
        entry: dict[str, str] = {}
        if a.get("family"):
            entry["last_name"] = a["family"]
        if a.get("given"):
            entry["first_name"] = a["given"]
        if entry:
            authors.append(entry)
    if authors:
        result["authors"] = authors

    date_parts = data.get("published", {}).get("date-parts", [[]])
    if date_parts and date_parts[0]:
        result["year"] = date_parts[0][0]

    abstract = data.get("abstract", "")
    if abstract:
        result["abstract"] = strip_jats(abstract)

    journals = data.get("container-title", [])
    if journals:
        result["source"] = journals[0]

    doi = data.get("DOI", "")
    if doi:
        result["identifiers"] = {"doi": doi}

    return result

# ── DOI extraction from PDF ───────────────────────────────────────────────────

DOI_RE = re.compile(r'\b(10\.\d{4,}/[^\s,\]"\'<>]+)', re.IGNORECASE)

def extract_doi_from_pdf(pdf_path: Path) -> str | None:
    """Scan first 3 pages of PDF for a DOI pattern."""
    try:
        doc = fitz.open(str(pdf_path))
        for page_num in range(min(3, len(doc))):
            text = doc[page_num].get_text()
            m = DOI_RE.search(text)
            if m:
                doi = m.group(1).rstrip(".")
                doc.close()
                return doi
        doc.close()
    except Exception:
        pass
    return None

# ── PDF metadata writer ───────────────────────────────────────────────────────

def write_pdf_metadata(pdf_path: Path, fields: dict) -> bool:
    """Write metadata fields to PDF. Returns True on success."""
    try:
        doc = fitz.open(str(pdf_path))
        existing = doc.metadata

        new_meta = dict(existing)  # start with existing
        changed = False

        if fields.get("title") and not existing.get("title"):
            new_meta["title"] = fields["title"]
            changed = True

        if fields.get("authors") and not existing.get("author"):
            authors_str = "; ".join(
                f"{a.get('last_name', '')} {a.get('first_name', '')}".strip()
                for a in fields["authors"]
            )
            new_meta["author"] = authors_str
            changed = True

        if fields.get("year") and not existing.get("creationDate"):
            new_meta["creationDate"] = f"D:{fields['year']}0101000000"
            changed = True

        if fields.get("abstract") and not existing.get("subject"):
            new_meta["subject"] = fields["abstract"][:500]  # cap length
            changed = True

        if not changed:
            doc.close()
            return False

        doc.set_metadata(new_meta)

        # Save to temp file then replace original
        tmp = pdf_path.with_suffix(".tmp.pdf")
        doc.save(str(tmp), garbage=4, deflate=True)
        doc.close()
        tmp.replace(pdf_path)
        return True

    except Exception as e:
        print(f"      PDF write error: {e}")
        return False

# ── Matching (same logic as organizer) ───────────────────────────────────────

def normalize(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()

def similarity(a: str, b: str) -> float:
    stop = {"a","an","the","of","in","on","for","and","with","to",
            "de","da","do","e","em","um","uma","para"}
    ta = set(normalize(a).split()) - stop
    tb = set(normalize(b).split()) - stop
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / max(len(ta), len(tb))

def match_pdf_to_doc(pdf_name: str, docs: list[dict]) -> dict | None:
    stem = Path(pdf_name).stem
    best_score, best_doc = 0.0, None
    for doc in docs:
        score = similarity(stem, doc.get("title", ""))
        if score > best_score:
            best_score, best_doc = score, doc
    return best_doc if best_score >= MATCH_THRESHOLD else None

def _parse_next_link(link_header: str) -> str | None:
    for part in link_header.split(","):
        if 'rel="next"' in part:
            m = re.search(r"<([^>]+)>", part)
            if m:
                return m.group(1)
    return None

# ── Merge logic ───────────────────────────────────────────────────────────────

def fields_to_update(mendeley_doc: dict, crossref: dict) -> dict:
    """Return only the CrossRef fields missing from the Mendeley doc."""
    update: dict[str, Any] = {}

    if crossref.get("title") and not mendeley_doc.get("title"):
        update["title"] = crossref["title"]

    if crossref.get("authors") and not mendeley_doc.get("authors"):
        update["authors"] = crossref["authors"]

    if crossref.get("year") and not mendeley_doc.get("year"):
        update["year"] = crossref["year"]

    if crossref.get("abstract") and not mendeley_doc.get("abstract"):
        update["abstract"] = crossref["abstract"]

    if crossref.get("source") and not mendeley_doc.get("source"):
        update["source"] = crossref["source"]

    if crossref.get("identifiers"):
        existing_ids = mendeley_doc.get("identifiers", {})
        new_ids = {k: v for k, v in crossref["identifiers"].items()
                   if not existing_ids.get(k)}
        if new_ids:
            update["identifiers"] = {**existing_ids, **new_ids}

    return update

# ── Main ──────────────────────────────────────────────────────────────────────

async def main(dry_run: bool = True) -> None:
    print("=" * 60)
    print("Mendeley Metadata Enricher")
    print("=" * 60)
    if dry_run:
        print("DRY RUN — no changes will be made\n")

    creds = load_credentials()
    api = MendeleyAPI(creds)
    crossref_client = httpx.AsyncClient()

    stats = {"crossref_hit": 0, "crossref_miss": 0,
             "mendeley_updated": 0, "pdf_updated": 0, "skipped": 0}

    try:
        print("[1/3] Fetching Mendeley library...")
        docs = await api.get_all_documents()
        print(f"  {len(docs)} documents loaded.")

        print("\n[2/3] Building PDF → document pairs...")
        pairs: list[tuple[Path, dict]] = []
        for local_folder in FOLDER_MAP:
            folder_path = MATERIAL_DIR / local_folder
            if not folder_path.is_dir():
                continue
            for pdf_path in sorted(folder_path.glob("*.pdf")):
                doc = match_pdf_to_doc(pdf_path.name, docs)
                if doc:
                    pairs.append((pdf_path, doc))
        print(f"  {len(pairs)} matched pairs.")

        print("\n[3/3] Enriching metadata...")
        for i, (pdf_path, mendeley_doc) in enumerate(pairs, 1):
            title_short = mendeley_doc["title"][:55]
            print(f"\n  [{i}/{len(pairs)}] {title_short}")

            # Step 1: find DOI
            doi = None
            existing_ids = mendeley_doc.get("identifiers") or {}
            if existing_ids.get("doi"):
                doi = existing_ids["doi"]
                print(f"    DOI (Mendeley): {doi}")
            else:
                doi = extract_doi_from_pdf(pdf_path)
                if doi:
                    print(f"    DOI (PDF scan): {doi}")

            # Step 2: query CrossRef
            crossref_data: dict | None = None
            if doi:
                crossref_data = await crossref_by_doi(crossref_client, doi)
            if not crossref_data:
                crossref_data = await crossref_by_title(
                    crossref_client, mendeley_doc["title"])

            if not crossref_data:
                print("    CrossRef: no match found")
                stats["crossref_miss"] += 1
                continue

            stats["crossref_hit"] += 1
            parsed = parse_crossref(crossref_data)

            # Step 3: determine what to update
            update = fields_to_update(mendeley_doc, parsed)
            if not update:
                print("    Mendeley: already complete — skipped")
                stats["skipped"] += 1
            else:
                keys = ", ".join(update.keys())
                print(f"    Mendeley update: {keys}")
                if not dry_run:
                    try:
                        await api.patch_document(mendeley_doc["id"], update)
                        stats["mendeley_updated"] += 1
                    except httpx.HTTPStatusError as e:
                        print(f"    Mendeley error: {e.response.status_code} {e.response.text[:80]}")
                else:
                    stats["mendeley_updated"] += 1

            # Step 4: write PDF metadata
            pdf_changed = write_pdf_metadata(pdf_path, parsed) if not dry_run else bool(parsed)
            if pdf_changed:
                print(f"    PDF: metadata written")
                stats["pdf_updated"] += 1
            else:
                print(f"    PDF: already complete — skipped")

            # Polite rate limit for CrossRef
            await asyncio.sleep(0.5)

        print(f"\n{'=' * 60}")
        print("Summary:")
        print(f"  CrossRef matches : {stats['crossref_hit']}")
        print(f"  CrossRef misses  : {stats['crossref_miss']}")
        print(f"  Mendeley updated : {stats['mendeley_updated']}")
        print(f"  PDFs updated     : {stats['pdf_updated']}")
        print(f"  Already complete : {stats['skipped']}")
        if dry_run:
            print("\nDry run complete. Run with --apply to make changes.")
        else:
            print("\nDone!")

    finally:
        await api.close()
        await crossref_client.aclose()


if __name__ == "__main__":
    dry_run = "--apply" not in sys.argv
    if not dry_run:
        print("Running in APPLY mode — Mendeley and PDFs will be modified.")
    else:
        print("Running in DRY RUN mode. Use --apply to make changes.")
    asyncio.run(main(dry_run=dry_run))
