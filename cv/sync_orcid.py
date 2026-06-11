#!/usr/bin/env python3
"""
sync_orcid.py — Additive ORCID -> publications.yaml sync for pem725.github.io

Fetches the ORCID *public* record (no auth, no client secret required) and finds
works that exist on ORCID but are missing from cv/publications.yaml.

  Dry run (default): prints a report of missing/orphan works, changes nothing.
  --write          : appends missing journal articles under `articles:`,
                     flagged `category: "TODO"`, after backing up the file.

Curation-safe by design: this script computes the set difference (ORCID - YAML)
and only ever APPENDS. It never edits or deletes an existing entry, so your
hand-curated categories, citation counts, and author strings are untouchable.

No client secret is used or needed. The ORCID Public API serves the public
record openly; a secret only matters for writing to ORCID or reading private
fields, neither of which a static GitHub Pages site can do safely.

Usage:
    python3 cv/sync_orcid.py            # report only
    python3 cv/sync_orcid.py --write    # append missing articles
"""
import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

ORCID_ID = "0000-0002-9067-9066"
PUB_API = "https://pub.orcid.org/v3.0"
YAML_PATH = Path(__file__).resolve().parent / "publications.yaml"

# ORCID work types we auto-append into the `articles:` section. Other types
# (books, book chapters, datasets...) are reported but left for manual placement,
# since they belong in different YAML sections with different fields.
AUTO_APPEND_TYPES = {"journal-article"}

# Titles starting with these are errata/corrections to papers already listed,
# not standalone publications -- skip them from auto-append.
SKIP_TITLE_PREFIXES = ("corrigendum", "erratum", "correction to", "retraction")


# ---------------------------------------------------------------------------
# ORCID fetching
# ---------------------------------------------------------------------------
def fetch(url):
    """GET a JSON document from the ORCID public API."""
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def fetch_work_detail(put_code):
    """Fetch a single work's full record (for authors + journal title)."""
    return fetch(f"{PUB_API}/{ORCID_ID}/work/{put_code}")


def get_orcid_works():
    """Return a list of summarized works from the ORCID public record.

    Each item: dict(title, year, type, doi, put_code).
    """
    data = fetch(f"{PUB_API}/{ORCID_ID}/works")
    works = []
    for group in data.get("group", []):
        summary = group["work-summary"][0]
        title = (
            summary.get("title", {}).get("title", {}).get("value", "").strip()
        )
        pub_date = summary.get("publication-date") or {}
        year = (pub_date.get("year") or {}).get("value", "")
        doi = ""
        for eid in (summary.get("external-ids") or {}).get("external-id", []):
            if eid.get("external-id-type") == "doi":
                doi = eid.get("external-id-value", "")
                break
        works.append(
            {
                "title": title,
                "year": year,
                "type": summary.get("type", ""),
                "doi": doi,
                "put_code": summary.get("put-code"),
            }
        )
    return works


# ---------------------------------------------------------------------------
# Normalization + matching
# ---------------------------------------------------------------------------
def norm_doi(doi):
    """Lowercase a DOI and strip any resolver prefix so two forms compare equal."""
    if not doi:
        return ""
    d = doi.strip().lower()
    d = re.sub(r"^https?://(dx\.)?doi\.org/", "", d)
    return d


def norm_title(title):
    """Reduce a title to alphanumerics for fuzzy fallback matching."""
    return re.sub(r"[^a-z0-9]", "", (title or "").lower())


def read_yaml_text():
    return YAML_PATH.read_text(encoding="utf-8")


def existing_keys(yaml_text):
    """Extract the set of DOIs and normalized titles already in the YAML.

    We scan the raw text (no YAML parser) precisely so we never have to
    re-serialize and risk mangling the file's comments and ordering.
    """
    dois, titles = set(), set()
    for m in re.finditer(r'doi:\s*"?([^"\n]+)"?', yaml_text):
        dois.add(norm_doi(m.group(1)))
    # also catch DOIs embedded in url: fields
    for m in re.finditer(r"10\.\d{4,9}/[^\s\"\)]+", yaml_text):
        dois.add(norm_doi(m.group(0)))
    for m in re.finditer(r'title:\s*"([^"]+)"', yaml_text):
        titles.add(norm_title(m.group(1)))
    return {d for d in dois if d}, titles


