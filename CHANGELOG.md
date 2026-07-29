# Changelog

## [Unreleased]

## [0.6.0] — 2026-07-29

Redução do repositório às ferramentas Mendeley. Até aqui a pasta `material/` do projecto do mestrado *era* o clone deste repositório, pelo que ficheiros que nada têm de independente foram versionados aqui por arrastamento.

### Removed
- **BREAKING** — saíram 15 ficheiros que pertencem ao projecto que usa as ferramentas, não às ferramentas: os *scripts* Elicit (`elicit_download.py`, `elicit_fetch_missing.py`, `elicit_sync.py` — este último lê os capítulos da dissertação), `extract_figures_tables.py`, `flag_titles.py`, `rename_pdfs.py`, `organize_toorganize.py`, os dados da tese (`figures_tables_index.md`, `figures_tables_suggestions.md`, `titles_to_fix.txt`, `dadosantropometricos-dined.txt`) e artefactos que nunca deviam ter sido versionados (`.elicit_cache.json`, `.fetch_cache.json`, `.ss_cache.json` e um ficheiro de bloqueio do LibreOffice). Todos continuam no repositório do mestrado, em versões mais recentes: as cópias que aqui estavam eram anteriores e ainda continham caminhos absolutos como `/home/pec/Desktop/mestrado/projeto/material`.

### Fixed
- `.gitignore` — era o da pasta `material/` e ignorava as pastas temáticas de PDFs, `capitulos/` e `*.csv`. Substituído pelo de um repositório de ferramentas: `__pycache__`, credenciais, e os artefactos de execução (dumps da biblioteca, relatórios, PDFs).
- `README.md` — a secção «Other Files» e a resolução de problemas referiam `titles_to_fix.txt`, `flag_titles.py` e `rename_pdfs.py`, que saíram; o diagnóstico de PDFs sem correspondência passa a descrever o que o enriquecedor imprime.

### Note
- As entradas anteriores a 0.5.0 descrevem vários destes *scripts*. Ficam como registo histórico do período em que este repositório e a pasta `material/` eram a mesma coisa.

## [0.5.0] — 2026-07-29

Reunião do repositório com os scripts que tinham divergido no repositório do mestrado, onde eram mantidos desde 2026-05-03. O repositório passa a ser consumido como submódulo em `tools/mendeley-tools`.

### Added
- `mendeley_normalise_titles.py` — normaliza títulos, autores e fontes: TÍTULOS EM MAIÚSCULAS, apelidos em maiúsculas, entidades e etiquetas HTML, quebras de linha vindas da extracção de PDF, espaços duplicados, ponto final, iniciais com ponto duplicado e nomes de ficheiro usados como título. Prefere o título do CrossRef quando o registo tem DOI e é idempotente: uma segunda execução não regrava o que já está correcto.
- `mendeley_title_overrides.json` — títulos revistos à mão para os registos que nenhuma heurística resolve, porque o próprio CrossRef guarda o título em maiúsculas. Um valor `null` exclui o registo.
- `mendeley_dedupe.py` e `mendeley_sync_dois.py` — deduplicação da biblioteca e sincronização de DOIs contra a bibliografia de um manuscrito; existiam desde 2026-07-23 mas nunca tinham chegado a este repositório.
- `mendeley_paths.py` — resolução partilhada de caminhos, para que os scripts deixem de assumir que estão dentro de um repositório concreto.
- `README.md` — as três ferramentas em falta documentadas com o par pré-visualização/`--apply`, mais a explicação de por que razão os títulos em maiúsculas não se corrigem automaticamente quando é o editor que os guarda assim no CrossRef.

### Changed
- **BREAKING** — `mendeley_enrich.py` e `mendeley_organizer.py` deixam de assumir que a pasta dos PDFs é `../material`: aceitam `--material DIR` ou `$MENDELEY_MATERIAL` e, em último recurso, procuram `./material` e o directório actual. `mendeley_sync_dois.py` deixa de ter o nome do manuscrito escrito no código e exige `--md FILE` ou `$MENDELEY_MANUSCRIPT`; em `mendeley_normalise_titles.py` o manuscrito só é necessário para `--only-cited`. Um caminho indicado explicitamente e inexistente termina o script, em vez de recorrer silenciosamente ao directório actual.
- `mendeley_enrich.py` — incorporadas as melhorias feitas do lado do mestrado: opção `--dir` para percorrer uma pasta única e listagem dos PDFs sem correspondência.

