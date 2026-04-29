#!/usr/bin/env python3
"""
Mendeley Library Organizer
Matches local PDFs to Mendeley documents and organizes them into folders.
"""

from __future__ import annotations

import asyncio
import base64
import json
import re
import sys
from pathlib import Path
from typing import Any

import httpx

# ── Config ────────────────────────────────────────────────────────────────────

MATERIAL_DIR = Path(__file__).parent
MENDELEY_API_BASE = "https://api.mendeley.com"

# Map local folder name → Mendeley folder name to create
FOLDER_MAP = {
    "prosthetics-design":   "Design de Próteses",
    "3dprinting-prosthetics": "Impressão 3D em Próteses",
    "antropometria":        "Antropometria",
    "amputacao":            "Amputação",
    "reabilitacao":         "Reabilitação",
    "parametrico":          "Modelação Paramétrica",
    "prosthetics-user":     "Utilizador de Próteses",
    "colaboracao":          "Colaboração e Co-design",
    "prosthetics-control":  "Controlo de Próteses",
    "outros":               "Outros",
    "lower-limb":           "Membro Inferior",
    "normas":               "Normas",
}

# ── Credentials ───────────────────────────────────────────────────────────────

def load_credentials() -> dict[str, str]:
    """Load credentials from mendeley-auth keyring/config."""
    config_file = Path.home() / ".config" / "mendeley-mcp" / "credentials.json"
    if not config_file.exists():
        print("ERROR: No credentials found. Run 'mendeley-auth login' first.")
        sys.exit(1)

    with open(config_file) as f:
        config = json.load(f)

    if config.get("use_keyring"):
        try:
            import keyring
            config["client_secret"] = keyring.get_password("mendeley-mcp", "client_secret")
            config["access_token"]  = keyring.get_password("mendeley-mcp", "access_token")
            config["refresh_token"] = keyring.get_password("mendeley-mcp", "refresh_token")
        except Exception as e:
            print(f"ERROR: Could not load from keyring: {e}")
            sys.exit(1)

    required = ["client_id", "client_secret", "refresh_token"]
    for key in required:
        if not config.get(key):
            print(f"ERROR: Missing credential: {key}. Run 'mendeley-auth login'.")
            sys.exit(1)

    return config

# ── API Client ────────────────────────────────────────────────────────────────

