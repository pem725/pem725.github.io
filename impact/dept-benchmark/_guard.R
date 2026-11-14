# Attribution guard: catches a wrong ORCID / author id / namesake merge BEFORE the
# page is rebuilt. Sourced by 05_export_web.R (which stops on any open flag) and
# runnable on its own:   Rscript _guard.R
#
# Every attribution error found so far (Fischer and Wiener wrong ORCIDs, the
# Thompson and Adams namesake merges) showed at least one of these signs:
#   oa_above_scholar  OpenAlex citations well above Google Scholar's. Scholar
#                     indexes more, so OpenAlex normally runs LOWER.
#   snapshot_jump     OpenAlex citations moved > JUMP vs the previous snapshot,
#                     unless it is a rise that still sits below Scholar (that is
#                     an undercount being repaired, e.g. fragments folded in).
#   career_gap        GAP_YEARS+ with no papers between an early stretch and the
#                     real career: an old namesake (or an earlier career, which
#                     you then accept in guard_ok.csv).
# A flag you have checked and accepted goes in guard_ok.csv
# (faculty_key,check,reason) and stops blocking.

suppressMessages({ library(readr); library(dplyr) })

GUARD <- list(
  above_ratio = 1.05, above_min = 300,   # OA > Scholar*1.05 and by 300+ (Wiener was +8%)
  jump        = 0.30, jump_min  = 200,   # +-30% and 200+ cites between OA snapshots
  gap_years   = 10,   gap_after = 3)     # 10+ silent years, 1+ paper before, 3+ after

run_guard <- function(dir = ".") {
  num <- c("works_count", "cited_by_count")
  m <- read_csv(file.path(dir, "metrics_long.csv"), show_col_types = FALSE,
                col_types = cols(.default = col_character())) |>
    mutate(across(all_of(num), as.numeric))
  name <- with(read_csv(file.path(dir, "faculty.csv"), show_col_types = FALSE,
                        col_types = cols(.default = col_character())), setNames(full_name, faculty_key))
  snaps   <- sort(unique(m$snapshot_date[m$source == "openalex"]), decreasing = TRUE)
  oa      <- m |> filter(source == "openalex", snapshot_date == snaps[1])
  oa_prev <- if (length(snaps) > 1) m |> filter(source == "openalex", snapshot_date == snaps[2]) else oa[0, ]
  sch     <- m |> filter(source == "scholar") |> filter(snapshot_date == max(snapshot_date))
  life <- function(d) d |> filter(metric_year == "lifetime") |> select(faculty_key, cites = cited_by_count)

  flags <- list(); add <- function(k, check, detail)
    flags[[length(flags) + 1]] <<- data.frame(faculty_key = k, name = unname(name[k]) %||% k,
                                              check = check, detail = detail)
  cur <- life(oa); prv <- life(oa_prev); sc <- life(sch)

  for (k in cur$faculty_key) {
    c1 <- cur$cites[cur$faculty_key == k]
    s  <- sc$cites[sc$faculty_key == k]
    if (length(s) && !is.na(s) && c1 > s * GUARD$above_ratio && c1 - s >= GUARD$above_min)
      add(k, "oa_above_scholar", sprintf("OpenAlex %s vs Scholar %s cites", c1, s))
    p <- prv$cites[prv$faculty_key == k]
    if (length(p) && !is.na(p) && p > 0 && abs(c1 - p) >= GUARD$jump_min && abs(c1 / p - 1) > GUARD$jump &&
        !(c1 > p && length(s) && !is.na(s) && c1 <= s))          # a rise still under Scholar = repair
      add(k, "snapshot_jump", sprintf("%s -> %s cites (%+d%%) since %s", p, c1, round(100 * (c1 / p - 1)), snaps[2]))

    yrs <- oa |> filter(faculty_key == k, metric_year != "lifetime", works_count > 0) |>
      transmute(y = as.integer(metric_year), n = works_count) |> arrange(y)
    if (nrow(yrs) > 1) {
      d <- diff(yrs$y); j <- which.max(d)
      if (d[j] >= GUARD$gap_years && sum(yrs$n[(j + 1):nrow(yrs)]) >= GUARD$gap_after)
        add(k, "career_gap", sprintf("no papers %d-%d (%d before, %d after)", yrs$y[j] + 1, yrs$y[j + 1] - 1,
                                     sum(yrs$n[1:j]), sum(yrs$n[(j + 1):nrow(yrs)])))
    }
  }
  out <- if (length(flags)) do.call(rbind, flags) else
    data.frame(faculty_key = character(), name = character(), check = character(), detail = character())
  okf <- file.path(dir, "guard_ok.csv")
  ok <- if (file.exists(okf)) read_csv(okf, show_col_types = FALSE, col_types = cols(.default = col_character())) else NULL
  out$accepted <- if (is.null(ok)) FALSE else paste(out$faculty_key, out$check) %in% paste(ok$faculty_key, ok$check)
  write_csv(out, file.path(dir, "guard_report.csv"))
  out
}

`%||%` <- function(x, y) if (is.null(x) || !length(x) || all(is.na(x))) y else x

print_guard <- function(g) {
  open <- g[!g$accepted, ]
  cat(sprintf("Attribution guard: %d flag(s), %d accepted in guard_ok.csv, %d OPEN\n",
              nrow(g), sum(g$accepted), nrow(open)))
  for (i in seq_len(nrow(g)))
    cat(sprintf("  %s %-22s %-17s %s\n", if (g$accepted[i]) "ok  " else "OPEN",
                g$name[i], g$check[i], g$detail[i]))
  invisible(open)
}

if (sys.nframe() == 0L) {   # run as a script
  setwd(dirname(sub("--file=", "", grep("--file=", commandArgs(FALSE), value = TRUE)[1])))
  open <- print_guard(run_guard())
  quit(status = if (nrow(open)) 1L else 0L)
}
