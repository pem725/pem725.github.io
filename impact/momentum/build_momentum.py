#!/usr/bin/env python3
"""Momentum: is the work still moving? Citation velocity, acceleration and
fresh-work share from OpenAlex, for Patrick, his graduate students and the
GMU Psychology department.

Total citations is a stock: it only goes up, so it cannot tell a scientist who
is pushing forward from one living off a 2009 paper. This script measures flow:

  velocity      citations received per calendar year (current year projected
                from the year-to-date count, and labelled as a projection)
  growth        compound yearly change in velocity, last 3 complete years vs
                the 3 before them  ((recent/prior) ** (1/3) - 1)
  acceleration  the same comparison in citations/year gained per year
  fresh share   of the citations received in a year, the share that went to
                papers published in that year or the 4 before it. High = the
                new work is what people are citing; low = living off classics.

Sources: OpenAlex only (public, scriptable, no login). Google Scholar numbers
are larger but cannot be pulled by a script; the department page keeps those
as a hand-harvested second source. OpenAlex's by-year counts start in 2012.

Outputs (all under impact/data/):
  momentum.js           window.MOMENTUM = {...}  read by the impact,
                        students and department pages
  momentum.json         the same data, for scripts (the AI-box watch)
  momentum_history.csv  one row per person per run date, append-only, so the
                        change in these numbers over time is kept

Usage:
  python3 impact/momentum/build_momentum.py                # weekly refresh
  python3 impact/momentum/build_momentum.py --resolve-students ~/GitTemp/cv/publications.yaml
      (one-off: match the CV's student roster to OpenAlex authors via papers
       co-authored with Patrick; writes impact/students/students.csv to review)

Stdlib only, like the CV tooling. Optional env OPENALEX_API_KEY.
"""
import argparse, csv, datetime as dt, json, os, re, sys, time, unicodedata
import urllib.parse, urllib.request
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FACULTY_CSV = ROOT / "impact/dept-benchmark/faculty.csv"
STUDENTS_CSV = ROOT / "impact/students/students.csv"
DATA = ROOT / "impact/data"
SELF_ORCID = "0000-0002-9067-9066"
SELF_KEY = "mcknight_p"
API = "https://api.openalex.org"
MIN_BASE = 5            # growth needs >= 5 citations/yr in the prior 3 years
FRESH_WINDOW = 5          # "recent" = published in the citing year or the 4 before
SKIP_TYPES = {"erratum", "paratext", "retraction", "peer-review", "dataset", "preprint"}
# Known OpenAlex fragment ids for faculty without an ORCID (mirrors _openalex.R).
EXTRA_IDS = {"matthews_g": ["A5101575317", "A5101575318", "A5025982678", "A5114001556", "A5134484372"],
             "adams_l": ["A5084875053"]}
# Namesake guard (mirrors AFFIL_RULES in impact/dept-benchmark/_openalex.R): OpenAlex
# merged James Chilton Thompson (UTMB Galveston surgeon) and others into James C.
# Thompson's ORCID. A work counts only if his authorship lists one of his own
# institutions (Swinburne -> West Virginia U -> George Mason) or is on the audited list.
AFFIL_RULES = {"thompson_j": {
    "orcid": "0000-0002-9824-8543",
    "insts": {"I57093077", "I12097938", "I162714631"},
    "keep_unaffiliated": {"W2013420665", "W2496223641", "W1750447121", "W264001252", "W4250014721",
                          "W2267885241", "W2015811195", "W2200247079", "W70651515"}},
    # Leah M. Adams: her GMU-era work sits on a second record (ORCID ...6442) merged
    # with a London respiratory physiologist (Charing Cross/Imperial/Griffith, 1975-2019).
    "adams_l": {
    "orcid": ["0000-0002-1627-743X", "0000-0002-2042-6442"],
    "insts": {"I162714631", "I150117356", "I51713134", "I121820613"},
    "keep_unaffiliated": {"W3015362523"},
    "unaffiliated_from": 2010}}


# Individual namesake works (mirrors EXCLUDE_WORKS in _openalex.R).
EXCLUDE_WORKS = {"W2184987074", "W2896126560", "W167837768", "W571322674", "W656031738", "W2058590783"}


