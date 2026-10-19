# 9) Consensus of 5 runs of GPT Classified News Outlets Y/N  

library(readr) # read/write csvs
library(dplyr) # work with tables
library(stringr) # clean text
library(purrr) # repeat a task for each file

files <- c(
  "Run_1.csv",
  "Run_2.csv",
  "Run_3.csv",
  "Run_4.csv",
  "Run_5.csv"
)
out_file <- "Consensus_Outlets.csv"

# Makes domain look same in every file
norm_domain <- function(x) {
  x %>% as.character() %>% str_trim() %>% str_to_lower() %>% str_replace("^\ufeff", "")
}

# Return answer that appears most often 
majority_vote <- function(values) {
  # Remove missing answers (NA) and empty ones
  vals <- values[!is.na(values) & nzchar(values)]
  # If no answers left return NA
  if (length(vals) == 0) return(NA_character_)
  # Count the votes for each answer
  tab <- sort(table(vals), decreasing = TRUE)
  # Find the answer with most votes
  winners <- names(tab)[tab == max(tab)]
}

# Read csv and keep domain and news columns 
load_run <- function(path) {
  # Read file and remove spaces around the column names
  df <- read_csv(path, show_col_types = FALSE)
  names(df) <- trimws(names(df))
  # Check the two columns are there
  required <- c("Domain","News outlet (Yes/No)")
  missing <- setdiff(required, names(df))
  if (length(missing)) stop(sprintf("%s is missing columns: %s", path, paste(missing, collapse=", ")))
  
  df %>%
  # Keep only the two columns
    transmute(
      Domain = norm_domain(.data$Domain),
      News   = as.character(`News outlet (Yes/No)`) %>% str_trim()
    ) %>%
    distinct(Domain, .keep_all = TRUE)
}

# Check that list of files has 5 names 
if (length(files) != 5) stop("Please provide exactly 5 CSV paths in `files`.")
# Load each of the 5 files with load_run
runs <- map(files, load_run)
# Give the 5 tables short names
names(runs) <- paste0("r", seq_along(runs))

# Put the runs side by side 
wide <- runs %>%
# Rename each table's news column after its run
  imap(~ rename(.x, !!paste0("News_", .y) := News)) %>%
# Join the 5 tables together, matching rows by domain
  reduce(full_join, by = "Domain")

# Make a list of the names of the 5 answer columns 
news_cols <- grep("^News_", names(wide), value = TRUE)

# Take the vote for every domain
consensus <- wide %>%
  rowwise() %>% # work on one domain (row)
  mutate(
    #  collect this domain's 5 answers and take the vote 
    `News outlet (Yes/No)` = majority_vote(c_across(all_of(news_cols)))
  ) %>%
  ungroup() %>%
  select(Domain, `News outlet (Yes/No)`) %>%
  arrange(Domain)

write_csv(consensus, out_file)