# Minimum normalized-title length before prefix matching is trusted. Short
# titles ("Reply", "Introduction") could collide by prefix; this guards against
# that. Tune to taste -- lower = more aggressive dedup, higher = more duplicates.
MIN_PREFIX_LEN = 14


def titles_match(orcid_title, yaml_title):
    """True if these refer to the same work.

    Your YAML stores main titles only ("When curiosity breeds intimacy") while
    ORCID appends subtitles ("...: Taking advantage of intimacy opportunities").
    So a YAML title is typically a *prefix* of the ORCID one. We match on exact
    equality OR shorter-is-a-prefix-of-longer, guarded by MIN_PREFIX_LEN.
    """
    a, b = norm_title(orcid_title), norm_title(yaml_title)
    if not a or not b:
        return False
    if a == b:
        return True
    short, long = (a, b) if len(a) <= len(b) else (b, a)
    return len(short) >= MIN_PREFIX_LEN and long.startswith(short)


def is_present(work, yaml_dois, yaml_titles):
    """True if this ORCID work already appears in the YAML (by DOI, then title)."""
    d = norm_doi(work["doi"])
    if d and d in yaml_dois:
        return True
    return any(titles_match(work["title"], yt) for yt in yaml_titles)


# ---------------------------------------------------------------------------
# Author formatting  --  see learning note below; refine to taste
# ---------------------------------------------------------------------------
def format_authors_orcid_to_house_style(full_names):
    """Convert ORCID contributor names into this CV's house style.

    ORCID gives full names like ["Patrick E. McKnight", "Todd B. Kashdan"].
    The YAML house style is:  "McKnight, P.E., Kashdan, T.B., & Gross, M."
    i.e. Family, Initials  --  comma-separated, with "&" before the last author.

    This is a deliberately simple first pass. Edge cases worth your judgment:
      - hyphenated surnames ("Blanco-Donoso")
      - name particles ("van der Berg", "de la Cruz")
      - single-name or initials-only contributors
      - whether to abbreviate to initials at all, or keep given names

    >>> format_authors_orcid_to_house_style(["Patrick E. McKnight", "Madeleine Gross"])
    'McKnight, P.E., & Gross, M.'
    """
    formatted = [_one_author(n) for n in full_names if n.strip()]
    if not formatted:
        return ""
    if len(formatted) == 1:
        return formatted[0]
    return ", ".join(formatted[:-1]) + ", & " + formatted[-1]


def _initials(given):
    """Turn a given-name string into initials: 'Jean-Christophe' -> 'J.C.',
    and already-abbreviated 'P.M.' -> 'P.M.' (split on space, hyphen, and period)."""
    chunks = re.split(r"[\s\-.]+", given.strip())
    return "".join(f"{c[0].upper()}." for c in chunks if c and c[0].isalpha())


def _one_author(name):
    """Format a single ORCID credit-name as 'Family, I.I.'.

    Handles ORCID's two deposit formats:
      'Jacobson, E.'        (comma -> already Family-first)
      'Jean-Christophe Mougeot'  (no comma -> Given ... Family)
    """
    name = name.strip()
    if "," in name:
        family, _, given = name.partition(",")
        family = family.strip()
        ini = _initials(given)
        return f"{family}, {ini}" if ini else family
    parts = name.split()
    if len(parts) < 2:
        return name
    family = parts[-1]
    ini = _initials(" ".join(parts[:-1]))
    return f"{family}, {ini}" if ini else family


# ---------------------------------------------------------------------------
# YAML entry generation
# ---------------------------------------------------------------------------
def yaml_escape(s):
    return (s or "").replace('"', '\\"')


