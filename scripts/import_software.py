#!/usr/bin/env python3
"""Generate content/projects/<slug>/index.md pages from data/cv.yml's
open_source list (rendered on the site as the "Software" section).

Every page under content/projects/ is fully derived from cv.yml — do not
hand-edit them, edit data/cv.yml and re-run this script. Folders for
entries no longer in cv.yml are pruned.

Usage:
    python scripts/import_software.py
    python scripts/import_software.py --dry-run
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
DEFAULT_OUTPUT_DIR = ROOT / "content" / "projects"


def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text or "untitled"


def link_type(url: str) -> str:
    return "code" if "github.com" in url else "site"


def build_front_matter(item: dict, weight: int) -> dict:
    return {
        "title": item["name"],
        "weight": weight,
        "summary": item.get("description", ""),
        "links": [{"type": link_type(url), "url": url} for url in item.get("links", [])],
        "tags": [],
        "reading_time": False,
    }


def render_page(item: dict, weight: int) -> str:
    fm = build_front_matter(item, weight)
    front_matter = yaml.safe_dump(fm, allow_unicode=True, sort_keys=False, default_flow_style=False)
    body = item.get("description", "")
    return f"---\n{front_matter}---\n\n{body}\n"


def sync_pages(items: list[dict], output_dir: Path, dry_run: bool) -> None:
    slugs = [slugify(item["name"]) for item in items]
    expected = set(slugs)

    existing = {p.name for p in output_dir.iterdir() if p.is_dir()} if output_dir.exists() else set()
    stale = existing - expected
    for name in stale:
        eprint(f"prune: content/projects/{name}/ (no longer in data/cv.yml)")
        if not dry_run:
            shutil.rmtree(output_dir / name)

    for weight, (item, slug) in enumerate(zip(items, slugs), start=1):
        page = render_page(item, weight)
        target = output_dir / slug / "index.md"
        if not dry_run:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(page, encoding="utf-8")

    eprint(f"{'Would write' if dry_run else 'Wrote'} {len(items)} software pages, pruned {len(stale)}.")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Regenerate content/projects/<slug>/index.md (the Software section) from data/cv.yml."
    )
    parser.add_argument("--cv-path", type=Path, default=DEFAULT_CV_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    with args.cv_path.open(encoding="utf-8") as f:
        cv = yaml.safe_load(f)
    sync_pages(cv.get("open_source", []), args.output_dir, args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
