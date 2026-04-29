#!/usr/bin/env python3
"""
Rename PDFs to their actual title.
Priority:
  1. PDF metadata Title (if clean)
  2. Extract title from filename pattern
  3. pdftotext first-page analysis (last resort)
  4. Skip if no reliable title found
"""

import os
import re
import subprocess
import sys

ROOT = "/home/pec/Desktop/mestrado/projeto/material"

# ── Metadata quality checks ───────────────────────────────────────────────────

BAD_META_RE = re.compile(
    r"^microsoft word"
    r"|^doi[:.]\s*\S"
    r"|^untitled\s*$"
    r"|^layout \d"
    r"|^no title\s*$"
    r"|^none\s*$"
    r"|^atao:"
    r"|^unknown\s*$"
    r"|^title\s*$"
    r"|^http"
    r"|^\s*$"
    r"|^﻿"                        # BOM character
    r"|\d+\.\.\d+$"                    # page range like 574..589
    r"|^[A-Z0-9][A-Z0-9\-_]{3,20}[\-_]\d{2,}"    # article IDs like POI-D-23, ICMERE-2011
    r"|\.indd$"                        # InDesign print file
    r"|^[a-f0-9]{32}$"                 # MD5 hash
    r"|^[cdce]:\\|^\/users\/"          # filesystem paths
    r"|^indonesian journal"            # journal names not caught by JOURNAL_HEADER_RE
    r"|template$"                      # template files
    r"|^chapter \d"                    # chapter markers
    r"|^part \d"                       # part markers like "Part 1_..."
    r"|^\d{3,}[_-]",                  # starts with numeric ID like "17164_"
    re.IGNORECASE,
)

JOURNAL_HEADER_RE = re.compile(
    r"(^journal of |^international journal|^frontiers in|^proceedings of"
    r"|^ieee |^acm |^bmc |^springer|^elsevier|^wiley|^sage |^mdpi"
    r"|open access proceedings|^plos |^annals of|^archives of)",
    re.IGNORECASE,
)


def is_clean_meta_title(title):
    if not title or len(title) < 10:
        return False
    if BAD_META_RE.search(title):
        return False
    if JOURNAL_HEADER_RE.search(title):
        return False
    if re.search(r"\.(doc|docx|xls|ppt)$", title, re.IGNORECASE):
        return False
    # All-caps short strings → likely an ID or abbreviation
    if re.match(r"^[A-Z0-9\-_/]+$", title) and len(title) < 25:
        return False
    return True


def get_metadata_title(path):
    try:
        out = subprocess.check_output(
            ["pdfinfo", path], stderr=subprocess.DEVNULL
        ).decode("utf-8", errors="replace")
        for line in out.splitlines():
            if line.startswith("Title:"):
                title = line[6:].strip()
                # Strip BOM
                title = title.lstrip("﻿￾")
                # Strip trailing .pdf suffix (some metadata embed the filename)
                title = re.sub(r"\.pdf$", "", title, flags=re.IGNORECASE).strip()
                if is_clean_meta_title(title):
                    return title
    except Exception:
        pass
    return None


# ── Filename-based extraction ─────────────────────────────────────────────────

