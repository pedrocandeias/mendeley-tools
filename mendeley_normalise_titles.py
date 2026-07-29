#!/usr/bin/env python3
"""Normaliza títulos, autores e fontes na biblioteca Mendeley.

O DOCX canónico é gerido pelo Mendeley Cite: a bibliografia regenera-se a
partir da biblioteca na nuvem em cada *Refresh*. Erros de inserção que
entram nos registos Mendeley — títulos em MAIÚSCULAS, apelidos em
MAIÚSCULAS, entidades HTML, quebras de linha, ponto final, espaços a mais,
nomes de ficheiro usados como título — aparecem tal e qual na bibliografia
do manuscrito. Este script deteta e corrige esses casos no Mendeley.

Estratégia de correção de um título em MAIÚSCULAS:
  1. Se o registo tem DOI, usa o título do CrossRef (autoritativo).
  2. Caso contrário, aplica capitalização de frase com preservação de
     siglas conhecidas, romanos, e palavras com maiúsculas internas.

Uso:
    mendeley_normalise_titles.py                 # auditoria (dry-run)
    mendeley_normalise_titles.py --apply         # aplica as correções
    mendeley_normalise_titles.py --report FILE   # grava relatório markdown
    mendeley_normalise_titles.py --only-cited --md manuscrito.md

Sem `--md` a ferramenta trabalha sobre toda a biblioteca; o manuscrito só é
necessário para `--only-cited`, que restringe a normalização às obras
efectivamente citadas.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import unicodedata
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mendeley_enrich import (  # noqa: E402
    MendeleyAPI,
    crossref_by_doi,
    load_credentials,
    CROSSREF_HEADERS,
)
from mendeley_paths import (  # noqa: E402
    add_manuscript_argument,
    resolve_manuscript,
)

# ── Léxico de preservação ─────────────────────────────────────────────────────

# Siglas e marcas que devem manter-se em maiúsculas ao converter de ALL CAPS.
ACRONYMS = {
    "3D", "2D", "4D", "AI", "AM", "API", "AR", "VR", "XR", "CAD", "CAM", "CAE",
    "CNC", "CT", "MRI", "EMG", "EEG", "ECG", "FDM", "SLA", "SLS", "MJF", "PLA",
    "ABS", "PETG", "TPU", "PEEK", "ASA", "HCI", "HCD", "UCD", "UX", "UI", "ICF",
    "WHO", "OMS", "ISO", "IEC", "ANSI", "ASTM", "NIST", "IEEE", "ACM", "USA",
    "UK", "EU", "US", "R&D", "DIY", "STL", "STEP", "IGES", "PDF", "GDP", "QOL",
    "ADL", "ADLs", "PROM", "PROMs", "TAM", "SUS", "NASA", "TLX", "ANSUR",
    "LLM", "LLMs", "GAN", "GANs", "CNN", "CNNs", "ML", "DL", "NLP", "XAI",
    "RCT", "RCTs", "PRISMA", "SWOT", "COVID", "COVID-19", "SARS-CoV-2",
    "IoT", "3DP", "AMP", "ROM", "OT", "PT", "TMR", "IMU", "PCB", "FEA", "FEM",
    "MPT", "QUEST", "OPUS", "DASH", "SHAP", "TRL", "OSHW", "OSAT", "GIS",
    "MDDDP", "IPCA", "APA", "DOI", "ISBN", "ISSN", "URL", "HTML", "XML", "JSON",
    "SA", "USAID", "UE", "CE", "CEE", "EMBC", "CHI", "ASEE", "HFUE", "SAPA",
}

# Palavras minúsculas em títulos em inglês (só relevantes se optarmos por
# title case; usamos sentence case, portanto servem apenas para não capitalizar
# indevidamente depois de dois pontos curtos).
ROMAN_RE = re.compile(r"^[IVXLCDM]+$")
# U.S., U.K., i.e., e.g. — abreviaturas pontuadas: não abrem frase nova.
DOTTED_ABBR_RE = re.compile(r"^(?:[A-Za-z]\.){2,}$")


def norm_key(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def letters(s: str) -> str:
    return "".join(c for c in s if c.isalpha())


def is_all_caps(s: str) -> bool:
    """Verdadeiro se o texto tem letras e nenhuma minúscula, e não é sigla curta."""
    ls = letters(s)
    if len(ls) < 6:
        return False
    return ls.upper() == ls


def mostly_caps(s: str) -> bool:
    """Título com maioria de palavras integralmente em maiúsculas (>60%)."""
    words = [w for w in re.findall(r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ'’-]*", s) if len(w) > 2]
    if len(words) < 4:
        return False
    caps = [w for w in words if w.upper() == w and w not in ACRONYMS]
    return len(caps) / len(words) > 0.60


def sentence_case(title: str) -> str:
    """Converte um título em MAIÚSCULAS para capitalização de frase."""
    out: list[str] = []
    # Divide preservando a pontuação e os espaços.
    tokens = re.split(r"(\s+)", title.strip())
    start_of_sentence = True
    for tok in tokens:
        if not tok or tok.isspace():
            out.append(tok)
            continue
        core = tok.strip("()[]{}«»\"'“”‘’,.;:!?")
        prefix = tok[: len(tok) - len(tok.lstrip("([{«\"'“‘"))]
        inner = tok[len(prefix):]
        abbr = DOTTED_ABBR_RE.match(inner.rstrip(")]}»\"'”’,;:!?"))
        if abbr:
            # U.S., U.K., i.e. — mantém tal e qual e não abre frase nova
            out.append(tok)
            start_of_sentence = False
            continue
        suffix = tok[len(tok.rstrip(")]}»\"'”’,.;:!?")):]
        bare = tok[len(prefix): len(tok) - len(suffix)] if suffix else tok[len(prefix):]

        if bare.upper() in ACRONYMS or ROMAN_RE.match(bare) and len(bare) > 1:
            new = bare.upper() if bare.upper() in ACRONYMS else bare
        elif re.search(r"\d", bare) and re.search(r"[A-Za-z]", bare):
            # p.ex. "COVID-19", "3D", "PM2.5" — mantém como está se for sigla
            new = bare if bare.upper() in ACRONYMS else bare.capitalize()
            if bare.upper() in ACRONYMS:
                new = bare.upper()
        elif "-" in bare:
            parts = bare.split("-")
            new = "-".join(
                p.upper() if p.upper() in ACRONYMS else p.lower() for p in parts
            )
            if start_of_sentence:
                new = new[:1].upper() + new[1:]
        else:
            new = bare.lower()
            if start_of_sentence:
                new = new[:1].upper() + new[1:]

        out.append(prefix + new + suffix)
        start_of_sentence = bool(re.search(r"[.:?!]$", suffix or bare))
        if not core:
            start_of_sentence = True
    result = "".join(out)
    # Primeira letra sempre maiúscula.
    m = re.search(r"[A-Za-zÀ-ÿ]", result)
    if m:
        i = m.start()
        result = result[:i] + result[i].upper() + result[i + 1:]
    return result


def name_case(name: str) -> str:
    """MAIÚSCULAS → Capitalização de nome próprio, com O'/Mc/Mac/de/van."""
    def cap_part(p: str) -> str:
        if not p:
            return p
        low = p.lower()
        if low in {"de", "da", "do", "dos", "das", "van", "von", "der", "den",
                   "del", "della", "di", "du", "la", "le", "bin", "ibn", "e"}:
            return low
        if low.startswith("mc") and len(low) > 2:
            return "Mc" + low[2:].capitalize()
        if low.startswith("mac") and len(low) > 4:
            return "Mac" + low[3:].capitalize()
        if "'" in p or "’" in p:
            sep = "'" if "'" in p else "’"
            a, _, b = p.partition(sep)
            return a.capitalize() + sep + b.capitalize()
        return low.capitalize()

    parts = re.split(r"([ \-]+)", name.strip())
    return "".join(p if re.match(r"^[ \-]+$", p) else cap_part(p) for p in parts)


