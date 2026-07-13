#!/usr/bin/env Rscript
# 01 — Resolve each faculty member to an OpenAlex author ID (run once, then
# only for newly added faculty). ORCID first, GMU-affiliated name search second.
# Auto-fills high-confidence matches; flags the rest for you to eyeball.
#
#   Rscript 01_resolve_openalex_ids.R
#
# Safe: backs up faculty.csv before writing, never overwrites an ID you already set.

setwd(dirname(sub("--file=", "", grep("--file=", commandArgs(FALSE), value = TRUE)[1])))
source("_openalex.R")
suppressMessages({ library(readr); library(dplyr) })

fac <- read_csv("faculty.csv", show_col_types = FALSE,
                col_types = cols(.default = col_character()))

review <- list()
for (i in seq_len(nrow(fac))) {
  if (!is.na(fac$openalex_id[i]) && nzchar(fac$openalex_id[i])) next  # already resolved
  orcid <- fac$orcid[i]
  r <- oa_resolve_author(fac$full_name[i], orcid = if (is.na(orcid)) NA else orcid)
  cat(sprintf("%-28s -> %-12s %-26s [%s]\n",
              fac$full_name[i], r$openalex_id %||% "NA",
              r$display_name %||% "", r$confidence))
  # Auto-fill only high-confidence resolutions into the master.
  if (!is.na(r$openalex_id) && grepl("^high", r$confidence)) {
    fac$openalex_id[i] <- r$openalex_id
    if ((is.na(fac$orcid[i]) || !nzchar(fac$orcid[i])) && !is.na(r$orcid))
      fac$orcid[i] <- r$orcid
  }
  review[[length(review) + 1]] <- data.frame(
    faculty_key = fac$faculty_key[i], full_name = fac$full_name[i],
    resolved_id = r$openalex_id %||% NA, oa_name = r$display_name %||% NA,
    works_count = r$works_count %||% NA, confidence = r$confidence,
    note = r$note, stringsAsFactors = FALSE)
  Sys.sleep(0.2)  # be polite
}

# Back up, then write the enriched master + a review sheet for the ambiguous ones.
if (file.exists("faculty.csv")) file.copy("faculty.csv", "faculty.csv.bak", overwrite = TRUE)
write_csv(fac, "faculty.csv")
rev_df <- bind_rows(review)
write_csv(rev_df, "resolve_review.csv")

cat("\n--- Needs your eyes (not auto-filled) ---\n")
flagged <- rev_df[!grepl("^high", rev_df$confidence), , drop = FALSE]
if (nrow(flagged) == 0) cat("None. All resolved with high confidence.\n") else print(flagged)
cat(sprintf("\nWrote faculty.csv (backup: faculty.csv.bak) and resolve_review.csv\n"))