def build_entry(work):
    """Render one missing work as a ready-to-paste YAML article block."""
    detail = fetch_work_detail(work["put_code"])
    contributors = (detail.get("contributors") or {}).get("contributor", [])
    names = [
        (c.get("credit-name") or {}).get("value", "").strip()
        for c in contributors
        if (c.get("credit-name") or {}).get("value")
    ]
    authors = format_authors_orcid_to_house_style(names)
    journal = (detail.get("journal-title") or {}).get("value", "")

    lines = [f'    - authors: "{yaml_escape(authors)}"']
    if work["year"]:
        lines.append(f"      year: {work['year']}")
    lines.append(f'      title: "{yaml_escape(work["title"])}"')
    if journal:
        lines.append(f'      journal: "{yaml_escape(journal)}"')
    if work["doi"]:
        lines.append(f'      doi: "{norm_doi(work["doi"])}"')
    lines.append('      category: "TODO"  # <- ORCID import: set category')
    return "\n".join(lines)


def append_entries(yaml_text, entry_blocks):
    """Insert new entries right after the `  articles:` line (newest-first)."""
    marker = re.search(r"^  articles:\s*$", yaml_text, flags=re.MULTILINE)
    if not marker:
        raise SystemExit("Could not find `  articles:` section in YAML.")
    insert_at = marker.end()
    block = "\n" + "\n\n".join(entry_blocks)
    return yaml_text[:insert_at] + block + yaml_text[insert_at:]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Additive ORCID -> publications.yaml sync")
    ap.add_argument(
        "--write",
        action="store_true",
        help="append missing journal articles to publications.yaml (backs up first)",
    )
    args = ap.parse_args()

    yaml_text = read_yaml_text()
    yaml_dois, yaml_titles = existing_keys(yaml_text)

    works = get_orcid_works()
    missing = [w for w in works if not is_present(w, yaml_dois, yaml_titles)]

    print(f"ORCID works:        {len(works)}")
    print(f"Already in YAML:    {len(works) - len(missing)}")
    print(f"Missing from YAML:  {len(missing)}\n")

    if not missing:
        print("Nothing to add. publications.yaml is in sync with ORCID.")
        return

    def is_erratum(w):
        return w["title"].strip().lower().startswith(SKIP_TITLE_PREFIXES)

    auto = [w for w in missing if w["type"] in AUTO_APPEND_TYPES and not is_erratum(w)]
    manual = [w for w in missing if w["type"] not in AUTO_APPEND_TYPES]
    skipped = [w for w in missing if w["type"] in AUTO_APPEND_TYPES and is_erratum(w)]
    if skipped:
        print(f"Skipped {len(skipped)} erratum/corrigendum item(s):")
        for w in skipped:
            print(f"  - {w['title'][:70]}")
        print()

    print("=== Missing journal articles (auto-appendable) ===")
    for w in auto:
        print(f"  [{w['year']}] {w['title'][:70]}  doi={w['doi'] or '-'}")
    if manual:
        print("\n=== Missing non-article works (place by hand) ===")
        for w in manual:
            print(f"  [{w['year']}] ({w['type']}) {w['title'][:60]}  doi={w['doi'] or '-'}")

    if not args.write:
        print("\n(Dry run. Re-run with --write to append the articles above.)")
        return

    if not auto:
        print("\nNo auto-appendable articles; nothing written.")
        return

    print(f"\nFetching authors for {len(auto)} new article(s)...")
    blocks = [build_entry(w) for w in auto]

    backup = YAML_PATH.with_suffix(".yaml.bak")
    backup.write_text(yaml_text, encoding="utf-8")
    new_text = append_entries(yaml_text, blocks)
    YAML_PATH.write_text(new_text, encoding="utf-8")

    print(f"Backed up to:  {backup.name}")
    print(f"Appended {len(blocks)} article(s) to publications.yaml.")
    print('Review them, replace each category: "TODO", then commit.')


if __name__ == "__main__":
    main()
