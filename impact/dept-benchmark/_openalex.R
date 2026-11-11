# Shared OpenAlex helpers (sourced by the numbered scripts).
# OpenAlex is free and needs no key; adding your email joins the "polite pool"
# (faster, more reliable). No scraping, no blocking -- reproducible every year.

suppressMessages({
  library(jsonlite)
})

OA_BASE   <- "https://api.openalex.org"
OA_MAILTO <- "pem725@gmail.com"          # polite-pool contact
GMU_ROR   <- "https://ror.org/02jqj7156" # George Mason University

# Polite GET with retry. Returns parsed list, or NULL on repeated failure.
oa_get <- function(url) {
  sep <- if (grepl("\\?", url)) "&" else "?"
  url <- paste0(url, sep, "mailto=", OA_MAILTO)
  for (attempt in 1:4) {
    out <- tryCatch(
      jsonlite::fromJSON(url, simplifyVector = FALSE),
      error = function(e) NULL
    )
    if (!is.null(out)) return(out)
    Sys.sleep(attempt)  # linear backoff
  }
  warning("OpenAlex request failed: ", url)
  NULL
}

# Resolve one faculty row to an OpenAlex author.
# Priority 1: ORCID (exact, gold standard). Priority 2: name + GMU affiliation.
# Returns list(openalex_id, orcid, display_name, works_count, confidence, note).
oa_resolve_author <- function(full_name, orcid = NA) {
  # --- Path 1: ORCID direct ---
  if (!is.na(orcid) && nzchar(orcid)) {
    a <- oa_get(sprintf("%s/authors/https://orcid.org/%s", OA_BASE, orcid))
    if (!is.null(a) && !is.null(a$id)) {
      return(list(
        openalex_id  = sub(".*/", "", a$id),
        orcid        = orcid,
        display_name = a$display_name,
        works_count  = a$works_count %||% NA,
        confidence   = "high (orcid)",
        note         = ""
      ))
    }
  }
  # --- Path 2: name search, constrained to George Mason ---
  q <- utils::URLencode(full_name, reserved = TRUE)
  res <- oa_get(sprintf("%s/authors?search=%s&filter=affiliations.institution.ror:%s",
                        OA_BASE, q, GMU_ROR))
  hits <- res$results %||% list()
  if (length(hits) == 0) {
    return(list(openalex_id = NA, orcid = orcid, display_name = NA,
                works_count = NA, confidence = "none",
                note = "no GMU-affiliated match; resolve by hand"))
  }
  # Pick the record with the most works (OpenAlex fragments authors; the
  # dominant record is almost always the real profile).
  wc  <- vapply(hits, function(h) h$works_count %||% 0L, integer(1))
  top <- hits[[which.max(wc)]]
  conf <- if (length(hits) == 1) "high (single GMU match)" else "review (multiple GMU matches)"
  list(
    openalex_id  = sub(".*/", "", top$id),
    orcid        = if (!is.null(top$orcid)) sub(".*/", "", top$orcid) else orcid,
    display_name = top$display_name,
    works_count  = top$works_count %||% NA,
    confidence   = conf,
    note         = if (length(hits) > 1)
      sprintf("%d GMU matches; picked max-works. Verify.", length(hits)) else ""
  )
}

`%||%` <- function(x, y) if (is.null(x)) y else x

# Fragmentation-proof: fetch ALL of an author's works by ORCID (preferred) or
# author.id, following OpenAlex page pagination. Returns a list of works, each
# a list(year, cites, counts_by_year). Summing over these avoids the undercount
# you get from a single (possibly fragmented) author record's summary_stats.
oa_author_works <- function(orcid = NA, author_id = NA, extra_ids = character(0), key = NA) {
  rule <- if (!is.na(key)) AFFIL_RULES[[key]] else NULL
  filt <- if (!is.na(orcid) && nzchar(orcid) && orcid != "NA") paste0("author.orcid:", orcid)
          else paste0("author.id:", author_id)
  if (length(extra_ids) || !is.null(rule)) {  # union known fragments, dedup by work id
    byid <- list()
    filts <- c(filt, if (length(extra_ids)) paste0("author.id:", extra_ids))
    for (f in filts)
      for (w in oa_author_works_filt(f, rule)) byid[[w$id]] <- w
    return(unname(byid))
  }
  oa_author_works_filt(filt, rule)
}

# Known OpenAlex fragment ids for people whose record is split across several
# author ids that ORCID/primary-id alone don't reach. Unioned by work id, so
# overlap is harmless. Verify any addition (GMU affiliation + on-topic works).
#   Gerald Matthews (no ORCID on roster): 5+ GMU fragments, checked 2026-11-11.
EXTRA_IDS <- list(
  matthews_g = c("A5101575317", "A5101575318", "A5025982678", "A5114001556", "A5134484372")
)

