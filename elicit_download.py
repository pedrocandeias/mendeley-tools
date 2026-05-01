#!/usr/bin/env python3
"""
Elicit Paper Classifier and Downloader

Phase 1 — Classify: assign each Elicit-only paper to a local folder
Phase 2 — Download: fetch open-access PDFs via Semantic Scholar
Phase 3 — Export: write a CSV report of all results
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
from urllib.parse import urlparse, quote

import httpx

# ── Config ────────────────────────────────────────────────────────────────────

MATERIAL_DIR = Path(__file__).parent
REPORT_CSV = MATERIAL_DIR / "elicit_download_report.csv"
SS_CACHE_FILE = MATERIAL_DIR / ".ss_cache.json"
USER_EMAIL = "pedrocandeias+claude@gmail.com"

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

ELICIT_CSV_PATHS: list[Path] = [
    MATERIAL_DIR / "Elicit - Papers Upper Limb Anthropometry for Prosthetic Design.csv",
    Path.home() / "dev/mestrado/sources/capitulo2",
]

# (folder, [(keyword, weight), ...])
# Checked in order; first folder to reach threshold wins
FOLDER_RULES: list[tuple[str, list[tuple[str, float]]]] = [
    ("amputacao", [
        ("limb amputation", 3), ("limb loss", 3),
        ("amputee", 2), ("amputat", 2),
    ]),
    ("prosthetics-control", [
        ("myoelectric control", 4), ("emg control", 4),
        ("neural interface", 3), ("pattern recognition", 3), ("brain-computer", 3),
    ]),
    ("lower-limb", [
        ("transtibial", 3), ("transfemoral", 3), ("trans tibial", 3), ("trans femoral", 3),
        ("below knee", 3), ("above knee", 3),
        ("residual limb", 3), ("prosthetic socket", 3), ("socket design", 3),
        ("ankle prosth", 3), ("ankle foot orthes", 3), ("foot prosth", 3),
        ("prosthetic leg", 3), ("leg prosth", 3), ("tibial prosth", 3),
        ("femoral prosth", 3), ("lower limb prosth", 3), ("lower limb prosthetics", 3),
        ("lowerlimb prosth", 3),  # "lower-limb prosth" after normalize
        ("stump socket", 3), ("inferior limb", 2), ("lower extremit prosth", 3),
        ("residual lower limb", 3), ("brim adapter", 2), ("socket", 1),
    ]),
    ("3dprinting-prosthetics", [
        ("3d printed prosth", 4), ("3d printing prosth", 4),
        ("additive manufactur prosth", 4), ("3d printed orthes", 3),
        ("additive manufactur orthes", 3), ("additive manufactur exosk", 3),
        ("3d printed socket", 3), ("3d printed prostheses", 4),
        ("low cost prosthetics", 3), ("low cost prostheses", 3),
        ("3dprinting prosth", 3),
    ]),
    ("antropometria", [
        ("anthropometr", 2), ("body measurement", 2), ("hand dimension", 3),
        ("3d scan", 2), ("3d scanner", 2), ("photogrammetr", 2), ("laser scan", 2),
        ("body scan", 2), ("surface reconstruction", 2), ("3d body", 2),
        ("body model", 2), ("optical measur", 2), ("non-contact measur", 2),
        ("scanning technolog", 2), ("anthropomorphic measur", 2),
        ("shape sensing", 2), ("digitiz", 1), ("shape model", 1),
        ("3d model human", 2),
    ]),
    ("parametrico", [
        ("parametric design", 3), ("parametric model", 3), ("parametric prosth", 4),
        ("parametric cad", 3), ("parametric approach", 2), ("parametric method", 2),
        ("cad cam", 2), ("cad/cam", 2), ("generative design", 3),
        ("topology optim", 3), ("computational design", 2), ("automated design", 2),
        ("design automation", 2), ("generative adversarial", 3),
        ("computer aided design", 2), ("algorithmic design", 2),
        ("machine learned generative", 3), ("generative model", 2),
    ]),
    ("colaboracao", [
        ("co-design", 3), ("codesign", 3), ("collaborative design", 3),
        ("participatory design", 3), ("user co-creat", 3), ("co-creat", 2),
        ("participatory research", 2), ("user participat", 2),
    ]),
    ("reabilitacao", [
        ("rehabilitation", 2), ("occupational therap", 3), ("physical therap", 3),
        ("assistive technolog", 2), ("stroke rehab", 3), ("upper limb rehab", 3),
        ("assistive device", 2), ("mobility assistive", 2),
        ("home-based technolog", 2), ("therapy", 1),
    ]),
    ("prosthetics-user", [
        ("user involvement", 2), ("patient-centered", 2), ("user-centered", 2),
        ("human-centered design", 2), ("inclusive design", 2), ("universal design", 2),
        ("user require", 2), ("user satisfaction", 2), ("user acceptance", 2),
        ("user experience prosth", 3), ("design for disabled", 2),
    ]),
    ("prosthetics-design", [
        ("upper limb prosth", 4), ("upper extremit prosth", 4),
        ("upperlimb prosth", 4),  # handles "upper-limb prosth" after normalize
        ("hand prosth", 3), ("arm prosth", 3), ("myoelectric", 3),
        ("transradial", 3), ("transhumeral", 3), ("trans humeral", 3),
        ("prosthetic hand", 3), ("prosthetic arm", 3), ("prosthetic limb", 3),
        ("prostheses", 1.5), ("prosthesis", 1.5),  # catch "prosthesis/prostheses"
        ("orthosis design", 2), ("orthotic design", 2), ("custom orthes", 2),
        ("exoskeleton", 2), ("wrist hand orthosis", 3), ("wrist hand orthes", 3),
        ("cervical orthosis", 2), ("replacement hand", 3), ("robotic prosth", 3),
        ("prosthetic cover", 2), ("prostheti", 1), ("orthosi", 1), ("orthes", 1),
    ]),
    ("normas", [
        ("standard guide", 3), ("iso standard", 3), ("testing protocol", 3),
        ("evaluation protocol", 2), ("assessment protocol", 2),
    ]),
]

MIN_SCORE = 1.5  # below this → "outros"

# Keywords that strongly indicate the paper is NOT about prosthetics/orthotics
IRRELEVANT_MARKERS = [
    "office chair", "apparel industr", "clothing", "furniture design",
    "architecture", "intravenous therap", "urban public", "fluid dynam",
    "shoe design", "learning environment", "hospital logistic",
]

# ── Helpers ───────────────────────────────────────────────────────────────────

def normalize(text: str) -> str:
    text = text.lower()
    text = re.sub(r'(?<=\w)-(?=\w)', ' ', text)  # split hyphenated compounds
    text = re.sub(r'[^\w\s]', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()

def token_similarity(a: str, b: str) -> float:
    stop = {'a','an','the','of','in','on','for','and','with','to','by','at',
            'as','is','are','from','using','based','via','its','de','da','do',
            'e','em','um','uma','para'}
    ta = set(normalize(a).split()) - stop
    tb = set(normalize(b).split()) - stop
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / max(len(ta), len(tb))

def sanitize_filename(title: str) -> str:
    """Convert title to a safe filename (no extension)."""
    name = re.sub(r'[<>:"/\\|?*]', '', title)
    name = re.sub(r'\s+', ' ', name).strip()
    return name[:120]  # keep filenames reasonable

def classify_paper(title: str) -> tuple[str, float]:
    """Return (folder, score) for a paper title."""
    t = normalize(title)
    # Force irrelevant papers to outros
    for marker in IRRELEVANT_MARKERS:
        if marker in t:
            return "outros", 0.0
    # Score all folders, pick the highest
    best_folder, best_score = "outros", 0.0
    for folder, rules in FOLDER_RULES:
        score = sum(w for kw, w in rules if normalize(kw) in t)
        if score > best_score:
            best_score = score
            best_folder = folder
    if best_score < MIN_SCORE:
        return "outros", best_score
    return best_folder, best_score

# ── Data Loading ──────────────────────────────────────────────────────────────

def load_elicit_csvs() -> dict[str, dict]:
    """Load all Elicit CSV exports. Returns {normalised_title: row_dict}."""
    papers: dict[str, dict] = {}

    def _load(path: Path) -> None:
        try:
            with open(path, encoding="utf-8-sig", newline="") as f:
                for row in csv.DictReader(f):
                    title = (row.get("Title") or "").strip()
                    if title:
                        norm = normalize(title)
                        if norm not in papers:
                            papers[norm] = {
                                "title": title,
                                "authors": row.get("Authors", ""),
                                "year": row.get("Year", ""),
                                "url": row.get("Url", ""),
                                "source_csv": path.name,
                            }
        except Exception as e:
            print(f"  Warning: {path.name}: {e}", file=sys.stderr)

    for entry in ELICIT_CSV_PATHS:
        if entry.is_file():
            _load(entry)
        elif entry.is_dir():
            for p in sorted(entry.glob("*.csv")):
                _load(p)
    return papers

def collect_local_titles() -> set[str]:
    """Normalised titles of all local PDFs."""
    titles: set[str] = set()
    for folder in FOLDER_MAP:
        folder_path = MATERIAL_DIR / folder
        if folder_path.is_dir():
            for p in folder_path.glob("*.pdf"):
                titles.add(normalize(p.stem))
    return titles

def find_elicit_only(elicit_papers: dict, local_titles: set[str]) -> list[dict]:
    """Papers in Elicit CSVs that have no matching local PDF."""
    result = []
    for norm_title, entry in elicit_papers.items():
        # Simple check: title not in local set (allow slight similarity)
        already_local = any(
            token_similarity(norm_title, lt) >= 0.45 for lt in local_titles
        )
        if not already_local:
            result.append(entry)
    return result

# ── Semantic Scholar ──────────────────────────────────────────────────────────

SS_BASE = "https://api.semanticscholar.org/graph/v1"
SS_FIELDS = "title,year,openAccessPdf,externalIds"

class SemanticScholar:
    def __init__(self) -> None:
        self.client = httpx.AsyncClient(timeout=20.0)
        self._last: float = 0.0

    async def close(self) -> None:
        await self.client.aclose()

    async def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last
        if elapsed < 1.1:
            await asyncio.sleep(1.1 - elapsed)
        self._last = time.monotonic()

    async def find_paper(self, title: str) -> dict | None:
        """Search by title, return best match with openAccessPdf if any."""
        await self._throttle()
        try:
            r = await self.client.get(
                f"{SS_BASE}/paper/search",
                params={"query": title, "fields": SS_FIELDS, "limit": 3},
            )
            if r.status_code == 429:
                await asyncio.sleep(int(r.headers.get("Retry-After", "60")))
                r = await self.client.get(
                    f"{SS_BASE}/paper/search",
                    params={"query": title, "fields": SS_FIELDS, "limit": 3},
                )
            r.raise_for_status()
            data = r.json().get("data", [])
            for candidate in data:
                cand_title = candidate.get("title") or ""
                if token_similarity(title, cand_title) >= 0.4:
                    return candidate
        except Exception:
            pass
        return None

    async def get_by_ss_id(self, ss_id: str) -> dict | None:
        await self._throttle()
        try:
            r = await self.client.get(
                f"{SS_BASE}/paper/{ss_id}",
                params={"fields": SS_FIELDS},
            )
            r.raise_for_status()
            return r.json()
        except Exception:
            return None

async def try_download_pdf(
    client: httpx.AsyncClient,
    url: str,
    dest: Path,
) -> bool:
    """Try to download a PDF from a URL. Returns True on success."""
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; elicit-downloader/1.0)",
        "Accept": "application/pdf,*/*",
    }
    try:
        async with client.stream("GET", url, headers=headers, follow_redirects=True) as r:
            if r.status_code != 200:
                return False
            content_type = r.headers.get("content-type", "")
            if "pdf" not in content_type and not url.lower().endswith(".pdf"):
                # Read a small chunk to check for PDF magic bytes
                chunk = await r.aread()
                if not chunk.startswith(b"%PDF"):
                    return False
                dest.write_bytes(chunk)
                return True
            dest.parent.mkdir(parents=True, exist_ok=True)
            content = await r.aread()
            if len(content) < 1000:
                return False
            dest.write_bytes(content)
            return True
    except Exception:
        return False

def pdf_url_from_elicit_csv(url: str) -> str | None:
    """Transform a known-pattern URL into a direct PDF URL."""
    if not url:
        return None
    # Already a PDF link
    if url.lower().endswith(".pdf") or "/pdf" in url.lower():
        return url
    # MDPI: add /pdf
    if "mdpi.com" in url and not url.endswith("/pdf"):
        return url.rstrip("/") + "/pdf"
    # arXiv: /abs/ → /pdf/
    if "arxiv.org/abs/" in url:
        return url.replace("/abs/", "/pdf/")
    # PLoS ONE
    if "journals.plos.org" in url:
        doi_match = re.search(r"10\.\d{4,}/[^\s&]+", url)
        if doi_match:
            return f"https://journals.plos.org/plosone/article/file?id={doi_match.group()}&type=printable"
    return url  # return as-is for direct attempt

def ss_id_from_url(url: str) -> str | None:
    """Extract Semantic Scholar paper ID from a SS URL."""
    m = re.search(r"semanticscholar\.org/paper/([a-f0-9]{40})", url)
    return m.group(1) if m else None

def doi_from_url(url: str) -> str | None:
    m = re.search(r"10\.\d{4,}/[^\s\"'>]+", url)
    return m.group(0).rstrip(".,)") if m else None

# ── Phase 1: Classify ─────────────────────────────────────────────────────────

def phase1_classify(papers: list[dict]) -> list[dict]:
    print(f"\n{'='*60}")
    print("PHASE 1 — CLASSIFICATION")
    print(f"{'='*60}")

    folder_counts: dict[str, int] = {}
    for p in papers:
        folder, score = classify_paper(p["title"])
        p["folder"] = folder
        p["score"] = score
        folder_counts[folder] = folder_counts.get(folder, 0) + 1

    print(f"\n  {len(papers)} papers classified:\n")
    for folder, display in FOLDER_MAP.items():
        count = folder_counts.get(folder, 0)
        if count:
            label = "Outros / sem classificação clara" if folder == "outros" else display
            print(f"  {count:4d}  [{label}]")
    print()

    # Detail per folder (outros printed last)
    for folder, display in FOLDER_MAP.items():
        if folder == "outros":
            continue
        subset = [p for p in papers if p["folder"] == folder]
        if not subset:
            continue
        print(f"\n  ── {display} ({len(subset)}) ──")
        for p in sorted(subset, key=lambda x: x["title"]):
            year = f" ({p['year']})" if p.get("year") else ""
            print(f"    · {p['title'][:65]}{year}")

    outros_list = [p for p in papers if p["folder"] == "outros"]
    if outros_list:
        print(f"\n  ── Outros / sem classificação clara ({len(outros_list)}) ──")
        for p in sorted(outros_list, key=lambda x: x["title"]):
            year = f" ({p['year']})" if p.get("year") else ""
            print(f"    · {p['title'][:65]}{year}")

    return papers

# ── Phase 2: Download ─────────────────────────────────────────────────────────

async def phase2_download(papers: list[dict]) -> list[dict]:
    print(f"\n{'='*60}")
    print("PHASE 2 — DOWNLOAD")
    print(f"{'='*60}")

    # Load SS cache
    ss_cache: dict[str, Any] = {}
    if SS_CACHE_FILE.exists():
        try:
            ss_cache = json.loads(SS_CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass

    ss = SemanticScholar()
    dl_client = httpx.AsyncClient(timeout=60.0, follow_redirects=True)

    to_download = [p for p in papers if p["folder"] != "outros"]
    print(f"\n  {len(to_download)} papers to attempt (skipping {len(papers)-len(to_download)} in 'outros')")

    downloaded = skipped = failed = cached = 0

    try:
        for i, p in enumerate(to_download, 1):
            title = p["title"]
            folder = p["folder"]
            csv_url = p.get("url", "")
            dest = MATERIAL_DIR / folder / (sanitize_filename(title) + ".pdf")

            print(f"\n  [{i}/{len(to_download)}] {title[:60]}")
            print(f"           → [{FOLDER_MAP[folder]}]")

            # Already exists locally
            if dest.exists():
                print(f"           ✓ already exists")
                p["download_status"] = "exists"
                p["local_path"] = str(dest.relative_to(MATERIAL_DIR))
                skipped += 1
                continue

            # --- Find PDF URL ---
            pdf_url: str | None = None

            # Try cache first
            cache_key = normalize(title)
            if cache_key in ss_cache:
                cached_data = ss_cache[cache_key]
                pdf_url = cached_data.get("pdf_url")
                if cached_data.get("not_found"):
                    print(f"           · not found (cached)")
                    p["download_status"] = "not_found"
                    failed += 1
                    continue
            else:
                # 1. Try URL from CSV
                if csv_url:
                    ss_id = ss_id_from_url(csv_url)
                    if ss_id:
                        ss_data = await ss.get_by_ss_id(ss_id)
                        if ss_data:
                            oa = ss_data.get("openAccessPdf") or {}
                            pdf_url = oa.get("url")
                    if not pdf_url:
                        pdf_url = pdf_url_from_elicit_csv(csv_url)

                # 2. Search Semantic Scholar by title
                if not pdf_url:
                    ss_data = await ss.find_paper(title)
                    if ss_data:
                        oa = ss_data.get("openAccessPdf") or {}
                        pdf_url = oa.get("url")
                        # Also get DOI for the report
                        p["doi"] = (ss_data.get("externalIds") or {}).get("DOI", "")
                        p["ss_year"] = ss_data.get("year")

                # Cache the result
                ss_cache[cache_key] = {
                    "pdf_url": pdf_url,
                    "not_found": pdf_url is None,
                    "doi": p.get("doi", ""),
                }
                SS_CACHE_FILE.write_text(
                    json.dumps(ss_cache, ensure_ascii=False, indent=2), encoding="utf-8"
                )

            if not pdf_url:
                print(f"           ✗ no open-access PDF found")
                p["download_status"] = "no_pdf"
                failed += 1
                continue

            print(f"           ↓ {pdf_url[:70]}")

            # --- Download ---
            dest.parent.mkdir(parents=True, exist_ok=True)
            ok = await try_download_pdf(dl_client, pdf_url, dest)
            if ok:
                size_kb = dest.stat().st_size // 1024
                print(f"           ✓ saved ({size_kb} KB)")
                p["download_status"] = "downloaded"
                p["local_path"] = str(dest.relative_to(MATERIAL_DIR))
                downloaded += 1
            else:
                if dest.exists():
                    dest.unlink()
                print(f"           ✗ download failed")
                p["download_status"] = "failed"
                failed += 1

    finally:
        await ss.close()
        await dl_client.aclose()

    print(f"\n  {'─'*50}")
    print(f"  Downloaded:  {downloaded}")
    print(f"  Already had: {skipped}")
    print(f"  No PDF:      {failed}")
    print(f"  Skipped (outros): {len(papers) - len(to_download)}")

    return papers

# ── Phase 3: Export CSV ───────────────────────────────────────────────────────

def phase3_export(papers: list[dict]) -> None:
    print(f"\n{'='*60}")
    print("PHASE 3 — CSV EXPORT")
    print(f"{'='*60}")

    fields = [
        "folder", "folder_display", "title", "year", "authors",
        "doi", "url", "download_status", "local_path", "score", "source_csv",
    ]

    with open(REPORT_CSV, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for p in sorted(papers, key=lambda x: (x.get("folder", ""), x.get("title", ""))):
            row = dict(p)
            row["folder_display"] = FOLDER_MAP.get(p.get("folder", "outros"), "Outros")
            writer.writerow(row)

    print(f"\n  Report saved to: {REPORT_CSV.name}")
    print(f"  {len(papers)} rows\n")

# ── Main ──────────────────────────────────────────────────────────────────────

async def main() -> None:
    print("=" * 60)
    print("Elicit Paper Classifier + Downloader")
    print("=" * 60)

    print("\nLoading data…")
    elicit_papers = load_elicit_csvs()
    local_titles = collect_local_titles()
    elicit_only = find_elicit_only(elicit_papers, local_titles)
    print(f"  {len(elicit_only)} papers in Elicit but not local")

    # Phase 1
    classified = phase1_classify(elicit_only)

    # Phase 2
    classified = await phase2_download(classified)

    # Phase 3
    phase3_export(classified)


if __name__ == "__main__":
    asyncio.run(main())
