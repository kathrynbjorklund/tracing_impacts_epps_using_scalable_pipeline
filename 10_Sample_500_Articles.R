# 10) 500 Randomly Sampled Articles for Manual Classification

library(readr) # read and write csvs

in_file   <- "articles.csv"                
out_samp  <- "Sampled_500.csv"     
out_rest  <- "Remaining.csv"        
set.seed(67)                      

# Read input file
df <- read_csv(in_file, show_col_types = FALSE)

# Pick 500 at random with no repeats
sampled_idx <- sample(nrow(df), size = min(500, nrow(df)))

# Split the table into sampled and leftover rows
sampled <- df[sampled_idx, ]
remaining <- df[-sampled_idx, ]

write_csv(sampled, out_samp)
write_csv(remaining, out_rest)
