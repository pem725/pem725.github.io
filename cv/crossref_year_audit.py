#!/usr/bin/env python3
"""
crossref_year_audit.py — Verify publication years in publications.yaml against
Crossref's authoritative metadata (matched by DOI).

A paper can have different online-first vs print years; that's legitimate, so we
only flag a YAML year that matches NEITHER the Crossref issued year NOR the
print year. Reports mismatches; never edits (you decide the fix).
"""
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import yaml  # /usr/bin/python3 has it

YAML_PATH = Path(__file__).resolve().parent / "publications.yaml"
MAILTO = "pem725@gmail.com"
UA = f"McKnightCV-audit/1.0 (mailto:{MAILTO})"


def crossref(doi):
    url = "https://api.crossref.org/works/" + urllib.parse.quote(doi)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)["message"]


def years_from(msg):
    """Return the set of plausible publication years Crossref knows for a work."""
    ys = set()
    for key in ("issued", "published", "published-print", "published-online", "journal-issue"):
        node = msg.get(key) or {}
        if key == "journal-issue":
            node = node.get("published-print") or node.get("published-online") or {}
        parts = node.get("date-parts") or []
        if parts and parts[0] and parts[0][0]:
            ys.add(int(parts[0][0]))
    return ys


def main():
    data = yaml.safe_load(YAML_PATH.read_text())
    arts = [a for a in data["publications"]["articles"] if a.get("doi")]
    print(f"Auditing {len(arts)} articles that have a DOI...\n")

    mismatches, errors, ok = [], [], 0
    for a in arts:
        doi = a["doi"]
        try:
            msg = crossref(doi)
        except Exception as e:
            errors.append((a, str(e)))
            continue
        cy = years_from(msg)
        yy = a.get("year")
        if cy and yy not in cy:
            mismatches.append((a, sorted(cy)))
        else:
            ok += 1
        time.sleep(0.05)  # gentle on the API

    print(f"OK (year matches Crossref): {ok}")
    print(f"Mismatches: {len(mismatches)}")
    for a, cy in sorted(mismatches, key=lambda x: x[0].get("year", 0)):
        print(f"  YAML {a.get('year')}  vs Crossref {cy}")
        print(f"    {a['title'][:66]}")
        print(f"    doi:{a['doi']}")
    if errors:
        print(f"\nCould not check {len(errors)} (DOI not found / network):")
        for a, e in errors:
            print(f"  [{a.get('year')}] {a['title'][:55]}  ({e})")


if __name__ == "__main__":
    main()