class MendeleyAPI:
    def __init__(self, creds: dict[str, str]) -> None:
        self.creds = creds
        self.client = httpx.AsyncClient(base_url=MENDELEY_API_BASE, timeout=30.0)

    async def close(self) -> None:
        await self.client.aclose()

    def _headers(self, content_type: str | None = None, accept: str = "application/json") -> dict:
        h = {
            "Authorization": f"Bearer {self.creds['access_token']}",
            "Accept": accept,
        }
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
            headers={"Authorization": f"Basic {auth}", "Content-Type": "application/x-www-form-urlencoded"},
        )
        r.raise_for_status()
        self.creds["access_token"] = r.json()["access_token"]

    async def _get(self, path: str, accept: str, params: dict | None = None) -> Any:
        r = await self.client.get(path, headers=self._headers(accept=accept), params=params)
        if r.status_code == 401:
            await self._refresh()
            r = await self.client.get(path, headers=self._headers(accept=accept), params=params)
        r.raise_for_status()
        return r

    async def _post(self, path: str, body: dict, content_type: str, accept: str) -> Any:
        r = await self.client.post(path, headers=self._headers(content_type, accept), json=body)
        if r.status_code == 401:
            await self._refresh()
            r = await self.client.post(path, headers=self._headers(content_type, accept), json=body)
        r.raise_for_status()
        return r

    async def get_all_documents(self) -> list[dict]:
        """Fetch all library documents with pagination."""
        docs: list[dict] = []
        params: dict[str, Any] = {"limit": 100, "sort": "title", "order": "asc", "view": "all"}
        accept = "application/vnd.mendeley-document.1+json"

        print("  Fetching documents", end="", flush=True)
        while True:
            r = await self._get("/documents", accept=accept, params=params)
            batch = r.json()
            docs.extend(batch)
            print(".", end="", flush=True)

            # Follow pagination via Link header
            link = r.headers.get("Link", "")
            next_url = _parse_next_link(link)
            if not next_url or not batch:
                break
            # Extract params from next URL for next iteration
            from urllib.parse import urlparse, parse_qs
            parsed = urlparse(next_url)
            params = {k: v[0] for k, v in parse_qs(parsed.query).items()}

        print(f" {len(docs)} documents found.")
        return docs

    async def get_folders(self) -> list[dict]:
        r = await self._get("/folders", accept="application/vnd.mendeley-folder.1+json")
        return r.json()

    async def create_folder(self, name: str, parent_id: str | None = None) -> dict:
        body: dict[str, Any] = {"name": name}
        if parent_id:
            body["parent_id"] = parent_id
        r = await self._post(
            "/folders",
            body,
            content_type="application/vnd.mendeley-folder.1+json",
            accept="application/vnd.mendeley-folder.1+json",
        )
        return r.json()

    async def add_to_folder(self, folder_id: str, doc_id: str) -> None:
        r = await self.client.post(
            f"/folders/{folder_id}/documents",
            headers=self._headers(content_type="application/vnd.mendeley-document.1+json"),
            json={"id": doc_id},
        )
        if r.status_code == 401:
            await self._refresh()
            r = await self.client.post(
                f"/folders/{folder_id}/documents",
                headers=self._headers(content_type="application/vnd.mendeley-document.1+json"),
                json={"id": doc_id},
            )
        if r.status_code not in (200, 201, 204):
            raise httpx.HTTPStatusError(f"Add to folder failed: {r.status_code} {r.text}", request=r.request, response=r)

# ── Matching ──────────────────────────────────────────────────────────────────

