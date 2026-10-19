# 3) Scrape Google News URLs

library(chromote) # controls a hidden Chrome browser
library(rvest) # reads web pages
library(httr) # downloads web pages
library(jsonlite) # reads JSON data
library(stringr) # text pattern matching
library(urltools) # splits URLs into parts
library(dplyr) # the %>% pipe
library(future.apply) # runs several jobs at the same time

# Load CSV
# Filter out troublesome URLs causing formatting issues in the resulting csv 
urls_df         <- read.csv("Zika.csv", stringsAsFactors = FALSE)
rows_to_process <- 1:4000
all_urls        <- urls_df$url[rows_to_process]
all_urls        <- all_urls[!grepl("philstar\\.com|nature\\.com|biomedcentral\\.com|reliefweb\\.int",
                                   all_urls, ignore.case = TRUE)]

# Functions
# Is this link still a Google News link? (TRUE = we have not reached the article yet)
is_gnews <- function(url) grepl("news\\.google\\.com", url, ignore.case = TRUE)

# Is this link NOT a Google link? (used to pick out outside websites)
not_google <- function(x) x[!grepl("google\\.", x, ignore.case = TRUE)]

# Run JavaScript inside the browser page. If it fails, return `default`.
run_js <- function(session, code, default = NULL) {
  tryCatch(session$Runtime$evaluate(code)$result$value, error = function(e) default)
}

# Ask the browser: "what page did you end up on?" If it can't say, return `default`.
last_url <- function(session, default) {
  tryCatch({
    h <- session$Page$getNavigationHistory()$entries
    if (length(h) > 0) h[[length(h)]]$url else default
  }, error = function(e) {
    cat("Error retrieving navigation history for:", default, "\n", e$message, "\n")
    default
  })
}

# Send the browser to a new link, wait 3 seconds, and report where it landed.
# If the browser fails, keep the link we already had (`current_url`).
go_to <- function(session, url, current_url, label) {
  tryCatch({
    session$Page$navigate(url)
    Sys.sleep(3)
    new_final <- last_url(session, url)
    if (is_gnews(new_final)) cat("    ", label, "=> still Google News =>", new_final, "\n")
    new_final
  }, error = function(e) {
    cat("    ", label, "Error navigating =>", url, "\n", e$message, "\n")
    current_url
  })
}

# 3 methods to find real article link (each takes current link and returns a different one if it finds it, 
# or the returns the same link if it does not)
           
# 1) Look for the page's "official address" tag (<link rel="canonical">) 
fallback_canonical <- function(session, current_url) {
  can_url <- run_js(session, "(document.querySelector('link[rel=canonical]') || {}).href || ''", "")
  if (!nzchar(can_url)) {
    cat("    [fallback_canonical] No canonical link found.\n")
  } else if (is_gnews(can_url)) {
    cat("    [fallback_canonical] Canonical is Google News =>", can_url, "\n")
  } else {
    cat("    [fallback_canonical] Found canonical link =>", can_url, "\n")
    return(can_url)
  }
  current_url
}

# 2) Look for an "auto-redirect" tag (<meta http-equiv="refresh">) and follow it
fallback_meta_refresh <- function(session, current_url) {
  meta <- run_js(session, "(document.querySelector('meta[http-equiv=refresh]') || {}).content || ''", "")
  if (!nzchar(meta)) return(current_url)
  cat("    [fallback_meta_refresh] Found meta refresh =>", meta, "\n")
  refresh_url <- sub(".*url=([^;]+).*", "\\1", meta)
  if (!grepl("^http", refresh_url)) return(current_url)
  cat("    Navigating to meta refresh URL =>", refresh_url, "\n")
  go_to(session, refresh_url, current_url, "[fallback_meta_refresh]")
}

# 3.1) Helper that digs through nested data and collect anything labeled "url" or "mainEntityOfPage"
           
