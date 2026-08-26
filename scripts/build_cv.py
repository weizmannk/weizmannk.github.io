#!/usr/bin/env python3
"""Render cv/template.tex.j2 from data/cv.yml + bibliography/publications.bib
and compile it to a PDF.

Usage:
    python scripts/build_cv.py --variant full
    python scripts/build_cv.py --variant short
    python scripts/build_cv.py --variant both
    python scripts/build_cv.py --variant full --keep-tex

Requires a LaTeX distribution on PATH (pdflatex) with the extsizes,
titlesec, enumitem, geometry, xcolor, babel, fancyhdr and hyperref
packages installed.

Text in data/cv.yml and bibliography/publications.bib is trusted to
already be LaTeX-safe (accented characters as raw UTF-8, special
characters like & pre-escaped) — this script does not auto-escape
anything, since doing so risks mangling text that's already correct.
"""

from __future__ import annotations

import argparse
import calendar
import re
import shutil
import subprocess
import sys
from pathlib import Path

import bibtexparser
import yaml
from jinja2 import Environment, FileSystemLoader

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CV_PATH = ROOT / "data" / "cv.yml"
DEFAULT_BIB_PATH = ROOT / "bibliography" / "publications.bib"
DEFAULT_TEMPLATE_PATH = ROOT / "cv" / "template.tex.j2"
DEFAULT_OUTPUT_DIR = ROOT / "static" / "uploads"
BUILD_DIR = ROOT / "cv" / "build"

OUTPUT_NAMES = {"full": "CV_Kiendrebeogo.pdf", "short": "CV_Kiendrebeogo_short.pdf"}

# Only these identity links go in the CV PDF header, matching main_CV.tex —
# e.g. LinkedIn is website-only, deliberately excluded here (see data/cv.yml).
CV_HEADER_LINK_ORDER = ["website", "github", "orcid", "google_scholar"]

PUBLICATION_SECTIONS = ["submitted", "refereed", "proceedings", "collaboration", "technical_report"]


def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)


# data/cv.yml holds plain prose (not LaTeX) — every string pulled from it
# must be escaped before going into the .tex output. bibliography/
# publications.bib is the opposite: hand-authored as LaTeX-ready text
# (e.g. "Astronomy \& Astrophysics"), so it is never passed through this.
_LATEX_SPECIAL_CHARS = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
    "─": "--",  # ADS sometimes uses a box-drawing dash (U+2500) as a range dash
}


def esc(text) -> str:
    if text is None:
        return ""
    return "".join(_LATEX_SPECIAL_CHARS.get(ch, ch) for ch in str(text))


# ---------------------------------------------------------------------------
# Date formatting
# ---------------------------------------------------------------------------


def humanize_single(token) -> str:
    if token is None:
        return ""
    token = str(token)
    if token == "present":
        return "present"
    parts = token.split("-")
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return f"{calendar.month_name[int(parts[1])]} {parts[0]}"
    return f"{int(parts[2])} {calendar.month_name[int(parts[1])]} {parts[0]}"


def humanize(token) -> str:
    """Handles both plain tokens and 'start/end' range tokens from cv.yml."""
    if token is None:
        return ""
    token = str(token)
    if "/" in token:
        start, end = token.split("/", 1)
        return f"{humanize_single(start)} -- {humanize_single(end)}"
    return humanize_single(token)


def date_range(start, end=None) -> str:
    start_label = humanize_single(start)
    if not end:
        return start_label
    end_label = humanize_single(end)
    if not start_label:
        return end_label
    return f"{start_label} - {end_label}"


# ---------------------------------------------------------------------------
# Publication formatting
# ---------------------------------------------------------------------------


def clean_title(raw: str) -> str:
    title = (raw or "").strip()
    if title.startswith("{") and title.endswith("}"):
        title = title[1:-1]
    return title