# Affiliation trail rules for people whose ORCID/author record OpenAlex has
# merged with a namesake. A work counts only if THIS person's authorship on it
# lists one of their known institutions, or it is on an audited list of their
# genuinely unaffiliated works. Everything else is the namesake.
#   James C. Thompson (GMU CBN): Swinburne (PhD, Melbourne) -> West Virginia U
#   (postdoc) -> George Mason. OpenAlex merged in James Chilton Thompson (UTMB
#   Galveston surgeon, gastrin/pancreas, 1960s-2000s), UT Austin chemistry and
#   UCLA medicine: ~363 works / ~9,000 cites that are not his. Audited 2026-11-11.
AFFIL_RULES <- list(
  thompson_j = list(
    orcid = "0000-0002-9824-8543",
    insts = c("I57093077",    # Swinburne University of Technology
              "I12097938",    # West Virginia University
              "I162714631"),  # George Mason University
    keep_unaffiliated = c(
      "W2013420665",  # 2007 It's all in the eyes: gaze shifts
      "W2496223641",  # 2012 Configural processing of human movement (chapter)
      "W1750447121",  # 2000 Prefrontal SSVEP in visual vigilance
      "W264001252",   # 2008 Intentions of others / mirror system
      "W4250014721",  # 2013 Neuroimaging primer for I/O psychology
      "W2267885241",  # 2002 ERPs: facial motion vs motion in general
      "W2015811195",  # 2001 Cholinergic modulation of brain electrical activity
      "W2200247079",  # 2003 Representation of digits
      "W70651515"))   # 2000 Acetylcholine and normal variations in intelligence
)

# Non-scholarly record types never counted as works (same set as
# impact/momentum/build_momentum.py). PsycTESTS "dataset" records and book
# index/preface "paratext" entries otherwise pad prolific authors' counts.
SKIP_TYPES <- c("erratum", "paratext", "retraction", "peer-review", "dataset", "preprint")

# Individual works OpenAlex wrongly attributes to a faculty member (namesakes).
# Audited 2026-11-11.
EXCLUDE_WORKS <- c(
  "W2184987074",  # 1951 homing-pigeon navigation -- G.V.T. Matthews, ornithologist (not Gerald)
  "W2896126560")  # 2017 'State-Trait Anxiety Inventory' reference entry -- Spielberger's instrument

# TRUE if a raw OpenAlex work (selected WITH authorships) belongs to the person
# under `rule`. No rule -> always TRUE.
affil_ok <- function(w, rule) {
  if (is.null(rule)) return(TRUE)
  wid <- sub(".*/", "", w$id %||% "")
  mine <- Filter(function(a) endsWith(a$author$orcid %||% "", rule$orcid), w$authorships %||% list())
  inst <- unlist(lapply(mine, function(a) vapply(a$institutions %||% list(),
                                                 function(i) sub(".*/", "", i$id %||% ""), "")))
  if (length(inst)) any(inst %in% rule$insts) else wid %in% rule$keep_unaffiliated
}

oa_author_works_filt <- function(filt, rule = NULL) {
  sel <- paste0("id,type,publication_year,cited_by_count,counts_by_year", if (!is.null(rule)) ",authorships" else "")
  # Page (not cursor) paging: since 2026 OpenAlex rejects cursor paging without
  # an API key (HTTP 401). page= tops out at 10,000 results -- ample per person.
  # A failed request STOPS rather than returning a silently truncated record.
  works <- list(); pg <- 1L
  repeat {
    url <- sprintf("%s/works?filter=%s&per-page=200&page=%d&select=%s", OA_BASE, filt, pg, sel)
    page <- oa_get(url)
    if (is.null(page)) stop("OpenAlex request failed for ", filt, " (page ", pg, ")")
    if (length(page$results) == 0) break
    for (w in page$results) {
      if (!affil_ok(w, rule)) next
      if ((w$type %||% "") %in% SKIP_TYPES || sub(".*/", "", w$id %||% "") %in% EXCLUDE_WORKS) next
      cby <- list()
      for (c in (w$counts_by_year %||% list())) cby[[as.character(c$year)]] <- c$cited_by_count %||% 0L
      works[[length(works) + 1]] <- list(
        id    = if (!is.null(w$id)) sub(".*/", "", w$id) else NA_character_,
        year  = w$publication_year %||% NA,
        cites = w$cited_by_count %||% 0L,
        cby   = cby)
    }
    if (pg * 200 >= (page$meta$count %||% 0)) break
    pg <- pg + 1L
  }
  works
}

# h-index and i10 from a vector of per-work citation counts.
h_index <- function(cites) { s <- sort(cites, decreasing = TRUE); sum(s >= seq_along(s)) }
i10_index <- function(cites) sum(cites >= 10)
