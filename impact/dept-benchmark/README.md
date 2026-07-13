# GMU Psychology — Department Bibliometric Benchmark

**Purpose.** Put every faculty member's research impact on the same footing, measured the
same way, from **multiple bibliometric sources at once**, so that (a) I can see where I
stand relative to the department on breadth *and* depth of impact, and (b) anyone reading
it can see **how much the "impact" number depends on which source you cite.**

This is deliberately a *transparency* project, not a leaderboard. The headline finding is
usually the **disagreement between sources**, not any single ranking.

---

## Why three sources (and why they disagree)

| Source | What it counts | Bias | Automatable? |
|---|---|---|---|
| **Google Scholar** | Everything crawlable: journals, preprints, theses, conference papers, book chapters, self-citations | **Highest** counts, noisiest. Favors applied fields with lots of gray literature. | No public API; scraping gets blocked. Semi-manual / annual. |
| **OpenAlex** | Open catalog built from Crossref + MAG + PubMed; journal + many non-journal works | **Middle.** Comprehensive but cleaner than Scholar. | **Yes** — free REST API, no key, no blocking. This is our reproducible backbone. |
| **Web of Science / Scopus** | Only citations from their *curated* journal list | **Lowest**, most conservative, most "official." Favors lab sciences. | Needs institutional API key/entitlement, or annual manual entry. |

The same person can **rank differently depending on the source.** That flip is the point.

---

## Data model

Two kinds of files, kept separate on purpose:

### 1. `faculty.csv` — the master roster (hand-curated, updated yearly)
One row per person. This is the stable key that everything joins on. IDs are filled in
once (per source) and reused every year. Columns:

- `faculty_key` — stable slug, e.g. `mcknight_p` (never changes)
- `last_name`, `first_name`, `full_name`
- `rank` — Professor / Associate / Assistant / Term / Adjunct / Emeritus / Research
- `category` — tenure_line / term / adjunct / emeritus / research / self
- `discipline` — Clinical / Applied Developmental / CBN / Human Factors / I-O
- `is_tenure_line` — TRUE/FALSE (the default fair peer group)
- `is_self` — TRUE for me, so analysis can locate my position
- `orcid` — used to resolve OpenAlex/Scopus reliably
- `openalex_id` — e.g. A5012345678 (resolved once, then reused)
- `scholar_id` — Google Scholar user= id
- `scopus_id`, `wos_id` — filled if/when we get entitlement
- `active`, `notes`

### 2. `metrics_long.csv` — the measurements (append-only, one snapshot per year)
**Tidy/long format** so year-over-year deltas and cross-source comparison are trivial.
One row per (person × source × year × metric). Columns:

- `faculty_key`, `source` (openalex|scholar|wos), `snapshot_date`
- `metric_year` — the publication/citation year (or `lifetime` for career totals)
- `works_count` — publications attributed to that year
- `cited_by_count` — citations received (see note below)
- `h_index`, `i10_index`, `two_yr_mean_citedness` — lifetime summary stats (repeat on the `lifetime` row only)

> **Delta = this year's snapshot − last year's snapshot**, per person per source. Because
> every snapshot is dated and append-only, deltas are just a `group_by(faculty_key, source)`
> lag. Never overwrite an old snapshot — that's how we get the year-to-year trend.

---

## Yearly workflow

1. **Refresh the roster** — re-pull https://psychology.gmu.edu/people, add/remove faculty,
   keep `faculty_key`s stable. New people get IDs resolved (step 2).
2. **Resolve IDs** for anyone missing an `openalex_id` (`01_resolve_openalex_ids.R`).
3. **Pull OpenAlex** for everyone (`02_pull_openalex.R`) → appends to `metrics_long.csv`.
4. **Add Scholar / WoS numbers** (annual manual entry or entitlement pull) → same file.
5. **Analyze** (`03_analyze.R`) → cross-source variability, department ranking, my
   percentile, breadth-vs-depth, deltas.
6. **Publish** into the impact page.

---

## Status / open items

- [x] Roster seeded from the live directory (26 tenure-line + self). **Still verify my own
      GMU status** — I did not appear in the tenure-line directory fetch.
- [x] OpenAlex IDs resolved (ORCID-first) and **fragmentation-corrected** (totals summed
      from works via ORCID, not from a single author record).
- [x] Google Scholar harvested via browser: IDs + totals + h/i10 + citations-by-year for
      22 faculty (5 have no profile). Legacy `../GMUurls.txt` superseded.
- [x] Disagreement metric = **fold-ratio + CV** (both reported).
- [x] Web page `index.html` built (self-contained, theme-aware) + linked from `impact/index.html`.
- [ ] Add Web of Science / Scopus as a third source (deferred — needs GMU entitlement).
- [ ] Scholar deltas: re-run next July for year-over-year change.

## Pipeline order
`01_resolve_openalex_ids.R` → `02_pull_openalex.R` → `04_load_scholar.R`
(scholar_manual.csv + scholar_byyear.txt) → `03_analyze.R` (console) → `05_export_web.R`
(web_data.js → index.html). Data of record: `faculty.csv` + `metrics_long.csv` (append-only).

## Provenance
Legacy scripts (`../GMUfacultyScholarImpact.py`, `../GFacImpactver_0.0.1.py`,
`../GFIv.0.0.2.py`, `../GMUurls.txt`) used the `scholarly` library and produced an empty
CSV (Google Scholar blocked them). This rebuild replaces that approach with OpenAlex as the
reproducible core and treats Scholar/WoS as comparison layers.
