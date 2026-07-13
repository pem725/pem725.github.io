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
# author.id, following OpenAlex cursor pagination. Returns a list of works, each
# a list(year, cites, counts_by_year). Summing over these avoids the undercount
# you get from a single (possibly fragmented) author record's summary_stats.
oa_author_works <- function(orcid = NA, author_id = NA) {
  filt <- if (!is.na(orcid) && nzchar(orcid)) paste0("author.orcid:", orcid)
          else paste0("author.id:", author_id)
  works <- list(); cursor <- "*"
  repeat {
    url <- sprintf("%s/works?filter=%s&per-page=200&cursor=%s&select=id,publication_year,cited_by_count,counts_by_year",
                   OA_BASE, filt, utils::URLencode(cursor, reserved = TRUE))
    page <- oa_get(url)
    if (is.null(page) || length(page$results) == 0) break
    for (w in page$results) {
      cby <- list()
      for (c in (w$counts_by_year %||% list())) cby[[as.character(c$year)]] <- c$cited_by_count %||% 0L
      works[[length(works) + 1]] <- list(
        id    = if (!is.null(w$id)) sub(".*/", "", w$id) else NA_character_,
        year  = w$publication_year %||% NA,
        cites = w$cited_by_count %||% 0L,
        cby   = cby)
    }
    cursor <- page$meta$next_cursor %||% NULL
    if (is.null(cursor)) break
  }
  works
}

# h-index and i10 from a vector of per-work citation counts.
h_index <- function(cites) { s <- sort(cites, decreasing = TRUE); sum(s >= seq_along(s)) }
i10_index <- function(cites) sum(cites >= 10)
