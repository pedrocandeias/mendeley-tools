#!/usr/bin/env python3
"""
Fetch open-access PDFs for papers in elicit_missing_papers.csv.

Sources tried in order for each paper:
  1. Unpaywall   — by DOI (legal open-access finder)
  2. OpenAlex    — title search → open_access.oa_url
  3. CORE        — title search → downloadUrl
  4. Semantic Scholar — title search → openAccessPdf (fallback, already tried some)

Results are saved back into elicit_missing_papers.csv and PDFs go into local folders.
Cache: .fetch_cache.json
"""

from __future__ import annotations

import asyncio
import csv
import json
import re
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

MATERIAL_DIR = Path(__file__).parent
INPUT_CSV    = MATERIAL_DIR / "elicit_missing_papers.csv"
CACHE_FILE   = MATERIAL_DIR / ".fetch_cache.json"
USER_EMAIL   = "pedrocandeias+claude@gmail.com"

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

# ── Helpers ───────────────────────────────────────────────────────────────────

def normalize(text: str) -> str:
    text = text.lower()
    text = re.sub(r'(?<=\w)-(?=\w)', ' ', text)
    text = re.sub(r'[^\w\s]', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()


def safe_filename(title: str, year: str = "") -> str:
    name = re.sub(r'[^\w\s\-]', '', title)
    name = re.sub(r'\s+', ' ', name).strip()
    name = name[:120]
    if year:
        name = f"{name} ({year})"
    return name + ".pdf"


def is_pdf(data: bytes) -> bool:
    return data[:4] == b'%PDF'


def extract_pdf_link(html: str, base_url: str) -> str | None:
    """Try to find a direct PDF download link in a repository landing page."""
    from urllib.parse import urljoin
    patterns = [
        # Zenodo: data-href on download button
        r'href="(/record/\d+/files/[^"]+\.pdf[^"]*)"',
        # DSpace/handle: bitstream
        r'href="([^"]*bitstream[^"]*\.pdf[^"]*)"',
        r'href="([^"]*\.pdf)"',
        # Generic PDF link
        r'(https?://[^\s"\'<>]+\.pdf(?:\?[^\s"\'<>]*)?)',
    ]
    for pat in patterns:
        m = re.search(pat, html, re.IGNORECASE)
        if m:
            href = m.group(1)
            return urljoin(base_url, href)
    return None


def load_cache() -> dict:
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_cache(cache: dict) -> None:
    CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


# ── HTTP client ───────────────────────────────────────────────────────────────

class ThrottledClient:
    def __init__(self, rps: float = 1.0) -> None:
        self.min_gap = 1.0 / rps
        self._last: float = 0.0
        self.client = httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            headers={"User-Agent": f"elicit-fetch/1.0 (mailto:{USER_EMAIL})"},
        )

    async def throttle(self) -> None:
        gap = time.monotonic() - self._last
        if gap < self.min_gap:
            await asyncio.sleep(self.min_gap - gap)
        self._last = time.monotonic()

    async def get_json(self, url: str) -> Any:
        await self.throttle()
        r = await self.client.get(url)
        r.raise_for_status()
        return r.json()

    async def download(self, url: str) -> bytes | None:
        await self.throttle()
        try:
            headers = {
                "Accept": "application/pdf,*/*",
                "Referer": "https://scholar.google.com/",
            }
            r = await self.client.get(url, headers=headers)
            if r.status_code == 200:
                if is_pdf(r.content):
                    return r.content
                # Repository landing page — try to extract a direct PDF link
                pdf_url = extract_pdf_link(r.text, str(r.url))
                if pdf_url and pdf_url != url:
                    await self.throttle()
                    r2 = await self.client.get(pdf_url, headers=headers)
                    if r2.status_code == 200 and is_pdf(r2.content):
                        return r2.content
        except Exception:
            pass
        return None

    async def close(self) -> None:
        await self.client.aclose()


# ── PDF source finders ────────────────────────────────────────────────────────

async def find_via_unpaywall(doi: str, http: ThrottledClient) -> str | None:
    if not doi:
        return None
    try:
        url = f"https://api.unpaywall.org/v2/{doi}?email={USER_EMAIL}"
        data = await http.get_json(url)
        best = data.get("best_oa_location") or {}
        pdf = best.get("url_for_pdf") or best.get("url")
        if pdf and pdf.endswith(".pdf") or (pdf and "pdf" in pdf.lower()):
            return pdf
        # Try all locations
        for loc in data.get("oa_locations", []):
            p = loc.get("url_for_pdf") or loc.get("url")
            if p and ("pdf" in p.lower() or p.lower().endswith(".pdf")):
                return p
        # Return best url even if not obviously pdf
        if best.get("url_for_pdf"):
            return best["url_for_pdf"]
    except Exception:
        pass
    return None


