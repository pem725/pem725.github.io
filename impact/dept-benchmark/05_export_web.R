#!/usr/bin/env Rscript
# 05 — Export the analysis to web_data.json for the benchmark web page.
# Run after 02 (OpenAlex) and 04 (Scholar). Re-run yearly to refresh the page.
#
#   Rscript 05_export_web.R

setwd(dirname(sub("--file=", "", grep("--file=", commandArgs(FALSE), value = TRUE)[1])))
suppressMessages({ library(readr); library(dplyr); library(tidyr); library(jsonlite) })

fac <- read_csv("faculty.csv", show_col_types = FALSE, col_types = cols(.default = col_character()))
m   <- read_csv("metrics_long.csv", show_col_types = FALSE, col_types = cols(.default = col_character())) |>
  mutate(across(c(works_count, cited_by_count, h_index, i10_index), as.numeric))
latest <- max(m$snapshot_date)

peers <- fac |> filter(is_tenure_line == "TRUE" | is_self == "TRUE")
life  <- m |> filter(metric_year == "lifetime", snapshot_date == latest)

wide <- peers |> select(faculty_key, full_name, discipline, is_self) |>
  left_join(life |> filter(source=="openalex") |>
              select(faculty_key, oa_works=works_count, oa_cites=cited_by_count,
                     oa_h=h_index, oa_i10=i10_index), by="faculty_key") |>
  left_join(life |> filter(source=="scholar") |>
              select(faculty_key, sch_cites=cited_by_count, sch_h=h_index, sch_i10=i10_index),
            by="faculty_key") |>
  mutate(is_self = is_self == "TRUE",
         fold = ifelse(!is.na(sch_cites) & !is.na(oa_cites), round(pmax(sch_cites,oa_cites)/pmin(sch_cites,oa_cites),2), NA),
         cv   = ifelse(!is.na(sch_cites) & !is.na(oa_cites),
                       round(apply(cbind(sch_cites,oa_cites),1,function(r) sd(r)/mean(r)),3), NA),
         oa_rank  = ifelse(is.na(oa_cites),  NA, rank(-oa_cites,  ties.method="min")),
         sch_rank = ifelse(is.na(sch_cites), NA, rank(-sch_cites, ties.method="min")))

# McKnight by-year, both sources
byyear <- function(src) m |> filter(faculty_key=="mcknight_p", source==src, metric_year!="lifetime",
                                     snapshot_date==latest) |>
  transmute(year=as.integer(metric_year), cites=cited_by_count) |> arrange(year) |> filter(!is.na(cites))

n_oa  <- sum(!is.na(wide$oa_cites)); n_sch <- sum(!is.na(wide$sch_cites))
self  <- wide |> filter(is_self)
out <- list(
  snapshot_date = latest,
  n_faculty = nrow(wide), n_openalex = n_oa, n_scholar = n_sch,
  no_scholar = wide$full_name[is.na(wide$sch_cites)],
  self = list(
    oa_rank = self$oa_rank, sch_rank = self$sch_rank,
    oa_pct = round(100*(1-(self$oa_rank-1)/(n_oa-1))),
    sch_pct = round(100*(1-(self$sch_rank-1)/(n_sch-1))),
    oa_cites = self$oa_cites, sch_cites = self$sch_cites,
    oa_h = self$oa_h, sch_h = self$sch_h, fold = self$fold, cv = self$cv),
  faculty = wide |> arrange(desc(oa_cites)) |>
    select(key=faculty_key, name=full_name, disc=discipline, is_self,
           oa_works, oa_cites, oa_h, oa_i10, sch_cites, sch_h, sch_i10,
           fold, cv, oa_rank, sch_rank),
  self_byyear = list(openalex = byyear("openalex"), scholar = byyear("scholar"))
)
json <- toJSON(out, auto_unbox=TRUE, na="null", pretty=TRUE)
write(json, "web_data.json")
# Also emit as a JS global so index.html is self-contained (works via file:// and
# GitHub Pages alike — no fetch/CORS). Regenerate yearly; never edit by hand.
write(paste0("window.BENCH = ", json, ";"), "web_data.js")
cat(sprintf("Wrote web_data.json + web_data.js (%d faculty; OpenAlex %d, Scholar %d; snapshot %s)\n",
            nrow(wide), n_oa, n_sch, latest))
