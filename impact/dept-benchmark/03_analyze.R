#!/usr/bin/env Rscript
# 03 — Analyze the snapshot(s): where I stand vs. the department, and how much
# the story depends on which bibliometric source you believe.
#
#   Rscript 03_analyze.R
#
# Reads faculty.csv + metrics_long.csv. Works with whatever sources are present
# (OpenAlex now; Scholar/WoS join automatically once their rows are added).

setwd(dirname(sub("--file=", "", grep("--file=", commandArgs(FALSE), value = TRUE)[1])))
suppressMessages({ library(readr); library(dplyr); library(tidyr) })

fac <- read_csv("faculty.csv", show_col_types = FALSE, col_types = cols(.default = col_character()))
m   <- read_csv("metrics_long.csv", show_col_types = FALSE, col_types = cols(.default = col_character())) |>
  mutate(across(c(works_count, cited_by_count, h_index, i10_index, two_yr_mean_citedness), as.numeric))

# Peer group: ALL active full-time faculty (professors, instructors, research) —
# including the research-zeros, so the distribution shows how skewed it really is.
peers <- fac |> filter(active == "TRUE") |>
  select(faculty_key, full_name, discipline, is_self, rank)

latest <- max(m$snapshot_date)
life <- m |> filter(metric_year == "lifetime", snapshot_date == latest) |>
  inner_join(peers, by = "faculty_key")

# ---- Career-total ranking (per source) ----
rank_table <- function(df, src) {
  df |> filter(source == src) |>
    arrange(desc(cited_by_count)) |>
    mutate(rank_cites = row_number(),
           pct_cites  = round(100 * (1 - (rank_cites - 1) / (n() - 1)))) |>
    select(rank_cites, full_name, discipline, is_self,
           works_count, cited_by_count, h_index, i10_index, pct_cites)
}

for (src in unique(life$source)) {
  cat(sprintf("\n===== %s — career totals (peer group: tenure-line + self) =====\n", toupper(src)))
  rt <- rank_table(life, src)
  print(as.data.frame(rt |> mutate(me = ifelse(is_self == "TRUE", "  <== YOU", ""))) |>
          (\(x){ x$is_self <- NULL; x })(), row.names = FALSE)
  me <- rt |> filter(is_self == "TRUE")
  if (nrow(me) == 1)
    cat(sprintf("\n  YOU: rank %d/%d on citations (%dth pct) | h=%d | works=%d\n",
                me$rank_cites, nrow(rt), me$pct_cites, me$h_index, me$works_count))
}

# ---- Breadth vs. depth ----
# Depth  = how heavily your best work is cited (h-index captures this).
# Breadth= how much of your corpus clears a citation bar (i10 / works).
# The scatter of these two separates "one big hit" from "broad sustained impact".
cat("\n===== Breadth vs. depth (OpenAlex) =====\n")
bd <- life |> filter(source == "openalex") |>
  transmute(full_name, is_self, depth_h = h_index,
            breadth_i10 = i10_index, works = works_count) |>
  arrange(desc(depth_h))
print(as.data.frame(bd), row.names = FALSE)

# =====================================================================
# ==== YOUR CONTRIBUTION: define the cross-source disagreement stat ====
# =====================================================================
# This is the heart of the reframed project and it's a genuine methods
# choice only you should make. Given one faculty member's citation totals
# from N sources (e.g. c(openalex = 7471, scholar = 16449, wos = 2900)),
# return a single number capturing how much the sources DISAGREE — so we can
# rank faculty by "how much does your headline number depend on which source
# you cite?"  Candidates you might weigh:
#   * range / max            (spread relative to the biggest number)
#   * coefficient of variation (sd / mean)  -- scale-free, classic
#   * max / min ratio         (fold-difference, very intuitive)
#   * IQR / median            (robust to a single outlier source)
# There's no single right answer — that's exactly why it's yours to pick,
# and your choice becomes part of the story you're telling readers.
# Report BOTH: fold-ratio (intuitive) and coefficient of variation (scale-free).
disagreement_fold <- function(x) { x <- x[!is.na(x)]; if (length(x) < 2) NA_real_ else max(x)/min(x) }
disagreement_cv   <- function(x) { x <- x[!is.na(x)]; if (length(x) < 2) NA_real_ else sd(x)/mean(x) }

# Wire-up (runs only once >= 2 sources exist per person):
sources_present <- unique(life$source)
if (length(sources_present) >= 2) {
  cat("\n===== Cross-source disagreement =====\n")
  wide <- life |> select(full_name, is_self, source, cited_by_count) |>
    pivot_wider(names_from = source, values_from = cited_by_count)
  src_cols <- intersect(sources_present, names(wide))
  wide$fold <- round(apply(wide[src_cols], 1, function(r) disagreement_fold(as.numeric(r))), 2)
  wide$cv   <- round(apply(wide[src_cols], 1, function(r) disagreement_cv(as.numeric(r))), 3)
  print(as.data.frame(wide |> arrange(desc(fold))), row.names = FALSE)
} else {
  cat(sprintf("\n(Only source present: %s. Add Scholar/WoS rows to unlock the disagreement analysis.)\n",
              paste(sources_present, collapse = ", ")))
}