find_url_fields <- function(x) {
  results <- character(0)
  if (is.list(x)) {
    for (nm in names(x)) {
      val <- x[[nm]]
      if (nm %in% c("url", "mainEntityOfPage") && is.character(val)) results <- c(results, val)
      if (is.list(val) || is.data.frame(val)) results <- c(results, find_url_fields(val))
    }
  }
  results
}

# 3.2)  Read the page's hidden "structured data" blocks (JSON-LD) and look for a non-Google link in there
fallback_jsonld <- function(session, current_url) {
  blocks <- run_js(session,
    "Array.from(document.querySelectorAll('script[type=\"application/ld+json\"]')).map(s => s.innerText)")
  for (json_str in blocks) {
    obj <- tryCatch(fromJSON(json_str), error = function(e) NULL)
    if (is.list(obj)) {
      links <- not_google(find_url_fields(obj))
      if (length(links) > 0) {
        cat("    [fallback_jsonld] Found external URL =>", links[1], "\n")
        return(links[1])
      }
    }
  }
  cat("    [fallback_jsonld] No external URLs found in JSON-LD.\n")
  current_url
}

# Find real article link                    
# See where the browser ends up. If still on Google News, run the three backup methods.
fallback_logic <- function(session, original_url) {
  final_url <- last_url(session, original_url)
  if (is_gnews(final_url)) {
    cat("[fallback_logic] Google News URL detected =>", final_url, "\n")
    for (f in list(fallback_canonical, fallback_meta_refresh, fallback_jsonld)) {
      if (is_gnews(final_url)) final_url <- f(session, final_url)
    }
  }
  cat("[fallback_logic] Final URL =>", final_url, "\n")
  final_url
}

# Open the link in the hidden browser (up to 3 tries), wait 5 seconds for it to load.
process_url <- function(url, max_attempts = 3) {
  for (attempt in seq_len(max_attempts)) {
    cat(sprintf("[process_url] Attempt %d to navigate: %s\n", attempt, url))
    session <- ChromoteSession$new()
    ok <- tryCatch({
      session$Page$navigate(url)
      Sys.sleep(5)
      TRUE
    }, error = function(e) {
      cat("    Navigation error on attempt", attempt, "for URL:", url, "\n    Message:", e$message, "\n")
      FALSE
    })
    if (ok) {
      final_url <- fallback_logic(session, url)
      session$close()
      return(final_url)
    }
    session$close()
    Sys.sleep(2)
  }
  cat("[process_url] All attempts failed for:", url, "\nReturning original URL.\n")
  url
}

# Get publication date. Tries four common places a website stores it and returns the first one found (or NA if none).
extract_publication_date <- function(page) {
  # Places 1 & 2: hidden <meta> tags in the page header
  for (sel in c("meta[property='article:published_time']", "meta[name='date'], meta[name='pubdate']")) {
    val <- page %>% html_nodes(sel) %>% html_attr("content")
    if (length(val) > 0 && nzchar(val[1])) return(val[1])
  }
  # Place 3: a <time> tag
  val <- page %>% html_node("time") %>% html_attr("datetime")
  if (!is.na(val) && nzchar(val)) return(val)
  # Place 4: "structured data" blocks (JSON-LD), at the top level or nested
  # inside "article" / "newsArticle"
  for (txt in page %>% html_nodes("script[type='application/ld+json']") %>% html_text(trim = TRUE)) {
    tmp <- tryCatch(fromJSON(txt), error = function(e) NULL)
    if (is.null(tmp)) next
    for (obj in list(tmp, tmp$article, tmp$newsArticle)) {
      d <- if (is.list(obj)) obj$datePublished
      if (!is.null(d) && nzchar(d[1])) return(d[1])
    }
  }
  NA_character_
}

# Get the article text. First try paragraphs inside the <article> section; 
# if there are none, take every paragraph on the page.
extract_full_text <- function(page) {
  for (sel in c("article p", "p")) {
    p <- page %>% html_nodes(sel) %>% html_text(trim = TRUE)
    if (length(p) > 0) return(paste(p, collapse = "\n\n"))
  }
  NA_character_
}