### Fixed
- `README.md` — as instruções de execução apontavam para uma pasta de scripts descompactados. Acrescentado o contorno para `ModuleNotFoundError: keyring` (usar o interpretador em `~/.local/share/uv/tools/mendeley-mcp/bin/python`) e a nota de que nenhuma correcção chega ao documento Word antes de um *Refresh* do Mendeley Cite.

### Note
- As entradas 0.4.1 a 0.4.3 descrevem `extract_suggested_assets.py`, que vive no repositório do mestrado e não aqui; acumularam neste ficheiro enquanto as duas cópias estiveram divergentes.

## [0.4.3] — 2026-05-03

### Fixed
- `extract_suggested_assets.py` — four improvements to `_find_figure_crop()`:
  1. **Two-column left threshold**: lowered `b[0] > page_w * 0.54` to `b[0] > page_w * 0.50` so right-column blocks starting just past the midpoint (e.g. x0=313 in 612pt pages) are detected; right boundary now set dynamically to `right_start − 5` rather than a fixed `px_mid + 15`.
  2. **Two-column right threshold**: lowered `cap_x_frac > 0.56` to `cap_x_frac > 0.52` to correctly classify right-column captions whose label centre lands between 0.52–0.56 (e.g. "Fig. 3." at x_frac=0.530); left boundary now set dynamically to `left_end + 5`.
  3. **Caption block x-filter**: `cap_block` search now requires the candidate block to start on the same side of the page midpoint as the caption search hit, preventing a tall left-column body block from being picked as the caption block for a right-column caption and pushing `bot_y` too far down.
  4. **Full-width figure guard**: opposing-column blocks are now only counted if they start above the caption (`b[1] < cap_top`); this prevents full-width figures (whose body text sits entirely below the caption) from being falsely cropped to half the page width.

## [0.4.2] — 2026-05-03

### Added
- `extract_suggested_assets.py`: script that reads `figures_tables_suggestions.md`, fuzzy-matches each referenced paper to its PDF, and extracts assets into two new folders.
- `figuras/`: 377 PNG/JPEG images extracted from the referenced PDF pages (all 8 thesis chapters covered, named `ch{N}_{paper}_{fig}{N}_p{page}_*.png`).
- `tabelas/`: 62 Markdown table files extracted from the referenced PDF pages (38 parsed tables + 24 raw-text fallbacks for image-rendered tables).

## [0.4.1] — 2026-05-03

### Changed
- `figures_tables_suggestions.md`: fully regenerated against the current index (273 papers, 2077 figures, 616 tables) and the complete thesis structure (Chapters 1–9). Suggestions now cover all developed chapters (1–8) with 2–6 items per subsection; notes section added at the end to guide folder-level usage.

## [0.4.0] — 2026-05-03

### Changed
- `figures_tables_suggestions.md`: fully regenerated against the updated index (268 papers, 2002 figures, 597 tables) and the complete Chapter 1–7 thesis structure. Three new papers with captions placed: `A framework for configuring participation in living labs.pdf` → §2.6 and §5.1; `Low Cost Hand-Tracking Devices to Design Customized Medical Devices.pdf` → §2.4 and §4.2; `Parametric CAD modeling for open source scientific hardware Comparing OpenSCAD and FreeCAD Python scripts.pdf` → §4.3, §5.3, and §5.5. Two scanned papers (no captions, not indexed) noted explicitly.

## [0.3.9] — 2026-05-03

### Added
- `figures_tables_suggestions.md`: curated mapping of figures and tables from `figures_tables_index.md` to specific thesis sections (Chapters 1–7). 2–5 items per subsection; sections with no suitable matches noted explicitly. Generated by cross-referencing 265 papers against the full thesis chapter structure.

## [0.3.8] — 2026-05-03

