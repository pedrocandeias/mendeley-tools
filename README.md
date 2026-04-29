# Mendeley Library Tools

Python scripts for organizing and enriching an academic reference library in Mendeley, built for a Master's dissertation on parametric prosthetic design.

## Scripts

### `mendeley_organizer.py`
Matches local PDF files to Mendeley library entries and assigns them to folders.

- Reads the local directory structure and maps folders to Mendeley folder names
- Fuzzy-matches PDF filenames to Mendeley document titles (token overlap similarity)
- Creates folders in Mendeley if they don't exist
- Adds matched documents to their respective folders (duplicates are safely skipped)

**Usage:**
```bash
# Dry run — preview changes without applying
python mendeley_organizer.py

# Apply changes to Mendeley
python mendeley_organizer.py --apply
```

### `mendeley_enrich.py`
Enriches metadata for organized documents via the CrossRef API and writes it back to both Mendeley and the PDF files.

- Extracts DOIs from PDF text (first 3 pages)
- Queries CrossRef by DOI or title to retrieve authors, year, abstract, journal, and identifiers
- Updates Mendeley documents via `PATCH /documents/{id}` (skips fields that already have data)
- Writes enriched metadata (title, authors, year, abstract) into PDF file properties

**Usage:**
```bash
# Dry run — preview what would be updated
python mendeley_enrich.py

# Apply changes to Mendeley and PDF files
python mendeley_enrich.py --apply
```

### `rename_pdfs.py`
Renames PDF files using metadata extracted from the PDF itself or from Mendeley.

### `flag_titles.py`
Scans PDF filenames and flags issues: wrong/garbled titles, truncated names, slugified names, and duplicate collision suffixes. Outputs findings to `titles_to_fix.txt`.

## Setup

### Prerequisites
- Python 3.10+
- [`uv`](https://docs.astral.sh/uv/) (recommended) or `pip`
- A Mendeley account with an API app registered at [dev.mendeley.com](https://dev.mendeley.com/myapps.html)

### Install dependencies
```bash
uv tool install mendeley-mcp
uv pip install pymupdf --python $(which python3)
```

### Authenticate with Mendeley
```bash
mendeley-auth login
```
This stores OAuth credentials securely in your system keyring.

## Folder Mapping

Local directories are mapped to Mendeley folder names:

| Local folder | Mendeley folder |
|---|---|
| `prosthetics-design` | Design de Próteses |
| `3dprinting-prosthetics` | Impressão 3D em Próteses |
| `antropometria` | Antropometria |
| `amputacao` | Amputação |
| `reabilitacao` | Reabilitação |
| `parametrico` | Modelação Paramétrica |
| `prosthetics-user` | Utilizador de Próteses |
| `colaboracao` | Colaboração e Co-design |
| `prosthetics-control` | Controlo de Próteses |
| `outros` | Outros |
| `lower-limb` | Membro Inferior |
| `normas` | Normas |

## Files

- `titles_to_fix.txt` — manually curated list of PDFs with title issues (wrong title, truncated, not matched in Mendeley, not enriched via CrossRef, duplicates)
- `Elicit - Papers Upper Limb Anthropometry for Prosthetic Design.csv` — exported paper list from Elicit

## Notes

- All Mendeley API calls go directly to `api.mendeley.com` — no third-party intermediaries
- CrossRef is queried with a polite User-Agent header as per their usage guidelines
- The enricher skips fields that already have data in Mendeley (no overwriting)
- PDF metadata is written using [PyMuPDF](https://pymupdf.readthedocs.io/)