# Get the website name from a link (e.g. "www.bbc.com").
extract_domain <- function(url) urltools::url_parse(url)$domain


# Download the webpage from real link, filters out pages with errors, pulls out data from working webpages
get_article_data <- function(original_url) {
  final_url <- process_url(original_url)

# Builds the output row 
  make_row <- function(pub_date = NA_character_, full_text = NA_character_) {
    data.frame(original_url = original_url, final_url = final_url,
               domain = extract_domain(final_url),
               pub_date = pub_date, full_text = full_text, stringsAsFactors = FALSE)
  }
  # Prints why we are skipping, then returns an empty row
  skip <- function(...) { message(...); make_row() }

  # Issue 1) Is the link an image/icon rather than a web page?
  if (grepl("\\.(ico|jpg|jpeg|png|gif)$", final_url, ignore.case = TRUE))
    return(skip("Skipping non-HTML resource: ", final_url))

  # Download the page (give up after 60 seconds)
  response <- tryCatch(
    httr::GET(final_url, httr::user_agent("Mozilla/5.0"), httr::timeout(60)),
    error = function(e) {
      message("Timeout or connection error for URL: ", final_url, "\n  Message: ", e$message)
      NULL
    })

  # Issue 2) Did the download work?
  if (is.null(response)) return(skip("Skipping URL due to GET error: ", final_url))

  # Issue 3) Did the website say "OK" (status 200)?
  if (httr::status_code(response) != 200)
    return(skip("Skipping URL due to non-200 status: ", final_url))

  # Issue 4) Is it actually a web page (HTML), not a PDF or other file?
  content_type <- httr::headers(response)$`content-type`
  if (is.null(content_type) || length(content_type) == 0 ||
      !grepl("text/html", content_type, ignore.case = TRUE))
    return(skip("Skipping URL due to non-HTML or missing content type: ", final_url,
                " (Content-Type: ", content_type, ")"))

  # Issue 5) Is the page nearly empty? (often means a login is required)
  html_text <- httr::content(response, "text", encoding = "UTF-8")
  if (nchar(trimws(html_text)) < 100)
    return(skip("Skipping URL due to blank or near-blank page (possible authentication requirement): ", final_url))

  # Issue 6) Can the page be read as HTML?
  page <- tryCatch(read_html(html_text), error = function(e) {
    message("[get_article_data] Error reading HTML => ", final_url, "\n  Message: ", e$message)
    NULL
  })
  if (is.null(page) || !inherits(page, "xml_document"))
    return(skip("Skipping URL due to invalid page: ", final_url))

  # Pull out the date and text
  make_row(extract_publication_date(page), extract_full_text(page))
}

# Process 100 links at a time, 4 at once in parallel
plan(multisession, workers = 4)   

urls_to_process <- all_urls
num_urls        <- length(urls_to_process)
batch_size      <- 100
num_batches     <- ceiling(num_urls / batch_size)
all_results     <- list()

for (batch in seq_len(num_batches)) {
  start_idx <- (batch - 1) * batch_size + 1
  end_idx   <- min(batch * batch_size, num_urls)
  cat("\n=== Processing batch", batch, "of", num_batches,
      " => URLs [", start_idx, ":", end_idx, "] ===\n")

  # Process this batch's links in parallel, then stack the rows into one table
  batch_out <- future_lapply(urls_to_process[start_idx:end_idx], get_article_data, future.seed = TRUE)
  batch_df  <- do.call(rbind, batch_out)
  all_results[[batch]] <- batch_df

  # Save this batch
  out_file <- paste0("Zika_batch_", batch, ".csv")
  write.csv(batch_df, out_file, row.names = FALSE)
  cat("   => Batch", batch, "written to", out_file, "\n")
}