def extract_from_filename(fname):
    # Strip .pdf extensions (handle double .pdf.pdf)
    name = fname
    for _ in range(2):
        name = re.sub(r"\.pdf$", "", name, flags=re.IGNORECASE)

    # Strip trailing year patterns: [2020], (2020), [2020]., [2022]-1
    name = re.sub(r"\s*[\[\(]\d{4}[\]\)][-\d]*\.?$", "", name).strip()

    # ── Pattern A: "Author(s) - Title" ──────────────────────────────────────
    # Split on first " - " and check if left part looks like an author.
    # Handles: "A. Name", "A U Name", "So-hye Jo", "Kathryn Ziegler-Graham",
    #          "First Last", "A. B. Last", "First Middle Last"
    if " - " in name:
        idx = name.index(" - ")
        author_part = name[:idx].strip()
        title_part  = name[idx + 3:].strip()
        # Author part heuristics: short, starts with capital, 1–4 words, no full sentence
        word_count = len(author_part.split())
        is_author = (
            len(author_part) < 65
            and len(title_part) > 15
            and word_count <= 5
            and re.match(r"^[A-ZÀ-ŽЀ-ӿ]", author_part)
            and not re.search(r"[!?]", author_part)
            and not re.match(r"^(cross|an |a |the |on |in )", author_part, re.IGNORECASE)
        )
        if is_author:
            return title_part

    # ── Pattern B1: "D-LastName-title-words" (initial-lastname-slug) ─────────
    # e.g. "D-McDonagh-Innovating-alongside-designers"
    m = re.match(r"^([A-Z])-[A-Za-z]+-(.+)$", name)
    if m and "-" in m.group(2):
        title = m.group(2).replace("-", " ")
        if len(title) > 10:
            return title[0].upper() + title[1:]

    # ── Pattern B2: slug "author[-et-al]-YEAR-title" ───────────────────��────
    # Handles: mcdonald-et-al-2020-title, biddiss-chau-2007-title,
    #          cohen-tanugi-et-al-2022-title, inouye-valero-cuevas-2013-title
    m = re.match(r"^[a-z][a-z-]*-(\d{4})-(.+)$", name)
    if m and len(m.group(2)) > 15:
        title = m.group(2).replace("-", " ")
        return title[0].upper() + title[1:]

    # ── Pattern C: Author_YEAR_Title (underscore with embedded year) ─────────
    # e.g. G._Smit_2014_The_lightweight_Delft_Cylinder_Hand
    m = re.match(r"^[A-Z]\._?[A-Za-z]+_\d{4}_(.+)$", name)
    if m:
        return m.group(1).replace("_", " ").strip()

    # ── Pattern D: underscore-joined title ───────────────────────────────────
    # Use when underscores are the primary word separator
    if name.count("_") >= 2 and name.count("_") >= name.count(" "):
        return name.replace("_", " ").strip()

    # ── Pattern E: TitleCase-Hyphenated-Name (hyphens as word separators) ────
    # e.g. "Anthropometric-Detailed-Data-Tables" — each word starts uppercase
    if "-" in name and " " not in name and re.match(r"^[A-Z]", name):
        # Check most words after splitting by hyphen start with uppercase or digit
        words = name.split("-")
        cap_words = sum(1 for w in words if w and (w[0].isupper() or w[0].isdigit()))
        if cap_words >= len(words) * 0.6:
            return " ".join(words).strip()

    # ── Pattern F: already sentence-like (has spaces, not a slug) ────────────
    if " " in name and len(name) > 10:
        return name.strip()

    return None


# ── pdftotext first-page fallback ────────────────────────────────────────────

NON_TITLE_LINE_RE = re.compile(
    r"(^https?://|^\d+\s*$|^doi\b|^vol\b|^pp[\s.]|^page\b|^issn\b|^isbn\b"
    r"|^received|^accepted|^published|^copyright|^©|@|\bORCID\b"
    r"|researchgate\.net|^see discussions"
    r"|^university |^department |^faculty |^instituto |^universidade "
    r"|^figure |^table |^abstract\s*$|^keywords\s*$"
    r"|^e-?mail|^tel\b|^fax\b)",
    re.IGNORECASE,
)


def get_text_title(path):
    try:
        out = subprocess.check_output(
            ["pdftotext", "-f", "1", "-l", "1", path, "-"],
            stderr=subprocess.DEVNULL,
            timeout=15,
        ).decode("utf-8", errors="replace")
    except Exception:
        return None

    lines = [l.strip() for l in out.splitlines()]
    lines = [l for l in lines if len(l) > 18]

    candidates = [
        l for l in lines[:30]
        if not NON_TITLE_LINE_RE.search(l)
        and not JOURNAL_HEADER_RE.search(l)
    ]
    if not candidates:
        return None

    scored = []
    for l in candidates[:15]:
        score = 0
        if l[0].isupper():
            score += 2
        if 20 < len(l) < 160:
            score += 2
        if re.search(r"\d", l):
            score -= 1
        if l.count(",") > 3:
            score -= 2
        if l.count(" ") > 3:
            score += 1
        scored.append((score, l))
    scored.sort(key=lambda x: -x[0])

    return scored[0][1].strip() if scored and len(scored[0][1]) > 12 else None


