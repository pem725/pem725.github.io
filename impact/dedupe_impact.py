#!/usr/bin/env python3
"""
dedupe_impact.py — Remove duplicate publications from impact/index.html.

The page (and its source scraped.json) had every pre-2025 publication listed
twice, inflating the count from a true ~135 to 272. This parses the pub list
with a div-nesting-aware scanner (so nested <details> abstracts are preserved),
dedupes by title+authors+journal (keeping the copy that HAS curated details),
then recomputes every displayed count and regenerates the period chart.

Run with no args to REPORT the plan; run with --write to apply (backs up first).
"""
import re
import sys
from pathlib import Path

HTML = Path(__file__).resolve().parent / "index.html"


def extract_div(chunk):
    """Return the first balanced <div>...</div> block at the start of chunk."""
    depth = 0
    for m in re.finditer(r"<div\b|</div>", chunk):
        if m.group() == "</div>":
            depth -= 1
            if depth == 0:
                return chunk[: m.end()]
        else:
            depth += 1
    return chunk  # unbalanced; return whole (shouldn't happen)


def text_of(block, cls):
    m = re.search(r'<div class="' + cls + r'">(.*?)</div>', block, re.S)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", m.group(1))).strip() if m else ""


def journal_of(block):
    m = re.search(r'<span class="pub-journal">(.*?)</span>', block, re.S)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", m.group(1))).strip() if m else ""