# ── Deteção de defeitos ───────────────────────────────────────────────────────

HTML_ENTITY_RE = re.compile(r"&(amp|lt|gt|quot|apos|nbsp|#\d+);", re.I)
HTML_TAG_RE = re.compile(r"</?(i|b|em|strong|sub|sup|scp|span|p)\b[^>]*>", re.I)
FILENAME_RE = re.compile(r"\.(pdf|docx?|epub|html?)\s*$", re.I)
WS_RE = re.compile(r"\s{2,}|[\n\r\t]")
NOISE_RE = re.compile(
    r"(downloaded from|^\s*microsoft word\s*-|^\s*untitled\b|^\s*doi:|"
    r"^\s*full[- ]text\b|^\s*author manuscript\b|^\s*\(?pdf\)?\s*$)", re.I)


def clean_text(s: str) -> str:
    """Limpezas seguras, independentes de maiúsculas."""
    # Descodificar entidades primeiro, depois remover as etiquetas resultantes,
    # senão `&lt;i&gt;` transforma-se em `<i>` literal em vez de desaparecer.
    s = (s.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
          .replace("&quot;", '"').replace("&apos;", "'").replace("&nbsp;", " "))
    s = HTML_TAG_RE.sub("", s)
    s = s.replace("­", "")           # soft hyphen
    s = re.sub(r"[\n\r\t]+", " ", s)
    s = re.sub(r"\s{2,}", " ", s).strip()
    # Espaço antes de pontuação: só quando é pontuação isolada (" : " → ": "),
    # nunca em "::" nem noutras sequências.
    s = re.sub(r"\s+([,;.])(?=\s|$)", r"\1", s)
    s = re.sub(r"\s+:(?!:)", ":", s)
    s = s.strip(" ,;")
    # Ponto final único no fim de um título (não abreviatura tipo "et al.")
    if s.endswith(".") and not re.search(r"\b([A-Z]|al|vs|ed|eds|Inc|Ltd)\.$", s):
        s = s[:-1]
    return s


