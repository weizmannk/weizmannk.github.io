#!/usr/bin/env python3
"""Refresh bibliography/publications.bib from NASA ADS and ORCID.

Usage:
    ADS_TOKEN=xxxxx python scripts/fetch_publications.py
    python scripts/fetch_publications.py --dry-run
    python scripts/fetch_publications.py --orcid-only --no-orcid-details

See --help for all options.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
import unicodedata
from pathlib import Path

import bibtexparser
import requests
from bibtexparser.bwriter import BibTexWriter
from bibtexparser.bibdatabase import BibDatabase

ADS_SEARCH_URL = "https://api.adsabs.harvard.edu/v1/search/query"
ADS_EXPORT_URL = "https://api.adsabs.harvard.edu/v1/export/bibtexabs"
ORCID_API_ROOT = "https://pub.orcid.org/v3.0"
DEFAULT_ORCID = "0000-0002-9108-5059"
DEFAULT_BIB_PATH = Path(__file__).resolve().parent.parent / "bibliography" / "publications.bib"
REQUEST_TIMEOUT = 30

VALID_PUBLICATION_TYPES = {
    "refereed",
    "submitted",
    "in_preparation",
    "proceedings",
    "collaboration",
    "technical_report",
}

# Normalizes journal names ADS/CrossRef/ORCID return in inconsistent forms.
# Keys are matched case-insensitively. Extend as new venues show up.
JOURNAL_NORMALIZATION = {
    "apj": "The Astrophysical Journal",
    "the astrophysical journal": "The Astrophysical Journal",
    "apjl": "The Astrophysical Journal Letters",
    "the astrophysical journal letters": "The Astrophysical Journal Letters",
    "apjs": "The Astrophysical Journal Supplement Series",
    "the astrophysical journal supplements": "The Astrophysical Journal Supplement Series",
    "the astrophysical journal supplement series": "The Astrophysical Journal Supplement Series",
    "mnras": "Monthly Notices of the Royal Astronomical Society",
    "monthly notices of the royal astronomical society": "Monthly Notices of the Royal Astronomical Society",
    "a&a": "Astronomy & Astrophysics",
    "aap": "Astronomy & Astrophysics",
    "astronomy and astrophysics": "Astronomy & Astrophysics",
    "astronomy & astrophysics": "Astronomy & Astrophysics",
    "pasp": "Publications of the Astronomical Society of the Pacific",
    "the astronomical society of the pacific": "Publications of the Astronomical Society of the Pacific",
    "publications of the astronomical society of the pacific": "Publications of the Astronomical Society of the Pacific",
    "phrvd": "Physical Review D",
    "prd": "Physical Review D",
    "physical review d": "Physical Review D",
    "american physical society": "Physical Review D",
    "prl": "Physical Review Letters",
    "physical review letters": "Physical Review Letters",
    "nature communications": "Nature Communications",
    "the nature communications": "Nature Communications",
    "astroparticle physics": "Astroparticle Physics",
    "proc. spie": "Proceedings of SPIE",
    "proceedings of spie": "Proceedings of SPIE",
}

# ORCID work "type" -> best-guess publication_type. Always flagged for
# review on creation (see --review-needed handling) since the distinction
# between e.g. refereed and collaboration credit isn't derivable from this.
ORCID_TYPE_TO_PUBLICATION_TYPE = {
    "journal-article": "refereed",
    "conference-paper": "proceedings",
    "conference-abstract": "proceedings",
    "data-set": "technical_report",
    "software": "technical_report",
    "preprint": "submitted",
    "report": "technical_report",
    "other": "technical_report",
}

SURNAME_VARIANTS = ("Kiendrebeogo", "Kiendrébéogo", "Kiendrebéogo")


def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)


def safe_get(d: dict | None, key: str, default=None):
    """Like dict.get, but also falls back to `default` when the value is
    explicitly null — ORCID's JSON uses null for absent optional fields
    rather than omitting the key.
    """
    if not d:
        return default
    value = d.get(key)
    return value if value is not None else default


def strip_accents(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def normalize_surname(text: str) -> str:
    """Rewrite any accented spelling of the surname to the canonical form.

    Some Zenodo/arXiv records use "Kiendrébéogo"; the site and CV always
    use the unaccented form for indexing consistency.
    """
    pattern = re.compile("|".join(re.escape(v) for v in SURNAME_VARIANTS))
    return pattern.sub("Kiendrebeogo", text)


def normalize_journal(name: str | None) -> str | None:
    if not name:
        return name
    # ADS's bibtexabs export gives AASTeX journal macros (e.g. "\apj")
    # instead of a spelled-out name.
    key = name.strip().lstrip("\\").lower().rstrip(".")
    return JOURNAL_NORMALIZATION.get(key, name.strip())


def find_highlight(author_field: str) -> str | None:
    """Return the exact substring around the surname to bold, or None."""
    pattern = re.compile(
        r"(?:[\wÀ-ÿ.\-]+\s+){0,2}(?:" + "|".join(re.escape(v) for v in SURNAME_VARIANTS) + r")"
    )
    match = pattern.search(author_field)
    if not match:
        return None
    return normalize_surname(match.group(0).strip())


def slugify(text: str, max_words: int = 4) -> str:
    text = strip_accents(text).lower()
    words = re.findall(r"[a-z0-9]+", text)
    return "_".join(words[:max_words]) or "untitled"


def is_manual(entry: dict) -> bool:
    keywords = entry.get("keywords", "")
    return any(k.strip().lower() == "manual" for k in keywords.split(","))


def entry_identity_keys(entry: dict) -> set[str]:
    """Identifiers usable to match this entry against a freshly fetched one."""
    keys = set()
    doi = entry.get("doi", "").strip().lower()
    if doi:
        keys.add(f"doi:{doi}")
    eprint_id = entry.get("eprint", "").strip().lower()
    if eprint_id:
        keys.add(f"arxiv:{eprint_id}")
    bibcode = entry.get("adsurl", "")
    m = re.search(r"abs/([^/]+)$", bibcode)
    if m:
        keys.add(f"bibcode:{m.group(1).lower()}")
    return keys


def load_existing(bib_path: Path) -> BibDatabase:
    if not bib_path.exists():
        return BibDatabase()
    with bib_path.open(encoding="utf-8") as f:
        return bibtexparser.load(f)


# ---------------------------------------------------------------------------
# NASA ADS
# ---------------------------------------------------------------------------


def ads_search_orcid(orcid: str, token: str) -> list[dict]:
    headers = {"Authorization": f"Bearer {token}"}
    params = {
        "q": f"orcid:{orcid}",
        "fl": "bibcode,doctype,property,title",
        "rows": 500,
    }
    resp = requests.get(ADS_SEARCH_URL, headers=headers, params=params, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.json()["response"]["docs"]


def ads_export_bibtex(bibcodes: list[str], token: str) -> str:
    if not bibcodes:
        return ""
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    resp = requests.post(
        ADS_EXPORT_URL, headers=headers, json={"bibcode": bibcodes}, timeout=REQUEST_TIMEOUT
    )
    resp.raise_for_status()
    return resp.json()["export"]


def classify_from_ads(doctype: str, properties: list[str]) -> str:
    properties = {p.upper() for p in properties}
    if "REFEREED" in properties:
        return "refereed"
    if doctype == "eprint":
        return "submitted"
    if doctype in ("inproceedings", "proceedings"):
        return "proceedings"
    if doctype in ("circular", "techreport", "dataset", "software", "catalog"):
        return "technical_report"
    return "submitted"


def fetch_from_ads(orcid: str, token: str) -> tuple[list[dict], dict]:
    """Return (bibtex entries with publication_type set, docs-by-bibcode)."""
    docs = ads_search_orcid(orcid, token)
    docs_by_bibcode = {d["bibcode"]: d for d in docs}
    bibtex_raw = ads_export_bibtex(list(docs_by_bibcode), token)
    db = bibtexparser.loads(bibtex_raw)
    for entry in db.entries:
        bibcode = entry.get("adsurl", "").rstrip("/").rsplit("/", 1)[-1]
        doc = docs_by_bibcode.get(bibcode, {})
        entry["publication_type"] = classify_from_ads(
            doc.get("doctype", ""), doc.get("property", [])
        )
    return db.entries, docs_by_bibcode


# ---------------------------------------------------------------------------
# ORCID
# ---------------------------------------------------------------------------


def orcid_get_works(orcid: str) -> list[dict]:
    resp = requests.get(
        f"{ORCID_API_ROOT}/{orcid}/works",
        headers={"Accept": "application/json"},
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    summaries = []
    for group in resp.json().get("group", []):
        # Each group can bundle several sources reporting the same work;
        # the first summary is representative.
        summaries.append(group["work-summary"][0])
    return summaries


def orcid_external_id(summary: dict, id_type: str) -> str | None:
    for ext in safe_get(safe_get(summary, "external-ids", {}), "external-id", []):
        if ext["external-id-type"] == id_type:
            return ext["external-id-value"]
    return None


def orcid_work_title(summary: dict) -> str:
    return safe_get(safe_get(summary, "title", {}), "title", {}).get("value") or "Untitled"


def orcid_work_year(summary: dict) -> str | None:
    pub_date = safe_get(summary, "publication-date")
    year = safe_get(pub_date, "year")
    return safe_get(year, "value")


def orcid_work_to_entry(summary: dict, key: str) -> dict:
    title = orcid_work_title(summary)
    year = orcid_work_year(summary)
    doi = orcid_external_id(summary, "doi")
    url = safe_get(summary, "url", {}).get("value")
    orcid_type = summary.get("type") or "other"

    entry = {
        "ENTRYTYPE": "misc",
        "ID": key,
        "title": title,
        "publication_type": ORCID_TYPE_TO_PUBLICATION_TYPE.get(orcid_type, "technical_report"),
        "review_needed": "true",
    }
    if year:
        entry["year"] = year
    if doi:
        entry["doi"] = doi
        entry["url"] = f"https://doi.org/{doi}"
    elif url:
        entry["url"] = url
    return entry


def fetch_from_orcid(orcid: str, skip_dois: set[str]) -> list[dict]:
    """Return minimal bib entries for ORCID works not already covered."""
    entries = []
    for summary in orcid_get_works(orcid):
        doi = orcid_external_id(summary, "doi")
        if doi and doi.strip().lower() in skip_dois:
            continue
        title = orcid_work_title(summary)
        year = orcid_work_year(summary) or ""
        key = f"orcid_{slugify(title)}_{year}".strip("_")
        entries.append(orcid_work_to_entry(summary, key))
    return entries


# ---------------------------------------------------------------------------
# Merge
# ---------------------------------------------------------------------------

# Fields we always refresh from source for non-manual entries. Custom
# fields (publication_type, featured, keywords, highlight, note,
# review_needed) are preserved from the existing entry when present, so a
# hand-tuned classification survives re-runs without needing `manual`.
BIBLIOGRAPHIC_FIELDS = {
    "title",
    "author",
    "journal",
    "booktitle",
    "year",
    "volume",
    "number",
    "pages",
    "eid",
    "doi",
    "url",
    "eprint",
    "archiveprefix",
    "primaryclass",
    "adsurl",
    "adsnote",
    "publisher",
    "abstract",
}


def merge_entry(existing: dict | None, fresh: dict) -> dict:
    if existing is None:
        merged = dict(fresh)
    else:
        merged = dict(existing)
        for field in BIBLIOGRAPHIC_FIELDS:
            if field in fresh:
                merged[field] = fresh[field]
        # New classification only applied if the existing entry never had one.
        if "publication_type" not in merged and "publication_type" in fresh:
            merged["publication_type"] = fresh["publication_type"]

    if merged.get("journal"):
        merged["journal"] = normalize_journal(merged["journal"])
    if merged.get("author"):
        merged["author"] = normalize_surname(merged["author"])
        highlight = find_highlight(merged["author"])
        if highlight and "highlight" not in (existing or {}):
            merged["highlight"] = highlight

    if merged.get("publication_type") not in VALID_PUBLICATION_TYPES:
        merged.setdefault("review_needed", "true")

    return merged


def merge_databases(
    existing_entries: list[dict], fresh_entries: list[dict]
) -> tuple[list[dict], dict]:
    manual_entries = [e for e in existing_entries if is_manual(e)]
    manual_ids = {e["ID"] for e in manual_entries}

    existing_by_identity: dict[str, dict] = {}
    for entry in existing_entries:
        if entry["ID"] in manual_ids:
            continue
        for ident in entry_identity_keys(entry):
            existing_by_identity[ident] = entry

    updated_ids: set[str] = set()
    created: list[dict] = []
    result_by_id: dict[str, dict] = {e["ID"]: e for e in existing_entries if e["ID"] in manual_ids}

    for fresh in fresh_entries:
        idents = entry_identity_keys(fresh)
        match = next((existing_by_identity[i] for i in idents if i in existing_by_identity), None)
        if match is not None:
            merged = merge_entry(match, fresh)
            merged["ID"] = match["ID"]  # never rename an existing citation key
            result_by_id[match["ID"]] = merged
            updated_ids.add(match["ID"])
        else:
            key = fresh["ID"]
            suffix = ord("a")
            while key in result_by_id:
                key = f"{fresh['ID']}{chr(suffix)}"
                suffix += 1
            merged = merge_entry(None, fresh)
            merged["ID"] = key
            result_by_id[key] = merged
            created.append(merged)

    # Anything that existed before, wasn't manual, and wasn't refreshed this
    # run (API hiccup, ADS/ORCID temporarily missing it, ...) is kept as-is
    # rather than dropped — never delete silently.
    for entry in existing_entries:
        if entry["ID"] not in result_by_id:
            result_by_id[entry["ID"]] = entry

    stats = {
        "manual": len(manual_entries),
        "updated": len(updated_ids),
        "created": len(created),
        "unchanged": len(existing_entries) - len(manual_entries) - len(updated_ids),
        "total": len(result_by_id),
    }
    return list(result_by_id.values()), stats


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

HEADER = """% ============================================================================
% publications.bib — single source of truth for R. Weizmann Kiendrebeogo's
% publications. Feeds both the website (content/publications/) and the CV
% PDF (scripts/build_cv.py). Regenerated in part by
% scripts/fetch_publications.py — re-running it is safe (idempotent) and
% will not touch anything below marked keywords={manual}.
%
% Custom fields (beyond standard BibTeX):
%
%   publication_type = {refereed | submitted | in_preparation | proceedings
%                        | collaboration | technical_report}
%       Required on every entry. Never mixed across sections on the site or
%       in the CV.
%
%   keywords = {manual}
%       Marks an entry as hand-edited/protected: fetch_publications.py will
%       never overwrite or reclassify it. Standard bibliographic fields
%       (author, title, journal, doi, ...) on *unmarked* entries are
%       refreshed from ADS/ORCID on each run; publication_type/featured/
%       keywords/highlight are always preserved once set, regardless.
%
%   featured = {true}
%       The ~10 most significant entries, used for the CV `--variant short`
%       and the site's featured-publications block.
%
%   highlight = {...}
%       Exact substring to bold in `author` for this entry (spelling of the
%       author's name varies across papers/sources).
%
%   review_needed = {true}
%       Set by fetch_publications.py on newly discovered entries whose
%       publication_type is a best-effort guess (e.g. from an ORCID work
%       type) — check it, fix publication_type/fields as needed, then
%       either remove this field or add keywords={manual}.
%
%   cite_authors = {...}
%       Pre-formatted author string (surnames, \textbf{} bolding, \ldots
%       truncation for very long author lists) used by scripts/build_cv.py
%       for the CV PDF — deriving this automatically from `author` is not
%       reliable for multi-particle surnames (e.g. "Tosta e Melo", "de
%       Bony de Lavergne"). Never touched by this script; add it by hand
%       for any new entry that needs to appear in the CV.
%
% Author name convention: "Kiendrebeogo" without accents everywhere, even
% where a source (e.g. a Zenodo or arXiv record) uses "Kiendrébéogo".
% ============================================================================

"""


def sort_key(entry: dict):
    try:
        year = -int(entry.get("year", 0))
    except ValueError:
        year = 0
    return (year, entry.get("ID", ""))


def write_bib(entries: list[dict], bib_path: Path) -> None:
    db = BibDatabase()
    db.entries = sorted(entries, key=sort_key)
    writer = BibTexWriter()
    writer.indent = "  "
    writer.order_entries_by = None
    writer.display_order = [
        "author",
        "cite_authors",
        "title",
        "journal",
        "booktitle",
        "year",
        "volume",
        "number",
        "pages",
        "eid",
        "doi",
        "url",
        "eprint",
        "archiveprefix",
        "publisher",
        "version",
        "howpublished",
        "publication_type",
        "featured",
        "keywords",
        "highlight",
        "review_needed",
        "note",
        "abstract",
    ]
    bib_path.parent.mkdir(parents=True, exist_ok=True)
    bib_path.write_text(HEADER + writer.write(db), encoding="utf-8")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Refresh bibliography/publications.bib from NASA ADS and ORCID. "
            "Idempotent: entries marked keywords={manual} are never touched, "
            "and rerunning with unchanged upstream data changes nothing."
        )
    )
    parser.add_argument("--orcid", default=DEFAULT_ORCID, help="ORCID iD to query (default: %(default)s)")
    parser.add_argument(
        "--bib-path",
        type=Path,
        default=DEFAULT_BIB_PATH,
        help="Path to publications.bib (default: %(default)s)",
    )
    parser.add_argument(
        "--ads-token",
        default=os.environ.get("ADS_TOKEN"),
        help="NASA ADS API token (default: $ADS_TOKEN)",
    )
    parser.add_argument("--no-ads", action="store_true", help="Skip the ADS query entirely")
    parser.add_argument("--no-orcid", action="store_true", help="Skip the ORCID query entirely")
    parser.add_argument(
        "--dry-run", action="store_true", help="Print a summary but do not write the .bib file"
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)

    existing_db = load_existing(args.bib_path)
    existing_entries = existing_db.entries
    eprint(f"Loaded {len(existing_entries)} existing entries from {args.bib_path}")

    fresh_entries: list[dict] = []
    covered_dois: set[str] = {
        e.get("doi", "").strip().lower() for e in existing_entries if e.get("doi")
    }

    if not args.no_ads:
        if not args.ads_token:
            eprint(
                "ADS_TOKEN not set and --ads-token not given — skipping ADS "
                "(pass --no-ads to silence this warning)."
            )
        else:
            eprint("Querying NASA ADS ...")
            ads_entries, _ = fetch_from_ads(args.orcid, args.ads_token)
            eprint(f"  {len(ads_entries)} entries from ADS")
            fresh_entries.extend(ads_entries)
            covered_dois |= {e.get("doi", "").strip().lower() for e in ads_entries if e.get("doi")}

    if not args.no_orcid:
        eprint("Querying public ORCID API ...")
        time.sleep(0.2)  # be polite; ORCID has no auth and no generous rate limit info
        orcid_entries = fetch_from_orcid(args.orcid, covered_dois)
        eprint(f"  {len(orcid_entries)} additional entries from ORCID (not already covered by ADS)")
        fresh_entries.extend(orcid_entries)

    if not fresh_entries and not args.no_ads and not args.no_orcid:
        eprint("No data fetched from either source — leaving the .bib file untouched.")
        return 1

    merged_entries, stats = merge_databases(existing_entries, fresh_entries)

    eprint(
        "Summary: "
        f"{stats['manual']} manual (untouched), "
        f"{stats['updated']} updated, "
        f"{stats['created']} new, "
        f"{stats['unchanged']} unchanged, "
        f"{stats['total']} total."
    )
    review = [e["ID"] for e in merged_entries if e.get("review_needed") == "true"]
    if review:
        eprint(f"Entries needing manual review (publication_type / details): {', '.join(review)}")

    if args.dry_run:
        eprint("--dry-run: not writing to disk.")
        return 0

    write_bib(merged_entries, args.bib_path)
    eprint(f"Wrote {args.bib_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
