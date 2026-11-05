#!/usr/bin/env python3
"""Site watch: a daily check on pem725.github.io, run against the AI box.

Built 2026-11-02 on Patrick's instruction to "fold in my AI box ... constantly
having something surveil the status of my page." Same shape as the Sports Page
morning desk and the house digest: it runs from the workstation's crontab,
code decides every finding, and the box's gpt-oss only words a short summary
on top. The findings list is always printed under it, so the wording cannot
hide one.

It never commits and never pushes. The weekly GitHub Action
(.github/workflows/refresh-momentum.yml) is the only thing that ships data.

Checks:
  LINKS     every link on the homepage, courses, impact, students and
            department pages; reports links that break (and new breaks).
  DATA      momentum.js age (the weekly Action failing shows up here), the CV's
            metrics date, the department snapshot age.
  ORCID     the CV repo's sync_orcid.py dry run: works on ORCID missing from
            the CV (the CV's Action adds journal articles itself; this catches
            preprints, chapters and anything it skipped).
  IN PRESS  CV entries marked "in press" that Crossref now shows as published.
  TODD      toddkashdan.com: up, and papers with McKnight as an author that are
            not in the CV. (Todd keeps his own pages; staleness there isn't ours.)
  STUDENTS  CV students missing from students.csv, and unlinked students who
            now appear as McKnight co-authors (re-run --resolve-students).
  SPORTS    The Sports Page feed: days since the last issue.
  MOMENTUM  week-over-week change in Patrick's and the students' numbers.

Usage:
  python3 impact/watch/site_watch.py              # full run, report + notice
  python3 impact/watch/site_watch.py --no-llm     # skip the box summary
  python3 impact/watch/site_watch.py --no-links   # skip the slow link check
Crontab (workstation):
  10 6 * * * cd ~/GitTemp/pem725.github.io && /usr/bin/python3 impact/watch/site_watch.py >> ~/.pem725-site-watch.log 2>&1
Report: ~/.local/share/pem725-site/watch-report.md
"""
import argparse, csv, datetime as dt, html, json, os, re, subprocess, sys
import urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SITE = Path(__file__).resolve().parents[2]
GIT = Path.home() / "GitTemp"
CV = GIT / "cv"
TODD = GIT / "toddkashdan-site"
STATE = Path.home() / ".local/share/pem725-site"
REPORT = STATE / "watch-report.md"
LAST = STATE / "watch-last.json"
OLLAMA = os.environ.get("OLLAMA_HOST", "192.168.0.65:11434")
MODEL = os.environ.get("WATCH_MODEL", "gpt-oss:20b")
PAGES = ["index.html", "courses/index.html", "impact/index.html",
         "impact/students/index.html", "impact/dept-benchmark/index.html"]
SPORTS_FEED = "https://pem725.github.io/the-sports-page/feed.xml"
UA = {"User-Agent": "Mozilla/5.0 (pem725.github.io site watch)"}
TODAY = dt.date.today()


def alert(findings, area, text):
    findings.append({"level": "ALERT", "area": area, "text": text})


def note(findings, area, text):
    findings.append({"level": "note", "area": area, "text": text})


