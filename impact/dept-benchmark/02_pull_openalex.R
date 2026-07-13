#!/usr/bin/env Rscript
# 02 — Pull OpenAlex metrics for every resolved faculty member and APPEND a
# dated snapshot to metrics_long.csv. FRAGMENTATION-PROOF: totals/h/i10 and the
# by-year series are computed by summing the author's WORKS (fetched via ORCID
# where available, else author.id) — not from a single author record, which
# OpenAlex often fragments and undercounts. Run yearly. Append-only.
#
#   Rscript 02_pull_openalex.R [YYYY-MM-DD]
#
# Long rows: faculty_key, source, snapshot_date, metric_year, works_count,
# cited_by_count, h_index, i10_index, two_yr_mean_citedness.
#   - one row per publication year: works_count = pubs that year,
#     cited_by_count = citations RECEIVED that year (summed across all works)
#   - one 'lifetime' row: career totals + h/i10 (fragmentation-proof)

setwd(dirname(sub("--file=", "", grep("--file=", commandArgs(FALSE), value = TRUE)[1])))
source("_openalex.R")
suppressMessages({ library(readr); library(dplyr) })

args <- commandArgs(trailingOnly = TRUE)
snapshot_date <- if (length(args) >= 1) args[1] else as.character(Sys.Date())

fac <- read_csv("faculty.csv", show_col_types = FALSE, col_types = cols(.default = col_character())) |>
  filter(!is.na(openalex_id) & nzchar(openalex_id))
if (nrow(fac) == 0) stop("No resolved openalex_id values. Run 01_resolve_openalex_ids.R first.")

rows <- list()
for (i in seq_len(nrow(fac))) {
  key <- fac$faculty_key[i]
  works <- oa_author_works(orcid = fac$orcid[i], author_id = fac$openalex_id[i])
  if (length(works) == 0) { warning("no works for ", key); next }

  cites <- vapply(works, function(w) as.integer(w$cites), integer(1))
  years <- vapply(works, function(w) if (is.na(w$year)) NA_integer_ else as.integer(w$year), integer(1))

  # publications per year
  pubyr <- as.data.frame(table(metric_year = years[!is.na(years)]), stringsAsFactors = FALSE)
  # citations received per year (sum each work's counts_by_year)
  cby <- list()
  for (w in works) for (y in names(w$cby)) cby[[y]] <- (cby[[y]] %||% 0L) + w$cby[[y]]

  all_years <- union(pubyr$metric_year, names(cby))
  for (y in all_years) {
    rows[[length(rows) + 1]] <- data.frame(
      faculty_key = key, source = "openalex", snapshot_date = snapshot_date,
      metric_year = as.character(y),
      works_count = { v <- pubyr$Freq[pubyr$metric_year == y]; if (length(v)) v else 0L },
      cited_by_count = cby[[y]] %||% 0L,
      h_index = NA_integer_, i10_index = NA_integer_,
      two_yr_mean_citedness = NA_real_, stringsAsFactors = FALSE)
  }
  # lifetime row (fragmentation-proof career totals)
  rows[[length(rows) + 1]] <- data.frame(
    faculty_key = key, source = "openalex", snapshot_date = snapshot_date,
    metric_year = "lifetime",
    works_count = length(works), cited_by_count = sum(cites),
    h_index = h_index(cites), i10_index = i10_index(cites),
    two_yr_mean_citedness = NA_real_, stringsAsFactors = FALSE)

  cat(sprintf("  %-22s works=%-4d cites=%-6d h=%-3d i10=%-3d %s\n",
              key, length(works), sum(cites), h_index(cites), i10_index(cites),
              if (!is.na(fac$orcid[i]) && nzchar(fac$orcid[i])) "(orcid)" else "(author.id)"))
  Sys.sleep(0.2)
}

new <- bind_rows(rows)
if (file.exists("metrics_long.csv")) {
  old <- read_csv("metrics_long.csv", show_col_types = FALSE, col_types = cols(.default = col_character())) |>
    filter(!(source == "openalex" & snapshot_date == !!snapshot_date))
  all <- bind_rows(mutate(old, across(everything(), as.character)),
                   mutate(new, across(everything(), as.character)))
} else {
  all <- mutate(new, across(everything(), as.character))
}
write_csv(all, "metrics_long.csv")
cat(sprintf("\nAppended %d rows for %d faculty (snapshot %s) -> metrics_long.csv\n",
            nrow(new), nrow(fac), snapshot_date))
