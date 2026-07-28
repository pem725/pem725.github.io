#!/usr/bin/env Rscript
# One-off: pull James C. Thompson's OpenAlex metrics (fragmentation-proof, via
# ORCID) and append his long rows to metrics_long.csv under the CURRENT OpenAlex
# snapshot date (2026-07-13), so he joins the OpenAlex side of the comparison.
# He was previously OA-unresolved (Scholar-only). Idempotent for his rows.
setwd(dirname(sub("--file=", "", grep("--file=", commandArgs(FALSE), value = TRUE)[1])))
source("_openalex.R")
suppressMessages({ library(readr); library(dplyr) })

KEY   <- "thompson_j"
ORCID <- "0000-0002-9824-8543"
SNAP  <- "2026-07-13"   # match the existing OpenAlex snapshot

works <- oa_author_works(orcid = ORCID)
stopifnot(length(works) > 0)
cites <- vapply(works, function(w) as.integer(w$cites), integer(1))
years <- vapply(works, function(w) if (is.na(w$year)) NA_integer_ else as.integer(w$year), integer(1))
pubyr <- as.data.frame(table(metric_year = years[!is.na(years)]), stringsAsFactors = FALSE)
cby <- list(); for (w in works) for (y in names(w$cby)) cby[[y]] <- (cby[[y]] %||% 0L) + w$cby[[y]]

rows <- list()
all_years <- union(pubyr$metric_year, names(cby))
for (y in all_years) {
  rows[[length(rows)+1]] <- data.frame(
    faculty_key=KEY, source="openalex", snapshot_date=SNAP, metric_year=as.character(y),
    works_count={ v<-pubyr$Freq[pubyr$metric_year==y]; if(length(v)) v else 0L },
    cited_by_count=cby[[y]] %||% 0L, h_index=NA_integer_, i10_index=NA_integer_,
    two_yr_mean_citedness=NA_real_, stringsAsFactors=FALSE)
}
rows[[length(rows)+1]] <- data.frame(
  faculty_key=KEY, source="openalex", snapshot_date=SNAP, metric_year="lifetime",
  works_count=length(works), cited_by_count=sum(cites),
  h_index=h_index(cites), i10_index=i10_index(cites),
  two_yr_mean_citedness=NA_real_, stringsAsFactors=FALSE)
new <- bind_rows(rows)

cat(sprintf("Thompson OpenAlex: works=%d cites=%d h=%d i10=%d\n",
            length(works), sum(cites), h_index(cites), i10_index(cites)))

old <- read_csv("metrics_long.csv", show_col_types=FALSE, col_types=cols(.default=col_character())) |>
  filter(!(faculty_key==KEY & source=="openalex" & snapshot_date==SNAP))
all <- bind_rows(mutate(old, across(everything(), as.character)),
                 mutate(new, across(everything(), as.character)))
write_csv(all, "metrics_long.csv")
cat(sprintf("Appended %d Thompson OpenAlex rows to snapshot %s\n", nrow(new), SNAP))
