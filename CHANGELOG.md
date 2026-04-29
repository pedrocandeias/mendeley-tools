# Changelog

## [Unreleased]

## [0.2.0] — 2026-04-29

### Added
- `mendeley_enrich.py` — metadata enrichment script
  - Extracts DOIs from PDF text (first 3 pages) using regex
  - Queries CrossRef API by DOI or title
  - Updates Mendeley documents via PATCH (skip-existing logic)
  - Writes title, authors, year, and abstract into PDF file metadata using PyMuPDF
  - Polite rate limiting (0.5s between CrossRef requests)
  - Dry-run mode by default; `--apply` flag to commit changes

### Results (first run, 2026-04-29)
- 145/158 documents matched on CrossRef
- 23 Mendeley entries updated
- 91 PDF files enriched
- 13 CrossRef misses logged in `titles_to_fix.txt`

## [0.1.0] — 2026-04-29

### Added
- `mendeley_organizer.py` — library organisation script
  - Fuzzy title matching (token overlap, threshold 0.45) between PDF filenames and Mendeley document titles
  - Creates Mendeley folders mirroring local directory structure
  - Adds matched documents to folders; 409 conflicts (already in folder) handled gracefully
  - Dry-run mode by default; `--apply` flag to commit changes
- `flag_titles.py` — scans filenames and flags wrong titles, truncated names, slugs, and duplicates
- `rename_pdfs.py` — renames PDFs using extracted or looked-up metadata
- `titles_to_fix.txt` — tracking file for PDF title issues, with sections:
  - `[WRONG TITLE]` — garbled or leftover filename artefacts
  - `[SKIPPED]` — files that kept their original slug name
  - `[TRUNCATED]` — titles cut off mid-sentence
  - `[NOT MATCHED IN MENDELEY]` — PDFs not found in the Mendeley library
  - `[NOT ENRICHED VIA CROSSREF]` — matched in Mendeley but CrossRef returned no metadata
  - `[DUPLICATES]` — collision-suffix copies to review

### Results (first run, 2026-04-29)
- 12 Mendeley folders created
- 158/202 PDFs matched and assigned to folders
- 44 unmatched PDFs logged in `titles_to_fix.txt`