def format_publication(entry: dict) -> str:
    cite = entry.get("cite_authors") or entry.get("author", "")
    year = entry.get("year", "")
    title = clean_title(entry.get("title", ""))
    pub_type = entry.get("publication_type", "")
    doi_url = f"https://doi.org/{entry['doi']}" if entry.get("doi") else ""
    url = entry.get("url") or doi_url

    if pub_type in ("refereed", "collaboration") and entry.get("journal"):
        venue = f"\\emph{{{entry['journal']}}}"
        if entry.get("volume"):
            venue += f" \\textbf{{{entry['volume']}}}"
        page = entry.get("pages") or entry.get("eid")
        venue += f", {page}." if page else "."
        out = f"{cite} ({year}), ``{title}.'' {venue}"
        if url:
            out += f" \\url{{{url}}}"
        return out

    if pub_type == "proceedings" and entry.get("booktitle"):
        out = f"{cite} ({year}), ``{title}.'' {entry['booktitle']}."
        if url:
            out += f" \\url{{{url}}}"
        return out

    if pub_type == "submitted":
        note = entry.get("note", "Submitted")
        out = f"{cite} ({year}), ``{title}.'' \\emph{{{note}}}."
        if url:
            out += f" \\url{{{url}}}"
        return out

    if pub_type == "in_preparation":
        return f"{cite} ({year}), ``{title}.'' \\emph{{In preparation}}."

    if pub_type == "technical_report":
        bits = []
        if entry.get("publisher"):
            bit = entry["publisher"]
            if entry.get("version"):
                bit += f", {entry['version']}"
            bits.append(bit)
        if entry.get("howpublished"):
            bits.append(entry["howpublished"])
        out = f"{cite}"
        if year:
            out += f" ({year})"
        out += f", \\emph{{{title}}}."
        if bits:
            out += f" {', '.join(bits)}."
        if url:
            out += f" \\url{{{url}}}"
        return out

    # Generic fallback (e.g. collaboration entries still on arXiv only)
    out = f"{cite} ({year}), ``{title}.''"
    if url:
        out += f" \\url{{{url}}}"
    return out


def pub_sort_key(entry: dict):
    if entry.get("order") is not None:
        try:
            return (0, int(entry["order"]), "")
        except ValueError:
            pass
    try:
        year = -int(entry.get("year") or 0)
    except ValueError:
        year = 0
    return (1, year, clean_title(entry.get("title", "")))


def group_publications(entries: list[dict]) -> dict[str, list[str]]:
    groups: dict[str, list[dict]] = {name: [] for name in PUBLICATION_SECTIONS}
    for entry in entries:
        ptype = entry.get("publication_type")
        if ptype in ("submitted", "in_preparation"):
            groups["submitted"].append(entry)
        elif ptype in groups:
            groups[ptype].append(entry)
        else:
            eprint(f"warning: {entry.get('ID')} has unknown publication_type {ptype!r}, skipping")

    groups["submitted"].sort(key=lambda e: (e.get("publication_type") != "submitted", pub_sort_key(e)))
    for name in ("refereed", "proceedings", "collaboration", "technical_report"):
        groups[name].sort(key=pub_sort_key)

    return {name: [format_publication(e) for e in items] for name, items in groups.items()}


def selected_publications(entries: list[dict]) -> list[str]:
    featured = [e for e in entries if str(e.get("featured", "")).lower() == "true"]
    featured.sort(key=pub_sort_key)
    return [format_publication(e) for e in featured]


# ---------------------------------------------------------------------------
# Context building
# ---------------------------------------------------------------------------


def build_header(identity: dict) -> dict:
    postnominals = identity.get("postnominals") or []
    display = identity["name"]["display"]
    family = identity["name"].get("family")
    if family and family in display:
        display = display.replace(family, family.upper())
    name = esc(display)
    if postnominals:
        name += ", " + ", ".join(esc(p) for p in postnominals)

    role_bits = [esc(identity["role"])]
    if identity.get("affiliation", {}).get("name"):
        role_bits.append(esc(identity["affiliation"]["name"]))
    location = identity.get("location")
    role_line = " \\listsep\\ ".join(role_bits)
    if location:
        role_line += f", {esc(location)}"

    emails = identity.get("emails") or []
    emails_line = " \\listsep\\ ".join(f"\\href{{mailto:{e}}}{{{esc(e)}}}" for e in emails)

    links = identity.get("links", {})
    link_parts = []
    for key in CV_HEADER_LINK_ORDER:
        url = links.get(key)
        if not url:
            continue
        if key == "website":
            label = url.replace("https://", "").rstrip("/")
            link_parts.append(f"\\href{{{url}}}{{{label}}}")
        elif key == "github":
            label = url.replace("https://", "")
            link_parts.append(f"\\href{{{url}}}{{{label}}}")
        elif key == "orcid":
            oid = url.replace("https://orcid.org/", "")
            link_parts.append(f"ORCID: \\href{{{url}}}{{{oid}}}")
        elif key == "google_scholar":
            link_parts.append(f"\\href{{{url}}}{{Google Scholar}}")
    links_line = " \\listsep\\ ".join(link_parts)

    return {"name": name, "role_line": role_line, "emails_line": emails_line, "links_line": links_line}


_ABBREV_PERIOD_RE = re.compile(r"\b(M\.Sc|B\.Sc|Ph\.D)\. ")