### Added
- `extract_figures_tables.py`: script that scans all PDFs in `material/` with PyMuPDF, extracts figure and table captions via block-anchored regex, and writes a structured markdown index.
- `figures_tables_index.md`: auto-generated index of 1,962 figures and 587 tables across 265 papers, organised by topic folder.

## [0.3.7] — 2026-05-02

### Changed
- `data_extraction_explained.md` substantially updated:
  - Section 5: added entries 5.10 (ANSUR II), 5.11 (DINED three sub-datasets), 5.12 (Hu et al. 2007 — Beijing elderly), 5.13 (Zhou et al. 2016 exclusion with rationale)
  - Section 8: script now described as 10 sections (was 7)
  - Section 9: row count updated to 1,790; countries to 9; studies to 11
  - Section 10: completely rewritten as "Cobertura Global e Lacunas" — replaces future-sources list with structured analysis of geographic, demographic, and statistical coverage; lacunas by region, age group, and population type; future sources retained as subsection 10.3 with verified DOIs; Zhuang et al. 2013 removed (reference unverifiable); Ran et al. 2009 and Chen et al. 2022 added as verified alternatives

## [0.3.6] — 2026-05-02

### Added
- `generate_multi_population_hand_csv.py` extended with China / Beijing elderly data; `multi_population_hand.csv` grows from 1,740 → 1,790 rows:
  - **China / Beijing elderly** (Hu et al. 2007, *Int. J. Industrial Ergonomics* 37:303–311, DOI: 10.1016/j.ergon.2006.11.006): n=108 community-dwelling elderly (58F, 50M), age 65–85, Beijing area. 5 hand/forearm measurements: hand breadth (metacarpal), maximum hand breadth, hand length, finger length (middle finger, GB/T 5703-1999), forearm-fingertip length. Stats per measurement × sex: mean, SD, P5, P50, P95. First Chinese population in the dataset; extends elderly coverage beyond the Netherlands.

### Changed
- `1-s2.0-S0169814106002642-main.pdf` renamed to `Anthropometric measurement of the Chinese elderly living in the Beijing area (Hu et al., 2007).pdf` in `material/antropometria/`
- `1-s2.0-S0169814115300445-main.pdf` renamed to `Anthropometric body modeling based on orthogonal-view images (Zhou et al., 2016).pdf` in `material/antropometria/` (methodology paper; no population data encoded)
- `Outcomes of assistive technology use by sex and gender a scoping review.pdf` moved from project root to `material/reabilitacao/`

## [0.3.5] — 2026-05-02

### Added
- `generate_multi_population_hand_csv.py` extended with Netherlands / DINED data (three sub-datasets); `multi_population_hand.csv` grows from 888 → 1,740 rows:
  - **Netherlands / kima1993** (TNO/DINED): Dutch children ages 2–12, integer-year age groups, by sex and combined. 8 hand measurements per group (hand length, hand width without thumb, thumb breadth, hand thickness, little-finger breadth, middle-finger length, hand diameter, grip circumference). Mean ± SD only (no percentiles). 528 rows.
  - **Netherlands / geron1998** (TNO/DINED): Dutch elderly ages 50–80+, 5-year bands, by sex and combined. 5 hand measurements per group (hand length, hand width without thumb, thumb breadth, forefinger breadth, grip circumference). Mean ± SD only. 210 rows.
  - **Netherlands / dined2004** (TNO/DINED): Dutch adults ages 20–30, 31–60, 60+, by sex and combined. 6–7 hand measurements per group (hand length, hand width without thumb, thumb breadth, forefinger breadth, hand width with thumb, hand thickness; grip circumference for 20–30 group only). Mean ± SD only. Combined 20–60 age group excluded (redundant summary). 114 rows.

## [0.3.4] — 2026-05-02