def main():
    write = "--write" in sys.argv
    h = HTML.read_text(encoding="utf-8")

    start = h.index('<div id="pub-list">')
    footer = h.index('<div class="footer"')
    region = h[start:footer]

    # Tokenize into year-header / pub items, then extract each balanced block.
    raw = re.split(r'(?=<div class="year-header"|<div class="pub" data-search)', region)
    items = []  # (kind, year_or_None, block, key)
    for chunk in raw:
        if chunk.startswith('<div class="year-header"'):
            block = extract_div(chunk)
            yr = re.search(r">(\d{4}|Other)</div>", block)
            items.append(("year", yr.group(1) if yr else "?", block, None))
        elif chunk.startswith('<div class="pub" data-search'):
            block = extract_div(chunk)
            key = (text_of(block, "pub-title") + "|" + text_of(block, "pub-authors")
                   + "|" + journal_of(block)).lower()
            items.append(("pub", None, block, key))

    # Dedupe pubs by key across the whole list; prefer the block WITH <details>.
    best = {}        # key -> block (richest)
    order = []       # keys in first-seen order
    for kind, _, block, key in items:
        if kind != "pub":
            continue
        if key not in best:
            best[key] = block
            order.append(key)
        elif "<details" in block and "<details" not in best[key]:
            best[key] = block  # upgrade to the copy that has the abstract

    # Rebuild list in original order, emitting year headers + first hit of each key.
    emitted = set()
    out_lines = ['<div id="pub-list">']
    cur_year = None
    kept_by_year = {}
    journals = set()
    for kind, yr, block, key in items:
        if kind == "year":
            cur_year = yr
            out_lines.append(block)  # placeholder; pruned below if empty
        else:
            if key in emitted:
                continue
            emitted.add(key)
            out_lines.append(best[key])
            kept_by_year.setdefault(cur_year, 0)
            kept_by_year[cur_year] += 1
            j = journal_of(best[key])
            if j:
                journals.add(j.lower())

    # Prune year headers that have no following kept pubs.
    pruned = []
    for i, line in enumerate(out_lines):
        if line.startswith('<div class="year-header"'):
            nxt = out_lines[i + 1] if i + 1 < len(out_lines) else ""
            if nxt.startswith('<div class="pub"'):
                pruned.append(line)
        else:
            pruned.append(line)
    new_list = "\n    ".join(pruned) + "\n  </div>\n\n  "

    total = len(emitted)
    n_journals = len(journals)
    years_present = sorted(int(y) for y in kept_by_year if y and y.isdigit())
    span = years_present[-1] - years_present[0] + 1 if years_present else 0

    # ---- report ----
    print(f"Pubs: 272 -> {total}   Journals: {n_journals}   Years active: {span}")
    print("Per-year (kept):")
    for y in sorted(kept_by_year, key=lambda x: (x != "Other", x), reverse=True):
        print(f"  {y}: {kept_by_year[y]}")

    # sanity: ensure every pub-title that HAD an abstract still has one
    def detailed_titles(text):
        titles = set()
        for m in re.finditer(r'<div class="pub" data-search.*?(?=<div class="pub" data-search|<div class="year-header"|$)', text, re.S):
            blk = m.group(0)
            if "<details" in blk:
                titles.add(text_of(blk, "pub-title").lower())
        return titles
    before_titles = detailed_titles(region)
    after_titles = detailed_titles("\n    ".join(pruned))
    lost = before_titles - after_titles
    details_before = h.count('<details class="pub-detail"')
    details_after = "\n".join(pruned).count('<details class="pub-detail"')
    print(f"\nCurated <details>: {details_before} instances -> {details_after} kept")
    print(f"Distinct pubs with an abstract: {len(before_titles)} -> {len(after_titles)}; LOST: {len(lost)}")
    if lost:
        print("  !!! ABSTRACTS LOST FOR:")
        for t in lost:
            print("   -", t[:60])

    # ---- regenerate the 5-year period chart ----
    buckets = [("1995-1999", range(1995, 2000)), ("2000-2004", range(2000, 2005)),
               ("2005-2009", range(2005, 2010)), ("2010-2014", range(2010, 2015)),
               ("2015-2019", range(2015, 2020)), ("2020-2024", range(2020, 2025)),
               ("2025-2029", range(2025, 2030))]
    counts = []
    for label, rng in buckets:
        counts.append(sum(kept_by_year.get(str(y), 0) for y in rng))
    mx = max(counts) or 1
    svg = ['<line x1="55" y1="190" x2="456" y2="190" stroke="#c8b99a" stroke-width="1"/>']
    for i, ((label, _), v) in enumerate(zip(buckets, counts)):
        x = 60 + i * 56
        hgt = v / mx * 160
        y = 190 - hgt
        cx = x + 24
        color = "#c9962a" if label == "2025-2029" else "#2c4a6e"
        svg.append(f'<rect x="{x}" y="{y:.2f}" width="48" height="{hgt:.2f}" fill="{color}" opacity="0.85"/>')
        svg.append(f'<text x="{cx:.1f}" y="{y-5:.2f}" text-anchor="middle" font-family="Roboto Mono" font-size="10" fill="#1a1208" font-weight="700">{v}</text>')
        svg.append(f'<text x="{cx:.1f}" y="207" text-anchor="middle" font-family="Roboto Mono" font-size="8" fill="#6b5e4a">{label}</text>')
    chart_inner = "\n      " + "\n      ".join(svg) + "\n    "
    print(f"\nChart buckets (corrected): {dict(zip([b[0] for b in buckets], counts))}")

    if not write:
        print("\n(Report only. Re-run with --write to apply.)")
        return

    # ---- write ----
    new_h = h[:start] + new_list + h[footer:]
    # scalar count fixes
    new_h = new_h.replace("272 publications · 110 journals", f"{total} publications · {n_journals} journals")
    new_h = re.sub(r'(<div class="v">)272(</div><div class="l">Publications)', rf'\g<1>{total}\g<2>', new_h)
    new_h = re.sub(r'(<div class="v">)110(</div><div class="l">Unique Journals)', rf'\g<1>{n_journals}\g<2>', new_h)
    new_h = re.sub(r'(<div class="v">)31(</div><div class="l">Years Active)', rf'\g<1>{span}\g<2>', new_h)
    new_h = new_h.replace("Showing all 272 publications", f"Showing all {total} publications")
    new_h = new_h.replace("of 268 publications matching", f"of {total} publications matching")

    # swap chart interior (baseline line through last label)
    new_h = re.sub(
        r'(<svg class="chart"[^>]*>).*?(\s*</svg>)',
        lambda m: m.group(1) + chart_inner + "</svg>",
        new_h, count=1, flags=re.S,
    )

    if lost:
        sys.exit("ABORT: would drop abstracts; not writing.")
    HTML.with_suffix(".html.bak").write_text(h, encoding="utf-8")
    HTML.write_text(new_h, encoding="utf-8")
    print(f"\nWrote {HTML.name} (backup: {HTML.name}.bak). Counts + chart updated.")
    return None


if __name__ == "__main__":
    main()
