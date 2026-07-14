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
         sch_rank = rank(-sch_c0, ties.method="min"),
         rank_group = case_when(
           category %in% c("instructor", "research") ~ "Other",
           rank == "Assistant"                        ~ "Assistant",
           rank == "Professor"                        ~ "Full",
           grepl("Associate", rank)                   ~ "Associate",
           TRUE                                       ~ "Other"))

n <- nrow(wide)
# concentration on OpenAlex (0-filled)
oc <- sort(wide$oa_c0, decreasing=TRUE); tot <- sum(oc)
g  <- sort(wide$oa_c0); gini <- sum((2*seq_len(n)-n-1)*g)/(n*sum(g))
conc <- list(
  total = tot, gini = round(gini,3),
  top3 = round(100*sum(oc[1:3])/tot), top5 = round(100*sum(oc[1:5])/tot),
  top6 = round(100*sum(oc[1:6])/tot), bottom30 = round(100*sum(tail(oc,30))/tot,1),
  median = median(wide$oa_c0))

# ---- Team view: my lab, counted as one unit (co-authored papers deduplicated) ----
source("_openalex.R")
TEAM_KEYS <- c("mcknight_p", "kashdan_t")   # shared lab — edit if the lab changes
team_orcids <- fac$orcid[match(TEAM_KEYS, fac$faculty_key)]
umap <- list(); sets <- list()
for (orc in team_orcids) {
  if (is.na(orc) || !nzchar(orc)) { sets[[length(sets)+1]] <- character(0); next }
  ids <- character(0)
  for (w in oa_author_works(orcid = orc)) if (!is.na(w$id)) { umap[[w$id]] <- w$cites; ids <- c(ids, w$id) }
  sets[[length(sets)+1]] <- ids
}
team_union  <- sum(unlist(umap)); team_works <- length(umap)
team_simple <- sum(wide$oa_c0[wide$faculty_key %in% TEAM_KEYS])
team_shared <- if (length(sets) >= 2) length(Reduce(intersect, sets)) else 0
team_others <- wide$oa_c0[!wide$faculty_key %in% TEAM_KEYS]
team <- list(
  members = fac$full_name[match(TEAM_KEYS, fac$faculty_key)], keys = TEAM_KEYS,
  union_cites = team_union, simple_cites = team_simple, works = team_works,
  shared_works = team_shared,
  share_union = round(100*team_union/tot, 1), share_simple = round(100*team_simple/tot, 1),
  rank = sum(team_others > team_union) + 1, n_others = length(team_others) + 1)

self <- wide |> filter(is_self)
byyear <- function(key, src) m |> filter(faculty_key==key, source==src, metric_year!="lifetime",
                                     snapshot_date==latest) |>
  transmute(year=as.integer(metric_year), cites=cited_by_count) |> arrange(year) |> filter(!is.na(cites))

# All-faculty by-year trajectories (both sources) for the career-centered overlay (Fig 5B).
# Each faculty is later re-centered client-side on their own first indexed-citation year.
traj_all <- lapply(seq_len(n), function(i) {
  k <- wide$faculty_key[i]
  oa <- byyear(k, "openalex"); sc <- byyear(k, "scholar")
  list(key = k, name = wide$full_name[i], rg = wide$rank_group[i],
       is_self = wide$is_self[i], team = k %in% TEAM_KEYS,
       openalex = oa, scholar = sc)
})
# keep only faculty who have at least one by-year series
traj_all <- Filter(function(t) nrow(t$openalex) > 0 || nrow(t$scholar) > 0, traj_all)

out <- list(
  snapshot_date = latest, n_faculty = n,
  n_openalex = sum(wide$oa_resolved), n_scholar = sum(wide$sch_resolved),
  no_profile = wide$full_name[!wide$oa_resolved & !wide$sch_resolved],
  concentration = conc,
  team = team,
  self = list(
    oa_rank = self$oa_rank, sch_rank = self$sch_rank, n = n,
    oa_pct = round(100*(1-(self$oa_rank-1)/(n-1))),
    sch_pct = round(100*(1-(self$sch_rank-1)/(n-1))),
    oa_cites = self$oa_cites, sch_cites = self$sch_cites,
    oa_h = self$oa_h, sch_h = self$sch_h, fold = self$fold, cv = self$cv,
    share = round(100*self$oa_c0/tot,1)),
  faculty = wide |> arrange(desc(oa_c0)) |>
    transmute(key=faculty_key, name=full_name, disc=discipline, rank, rank_group, category, is_self,
              oa_works, oa_cites, oa_h, oa_i10, sch_cites, sch_h, sch_i10,
              fold, cv, oa_rank, sch_rank, oa_resolved, sch_resolved),
  self_byyear = list(openalex = byyear("mcknight_p","openalex"), scholar = byyear("mcknight_p","scholar")),
  traj_all = traj_all
)
json <- toJSON(out, auto_unbox=TRUE, na="null", pretty=TRUE)
write(json, "web_data.json")
write(paste0("window.BENCH = ", json, ";"), "web_data.js")
cat(sprintf("Wrote web_data (n=%d; OpenAlex %d, Scholar %d; Gini %.2f; you #%d/%d OA, #%d/%d Scholar)\n",
            n, sum(wide$oa_resolved), sum(wide$sch_resolved), gini,
            self$oa_rank, n, self$sch_rank, n))
