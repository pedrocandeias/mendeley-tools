#!/usr/bin/env python3
"""
Organize files from toorganize/ (or the root dir) into the appropriate library folders.

Modes:
  default   — process toorganize/ subfolder (original behaviour)
  --root    — process PDFs sitting in the root material dir instead

Root mode extras (run before classification):
  • Renames files whose names contain newline characters (replaces \\n with space)
  • Strips double .pdf.pdf extensions
  • Skips files that are size-duplicates of a file already present in the target folder

Steps:
  1. Collect PDFs from the source (toorganize/ or root)
  2. For each PDF, try to match against missing papers in elicit_missing_papers.csv
     - If matched: move to the CSV-specified folder, mark paper as found
     - If unmatched: classify by title keywords and move to best folder (or outros)
  3. Rewrite elicit_missing_papers.csv with only the still-missing papers
"""

from __future__ import annotations

import csv
import os
import re
import shutil
import sys
from pathlib import Path
from collections import defaultdict

MATERIAL_DIR = Path(__file__).parent
TOORGANIZE   = MATERIAL_DIR / "toorganize"
MISSING_CSV  = MATERIAL_DIR / "elicit_missing_papers.csv"

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

# Dirs at root that are never PDFs to organise
_NON_PDF_DIRS = set(FOLDER_MAP) | {"capitulos", "Diagramas", "Modelos de proteses", "__pycache__"}