def audit_title(title: str) -> list[str]:
    flags = []
    if not title or not title.strip():
        return ["titulo-vazio"]
    if is_all_caps(title):
        flags.append("MAIUSCULAS")
    elif mostly_caps(title):
        flags.append("maioria-maiusculas")
    if HTML_ENTITY_RE.search(title) or HTML_TAG_RE.search(title):
        flags.append("html")
    if FILENAME_RE.search(title):
        flags.append("nome-de-ficheiro")
    if WS_RE.search(title):
        flags.append("espacos")
    if NOISE_RE.search(title):
        flags.append("ruido-extraccao")
    if title != title.strip():
        flags.append("espacos-extremos")
    if title.rstrip().endswith(".") and not re.search(r"\b([A-Z]|al)\.$", title.rstrip()):
        flags.append("ponto-final")
    if re.search(r"\b\w+-\s+\w+", title):
        flags.append("hifenizacao")
    return flags


def audit_doc(doc: dict) -> dict | None:
    """Devolve {flags, changes} ou None se o registo estiver limpo."""
    doc_id = doc.get("id", "")
    title = doc.get("title", "") or ""
    changes: dict = {}
    flags = audit_title(title)

    # Título
    new_title = clean_text(title)
    if "MAIUSCULAS" in flags or "maioria-maiusculas" in flags:
        new_title = sentence_case(new_title)
    if new_title and new_title != title:
        changes["title"] = new_title

    # Autores
    authors = doc.get("authors") or []
    new_authors = []
    authors_changed = False
    for a in authors:
        na = dict(a)
        # Autores institucionais (só apelido, sem nome próprio) — WHO, USAID,
        # ISO — não são nomes de pessoa e não levam capitalização de nome.
        institutional = not (a.get("first_name") or "").strip()
        for key in ("first_name", "last_name"):
            v = (a.get(key) or "").strip()
            if not v:
                continue
            nv = clean_text(v)
            if not institutional and (is_all_caps(nv)
                                      or (nv.isupper() and len(letters(nv)) >= 3)):
                nv = name_case(nv)
            # "Norman, Donald A.." → "Donald A." (ponto duplicado da inicial)
            nv = re.sub(r"\.\.+$", ".", nv)
            if nv != (a.get(key) or ""):
                na[key] = nv
                authors_changed = True
        new_authors.append(na)
    if authors_changed:
        changes["authors"] = new_authors
        flags.append("autores-MAIUSCULAS")

    # Fonte (revista / editora)
    source = (doc.get("source") or "").strip()
    if source:
        new_source = clean_text(source)
        if is_all_caps(new_source):
            new_source = sentence_case(new_source)
            # Fontes usam title case em APA: capitaliza palavras significativas.
            new_source = title_case_source(new_source)
            flags.append("fonte-MAIUSCULAS")
        if new_source != (doc.get("source") or ""):
            changes["source"] = new_source

    if not changes:
        return None
    return {"id": doc_id, "flags": sorted(set(flags)), "changes": changes,
            "before": {"title": title,
                       "authors": authors,
                       "source": doc.get("source")}}