# ── Sanitize for filesystem ───────────────────────────────────────────────────

def sanitize(title):
    title = re.sub(r'[\\/:*?"<>|]', "", title)
    title = re.sub(r"[\r\n\t]", " ", title)
    title = re.sub(r"\s+", " ", title).strip().rstrip(".")
    if len(title) > 180:
        title = title[:180].rsplit(" ", 1)[0]
    return title


# ── Walk folders ──────────────────────────────────────────────────────────────

def collect_pdfs(root):
    skip_dirs = {"capitulos", "Diagramas", "Modelos de proteses"}
    pdfs = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames
            if d not in skip_dirs and not d.startswith(".")
        ]
        for fname in filenames:
            if fname.lower().endswith(".pdf"):
                pdfs.append(os.path.join(dirpath, fname))
    return sorted(pdfs)


# ── Main ──────────────────────────────────────────────────────────────────────

def main(dry_run=True):
    pdfs = collect_pdfs(ROOT)
    print(f"Found {len(pdfs)} PDFs\n")

    renamed, skipped, errors = 0, 0, []

    for path in pdfs:
        folder   = os.path.dirname(path)
        old_name = os.path.basename(path)

        title, source = None, None

        # For slug-style filenames (lowercase or "X-Lastname-..." pattern),
        # the filename extraction is more reliable than potentially wrong metadata.
        is_slug = bool(re.match(r"^[a-z]|^[A-Z]-[A-Za-z]", old_name))

        TRUNC_RE = re.compile(r"\s[A-Za-z]{1,3}\.?$")   # ends with short word/abbrev

        if is_slug:
            t = extract_from_filename(old_name)
            if t:
                title, source = t, "filename"

        if not title:
            fn_title = extract_from_filename(old_name)
            meta_title = get_metadata_title(path)

            if meta_title and fn_title:
                # Prefer filename when it gives a clearly complete title and
                # metadata looks truncated or much shorter than the filename title
                if (not TRUNC_RE.search(fn_title)
                        and (TRUNC_RE.search(meta_title)
                             or len(fn_title) > len(meta_title) + 20)):
                    title, source = fn_title, "filename"
                else:
                    title, source = meta_title, "meta"
            elif meta_title:
                title, source = meta_title, "meta"
            elif fn_title:
                title, source = fn_title, "filename"

        if not title:
            t = get_text_title(path)
            if t:
                title, source = t, "text"

        if not title:
            skipped += 1
            print(f"  SKIP: {old_name}")
            continue

        new_name = sanitize(title) + ".pdf"

        if new_name == old_name:
            continue

        # Handle collisions
        new_path = os.path.join(folder, new_name)
        if os.path.exists(new_path) and os.path.abspath(new_path) != os.path.abspath(path):
            base = sanitize(title)
            counter = 2
            while os.path.exists(os.path.join(folder, f"{base} ({counter}).pdf")):
                counter += 1
            new_name = f"{base} ({counter}).pdf"
            new_path  = os.path.join(folder, new_name)

        print(f"[{source}] {old_name}")
        print(f"       → {new_name}\n")

        if not dry_run:
            try:
                os.rename(path, new_path)
                renamed += 1
            except Exception as e:
                errors.append((path, str(e)))
        else:
            renamed += 1

    label = "Would rename" if dry_run else "Renamed"
    print(f"\n{label}: {renamed}  |  Skipped: {skipped}  |  Errors: {len(errors)}")
    for p, e in errors:
        print(f"  ERROR {p}: {e}")


if __name__ == "__main__":
    dry_run = "--apply" not in sys.argv
    if dry_run:
        print("=== DRY RUN (pass --apply to rename) ===\n")
    else:
        print("=== APPLYING RENAMES ===\n")
    main(dry_run=dry_run)