### Added
- `generate_multi_population_hand_csv.py` extended with ANSUR II (2012) data; `multi_population_hand.csv` grows from 734 → 888 rows:
  - **USA / ANSUR II** (Gordon et al. 2015, NATICK/TR-15/007): n=6,068 US Army personnel (4,082M, 1,986F), age 17–58. Statistics computed from raw individual CSVs (public release 2017, CC BY 4.0). 7 hand/forearm measurements encoded: hand length, hand breadth (metacarpal), hand circumference, palm length, wrist circumference, forearm-hand length, forearm-center of grip length. Full 11-statistic set per measurement × sex: mean, SD, min, max, P5, P10, P25, P50, P75, P90, P95. `wristheight` excluded (floor-to-wrist standing posture measurement, not a hand dimension).

## [0.3.3] — 2026-05-02

### Changed
- `elicit_missing_papers.csv`: Mistarihi 2020 ("A data set on anthropometric measurements...") removed — confirmed present at `outros/1-s2.0-S2352340920303140-main.pdf` (DOI-based filename prevented fuzzy matching). Missing count: 44 → 43.
- Cross-checked all 44 missing papers against current 365-PDF library using token-overlap fuzzy matching (≥65% threshold). Three 67–75% score matches were investigated and confirmed as false positives (shared generic terms only). No additional papers found.

## [0.3.2] — 2026-05-02

### Changed
- `generate_multi_population_hand_csv.py` extended with two new population sources; `multi_population_hand.csv` grows from 723 → 734 rows:
  - **Jordan** (Mistarihi 2020, *Data in Brief* 30:105420): n=40 physically disabled workers, Irbid governorate, age 20-40, mixed sex combined. Added hand length (mean 168.3±3.9mm, P5=162, P95=173.3) and elbow-fingertip length (mean 42.6±1.4cm, P5=40, P95=45) from Table 4; hand width (8.1cm) from Figure 2 body-dimensions diagram (mean only, no SD). First Middle Eastern population in the dataset.
  - **USA / D2 index finger** (Lim et al. 2018, UC Berkeley): n=50 adults age 18-30. Added index finger (D2) length (MCP crease to tip, mean=90.9mm) and D2 width (PIP joint, mean=16.9mm). Mean only; no SD or percentiles. Flagged with R²=0.18 for length–width correlation (weak).

## [0.3.1] — 2026-05-01

### Added
- `generate_ansur_csv.py` in `/home/pec/dev/ai-parametric-prosthetic-hand-generator/data/` — embeds all 47 ANSUR 1988 measurements (Gordon et al. 1989) as Python dicts and generates two CSVs: `ansur_1988_complete.csv` (2,726 rows, all body regions) and `ansur_1988_hand_arm.csv` (696 rows, hand/forearm/upper_arm only). Schema: `source_document`, `source_page`, `source_citation`, `measurement_name`, `body_region`, `population`, `country`, `sex`, `sample_size`, `stat_type`, `percentile`, `value_cm`, `value_mm`, `value_in`, `data_quality_note`. Seven source-document typos corrected inline with notes.
- `generate_multi_population_hand_csv.py` in the same `data/` folder — encodes hand anthropometry from five additional population studies and generates `multi_population_hand.csv` (723 rows). Populations covered: Turkey (Chatzioglou et al. 2024, n=51, finger lengths by sex), Mexico (Rodríguez-Vega et al. 2024, n=2,837, hand length/breadth/palm length/grip diameter by sex and 8 age groups), India women (Nag et al. 2003, n=95, 51 dimensions with P5/P50/P95), Portugal (Anacleto Filho et al. 2023, n=343, hand length and breadth), Nigeria (Ibiwari et al. 2025, n=80 athletes, hand length/width/palmar length/digit length by sport). Schema adds `measurement_method_note` and `age_group` columns vs. ANSUR CSV.

## [0.3.0] — 2026-05-01

### Added
- `organize_toorganize.py --root` now matches root PDFs against all rows in `elicit_missing_papers.csv` (previously skipped rows without a `download_status` field)
- `CLAUDE.md` created at `/home/pec/dev/mestrado/` with instructions to update CHANGELOG and bump `Projecto completo.md` version after every change

### Changed
- `elicit_missing_papers.csv`: 13 papers resolved (session 1), then 2 more (session 2) — now 44 remaining
- Opaque filenames renamed to real paper titles before organizing so similarity matching works correctly
- Root-level duplicate PDFs (already present in topic folders) are removed automatically

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