def affil_ok(w, rule):
    if not rule:
        return True
    orcids = rule["orcid"] if isinstance(rule["orcid"], list) else [rule["orcid"]]
    mine = [a for a in w.get("authorships") or [] if (a["author"].get("orcid") or "").endswith(tuple(orcids))]
    insts = {(i.get("id") or "").rsplit("/", 1)[-1] for a in mine for i in a.get("institutions") or []}
    if insts:
        return bool(insts & rule["insts"])
    if (w.get("publication_year") or 0) >= rule.get("unaffiliated_from", 9999):
        return True
    return w["id"].rsplit("/", 1)[-1] in rule["keep_unaffiliated"]


# ---------------------------------------------------------------- OpenAlex
def get(path, params):
    key = os.environ.get("OPENALEX_API_KEY")
    if key:
        params = dict(params, api_key=key)
    url = f"{API}/{path}?{urllib.parse.urlencode(params, safe=':|,')}"
    for attempt in range(5):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "pem725.github.io momentum"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except Exception as e:  # network blips, 429s
            if attempt == 4:
                raise RuntimeError(f"OpenAlex failed: {url}: {e}")
            time.sleep(2 ** attempt)


def works_for(filters, select="id,doi,title,type,publication_year,cited_by_count,counts_by_year", rule=None):
    """Union of works matching any of the filters, deduplicated by work id."""
    out = {}
    if rule and "authorships" not in select:
        select += ",authorships"
    # Page (not cursor) paging: since 2026 OpenAlex refuses cursor paging
    # without an API key (HTTP 401). Page paging tops out at 10,000 results,
    # far above any one person's record.
    for f in filters:
        page = 1
        while True:
            j = get("works", {"filter": f, "per-page": 200, "page": page, "select": select})
            for w in j["results"]:
                if (w.get("type") not in SKIP_TYPES and affil_ok(w, rule)
                        and w["id"].rsplit("/", 1)[-1] not in EXCLUDE_WORKS):
                    out[w["id"]] = w
            if page * 200 >= j["meta"]["count"] or not j["results"]:
                break
            page += 1
            time.sleep(0.05)
    return list(out.values())


def filters_for(orcid, ids):
    if orcid:
        return [f"author.orcid:{orcid}"] + ([f"author.id:{'|'.join(ids)}"] if ids else [])
    return [f"author.id:{'|'.join(ids)}"] if ids else []


# ---------------------------------------------------------------- metrics
def year_frac(today):
    start = dt.date(today.year, 1, 1)
    return ((today - start).days + 1) / (dt.date(today.year + 1, 1, 1) - start).days


def metrics(works, today):
    cy, last = today.year, today.year - 1
    frac = year_frac(today)
    V = defaultdict(int)                          # citations received, by year
    fresh = defaultdict(int)                      # ... going to recent papers
    for w in works:
        py = w.get("publication_year") or 0
        for c in w.get("counts_by_year") or []:
            V[c["year"]] += c["cited_by_count"]
            if py >= c["year"] - (FRESH_WINDOW - 1):
                fresh[c["year"]] += c["cited_by_count"]
    years = list(range(2012, cy + 1))
    recent3 = sum(V[y] for y in range(last - 2, last + 1)) / 3
    prior3 = sum(V[y] for y in range(last - 5, last - 2)) / 3
    cites = sorted((w.get("cited_by_count") or 0 for w in works), reverse=True)
    h = sum(1 for i, c in enumerate(cites, 1) if c >= i)
    pubs = defaultdict(int)
    for w in works:
        if w.get("publication_year"):
            pubs[w["publication_year"]] += 1
    return {
        "years": years,
        "velocity": [V[y] for y in years],
        "fresh_share": [round(fresh[y] / V[y], 3) if V[y] else None for y in years],
        "pubs": [pubs[y] for y in years],
        "vel_last": V[last],
        "vel_cur_ytd": V[cy],
        "vel_cur_proj": round(V[cy] / frac) if frac > 0.15 else None,
        "recent3": round(recent3, 1),
        "prior3": round(prior3, 1),
        # Growth off a tiny base is noise (1 -> 3 citations reads as +44%/yr),
        # so it needs a prior baseline of at least MIN_BASE citations a year.
        "growth": round((recent3 / prior3) ** (1 / 3) - 1, 4) if prior3 >= MIN_BASE and recent3 > 0 else None,
        "accel": round((recent3 - prior3) / 3, 1),
        "fresh_last": round(fresh[last] / V[last], 3) if V[last] else None,
        "works": len(works),
        "works_3y": sum(pubs[y] for y in range(cy - 2, cy + 1)),
        "total_cites": sum(cites),
        "h": h,
        "first_year": min(pubs) if pubs else None,
    }


