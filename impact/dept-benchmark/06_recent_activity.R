#!/usr/bin/env Rscript
# 06 — RECENT ACTIVITY ("who does what when and how"). For each ACTIVE roster
# faculty, pull their 2025-2026 works from OpenAlex via ORCID (else author.id),
# ALL fields and ALL access (OA + closed) — the point is to credit every recent
# contribution, not just open-access or a single field. Writes recent_data.(js|json)
# consumed by the "Recent activity" section of index.html. Re-run yearly (bump YEARS).
#
#   Rscript 06_recent_activity.R
setwd(dirname(sub("--file=", "", grep("--file=", commandArgs(FALSE), value = TRUE)[1])))
source("_openalex.R")
suppressMessages({ library(readr); library(dplyr); library(jsonlite) })

YEARS <- "2025-2026"
SNAP  <- as.character(Sys.Date())

fac <- read_csv("faculty.csv", show_col_types = FALSE, col_types = cols(.default = col_character())) |>
  filter(active == "TRUE", !is.na(openalex_id) & nzchar(openalex_id) & openalex_id != "NA")

# Known OpenAlex author-id FRAGMENTS to fold in for faculty with no ORCID whose
# record OpenAlex has split (their recent works scatter across ids). Works are
# deduped by work id, so listing the primary id too would be harmless.
#   Gerald Matthews (no ORCID): recent papers sit on two secondary ids.
EXTRA_IDS <- list(matthews_g = c("A5134484372", "A5025982678"))

TYPES <- "type:article|review|book|book-chapter|conference-paper|report"
fetch_by <- function(filt) {
  out <- list(); cursor <- "*"
  repeat {
    url <- sprintf("%s/works?filter=%s,publication_year:%s,%s&per-page=200&cursor=%s&select=id,type,publication_year,primary_topic,open_access",
                   OA_BASE, filt, YEARS, TYPES, utils::URLencode(cursor, reserved = TRUE))
    p <- oa_get(url); if (is.null(p) || length(p$results) == 0) break
    out <- c(out, p$results)
    cursor <- p$meta$next_cursor %||% NULL; if (is.null(cursor)) break
  }
  out
}

# Fetch one faculty's recent works (via ORCID when present, else author.id),
# unioning any known fragment ids, deduped by work id.
recent_works <- function(key, orcid, author_id) {
  filts <- if (!is.na(orcid) && nzchar(orcid) && orcid != "NA")
             paste0("author.orcid:", orcid) else paste0("author.id:", author_id)
  filts <- c(filts, paste0("author.id:", EXTRA_IDS[[key]] %||% character(0)))
  byid <- list()
  for (f in filts) for (w in fetch_by(f)) byid[[w$id]] <- w
  unname(byid)
}

facout <- list(); dept_type <- list(); dept_topic <- list(); dept_field <- list()
dept_oa <- 0; dept_closed <- 0; dept_2025 <- 0; dept_2026 <- 0
for (i in seq_len(nrow(fac))) {
  w <- recent_works(fac$faculty_key[i], fac$orcid[i], fac$openalex_id[i])
  ty <- list(); tp <- list(); fld <- list(); oa <- 0; closed <- 0; y25 <- 0; y26 <- 0
  for (x in w) {
    t <- x$type %||% "other"; ty[[t]] <- (ty[[t]] %||% 0L) + 1L; dept_type[[t]] <- (dept_type[[t]] %||% 0L) + 1L
    isoa <- isTRUE(x$open_access$is_oa)
    if (isoa) { oa <- oa + 1; dept_oa <- dept_oa + 1 } else { closed <- closed + 1; dept_closed <- dept_closed + 1 }
    yr <- x$publication_year %||% NA
    if (!is.na(yr) && yr == 2025) { y25 <- y25 + 1; dept_2025 <- dept_2025 + 1 }
    if (!is.na(yr) && yr == 2026) { y26 <- y26 + 1; dept_2026 <- dept_2026 + 1 }
    pt <- x$primary_topic$display_name %||% NA
    if (!is.na(pt)) { tp[[pt]] <- (tp[[pt]] %||% 0L) + 1L; dept_topic[[pt]] <- (dept_topic[[pt]] %||% 0L) + 1L }
    fl <- x$primary_topic$field$display_name %||% NA
    if (!is.na(fl)) { fld[[fl]] <- (fld[[fl]] %||% 0L) + 1L; dept_field[[fl]] <- (dept_field[[fl]] %||% 0L) + 1L }
  }
  toptop <- if (length(tp)) {
    o <- order(unlist(tp), decreasing = TRUE)
    lapply(head(names(tp)[o], 3), function(nm) list(name = nm, n = tp[[nm]]))
  } else list()
  facout[[length(facout) + 1]] <- list(
    key = fac$faculty_key[i], name = fac$full_name[i], rank = fac$rank[i],
    is_self = fac$is_self[i] == "TRUE",
    works = length(w), y2025 = y25, y2026 = y26, oa = oa, closed = closed,
    by_type = ty, top_topics = toptop)
  cat(sprintf("  %-24s %2d works (%d/%d) oa=%d closed=%d\n",
              fac$faculty_key[i], length(w), y25, y26, oa, closed))
  Sys.sleep(0.15)
}

srt <- function(l, k = 8) {
  if (!length(l)) return(list())
  o <- order(unlist(l), decreasing = TRUE)
  lapply(head(names(l)[o], k), function(nm) list(name = nm, n = l[[nm]]))
}
facout <- facout[order(-vapply(facout, function(f) f$works, integer(1)))]
out <- list(
  snapshot_date = SNAP, years = YEARS,
  dept = list(
    n_faculty = length(facout),
    total_works = sum(vapply(facout, function(f) f$works, integer(1))),
    y2025 = dept_2025, y2026 = dept_2026, oa = dept_oa, closed = dept_closed,
    by_type = dept_type, top_topics = srt(dept_topic, 12), by_field = srt(dept_field, 8)),
  faculty = facout)
json <- toJSON(out, auto_unbox = TRUE, na = "null", pretty = TRUE)
write(json, "recent_data.json")
write(paste0("window.RECENT = ", json, ";"), "recent_data.js")
cat(sprintf("\nWrote recent_data (%d active faculty; %d works %s; OA %d / closed %d)\n",
            length(facout), out$dept$total_works, YEARS, dept_oa, dept_closed))
