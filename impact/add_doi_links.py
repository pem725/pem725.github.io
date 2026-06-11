#!/usr/bin/env python3
"""
add_doi_links.py — Add DOI links to each publication on impact/index.html.

The impact list comes from a Google Scholar scrape with no DOIs. This resolves a
DOI for each pub two ways, in order of trust:
  1. exact/containment title match against cv/publications.yaml (75 known DOIs)
  2. Crossref bibliographic search, accepted only on a strong title match
Then it injects a small "doi ↗" link after each pub's journal line.

Report-only by default; --write applies (backs up first). Never invents a link
when confidence is low -- those pubs simply stay link-free.
"""
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import yaml

HTML = Path(__file__).resolve().parent / "index.html"
YAML = Path(__file__).resolve().parent.parent / "cv" / "publications.yaml"
MAILTO = "pem725@gmail.com"
UA = f"McKnightImpact/1.0 (mailto:{MAILTO})"
ACCEPT = 0.72  # min title token-overlap to trust a Crossref hit


def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def toks(s):
    return set(re.findall(r"[a-z0-9]+", (s or "").lower()))


def overlap(a, b):
    ta, tb = toks(a), toks(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / min(len(ta), len(tb))  # containment-style


def yaml_doi_map():
    d = yaml.safe_load(YAML.read_text())
    m = {}
    for a in d["publications"]["articles"] + d["publications"]["books"]:
        if a.get("doi"):
            m[norm(a["title"])] = a["doi"]
    return m


def crossref_doi(title, author_hint="McKnight"):
    q = urllib.parse.urlencode({"query.bibliographic": title, "query.author": author_hint, "rows": 3})
    url = "https://api.crossref.org/works?" + q
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            items = json.load(r)["message"]["items"]
    except Exception:
        return None, 0.0
    best, score = None, 0.0
    for it in items:
        ct = (it.get("title") or [""])[0]
        s = overlap(title, ct)
        if s > score:
            best, score = it.get("DOI"), s
    return (best, score) if score >= ACCEPT else (None, score)


def extract_div(chunk):
    depth = 0
    for m in re.finditer(r"<div\b|</div>", chunk):
        if m.group() == "</div>":
            depth -= 1
            if depth == 0:
                return chunk[: m.end()]
        else:
            depth += 1
    return chunk


def main():
    write = "--write" in sys.argv
    h = HTML.read_text(encoding="utf-8")
    ymap = yaml_doi_map()

    start = h.index('<div id="pub-list">')
    footer = h.index('<div class="footer"')
    region = h[start:footer]
    chunks = re.split(r'(?=<div class="pub" data-search)', region)

    from_yaml = from_cref = unresolved = already = 0
    new_region = region
    details = []  # (title, doi, source)

    for chunk in chunks:
        if not chunk.startswith('<div class="pub" data-search'):
            continue
        block = extract_div(chunk)
        if "pub-doi-link" in block:
            already += 1
            continue
        tm = re.search(r'<div class="pub-title">(.*?)</div>', block, re.S)
        title = re.sub(r"<[^>]+>", "", tm.group(1)).strip() if tm else ""
        am = re.search(r'<div class="pub-authors">(.*?)</div>', block, re.S)
        authors = re.sub(r"<[^>]+>", "", am.group(1)).strip() if am else ""

        doi, src = ymap.get(norm(title)), "yaml"
        if not doi:
            # containment match against yaml titles
            for yt, yd in ymap.items():
                if len(yt) >= 14 and (yt in norm(title) or norm(title) in yt):
                    doi, src = yd, "yaml~"
                    break
        if not doi and len(toks(title)) >= 4:
            # only trust Crossref-by-title for titles long enough to be distinctive
            doi, score = crossref_doi(title, authors.split()[-1] if authors else "McKnight")
            src = "crossref"
            time.sleep(0.05)

        if not doi:
            unresolved += 1
            continue
        from_yaml += src.startswith("yaml")
        from_cref += src == "crossref"
        details.append((title, doi, src))

        # inject link after the </span> of pub-journal within this block
        link = f' <a class="pub-doi-link" href="https://doi.org/{doi}" target="_blank" rel="noopener">doi ↗</a>'
        new_block = re.sub(r'(<span class="pub-journal">.*?</span>)', r"\1" + link, block, count=1, flags=re.S)
        if new_block == block:  # no journal span; append before block close
            new_block = block[: block.rfind("</div>")] + link + block[block.rfind("</div>"):]
        new_region = new_region.replace(block, new_block, 1)

    print(f"Resolved from YAML: {from_yaml} | from Crossref: {from_cref} | "
          f"already had link: {already} | UNRESOLVED: {unresolved}")
    if details:
        cref = [d for d in details if d[2] == "crossref"]
        print(f"\nCrossref-sourced ({len(cref)}) -- verify these are right:")
        for t, doi, _ in cref:
            print(f"  {doi}  <- {t[:58]}")

    if not write:
        print("\n(Report only. Re-run with --write to inject links.)")
        return

    css = (".orcid-live .ol-msg{font-size:.8rem;color:var(--muted);font-style:italic}\n"
           ".pub-doi-link{font-family:'Roboto Mono',monospace;font-size:.64rem;color:var(--rust);"
           "border:none;letter-spacing:.04em;white-space:nowrap}\n"
           ".pub-doi-link:hover{text-decoration:underline}")
    new_h = h[:start] + new_region + h[footer:]
    new_h = new_h.replace(".orcid-live .ol-msg{font-size:.8rem;color:var(--muted);font-style:italic}", css, 1)

    HTML.with_suffix(".html.bak").write_text(h, encoding="utf-8")
    HTML.write_text(new_h, encoding="utf-8")
    print(f"\nWrote {HTML.name}. {from_yaml + from_cref} DOI links injected.")


if __name__ == "__main__":
    main()
