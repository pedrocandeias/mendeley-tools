#!/usr/bin/env python3
"""
Scan PDFs and write titles_to_fix.txt with four sections:
  WRONG      – bad metadata / garbled artifact in title
  SKIPPED    – never renamed (original slug/garbled name)
  TRUNCATED  – title clearly cut off mid-sentence
  DUPLICATES – collision files renamed (N); decide which to keep/delete
"""

import os
import re

ROOT     = "/home/pec/Desktop/mestrado/projeto/material"
SKIP_DIRS = {"capitulos", "Diagramas", "Modelos de proteses"}

# ── Helpers ───────────────────────────────────────────────────────────────────

def stem(name):
    """Strip .pdf (including .pdf.pdf)."""
    s = name
    for _ in range(2):
        s = re.sub(r"\.pdf$", "", s, flags=re.IGNORECASE)
    return s

def has_collision_suffix(name):
    return bool(re.search(r"\s\(\d+\)\.pdf$", name, re.IGNORECASE))

# ── WRONG patterns (bad metadata / leftover artifacts) ───────────────────────

WRONG_RE = re.compile(
    r"causesMcDonald_washington"           # thesis filename in title
    r"|libgen\.li\.pdf$"                   # libgen filename artifact
    r"|_7654048"                           # Dialnet ID in title
    r"|ountrieMaster"                      # thesis name fragment
    r"|\[201\."                            # broken year reference [201.
    r"|--\s*\.pdf$"                        # book metadata fragment (-- ...)
    r"|_ISO7250\.pdf$"                     # ISO number glued to title
    r"|\[4724\]"                           # arbitrary ID
    r"|diabetes\.6\.pdf$"                  # .6 version artifact
    r"|Dialnet Estimation"                 # Dialnet ID converted to spaces
    r"|IJSAR \d"                           # journal article code
    r"|^2024 - Goldin"                     # author+year prefix not stripped
    r"|^A U Iwuoha - "                     # author prefix not stripped
    r"|LOWER LIMB ACTIVE PROSTHETIC SYSTEMS OVERVIEW\.pdf$"  # kept all-caps original
    r"|Handbook of Return to Work.*--.*\.pdf$"  # long book archive filename
    r"|The Hand, an Organ.*9780262018845.*\.pdf$"  # long book archive filename
    r"|Parametric design.*develop custom \(3\)\.pdf$",  # M. Moreo – wrong metadata
    re.IGNORECASE,
)

# ── SKIPPED: file was not renamed (still original slug/garbled name) ─────────

SKIPPED_RE = re.compile(
    r"^standars-"                          # standars-for-prosthetics-part1
    r"|^An-introductory-\s"                # space in slug (never fixed)
    r"|^[a-z][a-z0-9-]{10,}\.pdf$",       # pure lowercase-hyphen slug, no year
    re.IGNORECASE,
)

# ── TRUNCATED: genuine cut-off detection ─────────────────────────────────────

# Short words that are valid title endings
SHORT_OK = {
    "a", "an", "the", "of", "in", "on", "to", "for", "and", "or", "is", "it",
    "by", "at", "as", "3d", "ai", "uk", "us", "eu", "no", "do", "use",
    "arm", "arm.", "old", "men", "age", "low",
}

def is_truncated(name):
    if has_collision_suffix(name):
        return False          # handled separately as duplicates
    s = stem(name)
    s_clean = s.rstrip("., ")

    # Explicit fragment patterns
    if re.search(
        r"(\s[a-z]{1,3}\.$"          # ends with ". va"
        r"|\s[a-z]{1,3}$"            # ends with lone 2-3 lowercase word: "scopi"
        r"|\[\d{3}$"                 # ends with "[201" (broken reference)
        r"|,\s*[a-zA-Z]$"            # ends with ", f"
        r"|\bAND\.?\s*$"             # ends with AND
        r"|\bDE\.?\s*$"              # Portuguese "DE"
        r"|\bDO\.?\s*$"              # Portuguese "DO"
        r"|\bDA\.?\s*$"              # Portuguese "DA"
        r"|\bHOW THE\s*$"            # "How the" fragment
        r"|\bfollowing\s*$"          # "following" with no object
        r"|\bus\s*$"                 # ends with "us" (e.g. "versus")
        r")",
        s_clean, re.IGNORECASE
    ):
        return True

    # Last word is suspiciously short and not a known OK ending
    words = s_clean.split()
    if words:
        last = words[-1].rstrip(".,;:").lower()
        if (len(last) <= 3
                and last not in SHORT_OK
                and not last.isdigit()
                and not re.match(r"^\(\d+\)$", last)   # skip (2) etc.
                and not re.match(r"^[ivxlc]+$", last)  # skip roman numerals
        ):
            return True
    return False

# ── Walk & collect ────────────────────────────────────────────────────────────

def collect(root):
    cats = {"wrong": [], "skipped": [], "truncated": [], "duplicate": []}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames
            if d not in SKIP_DIRS and not d.startswith(".")
        ]
        folder = os.path.relpath(dirpath, root)
        for fname in sorted(filenames):
            if not fname.lower().endswith(".pdf"):
                continue
            path = (folder, fname)

            if WRONG_RE.search(fname):
                cats["wrong"].append(path)
            elif SKIPPED_RE.search(fname):
                cats["skipped"].append(path)
            elif has_collision_suffix(fname):
                cats["duplicate"].append(path)
            elif is_truncated(fname):
                cats["truncated"].append(path)

    return cats

# ── Write report ──────────────────────────────────────────────────────────────

SECTIONS = [
    ("wrong",     "WRONG TITLE",
     "These files have bad metadata or leftover filename artifacts."),
    ("skipped",   "SKIPPED (never renamed)",
     "These files kept their original garbled/slug name."),
    ("truncated", "TRUNCATED (title cut off)",
     "These files have titles that appear to end mid-sentence."),
    ("duplicate", "DUPLICATES (collision suffix)",
     "Two or more files had the same title. Check which to keep/delete/merge."),
]

def main():
    cats = collect(ROOT)

    out = os.path.join(ROOT, "titles_to_fix.txt")
    with open(out, "w", encoding="utf-8") as f:
        f.write("PDF TITLES TO FIX MANUALLY\n")
        f.write("=" * 72 + "\n")
        f.write("Instructions:\n")
        f.write("  – Fill in 'Correct:' with the proper title (no .pdf extension).\n")
        f.write("  – Leave 'Correct:' blank to delete the file.\n")
        f.write("  – For DUPLICATES, mark which copy to keep with 'KEEP' and the\n")
        f.write("    others with 'DELETE'.\n\n")

        for key, label, note in SECTIONS:
            items = cats[key]
            f.write("─" * 72 + "\n")
            f.write(f"[{label}]  ({len(items)} files)\n")
            f.write(f"{note}\n")
            f.write("─" * 72 + "\n\n")
            for folder, fname in items:
                f.write(f"  Folder : {folder}\n")
                f.write(f"  Current: {fname}\n")
                f.write(f"  Correct: \n\n")

    total = sum(len(v) for v in cats.values())
    print(f"Written → titles_to_fix.txt")
    for key, label, _ in SECTIONS:
        print(f"  {label:<28} {len(cats[key])}")
    print(f"  {'TOTAL':<28} {total}")


if __name__ == "__main__":
    main()
