#!/usr/bin/env python3
"""Generate content/publications/<key>/index.md pages from
bibliography/publications.bib.

The theme ships its own `import-publications.yml` workflow that calls the
`academic` CLI (GetRD/academic-file-converter) — but that tool emits the
OLD wowchemy-era front matter schema (numeric publication_types, flat
url_pdf/url_code fields). The current HugoBlox kit theme uses a different,
CSL-based schema (publication_types: ["article-journal"], structured
`publication: {name, volume, issue, pages}`, `hugoblox.ids: {doi, arxiv}`,
typed `links:` array) that the old tool cannot produce. This script talks
that current schema directly instead.

Every page under content/publications/ is fully derived from the .bib —
do not hand-edit them, edit bibliography/publications.bib and re-run this
script. Folders for entries no longer in the .bib are pruned.

Usage:
    python scripts/import_publications.py
    python scripts/import_publications.py --dry-run
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
import unicodedata
from pathlib import Path

import bibtexparser
import yaml

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BIB_PATH = ROOT / "bibliography" / "publications.bib"
DEFAULT_OUTPUT_DIR = ROOT / "content" / "publications"

# bibliography/publications.bib publication_type -> Hugo taxonomy term.
# Hyphenated (not underscored) so the theme's Title-case display fallback
# reads "In-Preparation" / "Technical-Report" rather than showing a raw "_".
PUB_TYPE_TO_HUGO = {
    "refereed": "refereed",
    "submitted": "submitted",
    "in_preparation": "in-preparation",
    "proceedings": "proceedings",
    "collaboration": "collaboration",
    "technical_report": "technical-report",
}

_ACCENT_COMBINING = {
    "'": "\u0301",  # acute
    "`": "\u0300",  # grave
    '"': "\u0308",  # umlaut / diaeresis
    "^": "\u0302",  # circumflex
    "~": "\u0303",  # tilde
    "v": "\u030c",  # caron / h\u00e1\u010dek, e.g. Ma\v{s}ek -> Ma\u0161ek
}


def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)


def delatex(text: str) -> str:
    """Best-effort conversion of the LaTeX-ready text in publications.bib
    back to plain Unicode for web content. Not a general LaTeX parser —
    only handles the constructs actually used in this project's .bib
    (accents, \\&, \\ldots, \\textbf, double-braced titles, one math macro).
    """
    if not text:
        return ""
    t = text.strip()
    if t.startswith("{") and t.endswith("}"):
        t = t[1:-1]
    # ADS abstracts are hard-wrapped at ~60 chars with literal newlines —
    # collapse to a single paragraph of flowing text.
    t = re.sub(r"\s*\n\s*", " ", t)

    t = t.replace(r"$M_\odot$", "M\u2609")
    t = re.sub(r"\$[^$]*\\odot[^$]*\$", "\u2609", t)
    # ADS abstracts (bibtexabs export) wrap math symbols in \ensuremath{...}
    # without surrounding $...$, e.g. "137{\ensuremath{-}}18+23M{\ensuremath{\odot}}".
    t = re.sub(r"\\ensuremath\{([^{}]*)\}", r"\1", t)
    t = t.replace(r"\odot", "\u2609").replace(r"\sim", "\u223c").replace(r"\times", "\u00d7")
    t = t.replace(r"\textemdash", "\u2014").replace(r"\textendash", "\u2013")
    t = re.sub(r"\\textbf\{([^{}]*)\}", r"\1", t)
    t = re.sub(r"\\emph\{([^{}]*)\}", r"\1", t)
    t = t.replace(r"\ldots", "\u2026")
    t = re.sub(r"\\c\{([a-zA-Z])\}", lambda m: unicodedata.normalize("NFC", m.group(1) + "\u0327"), t)
    t = re.sub(
        r"\\([\'`\"^~]|v(?=\{))\{?([a-zA-Z])\}?",
        lambda m: unicodedata.normalize("NFC", m.group(2) + _ACCENT_COMBINING[m.group(1)]),
        t,
    )
    t = t.replace(r"\&", "&").replace(r"\%", "%").replace(r"\_", "_").replace(r"\#", "#")
    t = t.replace("--", "\u2013")
    t = t.replace("\u2500", "\u2013")  # ADS box-drawing dash used as a range dash
    t = re.sub(r"\{([^{}]*)\}", r"\1", t)  # any remaining protective braces
    return t.strip()


def split_authors(author_field: str) -> list[str]:
    if not author_field:
        return []
    parts = re.split(r"\s+and\s+", author_field)
    return [delatex(p.strip()) for p in parts if p.strip()]


def clean(text: str) -> str:
    return delatex(text or "")


def yaml_str(value) -> str:
    """Render a scalar via PyYAML so quoting/escaping is always correct."""
    return yaml.safe_dump(value, allow_unicode=True, default_flow_style=True).strip()


def build_front_matter(entry: dict) -> dict:
    pub_type = entry.get("publication_type", "")
    hugo_type = PUB_TYPE_TO_HUGO.get(pub_type, pub_type.replace("_", "-"))
    year = entry.get("year", "")

    # Collaboration papers (LVK, GRANDMA, ...) can list hundreds of authors in
    # the raw .bib `author` field. The site shows the curated `cite_authors`
    # byline instead in that case, matching how these are normally cited.
    if pub_type == "collaboration" and entry.get("cite_authors"):
        authors = [clean(entry["cite_authors"])]
    else:
        authors = split_authors(entry.get("author", ""))

    fm = {
        "title": clean(entry.get("title", "")),
        "authors": authors,
        "date": f"{year}-01-01T00:00:00Z" if year else None,
        "publication_types": [hugo_type],
        "publication_years": [str(year)] if year else [],
        "featured": str(entry.get("featured", "")).lower() == "true",
        "tags": [],
        "abstract": clean(entry.get("abstract", "")),
    }

    venue_name = clean(entry.get("journal") or entry.get("booktitle") or "")
    pages = entry.get("pages") or entry.get("eid") or ""
    if venue_name or entry.get("volume") or entry.get("number") or pages:
        fm["publication"] = {
            "name": venue_name,
            "volume": entry.get("volume", ""),
            "issue": entry.get("number", ""),
            "pages": pages,
            "publisher": clean(entry.get("publisher", "")),
        }

    ids = {}
    if entry.get("doi"):
        ids["doi"] = entry["doi"]
    if entry.get("eprint") and entry.get("archiveprefix", "").lower() == "arxiv":
        ids["arxiv"] = entry["eprint"]
    if ids:
        fm["hugoblox"] = {"ids": ids}

    links = []
    if not ids and entry.get("url"):
        link_type = "dataset" if entry.get("publisher") == "Zenodo" else "site"
        links.append({"type": link_type, "url": entry["url"]})
    if links:
        fm["links"] = links

    return {k: v for k, v in fm.items() if v not in (None, "", [], {})}


def render_page(entry: dict) -> str:
    fm = build_front_matter(entry)
    front_matter = yaml.safe_dump(fm, allow_unicode=True, sort_keys=False, default_flow_style=False)
    return f"---\n{front_matter}---\n"


def load_bib_entries(bib_path: Path) -> list[dict]:
    with bib_path.open(encoding="utf-8") as f:
        return bibtexparser.load(f).entries


def sync_pages(entries: list[dict], output_dir: Path, dry_run: bool) -> None:
    expected = {e["ID"] for e in entries}

    existing = {p.name for p in output_dir.iterdir() if p.is_dir()} if output_dir.exists() else set()
    stale = existing - expected
    for name in stale:
        eprint(f"prune: content/publications/{name}/ (no longer in publications.bib)")
        if not dry_run:
            shutil.rmtree(output_dir / name)

    written = 0
    for entry in entries:
        page = render_page(entry)
        target = output_dir / entry["ID"] / "index.md"
        if not dry_run:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(page, encoding="utf-8")
        written += 1

    eprint(f"{'Would write' if dry_run else 'Wrote'} {written} publication pages, pruned {len(stale)}.")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Regenerate content/publications/<key>/index.md from bibliography/publications.bib."
    )
    parser.add_argument("--bib-path", type=Path, default=DEFAULT_BIB_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    entries = load_bib_entries(args.bib_path)
    sync_pages(entries, args.output_dir, args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
