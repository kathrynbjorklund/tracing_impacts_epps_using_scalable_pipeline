# 8) Krippendorff A 

library(readr) # read and write csv files
library(dplyr) # work with tables and pipe notation
library(tidyr) # reshape tables
library(irr) # calculates KA

INPUT_CSV <- "Krippendorffs.csv" # file with 5 runs side by side
RUN_COLS  <- c("run1","run2","run3","run4","run5") # 5 answer columns
LEVEL     <- "nominal" 
B         <- 2000 # bootstrap reps for 95% CI 

df <- read_csv(INPUT_CSV, show_col_types = FALSE) %>%
  mutate(across(all_of(RUN_COLS), ~na_if(trimws(as.character(.x)), "")))

# Calculate KA
# irr kripp.alpha expects a matrix (coders x items)
# Make rows into columns
ratings <- t(as.matrix(df[, RUN_COLS]))

# Check that LEVEL is nominal or ordinal
method <- match.arg(LEVEL, c("nominal","ordinal"))

# Calculate alpha, $value takes just the number out of the result 
alpha_obj <- irr::kripp.alpha(ratings, method = method)
alpha_hat <- alpha_obj$value

# 95% confidence interval (bootstrap)

set.seed(42)

# Make a new sample by picking domains at random from own list, calculate alpha, repeat 2000 times
# idx = a random pick of domain numbers 
boot_vals <- replicate(B, {
  idx <- sample.int(n = ncol(ratings), size = ncol(ratings), replace = TRUE)
  suppressWarnings(irr::kripp.alpha(ratings[, idx, drop=FALSE], method = method)$value)
})

# Take the values at the 2.5% and 97.5% points
# Lowest 2.5% and highest 2.5% of the 2000 values
ci <- quantile(boot_vals, c(0.025, 0.975), na.rm = TRUE)
cat(sprintf("95%% bootstrap CI: [%.4f, %.4f]  (B=%d)\n", ci[1], ci[2], B))

# Agreement per domain 
agreement_rate <- df %>%
  rowwise() %>%
  mutate(agr = {
    x <- c_across(all_of(RUN_COLS)); x <- x[!is.na(x)]
    if(length(x) <= 1) NA_real_ else max(table(x)) / length(x)
      # count of most common answer / number of answers
  }) %>% ungroup() %>% pull(agr)

# Save a table with results as csv 
summary_out <- tibble(
  alpha_level = method,
  alpha = alpha_hat,
  ci_low = ci[1],
  ci_high = ci[2],
  n_items = ncol(ratings),
  n_coders = nrow(ratings)
)
write_csv(summary_out, "Alpha_Summary.csv")
cat('\nWrote Alpha_Summary.csv\n')
