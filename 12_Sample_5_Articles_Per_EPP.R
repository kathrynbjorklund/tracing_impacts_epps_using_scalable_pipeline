# 12) 5 Randomly Sampled Articles of Each EPP for Manual Classification

library(readr) # read and write csvs
library(dplyr) # work with tables
library(stringr) # clean text

in_file  <- "Relevant.csv"
out_samp <- "30_Sampled.csv"
out_rest <- "Leftover.csv"
set.seed(14)

# Read file
df <- read_csv(in_file, show_col_types = FALSE)

# Tidy feed title 
df <- df %>%
  mutate(
    feed_title = as.character(feed_title),
    feed_title = str_replace(feed_title, "^[\"'\\u201C\\u201D\\u2018\\u2019]+", ""),
    feed_title = str_trim(feed_title)
  )

# Take the first word of a text to get at EPP
first_token <- function(x) {
  str_to_lower(str_split_fixed(str_trim(as.character(x)), "\\s+", 2)[, 1])
}

# Add 3 new columns: .rowid, first, species (merges spelling variants)
# Fall armyworm conducted separately
df <- df %>%
  mutate(
    .rowid = row_number(),
    first  = first_token(feed_title),
    species = case_when(
      first == "dengue" ~ "Dengue",
      first == "zika"   ~ "Zika",
      first == "ebola"  ~ "Ebola",
      first %in% c("screw","screw-worm","screwworm","cochliomyia-hominivorax") ~ "Screwworm",
      first %in% c("schistocerca","desert-locust","desert")                    ~ "Desert locust",
      TRUE ~ NA_character_
    )
  )

# Shuffle within each species, then take first 5 rows from each
sampled <- df %>%
  filter(!is.na(species)) %>% # leave out articles with no species 
  group_by(species) %>% # treat each species separately
  mutate(.rand = runif(n())) %>% # give every article a random number
  arrange(species, .rand) %>% # sort by that random number (shuffle)
  slice_head(n = 5) %>% # keep the first 5 of each species 
  ungroup() %>% # back to one table 
  select(-.rand) # remove the random number column 

remaining <- df %>% filter(!.rowid %in% sampled$.rowid)

# Remove the .rowid and first columns before saving
sampled  <- sampled  %>% select(-.rowid, -first)
remaining <- remaining %>% select(-.rowid, -first)

# Save both files
write_csv(sampled,  out_samp)
write_csv(remaining, out_rest)