def fix_abbrev_spacing(text: str) -> str:
    """Force a normal inter-word space (not TeX's sentence space) after
    lowercase-ending abbreviations like 'M.Sc.' — TeX otherwise treats the
    period as end-of-sentence since it isn't preceded by a capital letter."""
    return _ABBREV_PERIOD_RE.sub(r"\1.\\ ", text)


def build_education(items: list[dict]) -> list[dict]:
    out = []
    for e in items:
        institution_line = esc(e["institution"])
        if e.get("location"):
            institution_line += f", {esc(e['location'])}"
        summary_line = esc(e.get("summary", ""))
        thesis = e.get("thesis")
        if thesis:
            thesis_line = f"Thesis: \\href{{{thesis['url']}}}{{\\emph{{{esc(thesis['title'])}}}}}"
            summary_line = f"{summary_line}\\\\[1pt]\n{thesis_line}" if summary_line else thesis_line
        out.append(
            {
                "degree": fix_abbrev_spacing(esc(e["degree"])),
                "institution_line": institution_line,
                "date_label": humanize(e.get("date")),
                "summary_line": summary_line,
            }
        )
    return out


def build_appointments(items: list[dict]) -> list[dict]:
    out = []
    for a in items:
        institution_line = esc(a["institution"])
        if a.get("location"):
            institution_line += f", {esc(a['location'])}"
        out.append(
            {
                "role": esc(a["role"]),
                "institution_line": institution_line,
                "date_range": date_range(a.get("start"), a.get("end")),
                "summary": esc(a.get("summary", "")),
            }
        )
    return out


def build_honors(items: list[dict]) -> list[dict]:
    return [{"title": esc(h["title"]), "awarder": esc(h.get("awarder", "")), "date": esc(h.get("date", ""))} for h in items]


def build_grants(items: list[dict]) -> list[dict]:
    out = []
    for g in items:
        role_line = esc(g.get("role", ""))
        if g.get("amount"):
            role_line += f" -- {esc(g['amount'])}"
        summary = g.get("summary", "").strip()
        sentences = [s.strip() for s in summary.split(". ") if s.strip()]
        summary_lines = [esc(s if s.endswith(".") else s + ".") for s in sentences]
        out.append(
            {
                "title": esc(g["title"]),
                "date": esc(g.get("date", "")),
                "role_line": role_line,
                "summary_lines": summary_lines,
            }
        )
    return out


def build_fellowships(items: list[dict]) -> list[dict]:
    return [
        {
            "title": esc(f["title"]),
            "awarder": esc(f.get("awarder", "")),
            "date_range": date_range(f.get("start"), f.get("end")),
        }
        for f in items
    ]


def build_teaching(items: list[dict]) -> list[dict]:
    out = []
    for t in items:
        institution_line = f", {esc(t['institution'])}" if t.get("institution") else ""
        out.append(
            {
                "role": esc(t["role"]),
                "institution_line": institution_line,
                "date_range": date_range(t.get("start"), t.get("end")) or humanize(t.get("date")),
                "summary": esc(t.get("summary", "")),
            }
        )
    return out


def build_talks(items: list[dict]) -> list[dict]:
    return [
        {
            "type": esc(t["type"]),
            "title": esc(t["title"]),
            "url": t.get("url", ""),
            "venue": esc(t["venue"]),
            "date_label": humanize(t.get("date")),
        }
        for t in items
    ]


def build_service(items: list[dict]) -> list[dict]:
    out = []
    for s in items:
        date_suffix = f" \\hfill {humanize(s['date'])}" if s.get("date") else ""
        out.append({"role": esc(s["role"]), "organization": esc(s.get("organization", "")), "date_suffix": date_suffix})
    return out


def build_schools_workshops(items: list[dict]) -> list[dict]:
    return [
        {"title": esc(s["title"]), "venue": esc(s.get("venue", "")), "date_label": humanize(s.get("date"))}
        for s in items
    ]


def build_open_source(items: list[dict]) -> list[dict]:
    out = []
    for o in items:
        links_line = " \\listsep ".join(f"\\url{{{link}}}" for link in o.get("links", []))
        out.append({"name": esc(o["name"]), "description": esc(o.get("description", "")), "links_line": links_line})
    return out


def build_skills(groups: list[dict]) -> list[dict]:
    return [{"category": esc(g["category"]), "items_line": ", ".join(esc(item) for item in g["items"])} for g in groups]


def build_languages_line(items: list[dict]) -> str:
    return " \\listsep ".join(f"{esc(lang['name'])} ({esc(lang['level'])})" for lang in items)


def load_bib_entries(bib_path: Path) -> list[dict]:
    with bib_path.open(encoding="utf-8") as f:
        db = bibtexparser.load(f)
    return db.entries


