# 7) Performance Metrics (Recall, Precision, F1)

# Compare "News outlet (Yes/No)" ground truth answers with vs 5 LLM run answers

  library(readr) # read and write CSVs
  library(dplyr) # work with tables
  library(stringr) # clean text (trim spaces, make lowercase)
  library(yardstick)  # calculates precision, recall, f1

# Load ground truth file 
gold_file <- "ground_truth.csv"  

# Load the model answer files
pred_files <- c(          
  "Domains_Sampled_100.csv",
  "Domains_Sampled_100_2.csv",
  "Domains_Sampled_100_3.csv",
  "Domains_Sampled_100_4.csv",
  "Domains_Sampled_100_5.csv"
)
target_col <- "News outlet (Yes/No)" # column to evaluate
positive_label <- "Yes" # the answer 'looking for'
out_file <- "Per_Run_Metrics.csv" 

# Remove spaces at the start and end of column names
norm_names <- function(x) trimws(x)

# Make sure domains look the same in every file 
norm_domain <- function(x) {
  x %>% as.character() %>% str_trim() %>% str_to_lower() %>% str_replace("^\ufeff", "")
}
has_domain <- function(df) "Domain" %in% names(df)

# Read one csv file, clean domains 
read_frame <- function(path, target) {
  df <- read_csv(path, show_col_types = FALSE)
  names(df) <- norm_names(names(df))
  if (!(target %in% names(df))) {
    stop(sprintf("File '%s' is missing the '%s' column.", path, target))
  }
  # Stop if there is no Domain column (needed to match the files up)
  if (!has_domain(df)) {
    stop(sprintf("File '%s' is missing the 'Domain' column.", path))
  }
  df$Domain <- norm_domain(df$Domain)
  df
}

# Calculate the three scores
# Truth = the correct answers from the ground truth set
# Estimate = the model's answers
# Positive = Yes answer
eval_binary <- function(truth, estimate, positive = "Yes") { 
  
  # Yardstick needs the answers as factors a.k.a. a fixed set of categories and needs to know which category is desired
  # We list the categories with 'Yes' first, followed by 'No'
  lvls <- c(positive, setdiff(unique(c(truth, estimate)), positive))

  # Put the correct answers and the model's answers side by side in a table 
  tib <- tibble(
    truth = factor(truth, levels = lvls),
    estimate = factor(estimate, levels = lvls)
  )

  # Calculate the three scores
  tibble(
    precision = precision(tib, truth, estimate, event_level = "first")$.estimate,
    recall    = recall(   tib, truth, estimate, event_level = "first")$.estimate,
    f1        = f_meas(   tib, truth, estimate, event_level = "first")$.estimate
  )
}

# Load the ground truth file and keep only the domain and the answer columns 
gold <- read_frame(gold_file, target_col) %>%
  transmute(
    Domain,
    truth = as.character(.data[[target_col]]) %>% str_trim()
  )

# Score each of the 5 runs 
rows <- list() # Empty list, one row of scores per run gets added 
for (pf in pred_files) { # repeat for each run's file 

  # Load this run's file and keep only domain and answer columns 
    pred <- read_frame(pf, target_col) %>%
    transmute(
      Domain,
      pred = as.character(.data[[target_col]]) %>% str_trim()
    )

  # Line up the ground truth and run's answers by domain
  # Result is one row per domain with 'truth' next to LLM answer
  merged <- gold %>% inner_join(pred, by = "Domain")

  # Count how many domains matched
  n_overlap <- nrow(merged)

  # Calculate precision, recall and F1 for this run
  mets <- eval_binary(merged$truth, merged$pred, positive = positive_label)

  # Save one row for this run - file name, number of matched domains, and the three scores
  rows[[pf]] <- tibble(run = pf, overlap = n_overlap) %>% bind_cols(mets)
}

# Stack the 5 rows into 1 table
summary_tbl <- bind_rows(rows) 

# Output
print(summary_tbl, n = nrow(summary_tbl)) # show rows in console
write_csv(summary_tbl, out_file) # save the table as a csv
