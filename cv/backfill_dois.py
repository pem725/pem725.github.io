#!/usr/bin/env python3
"""
backfill_dois.py — One-time enrichment: add ORCID DOIs to existing YAML entries.

Why: cv/publications.yaml currently has almost no DOIs, so the ORCID sync can
only match works by fuzzy title -- fragile against subtitles, hyphens, typos.
This backfills DOIs into matched entries so every *future* sync matches exactly.

Safety:
  * Default is a DRY RUN: prints a review table + unified diff, writes nothing.
  * Only ADDS a `doi:` line to entries that have none. Never edits other fields.
  * --write backs up to publications.yaml.bak before saving.
  * Matching uses word-overlap (Jaccard); only confident matches are applied,
    and every one is shown with its ORCID counterpart so you can eyeball it.

Usage:
    python3 cv/backfill_dois.py            # review table + diff, no changes
    python3 cv/backfill_dois.py --write    # apply after you're satisfied
"""
import argparse
import difflib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sync_orcid as orcid  # reuse fetching + normalization

YAML_PATH = Path(__file__).resolve().parent / "publications.yaml"

# Word-overlap above this auto-applies; the band below it is shown but skipped.
APPLY_THRESHOLD = 0.55
REVIEW_THRESHOLD = 0.30


def tokens(title):
    return set(re.findall(r"[a-z0-9]+", (title or "").lower()))


def jaccard(a, b):
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


# Minimum shared word count before a full-containment match is trusted. Your
# YAML often stores a title with its subtitle stripped, so the YAML words are a
# strict subset of the ORCID title -- containment catches that where Jaccard
# can't. The word floor stops a 2-word title matching a longer unrelated one.
CONTAINMENT_MIN_WORDS = 4


def match_score(yaml_title, orcid_title):
    """Return (score, contained) for a YAML/ORCID title pair.

    `contained` is True when the shorter title's words are entirely inside the
    longer's -- the signature of a subtitle-stripped duplicate.
    """
    ta, tb = tokens(yaml_title), tokens(orcid_title)
    if not ta or not tb:
        return 0.0, False
    inter = len(ta & tb)
    contained = inter == min(len(ta), len(tb)) and min(len(ta), len(tb)) >= CONTAINMENT_MIN_WORDS
    return inter / len(ta | tb), contained


def articles_span(text):
    """Return (start, end) char offsets of the `articles:` section body."""
    start = re.search(r"^  articles:\s*$", text, flags=re.MULTILINE)
    if not start:
        raise SystemExit("No `  articles:` section found.")
    nxt = re.search(r"^  [a-z_]+:\s*$", text[start.end():], flags=re.MULTILINE)
    end = start.end() + nxt.start() if nxt else len(text)
    return start.end(), end


def split_entries(section):
    """Split an articles section body into (text, title, has_doi) entry blocks.

    Returns a list of dicts; non-entry text (blank lines, `# 2025` comments) is
    attached to the following entry so reassembly is loss-free.
    """
    # Each entry starts at a line like `    - authors:` / `    - title:` etc.
    parts = re.split(r"(?m)(?=^    - )", section)
    entries = []
    for p in parts:
        if not p.strip():
            entries.append({"text": p, "title": None, "has_doi": False})
            continue
        tm = re.search(r'title:\s*"([^"]+)"', p)
        entries.append(
            {
                "text": p,
                "title": tm.group(1) if tm else None,
                "has_doi": bool(re.search(r"^\s*doi:", p, flags=re.MULTILINE)),
            }
        )
    return entries


def insert_doi(entry_text, doi):
    """Add a `doi:` line right after the entry's title line."""
    def repl(m):
        return m.group(0) + f'\n      doi: "{doi}"'
    return re.sub(r'(?m)^(      title:.*)$', repl, entry_text, count=1)


def main():
    ap = argparse.ArgumentParser(description="Backfill ORCID DOIs into publications.yaml")
    ap.add_argument("--write", action="store_true", help="apply changes (backs up first)")
    args = ap.parse_args()

    text = YAML_PATH.read_text(encoding="utf-8")
    a0, a1 = articles_span(text)
    section = text[a0:a1]
    entries = split_entries(section)

    # ORCID works that carry a DOI, newest first; each DOI used at most once.
    orcid_works = [w for w in orcid.get_orcid_works() if w["doi"]]
    used = set()

    applied, review = [], []
    for e in entries:
        if not e["title"] or e["has_doi"]:
            continue
        best, score, best_contained = None, 0.0, False
        for w in orcid_works:
            d = orcid.norm_doi(w["doi"])
            if d in used:
                continue
            s, contained = match_score(e["title"], w["title"])
            # rank by score, but a contained match always beats a non-contained one
            if (contained, s) > (best_contained, score):
                best, score, best_contained = w, s, contained
        accept = best and (score >= APPLY_THRESHOLD or best_contained)
        if accept:
            doi = orcid.norm_doi(best["doi"])
            used.add(doi)
            e["text"] = insert_doi(e["text"], doi)
            tag = "contained" if best_contained and score < APPLY_THRESHOLD else f"{score:.2f}"
            applied.append((e["title"], best["title"], tag, doi))
        elif best and score >= REVIEW_THRESHOLD:
            review.append((e["title"], best["title"], f"{score:.2f}", orcid.norm_doi(best["doi"])))

    print(f"Confident matches (DOI will be added): {len(applied)}")
    for yt, ot, sc, doi in applied:
        print(f"  [{sc:>9}] {yt[:48]}")
        print(f"         -> {ot[:48]}  ({doi})")

    if review:
        print(f"\nLow-confidence near-misses (NOT applied -- check by hand): {len(review)}")
        for yt, ot, sc, doi in review:
            print(f"  [{sc}] YAML: {yt[:46]}")
            print(f"         ORCID: {ot[:46]}  ({doi})")

    if not applied:
        print("\nNothing confident to backfill.")
        return

    new_section = "".join(e["text"] for e in entries)
    new_text = text[:a0] + new_section + text[a1:]

    diff = difflib.unified_diff(
        text.splitlines(keepends=True),
        new_text.splitlines(keepends=True),
        "publications.yaml (before)",
        "publications.yaml (after)",
    )
    print("\n===== UNIFIED DIFF =====")
    sys.stdout.writelines(diff)

    if not args.write:
        print("\n(Dry run. Re-run with --write to apply the diff above.)")
        return

    backup = YAML_PATH.with_suffix(".yaml.bak")
    backup.write_text(text, encoding="utf-8")
    YAML_PATH.write_text(new_text, encoding="utf-8")
    print(f"\nBacked up to {backup.name}; wrote {len(applied)} DOIs to publications.yaml.")


if __name__ == "__main__":
    main()
