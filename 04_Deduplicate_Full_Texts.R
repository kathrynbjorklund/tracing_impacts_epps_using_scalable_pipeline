# 4) Deduplicate full texts

# Load the cvs file 
df1 <- read.csv("Five_Spp_Full_Articles.csv")

# Drop rows where article text is NA
df1 <- df1[!is.na(df1$full.text), , drop = FALSE]

# Trim leading/trailing whitespace
norm <- function(x) trimws(x)

# Drop rows that are empty after trim
df1 <- df1[nzchar(norm(df1$full.text)), , drop = FALSE]

# De-dup based on article text
df1 <- df1[!duplicated(norm(df1$full.text)), , drop = FALSE]

# Export
out_file <- "Five_Spp_Full_Articles_Dedup.csv"
write.csv(df1, out_file, row.names = FALSE)