def fetch(url, timeout=20, method="GET"):
    req = urllib.request.Request(url, headers=UA, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read() if method == "GET" else b""


def ff_pull(repo):
    if (repo / ".git").exists():
        p = subprocess.run(["git", "pull", "--ff-only", "-q"], cwd=repo, capture_output=True, text=True, timeout=120)
        return p.returncode == 0
    return False


def norm(s):
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


# ------------------------------------------------------------------ LINKS
def check_links(findings, last):
    links = {}
    for page in PAGES:
        p = SITE / page
        if not p.exists():
            alert(findings, "links", f"page missing: {page}")
            continue
        for href in re.findall(r'href="([^"]+)"', p.read_text(errors="ignore")):
            if "'" in href or "+" in href or href.startswith(("#", "mailto:", "javascript:")):
                continue  # built by script at load time, or in-page
            links.setdefault(href, set()).add(page)

    def probe(href):
        pages = sorted(links[href])
        if href.startswith("http"):
            if "fonts.googleapis" in href:
                return None
            # HEAD first (cheap); any HEAD failure is re-tried as a GET, because some
            # publishers (Thieme) answer 404 to HEAD and 200 to GET.
            try:
                if fetch(href, timeout=15, method="HEAD")[0] < 400:
                    return None
            except Exception:
                pass
            try:
                code, _ = fetch(href, timeout=20)
                return None if code < 400 else (href, code, pages)
            except urllib.error.HTTPError as e:
                # 403/429/999 from bot-shy sites (Scholar, LinkedIn, journals) is not a dead link
                return None if e.code in (403, 429, 999) else (href, e.code, pages)
            except Exception as e:
                return (href, type(e).__name__, pages)
        target = ((SITE / pages[0]).parent / urllib.parse.unquote(href.split("#")[0].split("?")[0])).resolve()
        if target.is_dir():
            target = target / "index.html"
        if target.is_relative_to(SITE / "cv"):
            return None  # /cv/ is served by the separate pem725/cv repo, not this one
        return None if target.exists() else (href, "missing file", pages)

    with ThreadPoolExecutor(12) as ex:
        bad = [r for r in ex.map(probe, sorted(links)) if r]
    prev = set(last.get("bad_links", []))
    for href, why, pages in bad:
        (alert if href not in prev else note)(findings, "links",
            f"{'NEW ' if href not in prev else ''}broken link ({why}) on {', '.join(pages)}: {href}")
    if not bad:
        note(findings, "links", f"all {len(links)} links answer")
    return [b[0] for b in bad]


# ------------------------------------------------------------------ DATA
def check_data(findings):
    mj = SITE / "impact/data/momentum.json"
    if not mj.exists():
        alert(findings, "data", "impact/data/momentum.json missing")
        return None
    m = json.loads(mj.read_text())
    age = (TODAY - dt.date.fromisoformat(m["generated"])).days
    (alert if age > 9 else note)(findings, "data",
        f"momentum data is {age} day(s) old" + (" (the weekly refresh Action may be failing)" if age > 9 else ""))
    y = (CV / "publications.yaml").read_text() if (CV / "publications.yaml").exists() else ""
    mu = re.search(r'last_updated: "(\d{4}-\d\d-\d\d)"', y)
    if mu:
        age = (TODAY - dt.date.fromisoformat(mu.group(1))).days
        if age > 120:
            note(findings, "data", f"CV Google Scholar metrics last updated {mu.group(1)} ({age} days); refresh at the next review")
    wd = SITE / "impact/dept-benchmark/web_data.json"
    if wd.exists():
        snap = json.loads(wd.read_text()).get("snapshot_date")
        if snap and (TODAY - dt.date.fromisoformat(snap)).days > 365:
            alert(findings, "data", f"department benchmark snapshot {snap} is over a year old: re-run 02->05 (+ Scholar harvest)")
    return m


# ------------------------------------------------------------------ ORCID vs CV
def check_orcid(findings, last):
    tool = CV / "tools/sync_orcid.py"
    if not tool.exists():
        note(findings, "orcid", "CV repo not found; ORCID check skipped")
        return []
    out = subprocess.run([sys.executable, str(tool)], cwd=CV, capture_output=True, text=True, timeout=300).stdout
    items = re.findall(r"^\s+\[(\d*)\] (?:\(([\w-]+)\) )?(.+?)\s+doi=(\S+)", out, re.M)
    prev = set(last.get("orcid_missing", []))
    keys = []
    for yr, typ, title, doi in items:
        keys.append(doi)
        if doi not in prev:
            alert(findings, "orcid", f"NEW on ORCID, not in CV: [{yr}] ({typ or 'journal-article'}) {title.strip()} doi={doi}")
    if items and not [k for k in keys if k not in prev]:
        note(findings, "orcid", f"{len(items)} ORCID item(s) still not in the CV (known; preprints/conference papers)")
    return keys


# ------------------------------------------------------------------ Crossref helpers
def crossref_find(title, must_author="McKnight"):
    q = urllib.parse.urlencode({"query.bibliographic": title, "rows": 3,
                                "select": "DOI,title,author,published,type,container-title"})
    try:
        items = json.loads(fetch(f"https://api.crossref.org/works?{q}", timeout=30)[1])["message"]["items"]
    except Exception:
        return None
    for it in items:
        t = norm((it.get("title") or [""])[0])
        if t and (t.startswith(norm(title)[:50]) or norm(title).startswith(t[:50])) and \
                any(a.get("family", "").lower() == must_author.lower() for a in it.get("author", [])) and \
                it.get("type") not in ("posted-content",):
            return it
    return None


def check_in_press(findings):
    y = (CV / "publications.yaml").read_text() if (CV / "publications.yaml").exists() else ""
    for block in re.split(r"\n    - ", y):
        if re.search(r'status: "in press"', block, re.I):
            t = re.search(r'title: "([^"]+)"', block)
            if t and (hit := crossref_find(t.group(1))):
                alert(findings, "in press", f"CV lists as in press but Crossref shows published: "
                      f"'{t.group(1)[:70]}' -> {(hit.get('container-title') or [''])[0]}, doi {hit['DOI']}")


# ------------------------------------------------------------------ Todd's site
def check_todd(findings):
    try:
        code, _ = fetch("https://toddkashdan.com/", timeout=20)
        if code >= 400:
            alert(findings, "todd", f"toddkashdan.com answered {code}")
    except Exception as e:
        alert(findings, "todd", f"toddkashdan.com unreachable: {type(e).__name__}")
    lab = TODD / "site/lab.html"
    if not lab.exists():
        note(findings, "todd", "toddkashdan-site clone not found; content check skipped")
        return
    s = lab.read_text(errors="ignore")
    cv = (CV / "publications.yaml").read_text().lower() if (CV / "publications.yaml").exists() else ""
    for href, inner, after in re.findall(r'<li><a href="([^"]+)"[^>]*>(.*?)</a>([^<]{0,40})', s, re.S):
        # Todd maintains his own site (Patrick, 2026-11-05): only report what affects
        # Patrick's CV, never staleness on Todd's pages.
        title = html.unescape(re.sub("<[^>]+>", "", inner)).strip()
        m = re.search(r"(10\.\d{4,}/[^\s\"?#]+)", href)
        if not m:
            continue
        doi = m.group(1).lower()
        if doi in cv:
            continue
        try:
            au = json.loads(fetch(f"https://api.crossref.org/works/{doi}", timeout=30)[1])["message"].get("author", [])
        except Exception:
            continue
        if any(a.get("family", "").lower() == "mcknight" for a in au):
            alert(findings, "todd", f"McKnight paper on Todd's site but not in the CV: '{title[:60]}' doi {doi}")


# ------------------------------------------------------------------ STUDENTS
def check_students(findings, last):
    """New names on the CV roster, and unlinked students who have just co-authored
    with Patrick. Reports only; build_momentum.py --resolve-students does the linking."""
    flags = []
    path = SITE / "impact/students/students.csv"
    rows = list(csv.DictReader(open(path))) if path.exists() else []
    known = {norm(r["name"]) for r in rows}
    yml = (CV / "publications.yaml").read_text() if (CV / "publications.yaml").exists() else ""
    for sec in ("students_current", "students_graduated"):
        m = re.search(rf"^{sec}:\n(.*?)(?=^\S)", yml, re.S | re.M)
        for name in re.findall(r'- name: "?([^"\n]+)"?', m.group(1) if m else ""):
            if norm(name) not in known:
                flags.append(f"{name} is on the CV but not on the students page")
    pending = [r for r in rows if r["resolved_by"] == "UNRESOLVED"]
    if pending:
        since = (TODAY - dt.timedelta(days=730)).isoformat()
        url = ("https://api.openalex.org/works?per_page=200&select=title,authorships&filter="
               + urllib.parse.quote(f"author.orcid:0000-0002-9067-9066,from_publication_date:{since}"))
        try:
            works = json.loads(fetch(url, timeout=40)[1])["results"]
        except Exception as e:
            note(findings, "students", f"OpenAlex unreachable for the co-author check: {type(e).__name__}")
            works = []
        for r in pending:
            parts = norm(r["name"]).split()
            for w in works:
                if any((t := norm(a["author"].get("display_name")).split()) and t[-1] == parts[-1]
                       and t[0][0] == parts[0][0] for a in w["authorships"]):
                    flags.append(f"{r['name']} co-authored '{(w['title'] or '')[:60]}' with you; "
                                 "run build_momentum.py --resolve-students ~/GitTemp/cv/publications.yaml")
                    break
    seen = set(last.get("student_flags", []))
    for f in flags:
        (note if f in seen else alert)(findings, "students", f)
    return flags


# ------------------------------------------------------------------ Sports Page
def check_sports(findings):
    try:
        xml = fetch(SPORTS_FEED, timeout=20)[1].decode("utf-8", "ignore")
    except Exception as e:
        alert(findings, "sports", f"Sports Page feed unreachable: {type(e).__name__}")
        return
    dates = re.findall(r"<pubDate>([^<]+)</pubDate>", xml)
    if not dates:
        note(findings, "sports", "Sports Page feed has no dates")
        return
    from email.utils import parsedate_to_datetime
    newest = max(parsedate_to_datetime(d).date() for d in dates)
    age = (TODAY - newest).days
    (alert if age > 2 else note)(findings, "sports", f"Sports Page last issue {newest} ({age} day(s) ago)")


# ------------------------------------------------------------------ Momentum movers
def check_momentum(findings):
    hist = SITE / "impact/data/momentum_history.csv"
    if not hist.exists():
        return
    rows = list(csv.DictReader(open(hist)))
    dates = sorted({r["date"] for r in rows})
    if len(dates) < 2:
        note(findings, "momentum", "one snapshot so far; week-over-week changes start after the next refresh")
        return
    now = {(r["group"], r["key"]): r for r in rows if r["date"] == dates[-1]}
    was = {(r["group"], r["key"]): r for r in rows if r["date"] == dates[-2]}
    f = lambda r, k: float(r[k]) if r.get(k) not in (None, "") else None
    for (g, k), r in now.items():
        if g not in ("self", "student") or (g, k) not in was:
            continue
        a, b = f(was[(g, k)], "total_cites"), f(r, "total_cites")
        if a is not None and b is not None and b - a >= (25 if g == "self" else 10):
            note(findings, "momentum", f"{k}: +{int(b - a)} citations since {dates[-2]} (now {int(b)})")
        if was[(g, k)].get("label") != r.get("label") and r.get("label"):
            alert(findings, "momentum", f"{k}: momentum label changed {was[(g, k)].get('label') or '-'} -> {r['label']}")
        if f(r, "works") and f(was[(g, k)], "works") and f(r, "works") > f(was[(g, k)], "works"):
            note(findings, "momentum", f"{k}: {int(f(r, 'works') - f(was[(g, k)], 'works'))} new work(s) on OpenAlex")


# ------------------------------------------------------------------ LLM summary
def summarize(findings):
    facts = "\n".join(f"- [{x['level']}] {x['area']}: {x['text']}" for x in findings)
    prompt = ("You write a 3-5 sentence morning note for Patrick about his academic website. Lead with anything "
              "marked ALERT and say what to do about it. Plain words, no lists, no headings, no greetings. "
              "Use only these findings; do not invent any.\n\n" + facts)
    body = json.dumps({"model": MODEL, "stream": False, "messages": [{"role": "user", "content": prompt}],
                       "options": {"num_ctx": 8192}}).encode()
    try:
        req = urllib.request.Request(f"http://{OLLAMA}/api/chat", data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=300) as r:
            return json.load(r)["message"]["content"].strip()
    except Exception as e:
        return f"(AI box summary unavailable: {type(e).__name__}; findings below are complete.)"


def notify(msg):
    try:
        subprocess.run(["notify-send", "pem725.github.io watch", msg], timeout=10)
    except (OSError, subprocess.SubprocessError):
        pass


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--no-links", action="store_true")
    a = ap.parse_args()
    STATE.mkdir(parents=True, exist_ok=True)
    last = json.loads(LAST.read_text()) if LAST.exists() else {}
    findings = []
    for repo in (SITE, CV, TODD):
        if repo.exists() and not ff_pull(repo):
            note(findings, "git", f"could not fast-forward {repo.name}; checked the clone as it stands")
    state = {"date": TODAY.isoformat()}
    state["bad_links"] = last.get("bad_links", []) if a.no_links else check_links(findings, last)
    check_data(findings)
    state["orcid_missing"] = check_orcid(findings, last)
    check_in_press(findings)
    check_todd(findings)
    state["student_flags"] = check_students(findings, last)
    check_sports(findings)
    check_momentum(findings)
    findings.sort(key=lambda x: x["level"] != "ALERT")
    n_alert = sum(x["level"] == "ALERT" for x in findings)
    summary = "(summary skipped)" if a.no_llm else summarize(findings)
    out = [f"# Site watch — {dt.datetime.now():%A %Y-%m-%d %H:%M}", "",
           f"**{n_alert} alert(s)**" if n_alert else "No alerts.", "", summary, "", "## Findings", ""]
    out += [f"- **{x['level']}** · {x['area']} · {x['text']}" for x in findings]
    REPORT.write_text("\n".join(out) + "\n")
    LAST.write_text(json.dumps(state, indent=1))
    print("\n".join(out))
    if n_alert:
        notify(f"{n_alert} alert(s). Report: {REPORT}")


if __name__ == "__main__":
    main()
