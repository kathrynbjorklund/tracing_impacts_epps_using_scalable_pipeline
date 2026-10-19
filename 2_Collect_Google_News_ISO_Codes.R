# 2) Collect Google News ISO Codes

library(tidyRSS) # downloads an RSS feed and turns it into a data frame
library(dplyr) # for data frame manipulation
library(purrr) # provides tools for applying a function to each element of a list 
library(readr) # supplies write_csv() 

# List country ISO codes
country_codes <- c(
  "AF","AX","AL","DZ","AS","AD","AO","AI","AQ","AG","AR","AM","AW","AU","AT","AZ",
  "BS","BH","BD","BB","BY","BE","BZ","BJ","BM","BT","BO","BQ","BA","BW","BV","BR",
  "IO","BN","BG","BF","BI","CV","KH","CM","CA","KY","CF","TD","CL","CN","CX","CC",
  "CO","KM","CG","CD","CK","CR","CI","HR","CU","CW","CY","CZ","DK","DJ","DM","DO",
  "EC","EG","SV","GQ","ER","EE","SZ","ET","FK","FO","FJ","FI","FR","GF","PF","TF",
  "GA","GM","GE","DE","GH","GI","GR","GL","GD","GP","GU","GT","GG","GN","GW","GY",
  "HT","HM","VA","HN","HK","HU","IS","IN","ID","IR","IQ","IE","IM","IL","IT","JM",
  "JP","JE","JO","KZ","KE","KI","KP","KR","KW","KG","LA","LV","LB","LS","LR","LY",
  "LI","LT","LU","MO","MG","MW","MY","MV","ML","MT","MH","MQ","MR","MU","YT","MX",
  "FM","MD","MC","MN","ME","MS","MA","MZ","MM","NA","NR","NP","NL","NC","NZ","NI",
  "NE","NG","NU","NF","MK","MP","NO","OM","PK","PW","PS","PA","PG","PY","PE","PH",
  "PN","PL","PT","PR","QA","RE","RO","RU","RW","BL","SH","KN","LC","MF","PM","VC",
  "WS","SM","ST","SA","SN","RS","SC","SL","SG","SX","SK","SI","SB","SO","ZA","GS",
  "SS","ES","LK","SD","SR","SJ","SE","CH","SY","TW","TJ","TZ","TH","TL","TG","TK",
  "TO","TT","TN","TR","TM","TC","TV","UG","UA","AE","GB","UM","US","UY","UZ","VU",
  "VE","VN","VG","VI","WF","EH","YE","ZM","ZW"
)

# Define search term and base URL for RSS feed
base_url <- "https://news.google.com/rss/search?q=dengue+after:2000-01-01+before:2025-03-22"
urls <- paste0(base_url, "&hl=en&gl=", country_codes, "&ceid=", country_codes, ":en")

# Create progress bar 
pb <- txtProgressBar(min = 0, max = length(urls), style = 3)

# Fetch and parse each country's feed; return NULL for any feed that errors
feeds <- map2(urls, seq_along(urls), ~{
  setTxtProgressBar(pb, .y)
  tryCatch(
    tidyfeed(.x, clean_tags = TRUE, parse_dates = TRUE),
    error = function(e) NULL
  )
})
close(pb)

# Drop failed (NULL) feeds and put the rest into a single data frame 
valid_feeds <- compact(feeds)
combined_df <- bind_rows(valid_feeds)

# Identify the column holding the article link (name varies by feed), taking the first match
link_col <- intersect(c("item_link", "link", "guid", "item_guid_id"), names(combined_df))[1]
if (is.na(link_col)) stop("No link-like column found; check names(combined_df).")

# Remove duplicate articles returned across multiple country feeds
combined_df <- combined_df %>% distinct(.data[[link_col]], .keep_all = TRUE)

# Write to CSV
write_csv(combined_df, "~/Desktop/Dengue_ISO_EN.csv")