def momentum_label(m):
    """Turn one person's numbers into a short, neutral momentum label.

    m has: growth (compound yearly change in citations/yr, e.g. 0.08 = +8%/yr,
    None when there is no prior baseline), accel (citations/yr gained per year),
    recent3 / prior3 (mean citations per year, last 3 complete years vs the 3
    before), fresh_last (share of last year's citations going to papers from
    the last 5 years), works_3y (papers in the last 3 years), first_year
    (first year with a paper on OpenAlex).

    Return a short label such as "Accelerating", "Steady", "Cooling",
    "Emerging", or None to show numbers only. The pages colour-code whatever
    labels come back, so the wording is yours.

    TODO(Patrick): define the rule. See the note in the session for the
    trade-offs; until then every page shows the numbers without a label.
    """
    return None


# ---------------------------------------------------------------- people
def rank_group(row):
    cat, rank = row.get("category", ""), row.get("rank", "")
    if cat in ("instructor", "research"):
        return "Other"
    if rank == "Assistant":
        return "Assistant"
    if rank == "Professor":
        return "Full"
    if "Associate" in rank:
        return "Associate"
    return "Other"


def clean(v):
    return "" if v in (None, "", "NA") else v.strip()


def load_faculty():
    rows = [r for r in csv.DictReader(open(FACULTY_CSV)) if r["active"] == "TRUE"]
    out = []
    for r in rows:
        ids = [i for i in [clean(r["openalex_id"])] if i] + EXTRA_IDS.get(r["faculty_key"], [])
        orcid = clean(r["orcid"])
        out.append({"key": r["faculty_key"], "name": r["full_name"], "rank": r["rank"],
                    "rank_group": rank_group(r), "is_self": r["is_self"] == "TRUE",
                    # ORCID plus any audited fragment ids when present; the
                    # primary author id only for people without an ORCID.
                    "filters": filters_for(orcid, EXTRA_IDS.get(r["faculty_key"], []) if orcid else ids)})
    return out


def load_students():
    if not STUDENTS_CSV.exists():
        return []
    out = []
    for r in csv.DictReader(open(STUDENTS_CSV)):
        ids = [i for i in clean(r["openalex_ids"]).split(";") if i]
        f = filters_for(clean(r["orcid"]), ids)
        out.append({"key": r["key"], "name": r["name"], "status": r["status"],
                    "year": clean(r["year"]), "institution": clean(r["institution"]),
                    "resolved": bool(f), "filters": f, "note": clean(r.get("note", "")),
                    # Non-empty for students whose main output is invisible to
                    # bibliometrics (e.g. government internal reports); the
                    # students page marks them with an asterisk + this text.
                    "practice": clean(r.get("practice", ""))})
    return out


def top_recent(works, today, n=6):
    """Patrick's newest papers that are already drawing citations."""
    cy = today.year
    rec = [w for w in works if (w.get("publication_year") or 0) >= cy - 5]
    rec.sort(key=lambda w: w.get("cited_by_count") or 0, reverse=True)
    out = []
    for w in rec[:n]:
        cby = {c["year"]: c["cited_by_count"] for c in w.get("counts_by_year") or []}
        out.append({"title": w.get("title"), "year": w.get("publication_year"),
                    "doi": (w.get("doi") or "").replace("https://doi.org/", ""),
                    "cites": w.get("cited_by_count") or 0,
                    "by_year": [cby.get(y, 0) for y in range(w["publication_year"], cy + 1)]})
    return out


ERAS = [("before 2005", 0, 2004), ("2005–09", 2005, 2009), ("2010–14", 2010, 2014),
        ("2015–19", 2015, 2019), ("2020–24", 2020, 2024), ("2025 on", 2025, 9999)]


