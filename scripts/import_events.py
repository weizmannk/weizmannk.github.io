#!/usr/bin/env python3
"""Generate content/events/<slug>/index.md pages from data/cv.yml's talks
list (rendered on the site as the "Talks" section).

Every page under content/events/ is fully derived from cv.yml — do not
hand-edit them, edit data/cv.yml and re-run this script. Folders for
entries no longer in cv.yml are pruned.

Usage:
    python scripts/import_events.py
    python scripts/import_events.py --dry-run
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
import unicodedata
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CV_PATH = ROOT / "data" / "cv.yml"
DEFAULT_OUTPUT_DIR = ROOT / "content" / "events"


def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text or "untitled"


def event_datetime(date_token: str) -> str:
    parts = str(date_token).split("-")
    year, month = parts[0], parts[1] if len(parts) > 1 else "01"
    return f"{year}-{month}-01T00:00:00Z"


def build_front_matter(talk: dict) -> dict:
    fm = {
        "title": talk["title"],
        "date": event_datetime(talk["date"]),
        "event_name": talk["venue"],
        "event_start": event_datetime(talk["date"]),
        "authors": ["me"],
        "tags": [talk["type"]],
    }
    if talk.get("url"):
        fm["links"] = [{"type": "site", "url": talk["url"]}]
    return fm


def render_page(talk: dict) -> str:
    fm = build_front_matter(talk)
    front_matter = yaml.safe_dump(fm, allow_unicode=True, sort_keys=False, default_flow_style=False)
    return f"---\n{front_matter}---\n"


def sync_pages(talks: list[dict], output_dir: Path, dry_run: bool) -> None:
    slugs = [slugify(f"{t['date']}-{t['title']}") for t in talks]
    expected = set(slugs)

    existing = {p.name for p in output_dir.iterdir() if p.is_dir()} if output_dir.exists() else set()
    stale = existing - expected
    for name in stale:
        eprint(f"prune: content/events/{name}/ (no longer in data/cv.yml)")
        if not dry_run:
            shutil.rmtree(output_dir / name)

    for talk, slug in zip(talks, slugs):
        page = render_page(talk)
        target = output_dir / slug / "index.md"
        if not dry_run:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(page, encoding="utf-8")

    eprint(f"{'Would write' if dry_run else 'Wrote'} {len(talks)} talk pages, pruned {len(stale)}.")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Regenerate content/events/<slug>/index.md (the Talks section) from data/cv.yml."
    )
    parser.add_argument("--cv-path", type=Path, default=DEFAULT_CV_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    with args.cv_path.open(encoding="utf-8") as f:
        cv = yaml.safe_load(f)
    sync_pages(cv.get("talks", []), args.output_dir, args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