SOURCE_MINOR = {"a", "an", "and", "as", "at", "but", "by", "for", "in", "nor",
                "of", "on", "or", "the", "to", "up", "via", "with", "from",
                "de", "da", "do", "e", "em", "para", "dos", "das"}


def title_case_source(s: str) -> str:
    words = re.split(r"(\s+|:\s*)", s)
    out, first = [], True
    for w in words:
        if not w.strip() or w.strip() == ":":
            out.append(w)
            if ":" in w:
                first = True
            continue
        if w.upper() in ACRONYMS:
            out.append(w.upper())
        elif not first and w.lower() in SOURCE_MINOR:
            out.append(w.lower())
        else:
            out.append(w[:1].upper() + w[1:])
        first = False
    return "".join(out)


# ── Bibliografia do manuscrito (para --only-cited) ────────────────────────────

def cited_titles(md: Path) -> set[str]:
    lines = md.read_text(encoding="utf-8").split("\n")
    try:
        start = next(i for i, l in enumerate(lines) if l.strip() == "## Bibliografia")
        end = next(i for i in range(start + 1, len(lines)) if lines[i].startswith("## "))
    except StopIteration:
        return set()
    keys = set()
    for line in lines[start:end]:
        m = re.match(r'<a id="ref-[^"]+"></a> (.*)', line)
        if m:
            keys.add(norm_key(m.group(1)))
    return keys


# ── Main ──────────────────────────────────────────────────────────────────────

async def resolve_via_crossref(entries: list[dict], docs_by_id: dict) -> None:
    """Para títulos em MAIÚSCULAS com DOI, prefere o título do CrossRef."""
    async with httpx.AsyncClient(headers=CROSSREF_HEADERS, timeout=20.0) as client:
        for e in entries:
            if "title" not in e["changes"]:
                continue
            if not any(f.endswith("MAIUSCULAS") or f == "maioria-maiusculas"
                       for f in e["flags"]):
                continue
            doc = docs_by_id[e["id"]]
            doi = (doc.get("identifiers") or {}).get("doi")
            if not doi:
                continue
            data = await crossref_by_doi(client, doi)
            if not data:
                continue
            titles = data.get("title") or []
            if not titles:
                continue
            cr = clean_text(titles[0])
            if not cr or is_all_caps(cr):
                continue
            if norm_key(cr) == norm_key(e["changes"]["title"]) and cr != e["changes"]["title"]:
                e["changes"]["title"] = cr
                e["flags"].append("crossref")
            elif norm_key(cr) != norm_key(e["changes"]["title"]):
                # Título diverge do CrossRef — assinala mas não substitui em massa.
                e["crossref_alt"] = cr