def normalize(text: str) -> str:
    """Lowercase, strip punctuation and extra spaces for fuzzy comparison."""
    text = text.lower()
    text = re.sub(r'[^\w\s]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def similarity(a: str, b: str) -> float:
    """Token overlap similarity between two normalized strings."""
    tokens_a = set(normalize(a).split())
    tokens_b = set(normalize(b).split())
    if not tokens_a or not tokens_b:
        return 0.0
    # Remove very short/common tokens
    stop = {'a', 'an', 'the', 'of', 'in', 'on', 'for', 'and', 'with', 'to',
            'de', 'da', 'do', 'e', 'em', 'um', 'uma', 'para'}
    tokens_a -= stop
    tokens_b -= stop
    if not tokens_a or not tokens_b:
        return 0.0
    inter = tokens_a & tokens_b
    return len(inter) / max(len(tokens_a), len(tokens_b))

def match_pdf_to_doc(pdf_name: str, docs: list[dict], threshold: float = 0.45) -> dict | None:
    """Find best-matching Mendeley doc for a PDF filename."""
    stem = Path(pdf_name).stem
    best_score = 0.0
    best_doc = None
    for doc in docs:
        score = similarity(stem, doc.get("title", ""))
        if score > best_score:
            best_score = score
            best_doc = doc
    return best_doc if best_score >= threshold else None

def _parse_next_link(link_header: str) -> str | None:
    """Extract 'next' URL from Link header."""
    for part in link_header.split(","):
        if 'rel="next"' in part:
            m = re.search(r'<([^>]+)>', part)
            if m:
                return m.group(1)
    return None

# ── Local PDFs ────────────────────────────────────────────────────────────────

def collect_local_pdfs() -> dict[str, list[str]]:
    """Return {local_folder: [pdf_filename, ...]} for configured folders."""
    result: dict[str, list[str]] = {}
    for folder in FOLDER_MAP:
        folder_path = MATERIAL_DIR / folder
        if folder_path.is_dir():
            pdfs = [p.name for p in folder_path.glob("*.pdf")]
            if pdfs:
                result[folder] = sorted(pdfs)
    return result

# ── Main ──────────────────────────────────────────────────────────────────────

async def main(dry_run: bool = False) -> None:
    print("=" * 60)
    print("Mendeley Library Organizer")
    print("=" * 60)
    if dry_run:
        print("DRY RUN — no changes will be made to Mendeley\n")

    creds = load_credentials()
    api = MendeleyAPI(creds)

    try:
        # 1. Fetch existing state
        print("\n[1/4] Fetching Mendeley data...")
        docs = await api.get_all_documents()
        existing_folders = await api.get_folders()
        existing_folder_names = {f["name"]: f for f in existing_folders}
        print(f"  {len(existing_folders)} existing folders.")

        # 2. Collect local PDFs
        print("\n[2/4] Scanning local PDFs...")
        local_pdfs = collect_local_pdfs()
        total_pdfs = sum(len(v) for v in local_pdfs.values())
        print(f"  {total_pdfs} PDFs across {len(local_pdfs)} folders.")

        # 3. Match PDFs → Mendeley docs
        print("\n[3/4] Matching PDFs to Mendeley documents...")
        folder_assignments: dict[str, list[dict]] = {}  # mendeley_folder_name → [doc]
        unmatched: list[tuple[str, str]] = []           # (folder, pdf_name)

        for local_folder, pdfs in sorted(local_pdfs.items()):
            mendeley_name = FOLDER_MAP[local_folder]
            matched_docs: list[dict] = []
            for pdf in pdfs:
                doc = match_pdf_to_doc(pdf, docs)
                if doc:
                    matched_docs.append(doc)
                else:
                    unmatched.append((local_folder, pdf))
            folder_assignments[mendeley_name] = matched_docs

        total_matched = sum(len(v) for v in folder_assignments.values())
        print(f"  Matched: {total_matched} / {total_pdfs}")
        print(f"  Unmatched: {len(unmatched)}")

        # 4. Apply changes
        print("\n[4/4] Applying changes to Mendeley...")
        created_folders: dict[str, str] = {}  # name → id

        for mendeley_name, matched_docs in sorted(folder_assignments.items()):
            if not matched_docs:
                continue

            # Create folder if it doesn't exist
            if mendeley_name in existing_folder_names:
                folder_id = existing_folder_names[mendeley_name]["id"]
                print(f"\n  Folder '{mendeley_name}' (existing, id={folder_id[:8]}…)")
            else:
                if not dry_run:
                    folder = await api.create_folder(mendeley_name)
                    folder_id = folder["id"]
                    created_folders[mendeley_name] = folder_id
                    print(f"\n  Folder '{mendeley_name}' CREATED (id={folder_id[:8]}…)")
                else:
                    folder_id = "DRY-RUN"
                    print(f"\n  Folder '{mendeley_name}' would be CREATED")

            # Add documents to folder
            for doc in matched_docs:
                title_short = doc['title'][:60]
                if not dry_run:
                    try:
                        await api.add_to_folder(folder_id, doc["id"])
                        print(f"    ✓ {title_short}")
                    except httpx.HTTPStatusError as e:
                        if e.response.status_code == 409:
                            print(f"    = {title_short} (already in folder)")
                        else:
                            print(f"    ✗ {title_short} — {e}")
                else:
                    print(f"    → {title_short}")

        # Report unmatched
        if unmatched:
            print(f"\n{'─'*60}")
            print(f"Unmatched PDFs ({len(unmatched)}) — add manually in Mendeley:")
            for folder, pdf in sorted(unmatched):
                print(f"  [{FOLDER_MAP[folder]}] {pdf}")

        print(f"\n{'='*60}")
        if dry_run:
            print("Dry run complete. Run with --apply to make changes.")
        else:
            print("Done! Check Mendeley to verify the organization.")

    finally:
        await api.close()


if __name__ == "__main__":
    dry_run = "--apply" not in sys.argv
    if "--apply" in sys.argv:
        print("Running in APPLY mode — changes will be made to Mendeley.")
    else:
        print("Running in DRY RUN mode. Use --apply to actually make changes.")
    asyncio.run(main(dry_run=dry_run))