def build_context(cv: dict, bib_entries: list[dict], variant: str) -> dict:
    header = build_header(cv["identity"])
    context = {
        "variant": variant,
        "short": variant == "short",
        "header_name": header["name"],
        "header_role_line": header["role_line"],
        "header_emails_line": header["emails_line"],
        "header_links_line": header["links_line"],
        "identity": cv["identity"],
        "research_interests": cv.get("research_interests", []),
        "research_interests_line": " \\listsep ".join(esc(i) for i in cv.get("research_interests", [])),
        "education": build_education(cv.get("education", [])),
        "appointments": build_appointments(cv.get("appointments", [])),
        "honors": build_honors(cv.get("honors", [])),
        "grants": build_grants(cv.get("grants", [])),
        "fellowships": build_fellowships(cv.get("fellowships", [])),
        "talks": build_talks(cv.get("talks", [])),
        "teaching": build_teaching(cv.get("teaching", [])),
        "service": build_service(cv.get("service", [])),
        "schools_workshops": build_schools_workshops(cv.get("schools_workshops", [])),
        "open_source": build_open_source(cv.get("open_source", [])),
        "skills": build_skills(cv.get("skills", [])),
        "languages_line": build_languages_line(cv.get("languages", [])),
        "publications": group_publications(bib_entries),
        "selected_publications": selected_publications(bib_entries),
    }
    return context


# ---------------------------------------------------------------------------
# Rendering & compilation
# ---------------------------------------------------------------------------


def make_jinja_env(template_dir: Path) -> Environment:
    return Environment(
        loader=FileSystemLoader(str(template_dir)),
        block_start_string=r"\BLOCK{",
        block_end_string="}",
        variable_start_string=r"\VAR{",
        variable_end_string="}",
        comment_start_string=r"\#{",
        comment_end_string="}",
        trim_blocks=True,
        lstrip_blocks=True,
    )


def compile_pdf(tex_path: Path, build_dir: Path) -> Path:
    for _ in range(2):  # twice for hyperref's internal references to settle
        result = subprocess.run(
            ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", "-output-directory", str(build_dir), str(tex_path)],
            cwd=build_dir,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            log_tail = "\n".join(result.stdout.splitlines()[-60:])
            raise RuntimeError(f"pdflatex failed on {tex_path.name}:\n{log_tail}")
    pdf_path = build_dir / (tex_path.stem + ".pdf")
    if not pdf_path.exists():
        raise RuntimeError(f"pdflatex reported success but {pdf_path} is missing")
    return pdf_path


def build_variant(variant: str, cv: dict, bib_entries: list[dict], args) -> Path:
    eprint(f"Building {variant} CV ...")
    context = build_context(cv, bib_entries, variant)
    env = make_jinja_env(args.template_path.parent)
    template = env.get_template(args.template_path.name)
    rendered = template.render(**context)

    args.build_dir.mkdir(parents=True, exist_ok=True)
    tex_path = args.build_dir / f"cv_{variant}.tex"
    tex_path.write_text(rendered, encoding="utf-8")

    pdf_path = compile_pdf(tex_path, args.build_dir)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    final_path = args.output_dir / OUTPUT_NAMES[variant]
    shutil.copyfile(pdf_path, final_path)
    eprint(f"  -> {final_path}")

    if not args.keep_tex:
        for ext in (".tex", ".aux", ".log", ".out"):
            (args.build_dir / f"cv_{variant}{ext}").unlink(missing_ok=True)

    return final_path


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Render and compile the CV PDF from data/cv.yml + bibliography/publications.bib.")
    parser.add_argument("--variant", choices=["full", "short", "both"], default="full")
    parser.add_argument("--cv-path", type=Path, default=DEFAULT_CV_PATH)
    parser.add_argument("--bib-path", type=Path, default=DEFAULT_BIB_PATH)
    parser.add_argument("--template-path", type=Path, default=DEFAULT_TEMPLATE_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--build-dir", type=Path, default=BUILD_DIR)
    parser.add_argument("--keep-tex", action="store_true", help="Keep the rendered .tex/.log/.aux files for debugging")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)

    if shutil.which("pdflatex") is None:
        eprint("pdflatex not found on PATH. Install a LaTeX distribution (e.g. BasicTeX + tlmgr install titlesec enumitem).")
        return 1

    with args.cv_path.open(encoding="utf-8") as f:
        cv = yaml.safe_load(f)
    bib_entries = load_bib_entries(args.bib_path)

    variants = ["full", "short"] if args.variant == "both" else [args.variant]
    try:
        for variant in variants:
            build_variant(variant, cv, bib_entries, args)
    except RuntimeError as exc:
        eprint(str(exc))
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