def era_breakdown(works, today):
    """Citations received each year, split by the era the cited paper came from.
    Shows which periods of the work carry the citations now."""
    years = list(range(2012, today.year + 1))
    out = {label: [0] * len(years) for label, _, _ in ERAS}
    for w in works:
        py = w.get("publication_year") or 0
        label = next(l for l, a, b in ERAS if a <= py <= b)
        for c in w.get("counts_by_year") or []:
            if c["year"] in years:
                out[label][years.index(c["year"])] += c["cited_by_count"]
    return {"years": years, "eras": [{"label": l, "cites": out[l]} for l, _, _ in ERAS]}


# ---------------------------------------------------------------- build
def person(p, today, keep_works=False):
    if not p["filters"]:
        return dict({k: v for k, v in p.items() if k != "filters"}, m=None, label=None), []
    works = works_for(p["filters"], rule=AFFIL_RULES.get(p.get("key")))
    m = metrics(works, today)
    entry = {k: v for k, v in p.items() if k != "filters"}
    entry.update(m=m, label=momentum_label(m))
    return entry, (works if keep_works else [])


def build(today):
    print("self ...", file=sys.stderr)
    me, my_works = person({"key": SELF_KEY, "name": "Patrick E. McKnight",
                           "filters": filters_for(SELF_ORCID, [])}, today, keep_works=True)
    me["top_recent"] = top_recent(my_works, today)
    me["by_era"] = era_breakdown(my_works, today)
    fac = []
    for p in load_faculty():
        print(f"faculty {p['key']} ...", file=sys.stderr)
        fac.append(person(p, today)[0])
    stu = []
    for p in load_students():
        print(f"student {p['key']} ...", file=sys.stderr)
        stu.append(person(p, today)[0])
    return {"generated": today.isoformat(), "year_frac": round(year_frac(today), 3),
            "fresh_window": FRESH_WINDOW, "source": "OpenAlex",
            "self": me, "faculty": fac, "students": stu}


# Attribution guard for the unattended weekly run (the R pipeline has the fuller
# version in impact/dept-benchmark/_guard.R). A person whose citation total moves
# more than GUARD_JUMP (and by GUARD_MIN+) since the last build, or who loses their
# record entirely, keeps LAST WEEK'S numbers and is listed in data["held"]; the
# workflow then fails so GitHub emails a notice. An intended change (a fixed ID)
# is let through with --accept KEY.
GUARD_JUMP, GUARD_MIN = 0.30, 200


def guard(data, accept=()):
    prev_f = DATA / "momentum.json"
    if not prev_f.exists():
        return data
    prev = json.loads(prev_f.read_text())
    old = {p["key"]: p for p in [prev["self"]] + prev["faculty"] + prev["students"]}
    held = []

    def check(p):
        o = old.get(p["key"])
        if not o or not o.get("m") or p["key"] in accept:
            return p
        a, b = o["m"]["total_cites"], (p["m"] or {}).get("total_cites")
        if b is None:
            why = f"record vanished (was {a} cites)"
        elif abs(b - a) >= GUARD_MIN and a and abs(b / a - 1) > GUARD_JUMP:
            why = f"{a} -> {b} cites ({(b / a - 1) * 100:+.0f}%)"
        else:
            return p
        held.append({"key": p["key"], "name": p["name"], "why": why})
        print(f"::warning::guard held {p['name']}: {why}; kept last build's numbers", file=sys.stderr)
        return dict(o, held=why)

    data["self"] = check(data["self"])
    data["faculty"] = [check(p) for p in data["faculty"]]
    data["students"] = [check(p) for p in data["students"]]
    data["held"] = held
    return data


HIST_COLS = ["date", "group", "key", "total_cites", "h", "works", "works_3y", "vel_last",
             "vel_cur_ytd", "vel_cur_proj", "recent3", "prior3", "growth", "accel", "fresh_last", "label"]


def write(data):
    DATA.mkdir(parents=True, exist_ok=True)
    js = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    (DATA / "momentum.json").write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
    (DATA / "momentum.js").write_text(
        "// Generated by impact/momentum/build_momentum.py -- do not edit by hand.\n"
        f"window.MOMENTUM = {js};\n")
    hist = DATA / "momentum_history.csv"
    rows = list(csv.DictReader(open(hist))) if hist.exists() else []
    rows = [r for r in rows if r["date"] != data["generated"]]   # idempotent per day
    for group, people in (("self", [data["self"]]), ("faculty", data["faculty"]), ("student", data["students"])):
        for p in people:
            if p.get("m") and not p.get("held"):
                rows.append({"date": data["generated"], "group": group, "key": p["key"],
                             "label": p.get("label") or "",
                             **{c: p["m"].get(c) for c in HIST_COLS if c in p["m"]}})
    with open(hist, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=HIST_COLS)
        w.writeheader()
        w.writerows(rows)


