#!/usr/bin/env Rscript
# 04 — Merge Google Scholar numbers (from scholar_manual.csv) into the pipeline.
# Scholar has no usable API, so this file is filled by browser-harvest or by
# eyeballing each profile once a year. This script:
#   (1) writes each scholar_id back into faculty.csv, and
#   (2) appends source="scholar" lifetime rows into metrics_long.csv.
# Idempotent per (source, snapshot_date). Rows with a blank scholar_id are
# faculty with NO Scholar profile — recorded as a deliberate NA, not a zero.
#
#   Rscript 04_load_scholar.R

setwd(dirname(sub("--file=", "", grep("--file=", commandArgs(FALSE), value = TRUE)[1])))
suppressMessages({ library(readr); library(dplyr) })

sch <- read_csv("scholar_manual.csv", show_col_types = FALSE, col_types = cols(.default = col_character()))
fac <- read_csv("faculty.csv", show_col_types = FALSE, col_types = cols(.default = col_character()))

# (1) write scholar_id back into the master roster
id_map <- sch |> filter(!is.na(scholar_id) & nzchar(scholar_id)) |> select(faculty_key, scholar_id)
fac <- fac |> rows_update(id_map, by = "faculty_key", unmatched = "ignore")
file.copy("faculty.csv", "faculty.csv.bak", overwrite = TRUE)
write_csv(fac, "faculty.csv")

# (2a) build source="scholar" lifetime rows (only where we have a citation total)
life <- sch |>
  filter(!is.na(cited_by_count) & nzchar(cited_by_count)) |>
  transmute(faculty_key, source = "scholar", snapshot_date,
            metric_year = "lifetime",
            works_count = NA_character_, cited_by_count,
            h_index = ifelse(is.na(h_index), NA_character_, h_index),
            i10_index = ifelse(is.na(i10_index), NA_character_, i10_index),
            two_yr_mean_citedness = NA_character_)

# (2b) parse scholar_byyear.txt -> per-year citation-activity rows
byyear_rows <- list()
if (file.exists("scholar_byyear.txt")) {
  lines <- readLines("scholar_byyear.txt")
  lines <- lines[nzchar(lines) & !startsWith(trimws(lines), "#")]
  for (ln in lines) {
    p <- strsplit(ln, "\\|")[[1]]
    key <- trimws(p[1]); sdate <- trimws(p[2])
    for (pair in strsplit(p[3], ",")[[1]]) {
      yv <- strsplit(trimws(pair), ":")[[1]]
      byyear_rows[[length(byyear_rows) + 1]] <- data.frame(
        faculty_key = key, source = "scholar", snapshot_date = sdate,
        metric_year = yv[1], works_count = NA_character_,
        cited_by_count = yv[2], h_index = NA_character_,
        i10_index = NA_character_, two_yr_mean_citedness = NA_character_,
        stringsAsFactors = FALSE)
    }
  }
}
new <- bind_rows(life, bind_rows(byyear_rows))
date_used <- unique(new$snapshot_date)
m <- read_csv("metrics_long.csv", show_col_types = FALSE, col_types = cols(.default = col_character()))
m <- m |> filter(!(source == "scholar" & snapshot_date %in% date_used))
out <- bind_rows(m, new)
write_csv(out, "metrics_long.csv")

cat(sprintf("Loaded %d Scholar rows (%d faculty have no Scholar profile: %s)\n",
            nrow(new),
            sum(is.na(sch$scholar_id) | !nzchar(sch$scholar_id)),
            paste(sch$faculty_key[is.na(sch$scholar_id) | !nzchar(sch$scholar_id)], collapse = ", ")))