def render_report(entries: list[dict], applied: bool) -> str:
    lines = [f"# Normalização de títulos Mendeley ({'aplicado' if applied else 'dry-run'})",
             "", f"Registos com correções propostas: **{len(entries)}**", ""]
    by_flag: dict[str, int] = {}
    for e in entries:
        for f in e["flags"]:
            by_flag[f] = by_flag.get(f, 0) + 1
    lines += ["| Defeito | Registos |", "|---|---|"]
    for f, n in sorted(by_flag.items(), key=lambda kv: -kv[1]):
        lines.append(f"| {f} | {n} |")
    lines.append("")
    for e in entries:
        lines.append(f"### {e['id']}  \n`{', '.join(e['flags'])}`")
        b, c = e["before"], e["changes"]
        if "title" in c:
            lines += [f"- **título antes:** {b['title']}", f"- **título depois:** {c['title']}"]
        if e.get("crossref_alt"):
            lines.append(f"- **CrossRef diverge:** {e['crossref_alt']}")
        if "authors" in c:
            before = "; ".join(f"{a.get('first_name','')} {a.get('last_name','')}".strip()
                               for a in (b["authors"] or []))
            after = "; ".join(f"{a.get('first_name','')} {a.get('last_name','')}".strip()
                              for a in c["authors"])
            lines += [f"- **autores antes:** {before}", f"- **autores depois:** {after}"]
        if "source" in c:
            lines += [f"- **fonte antes:** {b['source']}", f"- **fonte depois:** {c['source']}"]
        lines.append("")
    return "\n".join(lines)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="grava as correções no Mendeley")
    ap.add_argument("--report", type=Path, help="grava relatório markdown")
    ap.add_argument("--only-cited", action="store_true",
                    help="só registos cujo título consta da bibliografia do MD "
                         "(exige --md)")
    add_manuscript_argument(ap, help_suffix="; só necessário com --only-cited")
    ap.add_argument("--no-crossref", action="store_true",
                    help="não consulta o CrossRef")
    ap.add_argument("--cache", type=Path, help="ficheiro JSON de cache dos documentos")
    ap.add_argument("--overrides", type=Path,
                    help="JSON {doc_id: {\"title\": \"...\"}} com títulos revistos à mão, "
                         "que prevalecem sobre a heurística e sobre o CrossRef")
    args = ap.parse_args()

    if args.cache and args.cache.exists():
        docs = json.loads(args.cache.read_text(encoding="utf-8"))
        api = None
    else:
        api = MendeleyAPI(load_credentials())
        docs = await api.get_all_documents()
        if args.cache:
            args.cache.write_text(json.dumps(docs, ensure_ascii=False), encoding="utf-8")
    print(f"Documentos na biblioteca: {len(docs)}", file=sys.stderr)

    if args.only_cited:
        md = resolve_manuscript(args.md, required=True)
        print(f"Manuscrito: {md}", file=sys.stderr)
        wanted = cited_titles(md)
        docs = [d for d in docs
                if any(norm_key(d.get("title", "")) and norm_key(d.get("title", "")) in k
                       for k in wanted)]
        print(f"Filtrados por citação no manuscrito: {len(docs)}", file=sys.stderr)

    docs_by_id = {d["id"]: d for d in docs}
    entries = [e for e in (audit_doc(d) for d in docs) if e]
    print(f"Registos com correções propostas: {len(entries)}", file=sys.stderr)

    if not args.no_crossref:
        await resolve_via_crossref(entries, docs_by_id)

    if args.overrides:
        ov = json.loads(args.overrides.read_text(encoding="utf-8"))
        by_id = {e["id"]: e for e in entries}
        for doc_id, fields in ov.items():
            if doc_id.startswith("_"):  # chaves de comentário
                continue
            if fields is None:  # null = não tocar neste registo
                entries = [e for e in entries if e["id"] != doc_id]
                by_id.pop(doc_id, None)
                continue
            e = by_id.get(doc_id)
            if e is None:
                doc = docs_by_id.get(doc_id)
                if doc is None:
                    print(f"AVISO: override para id desconhecido {doc_id}", file=sys.stderr)
                    continue
                e = {"id": doc_id, "flags": ["override"], "changes": {},
                     "before": {"title": doc.get("title"), "authors": doc.get("authors"),
                                "source": doc.get("source")}}
                entries.append(e)
                by_id[doc_id] = e
            doc = docs_by_id.get(doc_id, {})
            # Ignora overrides que já coincidem com o valor na nuvem, para que
            # uma segunda execução não volte a gravar o que já está correcto.
            fields = {k: v for k, v in fields.items() if doc.get(k) != v}
            e["changes"].update(fields)
            e["changes"] = {k: v for k, v in e["changes"].items() if doc.get(k) != v}
            e["flags"] = sorted(set(e["flags"]) | {"override"})
        entries = [e for e in entries if e["changes"]]

    report = render_report(entries, args.apply)
    if args.report:
        args.report.write_text(report, encoding="utf-8")
        print(f"Relatório: {args.report}", file=sys.stderr)
    else:
        print(report)

    if args.apply:
        if api is None:
            api = MendeleyAPI(load_credentials())
        ok = err = 0
        for e in entries:
            try:
                await api.patch_document(e["id"], e["changes"])
                ok += 1
            except Exception as exc:  # noqa: BLE001
                err += 1
                print(f"ERRO {e['id']}: {exc}", file=sys.stderr)
        print(f"Aplicados: {ok}; erros: {err}", file=sys.stderr)

    if api is not None:
        await api.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