# ---------------------------------------------------------------- students (one-off)
def norm(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z ]", " ", s).split()


def resolve_students(yaml_path):
    """Find each CV student among Patrick's OpenAlex co-authors (last name +
    first initial). A co-authored paper anchors the identity, which avoids the
    homonym trap of a bare name search. Writes students.csv for human review."""
    txt = Path(yaml_path).expanduser().read_text()
    roster = []
    for section, status in (("students_current", "current"), ("students_graduated", "graduated")):
        block = re.search(rf"^{section}:\n(.*?)(?=^\S)", txt, re.S | re.M).group(1)
        for item in re.split(r"\n  - ", "\n" + block)[1:]:
            g = lambda k: (re.search(rf'{k}: "?([^"\n]*)"?', item) or [None, ""])[1]
            roster.append({"name": g("name"), "status": status, "year": g("year"), "institution": g("institution")})
    works = works_for([f"author.orcid:{SELF_ORCID}"], select="id,authorships")
    coauthors = {}
    for w in works:
        for a in w["authorships"]:
            au = a["author"]
            if au.get("id"):
                coauthors.setdefault(au["id"].rsplit("/", 1)[-1], au.get("display_name") or "")
    old = {r["name"]: r for r in csv.DictReader(open(STUDENTS_CSV))} if STUDENTS_CSV.exists() else {}
    rows = []
    for s in roster:
        toks = norm(s["name"])
        last, first = toks[-1], toks[0][0]
        hits = [i for i, dn in coauthors.items()
                if (t := norm(dn)) and t[-1] == last and t[0][0] == first]
        orcid, notes = "", []
        for i in hits:
            a = get(f"authors/{i}", {"select": "id,orcid,works_count,display_name"})
            if a.get("orcid") and not orcid:
                orcid = a["orcid"].rsplit("/", 1)[-1]
            if (a.get("works_count") or 0) > 250:
                notes.append(f"{i} has {a['works_count']} works: check for a merged homonym")
        key = re.sub(r"[^a-z]", "", last) + "_" + first
        prev = old.get(s["name"], {})
        rows.append({"key": key, "name": s["name"], "status": s["status"], "year": s["year"],
                     "institution": s["institution"],
                     "orcid": prev.get("orcid") or orcid,
                     "openalex_ids": prev.get("openalex_ids") or ";".join(hits),
                     # a hand review beats co-authorship; co-authorship beats a stale UNRESOLVED
                     "resolved_by": (prev.get("resolved_by") if prev.get("resolved_by") not in (None, "", "UNRESOLVED")
                                     else ("co-authorship" if hits else "UNRESOLVED")),
                     "note": prev.get("note") or "; ".join(notes)})
        print(f"{s['name']:24} {len(hits)} id(s) {orcid or ''}", file=sys.stderr)
    STUDENTS_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(STUDENTS_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {STUDENTS_CSV} ({sum(r['resolved_by'] != 'UNRESOLVED' for r in rows)}/{len(rows)} resolved)", file=sys.stderr)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--resolve-students", metavar="PUBLICATIONS_YAML")
    ap.add_argument("--date", help="override today's date (YYYY-MM-DD), for testing")
    ap.add_argument("--accept", action="append", default=[], metavar="KEY",
                    help="let an intended big change for KEY through the guard")
    a = ap.parse_args()
    if a.resolve_students:
        resolve_students(a.resolve_students)
        sys.exit()
    today = dt.date.fromisoformat(a.date) if a.date else dt.date.today()
    data = guard(build(today), accept=set(a.accept))
    write(data)
    me = data["self"]["m"]
    print(f"self: {me['total_cites']} cites, h{me['h']}, last year {me['vel_last']}, "
          f"growth {me['growth']}, fresh {me['fresh_last']}", file=sys.stderr)