FOLDER_RULES = [
    # ── High-specificity folders first so their strong signals dominate ──────
    ("normas", [
        ("iso 8549", 8), ("iso 7250", 8), ("iso standard", 5),
        ("standars for prosthetics", 6), ("standars and prosthetics", 6),
        ("standars", 4), ("implementation manual prosthetics", 5),
        ("body measurement definitions", 5), ("measurement landmarks", 4),
        ("standard guide", 3), ("testing protocol", 3),
        ("evaluation protocol", 2), ("assessment protocol", 2),
    ]),
    ("prosthetics-user", [
        # Abandonment / rejection — very specific, scores must beat prosthetics-design baseline ~6.5
        ("prosthesis use and abandonment", 9), ("reasons for abandonment", 9),
        ("quality of life and reasons for abandonment", 9),
        ("prosthetic abandonment", 8), ("abandonment of upper limb prosthes", 8),
        ("prosthesis rejection", 8), ("rejection prosth", 7),
        ("product abandonment", 7), ("abandonment", 4),
        # Satisfaction / lived experience
        ("measuring satisfaction with upper limb", 9), ("measuring satisfaction", 8),
        ("lived experience of people with upper limb", 9), ("lived experience", 7),
        ("social aspects of prosthetic", 8), ("social aspects prosth", 7),
        ("upper limb absence", 7), ("consumer design priorities", 8),
        ("consumer design prosth", 6), ("quality of life prosth", 4),
        ("satisfaction prosth", 4), ("user needs prosth", 4),
        ("prosthetics users", 5),
        # General user-centred design
        ("user involvement", 2), ("patient centered", 2), ("user centered", 2),
        ("human centered design", 2), ("inclusive design", 2), ("universal design", 2),
        ("user require", 2), ("user satisfaction", 2), ("user acceptance", 2),
        ("user experience prosth", 3), ("design for disabled", 2),
        ("consumer", 1), ("end user", 2), ("end-user", 2),
    ]),
    ("prosthetics-control", [
        # EMG / myoelectric — very specific
        ("hd emg", 6), ("emg interfaces", 6), ("myoelectric control", 5),
        ("emg control", 5), ("switchable impedance", 6), ("multi grip myoelectric", 6),
        ("sensory feedback prosth", 6), ("sensory feedback from a prosth", 6),
        ("motor learning prosth", 5), ("enhanced motor learning", 5),
        ("electromyograph", 4), ("myoelectric prosth", 4), ("emg", 2),
        ("impedance control", 3), ("motor control", 2),
        ("neural interface", 3), ("pattern recognition", 3), ("brain computer", 3),
        ("artificial intelligence prosth control", 4),
    ]),
    ("colaboracao", [
        # Very specific collaboration signals
        ("alongside designer", 7), ("innovating alongside", 7),
        ("clients and carers", 7), ("designing industrial design highly regulated", 6),
        ("highly regulated medical device", 6), ("medical device development", 5),
        ("healthcare professional role", 5), ("citizen participation", 5),
        ("challenge of citizens participation", 7), ("challenge citizen", 4),
        ("human ai collaborat", 5),
        ("co design", 4), ("codesign", 4), ("collaborative design", 4),
        ("participatory design", 4), ("user co creat", 4), ("co creat", 3),
        ("participatory research", 3), ("user participat", 3),
    ]),
    ("reabilitacao", [
        # High-specificity rehab signals
        ("community reintegrat", 6), ("return to work", 6),
        ("access to prosthetic", 6), ("provision of prosthetic", 6),
        ("provision of orthotic", 6), ("low income countr prosthetic", 6),
        ("functional recovery", 5), ("barriers and facilitator", 5),
        ("social participation", 5), ("dysvascular", 5),
        ("care needs reintegrat", 5), ("prosthetic services", 4),
        ("quality of life and prosthesis use", 5), ("economic impact prosthetic", 5),
        ("epidemiology and burden of prosthetic joint", 6),
        ("economic impact of prosthetic joint infection", 7),
        ("effect of different prosthetic components on human functioning", 7),
        ("burden prosthetic joint infection", 6),
        ("joint infection prosthetic", 5), ("handbook return to work", 5),
        # General rehab signals
        ("rehabilitation", 2), ("occupational therap", 3), ("physical therap", 3),
        ("assistive technolog", 2), ("stroke rehab", 3), ("upper limb rehab", 3),
        ("assistive device", 2), ("mobility assistive", 2), ("therapy", 1),
    ]),
    ("amputacao", [
        # Very specific Portuguese/epidemiology signals
        ("amputações realizadas em portugal", 7), ("amputados membro inferior", 6),
        ("amputação de membros", 7), ("qualidade de vida após amputação", 7),
        ("consequências da amputação", 7), ("escalas de qualidade de vida amput", 7),
        ("unidade de medicina física", 6), ("população portuguesa de amputados", 7),
        ("caracterização psicossocial", 6), ("caracterização de uma população amput", 7),
        ("limb loss facts", 6), ("global trends incidence", 5),
        ("psychological consequences limb amputation", 6),
        ("psychiatric understanding treatment amput", 6),
        ("depression and ptsd in adults with surgically", 7),
        ("ptsd amput", 5), ("depression amput", 5),
        ("global burden traumatic amputation", 6), ("global prevalence traumatic", 6),
        ("incidence lower limb amputation", 6), ("causes lower limb amput", 5),
        ("prevalence limb loss", 5), ("estimating prevalence limb", 5),
        ("epidemiology amputation", 5), ("determinant causes limb amputation", 6),
        # General
        ("limb amputation", 3), ("limb loss", 3),
        ("amputee", 2), ("amputat", 2),
    ]),
    ("lower-limb", [
        ("lower limb active prosthetic systems", 7), ("lower limb active prosthetic", 5),
        ("transtibial", 3), ("transfemoral", 3), ("trans tibial", 3), ("trans femoral", 3),
        ("below knee", 3), ("above knee", 3),
        ("residual limb", 3), ("prosthetic socket", 3), ("socket design", 3),
        ("ankle prosth", 3), ("ankle foot orthes", 3), ("foot prosth", 3),
        ("prosthetic leg", 3), ("leg prosth", 3), ("tibial prosth", 3),
        ("femoral prosth", 3), ("lower limb prosth", 3), ("lower limb prosthetics", 3),
        ("lowerlimb prosth", 3), ("stump socket", 3), ("inferior limb", 2),
        ("lower extremit prosth", 3), ("residual lower limb", 3), ("socket", 1),
    ]),
    ("3dprinting-prosthetics", [
        ("digital fabrication prosth", 6), ("digital fabrication orthes", 6),
        ("scoping review digital fabricat", 6), ("digital fabrication techniques", 6),
        ("open source prosth", 6), ("open-source prosth", 6),
        ("implementation of 3d printing technology in the field of prosthetics", 8),
        ("implementation 3d printing prosth", 6), ("3d printing field prosth", 5),
        ("3d printed joints", 4), ("low cost 3d printed prosth", 5),
        ("3d printed prosth", 4), ("3d printing prosth", 4),
        ("additive manufactur prosth", 4), ("3d printed orthes", 3),
        ("additive manufactur orthes", 3), ("3d printed socket", 3),
        ("3d printed prostheses", 4), ("low cost prosthetics", 3),
        ("low cost prostheses", 3), ("3dprinting prosth", 3),
    ]),
    ("antropometria", [
        # Grasp studies — very specific
        ("common grasps used", 7), ("grasps used by adults", 7),
        ("grasps used", 6), ("common grasps", 5), ("daily living grasp", 5),
        ("grasp pattern", 4), ("hand grasp", 3), ("hand grip pattern", 4),
        # Portuguese anthropometry studies
        ("avaliação antropométrica", 6), ("avaliacao antropometrica", 6),
        ("população escolar", 5), ("ensino básico", 5),
        # General anthropometry
        ("anthropometr", 2), ("body measurement", 2), ("hand dimension", 3),
        ("3d scan", 2), ("3d scanner", 2), ("photogrammetr", 2), ("laser scan", 2),
        ("body scan", 2), ("surface reconstruction", 2), ("3d body", 2),
        ("body model", 2), ("optical measur", 2), ("non contact measur", 2),
        ("scanning technolog", 2), ("anthropomorphic measur", 2),
        ("shape sensing", 2), ("digitiz", 1), ("shape model", 1),
    ]),
    ("parametrico", [
        # Very specific
        ("grasshopper", 6), ("algorithms aided design", 6),
        ("genetic algorithm prosth", 7), ("genetic algorithm customized prosth", 7),
        ("genetic algorithm", 5),
        ("parametric 3d modeling prosth finger", 6), ("parametric 3d modeling", 5),
        # General parametric
        ("parametric design", 3), ("parametric model", 3), ("parametric prosth", 4),
        ("parametric cad", 3), ("parametric approach", 2), ("parametric method", 2),
        ("cad cam", 2), ("cad/cam", 2), ("generative design", 3),
        ("topology optim", 3), ("computational design", 2), ("automated design", 2),
        ("design automation", 2), ("generative adversarial", 3),
        ("computer aided design", 2), ("algorithmic design", 2),
    ]),
    ("prosthetics-design", [
        ("upper limb prosth", 4), ("upper extremit prosth", 4),
        ("upperlimb prosth", 4), ("hand prosth", 3), ("arm prosth", 3),
        ("myoelectric", 3), ("transradial", 3), ("transhumeral", 3),
        ("trans humeral", 3), ("prosthetic hand", 3), ("prosthetic arm", 3),
        ("prosthetic limb", 3), ("prostheses", 1.5), ("prosthesis", 1.5),
        ("biomimetic prosth", 4), ("anthropomorphic robotic hand", 4),
        ("tendon driven robotic hand", 5), ("lightweight prosthetic hand", 4),
        ("lightweight delft", 5), ("smit 2014 delft", 6),
        ("highly biomimetic", 4), ("artificial limb regenerat", 4),
        ("orthosis design", 2), ("orthotic design", 2), ("custom orthes", 2),
        ("exoskeleton", 2), ("prosthetic cover", 2), ("prostheti", 1),
        ("orthosi", 1), ("orthes", 1),
    ]),
]

