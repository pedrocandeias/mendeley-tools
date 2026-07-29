#!/usr/bin/env python3
"""Path resolution shared by the Mendeley scripts.

These scripts are independent tools: they must not assume they sit inside any
particular repository. Two locations are therefore never hardcoded —

  * the PDF collection ("material"), used by the organiser and the enricher;
  * a manuscript Markdown file whose bibliography is compared against the
    library, used by the DOI sync and (optionally) the title normaliser.

Each is resolved in the same order: the command-line option wins, then an
environment variable, then a sensible guess relative to the current directory.
Set the environment variables once per project to avoid repeating the paths:

    export MENDELEY_MATERIAL=~/dev/mestrado/material
    export MENDELEY_MANUSCRIPT=~/dev/mestrado/pedro-candeias-...-revisto.md
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

MATERIAL_ENV = "MENDELEY_MATERIAL"
MANUSCRIPT_ENV = "MENDELEY_MANUSCRIPT"


def add_material_argument(parser) -> None:
    parser.add_argument(
        "--material", type=Path, metavar="DIR",
        help=f"folder holding the organised PDF subfolders "
             f"(default: ${MATERIAL_ENV}, then ./material, then .)")


def add_manuscript_argument(parser, help_suffix: str = "") -> None:
    parser.add_argument(
        "--md", type=Path, metavar="FILE",
        help=f"Markdown manuscript whose '## Bibliografia' section is read "
             f"(default: ${MANUSCRIPT_ENV}){help_suffix}")


def resolve_material(cli_value: Path | None) -> Path:
    """Folder containing the topic subfolders of PDFs."""
    env_value = os.environ.get(MATERIAL_ENV)
    # A folder named explicitly must exist. Never fall back silently, or a typo
    # would send the whole scan to the current directory instead.
    for label, candidate in (("--material", cli_value),
                             (f"${MATERIAL_ENV}", Path(env_value) if env_value else None)):
        if candidate is None:
            continue
        if candidate.is_dir():
            return candidate.resolve()
        print(f"ERROR: not a directory ({label}): {candidate}", file=sys.stderr)
        sys.exit(2)
    for candidate in (Path.cwd() / "material", Path.cwd()):
        if candidate.is_dir():
            return candidate.resolve()
    print(f"ERROR: no PDF folder found. Pass --material DIR or set ${MATERIAL_ENV}.",
          file=sys.stderr)
    sys.exit(2)


def resolve_manuscript(cli_value: Path | None, required: bool) -> Path | None:
    """Markdown manuscript to read the bibliography from.

    Returns None when it is not required and none was given, so callers can
    degrade gracefully instead of failing.
    """
    for candidate in (cli_value,
                      Path(os.environ[MANUSCRIPT_ENV]) if os.environ.get(MANUSCRIPT_ENV) else None):
        if candidate and candidate.is_file():
            return candidate.resolve()
        if candidate:
            print(f"ERROR: manuscript not found: {candidate}", file=sys.stderr)
            sys.exit(2)
    if required:
        print(f"ERROR: this script needs a manuscript bibliography. "
              f"Pass --md FILE or set ${MANUSCRIPT_ENV}.", file=sys.stderr)
        sys.exit(2)
    return None
