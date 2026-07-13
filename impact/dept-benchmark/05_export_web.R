#!/usr/bin/env Rscript
# 05 — Export the full-department analysis to web_data.(json|js) for the page.
# Peer set = ALL active full-time faculty (professors, instructors, research),
# including research-zeros. Run after 02 (OpenAlex) and 04 (Scholar). Yearly.
#
#   Rscript 05_export_web.R

setwd(dirname(sub("--file=", "", grep("--file=", commandArgs(FALSE), value = TRUE)[1])))
suppressMessages({ library(readr); library(dplyr); library(tidyr); library(jsonlite) })

fac <- read_csv("faculty.csv", show_col_types = FALSE, col_types = cols(.default = col_character()))
m   <- read_csv("metrics_long.csv", show_col_types = FALSE, col_types = cols(.default = col_character())) |>
  mutate(across(c(works_count, cited_by_count, h_index, i10_index), as.numeric))
latest <- max(m$snapshot_date)
life <- m |> filter(metric_year == "lifetime", snapshot_date == latest)

peers <- fac |> filter(active == "TRUE") |>
  select(faculty_key, full_name, discipline, rank, category, is_self)

wide <- peers |>
  left_join(life |> filter(source=="openalex") |>
              select(faculty_key, oa_works=works_count, oa_cites=cited_by_count,
                     oa_h=h_index, oa_i10=i10_index), by="faculty_key") |>
  left_join(life |> filter(source=="scholar") |>
              select(faculty_key, sch_cites=cited_by_count, sch_h=h_index, sch_i10=i10_index),
            by="faculty_key") |>
  mutate(is_self = is_self == "TRUE",
         oa_resolved  = !is.na(oa_cites),
         sch_resolved = !is.na(sch_cites),
         # for ranking/distribution, unresolved counts as 0 (research-zero)
         oa_c0  = ifelse(is.na(oa_cites), 0, oa_cites),
         sch_c0 = ifelse(is.na(sch_cites), 0, sch_cites),
         fold = ifelse(oa_resolved & sch_resolved, round(pmax(sch_cites,oa_cites)/pmin(sch_cites,oa_cites),2), NA),
         cv   = ifelse(oa_resolved & sch_resolved,
                       round(apply(cbind(sch_cites,oa_cites),1,function(r) sd(r)/mean(r)),3), NA),
         oa_rank  = rank(-oa_c0,  ties.method="min"),
         sch_rank = rank(-sch_c0, ties.method="min"))

n <- nrow(wide)
# concentration on OpenAlex (0-filled)
oc <- sort(wide$oa_c0, decreasing=TRUE); tot <- sum(oc)
g  <- sort(wide$oa_c0); gini <- sum((2*seq_len(n)-n-1)*g)/(n*sum(g))
conc <- list(
  total = tot, gini = round(gini,3),
  top3 = round(100*sum(oc[1:3])/tot), top5 = round(100*sum(oc[1:5])/tot),
  top6 = round(100*sum(oc[1:6])/tot), bottom30 = round(100*sum(tail(oc,30))/tot,1),
  median = median(wide$oa_c0))

self <- wide |> filter(is_self)
byyear <- function(src) m |> filter(faculty_key=="mcknight_p", source==src, metric_year!="lifetime",
                                     snapshot_date==latest) |>
  transmute(year=as.integer(metric_year), cites=cited_by_count) |> arrange(year) |> filter(!is.na(cites))

out <- list(
  snapshot_date = latest, n_faculty = n,
  n_openalex = sum(wide$oa_resolved), n_scholar = sum(wide$sch_resolved),
  no_profile = wide$full_name[!wide$oa_resolved & !wide$sch_resolved],
  concentration = conc,
  self = list(
    oa_rank = self$oa_rank, sch_rank = self$sch_rank, n = n,
    oa_pct = round(100*(1-(self$oa_rank-1)/(n-1))),
    sch_pct = round(100*(1-(self$sch_rank-1)/(n-1))),
    oa_cites = self$oa_cites, sch_cites = self$sch_cites,
    oa_h = self$oa_h, sch_h = self$sch_h, fold = self$fold, cv = self$cv,
    share = round(100*self$oa_c0/tot,1)),
  faculty = wide |> arrange(desc(oa_c0)) |>
    transmute(key=faculty_key, name=full_name, disc=discipline, rank, category, is_self,
              oa_works, oa_cites, oa_h, oa_i10, sch_cites, sch_h, sch_i10,
              fold, cv, oa_rank, sch_rank, oa_resolved, sch_resolved),
  self_byyear = list(openalex = byyear("openalex"), scholar = byyear("scholar"))
)
json <- toJSON(out, auto_unbox=TRUE, na="null", pretty=TRUE)
write(json, "web_data.json")
write(paste0("window.BENCH = ", json, ";"), "web_data.js")
cat(sprintf("Wrote web_data (n=%d; OpenAlex %d, Scholar %d; Gini %.2f; you #%d/%d OA, #%d/%d Scholar)\n",
            n, sum(wide$oa_resolved), sum(wide$sch_resolved), gini,
            self$oa_rank, n, self$sch_rank, n))