MIN_SCORE = 1.5

IRRELEVANT_MARKERS = [
    "office chair", "apparel industr", "clothing", "furniture design",
    "architecture", "intravenous therap", "urban public", "fluid dynam",
    "shoe design", "learning environment", "hospital logistic",
]


def normalize(text: str) -> str:
    text = text.lower()
    text = text.replace('_', ' ')           # treat underscores as word separators
    text = re.sub(r'(?<=\w)-(?=\w)', ' ', text)
    text = re.sub(r'[^\w\s]', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()


def similarity(a: str, b: str) -> float:
    stop = {'a','an','the','of','in','on','for','and','with','to','by','at',
            'as','is','are','from','using','based','via','its','de','da','do',
            'e','em','um','uma','para'}
    ta = set(normalize(a).split()) - stop
    tb = set(normalize(b).split()) - stop
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / max(len(ta), len(tb))


def classify_paper(title: str) -> tuple[str, float]:
    t = normalize(title)
    for marker in IRRELEVANT_MARKERS:
        if marker in t:
            return "outros", 0.0
    best_folder, best_score = "outros", 0.0
    for folder, rules in FOLDER_RULES:
        score = sum(w for kw, w in rules if normalize(kw) in t)
        if score > best_score:
            best_score = score
            best_folder = folder
    if best_score < MIN_SCORE:
        return "outros", best_score
    return best_folder, best_score


def safe_dest(folder_path: Path, stem: str) -> Path:
    """Return a destination path that doesn't overwrite existing files."""
    dest = folder_path / (stem + ".pdf")
    if not dest.exists():
        return dest
    i = 2
    while True:
        dest = folder_path / f"{stem} ({i}).pdf"
        if not dest.exists():
            return dest
        i += 1


# ── Root-mode helpers ─────────────────────────────────────────────────────────

def _sizes_in_folder(folder: Path) -> set[int]:
    """Return the set of file sizes already present in a folder."""
    return {f.stat().st_size for f in folder.iterdir() if f.is_file() and f.suffix.lower() == ".pdf"}


def _fix_root_filename(pdf: Path, dry_run: bool) -> Path:
    """
    Fix two common issues in root-level filenames:
      1. Newline characters in the name  (replace with space)
      2. Double .pdf.pdf extension        (strip extra suffix)
    Returns the (possibly renamed) Path.
    """
    name = pdf.name
    fixed = name.replace("\n", " ").replace("\r", " ")
    # Collapse multiple spaces introduced by newline replacement
    fixed = re.sub(r" {2,}", " ", fixed).strip()
    # Strip double .pdf extension: "foo.pdf.pdf" → "foo.pdf"
    if re.search(r"\.pdf\.pdf$", fixed, re.IGNORECASE):
        fixed = fixed[:-4]  # remove trailing ".pdf"
    if fixed == name:
        return pdf
    new_path = pdf.parent / fixed
    if new_path.exists():
        # Already exists with clean name — the .pdf.pdf is a true duplicate; remove it
        print(f"  DEL (dup name) {name}")
        if not dry_run:
            pdf.unlink()
        return new_path  # caller will see it as already moved/deleted
    print(f"  REN {repr(name)}\n      → {repr(fixed)}")
    if not dry_run:
        pdf.rename(new_path)
    return new_path


def collect_root_pdfs() -> list[Path]:
    """Collect PDFs that sit directly in MATERIAL_DIR (not in subdirs)."""
    pdfs = []
    for entry in MATERIAL_DIR.iterdir():
        if entry.is_file() and entry.suffix.lower() == ".pdf":
            pdfs.append(entry)
    return sorted(pdfs)


def _is_size_duplicate(pdf: Path, dest_dir: Path) -> bool:
    """True if a file of the same size already exists in dest_dir."""
    size = pdf.stat().st_size
    return size in _sizes_in_folder(dest_dir)


# ── Main ──────────────────────────────────────────────────────────────────────

def main(root_mode: bool = False, dry_run: bool = False) -> None:
    # ── Load missing papers (no_pdf only) ─────────────────────────────────────
    all_rows: list[dict] = []
    if MISSING_CSV.exists():
        with open(MISSING_CSV, encoding="utf-8") as f:
            all_rows = list(csv.DictReader(f))
    # Accept rows with no download_status field (elicit_missing_papers.csv format)
    # or rows explicitly marked no_pdf (elicit_download_report format)
    missing = [r for r in all_rows
               if r.get("download_status") in (None, "", "no_pdf")]
    print(f"Missing papers in CSV: {len(missing)}")

    # ── Collect PDFs ──────────────────────────────────────────────────────────
    if root_mode:
        print("\n[Root mode] Pre-processing root filenames…")
        raw_pdfs = collect_root_pdfs()
        pdfs: list[Path] = []
        for pdf in raw_pdfs:
            fixed = _fix_root_filename(pdf, dry_run)
            if fixed.exists():
                pdfs.append(fixed)
        # Deduplicate list (renaming may have merged two entries to the same path)
        seen: set[Path] = set()
        unique_pdfs: list[Path] = []
        for p in pdfs:
            if p not in seen:
                seen.add(p)
                unique_pdfs.append(p)
        pdfs = unique_pdfs
        print(f"Root PDFs to organise: {len(pdfs)}")
    else:
        pdfs = list(TOORGANIZE.rglob("*.pdf"))
        print(f"PDFs in toorganize: {len(pdfs)}")

    moved: list[tuple[Path, Path, str]] = []
    skipped_dup: list[Path] = []
    matched_paper_titles: set[str] = set()

    # ── Step 1: match against missing papers ──────────────────────────────────
    print("\nMatching against missing papers…")
    for pdf in pdfs:
        if not pdf.exists():
            continue
        stem = pdf.stem
        # Strip trailing .pdf if double-extension slipped through
        if stem.lower().endswith(".pdf"):
            stem = stem[:-4]
        best_score = 0.0
        best_row = None
        for row in missing:
            s = similarity(stem, row["title"])
            if s > best_score:
                best_score = s
                best_row = row

        if best_score >= 0.45 and best_row:
            folder = best_row["folder"]
            dest_dir = MATERIAL_DIR / folder
            dest_dir.mkdir(exist_ok=True)
            if root_mode and _is_size_duplicate(pdf, dest_dir):
                print(f"  SKIP (dup size→{folder}) {stem[:60]}")
                skipped_dup.append(pdf)
                if not dry_run:
                    pdf.unlink()
                continue
            dest = safe_dest(dest_dir, stem)
            if not dry_run:
                shutil.move(str(pdf), dest)
            moved.append((pdf, dest, f"matched '{best_row['title'][:50]}' ({best_score:.2f})"))
            matched_paper_titles.add(best_row["title"])
            print(f"  ✓ [{folder}] {stem[:60]}  ({best_score:.2f})")

    # ── Step 2: classify & move remaining unmatched PDFs ──────────────────────
    remaining = [p for p in pdfs if p.exists()]

    print(f"\nClassifying {len(remaining)} unmatched PDFs…")
    for pdf in remaining:
        stem = pdf.stem
        if stem.lower().endswith(".pdf"):
            stem = stem[:-4]
        folder, score = classify_paper(stem)
        dest_dir = MATERIAL_DIR / folder
        dest_dir.mkdir(exist_ok=True)
        if root_mode and _is_size_duplicate(pdf, dest_dir):
            print(f"  SKIP (dup size→{folder}) {stem[:60]}")
            skipped_dup.append(pdf)
            if not dry_run:
                pdf.unlink()
            continue
        dest = safe_dest(dest_dir, stem)
        if not dry_run:
            shutil.move(str(pdf), dest)
        moved.append((pdf, dest, f"classified ({score:.1f})"))
        print(f"  → [{folder}] {stem[:65]}  ({score:.1f})")

    # ── Step 3: update missing CSV ────────────────────────────────────────────
    matched_titles_norm = {normalize(t) for t in matched_paper_titles}
    still_missing = [r for r in missing if normalize(r["title"]) not in matched_titles_norm]

    print(f"\nResults:")
    print(f"  PDFs moved:               {len(moved)}")
    print(f"  Duplicates removed:       {len(skipped_dup)}")
    print(f"  Missing papers resolved:  {len(matched_paper_titles)}")
    print(f"  Still missing:            {len(still_missing)}")

    if all_rows:
        fields = [f for f in all_rows[0].keys() if f not in ("download_status", "local_path")]
        if not dry_run:
            with open(MISSING_CSV, "w", encoding="utf-8", newline="") as f:
                w = csv.DictWriter(f, fieldnames=fields)
                w.writeheader()
                for row in still_missing:
                    w.writerow({k: row[k] for k in fields})
            print(f"  Updated {MISSING_CSV.name} → {len(still_missing)} rows")
        else:
            print(f"  (dry-run) would update {MISSING_CSV.name} → {len(still_missing)} rows")

    # ── Clean up empty toorganize subdirs (non-root mode only) ────────────────
    if not root_mode:
        for dirpath in sorted(TOORGANIZE.rglob("*"), reverse=True):
            if dirpath.is_dir():
                try:
                    dirpath.rmdir()
                    print(f"  Removed empty dir: {dirpath.relative_to(MATERIAL_DIR)}")
                except OSError:
                    pass
        try:
            TOORGANIZE.rmdir()
            print(f"  Removed empty toorganize/")
        except OSError:
            pass


def reclassify(dry_run: bool = False, all_folders: bool = False) -> None:
    """Re-evaluate PDFs in known subfolders and move misclassified ones.

    By default only promotes files out of 'outros' (the catch-all bucket).
    Pass all_folders=True to reclassify across every folder.
    """
    source_folders = list(FOLDER_MAP) if all_folders else ["outros"]
    moved = 0
    for folder in source_folders:
        folder_path = MATERIAL_DIR / folder
        if not folder_path.is_dir():
            continue
        for pdf in sorted(folder_path.glob("*.pdf")):
            stem = pdf.stem
            new_folder, score = classify_paper(stem)
            if new_folder == folder:
                continue  # already in the right place
            dest_dir = MATERIAL_DIR / new_folder
            dest_dir.mkdir(exist_ok=True)
            dest = safe_dest(dest_dir, stem)
            print(f"  [{folder}] → [{new_folder}] ({score:.1f})  {stem[:70]}")
            if not dry_run:
                shutil.move(str(pdf), dest)
            moved += 1
    print(f"\n{'Would move' if dry_run else 'Moved'}: {moved} files")


if __name__ == "__main__":
    root_mode    = "--root"       in sys.argv
    reclassify_  = "--reclassify" in sys.argv
    dry_run      = "--apply"      not in sys.argv
    if dry_run:
        print("=== DRY RUN (pass --apply to make changes) ===\n")
    else:
        print("=== APPLYING CHANGES ===\n")
    if reclassify_:
        all_folders = "--all" in sys.argv
        mode_label = "ALL subfolders" if all_folders else "outros only"
        print(f"=== RECLASSIFY MODE ({mode_label}) — pass --all to reclassify every folder ===\n")
        reclassify(dry_run=dry_run, all_folders=all_folders)
    else:
        if root_mode:
            print("=== ROOT MODE — processing root-level PDFs ===\n")
        main(root_mode=root_mode, dry_run=dry_run)