async def find_via_openalex(title: str, http: ThrottledClient) -> str | None:
    try:
        q = quote(title)
        url = f"https://api.openalex.org/works?search={q}&per-page=3&select=title,open_access,doi&mailto={USER_EMAIL}"
        data = await http.get_json(url)
        results = data.get("results", [])
        for r in results:
            oa = r.get("open_access", {})
            pdf = oa.get("oa_url")
            if pdf:
                return pdf
    except Exception:
        pass
    return None


async def find_via_core(title: str, http: ThrottledClient) -> str | None:
    try:
        q = quote(title)
        url = f"https://api.core.ac.uk/v3/search/works?q={q}&limit=3"
        data = await http.get_json(url)
        for item in data.get("results", []):
            pdf = item.get("downloadUrl") or item.get("fullTextLink")
            if pdf:
                return pdf
    except Exception:
        pass
    return None


async def find_via_semantic_scholar(title: str, http: ThrottledClient) -> str | None:
    try:
        q = quote(title)
        url = f"https://api.semanticscholar.org/graph/v1/paper/search?query={q}&limit=3&fields=title,openAccessPdf"
        data = await http.get_json(url)
        for paper in data.get("data", []):
            oa = paper.get("openAccessPdf") or {}
            pdf = oa.get("url")
            if pdf:
                return pdf
    except Exception:
        pass
    return None


# ── Download ──────────────────────────────────────────────────────────────────

async def find_pdf_url(title: str, doi: str, http: ThrottledClient, cache: dict) -> str | None:
    key = normalize(title)
    if key in cache:
        return cache[key]

    pdf_url = None

    # 1. Unpaywall by DOI
    if doi:
        pdf_url = await find_via_unpaywall(doi, http)

    # 2. OpenAlex by title
    if not pdf_url:
        pdf_url = await find_via_openalex(title, http)

    # 3. CORE by title
    if not pdf_url:
        pdf_url = await find_via_core(title, http)

    # 4. Semantic Scholar
    if not pdf_url:
        pdf_url = await find_via_semantic_scholar(title, http)

    cache[key] = pdf_url
    return pdf_url


async def download_paper(row: dict, http: ThrottledClient, cache: dict) -> dict:
    title  = row["title"]
    doi    = row["doi"].strip()
    folder = row["folder"]
    year   = row.get("year", "").strip()

    dest_dir = MATERIAL_DIR / folder
    dest_dir.mkdir(exist_ok=True)

    pdf_url = await find_pdf_url(title, doi, http, cache)
    if not pdf_url:
        return {**row, "download_status": "no_pdf", "local_path": ""}

    content = await http.download(pdf_url)
    if not content:
        return {**row, "download_status": "no_pdf", "local_path": ""}

    fname = safe_filename(title, year)
    dest  = dest_dir / fname
    dest.write_bytes(content)
    return {**row, "download_status": "downloaded", "local_path": str(dest.relative_to(MATERIAL_DIR))}


# ── Main ──────────────────────────────────────────────────────────────────────

async def main(retry_only: bool = False) -> None:
    rows = []
    with open(INPUT_CSV, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    if retry_only:
        # Only re-attempt papers that previously had no_pdf but have a cached URL
        cache = load_cache()
        to_process = [r for r in rows if r.get("download_status") == "no_pdf"
                      and cache.get(normalize(r["title"]))]
        print(f"Retrying {len(to_process)} papers with cached PDF URLs (improved downloader)…")
    else:
        to_process = [r for r in rows if r.get("download_status") != "downloaded"]
        cache = load_cache()
        print(f"Papers to process: {len(to_process)}")

    http = ThrottledClient(rps=0.8)
    results_map = {r["title"]: r for r in rows}  # preserve all rows
    downloaded = 0
    no_pdf = 0

    try:
        for i, row in enumerate(to_process, 1):
            sys.stdout.write(f"\r  [{i}/{len(to_process)}] {row['title'][:60]:<60}")
            sys.stdout.flush()

            result = await download_paper(row, http, cache)
            results_map[row["title"]] = result

            if result["download_status"] == "downloaded":
                downloaded += 1
                print(f"\n    ✓ saved to {result['local_path']}")
            else:
                no_pdf += 1

            if i % 10 == 0:
                save_cache(cache)

    finally:
        await http.close()
        save_cache(cache)

    print(f"\n\nDone.")
    print(f"  Downloaded: {downloaded}")
    print(f"  No PDF:     {no_pdf}")

    results = list(results_map.values())
    fields = list(rows[0].keys())
    if "download_status" not in fields:
        fields += ["download_status", "local_path"]
    with open(INPUT_CSV, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(results)
    print(f"  Updated {INPUT_CSV.name}")


if __name__ == "__main__":
    retry = "--retry" in sys.argv
    asyncio.run(main(retry_only=retry))
