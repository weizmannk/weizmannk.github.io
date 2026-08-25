#!/usr/bin/env python3
"""Regenerate data/authors/me.yaml (Hugo's author schema) from data/cv.yml.

data/cv.yml is the single source of truth for everything about the CV that
isn't a publication. This script is the "site" half of the pipeline: it
maps cv.yml's plain structure onto HugoBlox's `hugoblox/author/v1` schema
so the website reflects it without a second hand-maintained copy.

The `bio` text and a couple of presentation-only fields (postnominals,
status icon, pronouns) are NOT derivable from cv.yml and are preserved
from the existing data/authors/me.yaml across runs — see --help.

Usage:
    python scripts/sync_authors_data.py
    python scripts/sync_authors_data.py --dry-run
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CV_PATH = ROOT / "data" / "cv.yml"
DEFAULT_AUTHOR_PATH = ROOT / "data" / "authors" / "me.yaml"

# Fields in the generated author file that this script does not own —
# preserved verbatim from whatever is already on disk.
PRESERVED_FIELDS = ["postnominals", "status", "bio"]


def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)


def month_label(value) -> str:
    """cv.yml dates are 'YYYY', 'YYYY-MM', or 'present' — Hugo wants
    RFC3339-ish 'YYYY-MM-DD'."""
    if value is None:
        return ""
    text = str(value)
    if text == "present":
        return ""
    parts = text.split("-")
    if len(parts) == 1:
        return f"{parts[0]}-01-01"
    if len(parts) == 2:
        return f"{parts[0]}-{parts[1]}-01"
    return text


def build_links(identity: dict) -> list[dict]:
    links = []
    emails = identity.get("emails") or []
    if emails:
        links.append({"icon": "at-symbol", "url": f"mailto:{emails[0]}", "label": "E-mail Me"})
    link_map = identity.get("links", {})
    icon_by_key = {
        "github": "brands/github",
        "orcid": "academicons/orcid",
        "google_scholar": "academicons/google-scholar",
        "linkedin": "brands/linkedin",
    }
    for key, icon in icon_by_key.items():
        if link_map.get(key):
            links.append({"icon": icon, "url": link_map[key]})
    return links


def build_education(cv: dict) -> list[dict]:
    # cv.yml records a single completion date per degree, not a start/end
    # range, so only `end` (graduation) is set — an identical start/end
    # pair would render as a zero-length "duration" on the site.
    out = []
    for entry in cv.get("education", []):
        out.append(
            {
                "degree": entry["degree"],
                "institution": entry["institution"],
                "end": month_label(entry.get("date")),
                "summary": (entry.get("thesis", {}) or {}).get("title", entry.get("summary", "")),
            }
        )
    return out


def build_experience(cv: dict) -> list[dict]:
    out = []
    for entry in cv.get("appointments", []):
        item = {
            "role": entry["role"],
            "org": entry["institution"],
            "start": month_label(entry.get("start")),
            "summary": entry.get("summary", "") or "",
        }
        end = entry.get("end")
        if end and end != "present":
            item["end"] = month_label(end)
        out.append(item)
    return out


def build_skills(cv: dict) -> list[dict]:
    return [
        {
            "name": group["category"],
            "items": [{"label": item, "level": None} for item in group["items"]],
        }
        for group in cv.get("skills", [])
    ]


def build_languages(cv: dict) -> list[dict]:
    return [{"name": lang["name"], "label": lang["level"]} for lang in cv.get("languages", [])]


def build_awards(cv: dict) -> list[dict]:
    out = []
    for entry in cv.get("honors", []):
        out.append({"title": entry["title"], "awarder": entry.get("awarder", ""), "date": str(entry.get("date", ""))})
    for entry in cv.get("fellowships", []):
        out.append({"title": entry["title"], "awarder": entry.get("awarder", ""), "date": str(entry.get("start", ""))})
    return out


def load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def build_author(cv: dict, existing: dict) -> dict:
    identity = cv["identity"]
    author = {
        "schema": "hugoblox/author/v1",
        "slug": "me",
        "is_owner": True,
        "name": {
            "display": identity["name"]["display"],
            "given": identity["name"]["given"],
            "family": identity["name"]["family"],
            "alternate": existing.get("name", {}).get("alternate", ""),
            "pronunciation": existing.get("name", {}).get("pronunciation", ""),
            "pronouns": existing.get("name", {}).get("pronouns", ""),
        },
        "role": identity["role"],
        "affiliations": [identity["affiliation"]],
        "links": build_links(identity),
        "interests": cv.get("research_interests", []),
        "education": build_education(cv),
        "experience": build_experience(cv),
        "skills": build_skills(cv),
        "languages": build_languages(cv),
        "awards": build_awards(cv),
    }
    for field in PRESERVED_FIELDS:
        if field in existing:
            author[field] = existing[field]
        elif field not in author:
            author[field] = "" if field == "bio" else {}
    return author


class IndentedDumper(yaml.Dumper):
    def increase_indent(self, flow=False, indentless=False):
        return super().increase_indent(flow, False)


def str_presenter(dumper, data):
    style = "|" if "\n" in data else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


IndentedDumper.add_representer(str, str_presenter)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Regenerate data/authors/me.yaml from data/cv.yml."
    )
    parser.add_argument("--cv-path", type=Path, default=DEFAULT_CV_PATH)
    parser.add_argument("--author-path", type=Path, default=DEFAULT_AUTHOR_PATH)
    parser.add_argument("--dry-run", action="store_true", help="Print the result, don't write it")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    cv = load_yaml(args.cv_path)
    if not cv:
        eprint(f"{args.cv_path} is empty or missing.")
        return 1
    existing = load_yaml(args.author_path)

    author = build_author(cv, existing)
    text = yaml.dump(
        author, Dumper=IndentedDumper, sort_keys=False, allow_unicode=True, width=100
    )

    if args.dry_run:
        print(text)
        return 0

    args.author_path.parent.mkdir(parents=True, exist_ok=True)
    args.author_path.write_text(text, encoding="utf-8")
    eprint(f"Wrote {args.author_path} from {args.cv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
