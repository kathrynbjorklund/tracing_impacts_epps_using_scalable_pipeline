# 5) 100 Randomly Sampled Domains for Manual Classification

library(readr)
library(dplyr)

in_file   <- "Domains.csv"               
out_samp  <- "Domains_Sampled_100.csv"     
out_rest  <- "Remaining.csv"        
set.seed(62)                        

# Read file with all unique domains
df <- read_csv(in_file, show_col_types = FALSE)

# Sample 500 rows 
sampled_idx <- sample(nrow(df), size = min(100, nrow(df)))
sampled <- df[sampled_idx, ]
remaining <- df[-sampled_idx, ]

# Save as a 500 sample and the rest
write_csv(sampled, out_samp)
write_csv(remaining, out_rest)
