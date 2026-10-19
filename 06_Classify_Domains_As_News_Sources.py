# 6) Classifying domains as news sources 

# Load packages
import os, sys, json
# os - read API key 
# sys - stop the script
# json - read the model's JSON answer
 
from pathlib import Path # handles file paths
from openai import OpenAI # OpenAI service 

# Settings 
MODEL       = "gpt-5-nano"                
INPUT_FILE  = "Unique_Domains_All.csv"    
OUTPUT_FILE = "Dom_All_GPT_Class_1.csv"   
LIMIT       = None                                                
PROGRESS_EVERY = 50 # print a progress message every 50 domains

# Column names for output CSV
HEADER = "Domain,News outlet (Yes/No),Short description,Type of content,Confidence"

# The only content the model is allowed to choose from
TYPE_OPTIONS = [
    "General content",
    "Business/Finance",
    "Technology",
    "Health/Science",
    "Sports",
    "Entertainment (music/film/TV/gaming/celebrity)",
    "Lifestyle/Travel",
    "Corporate/Press releases",
    "Trade/Industry",
    "Other",
]

# The instructions sent to the model with every request
SYSTEM_INSTRUCTIONS = """JSON-only domain classifier. TOP-LEVEL OUTPUT MUST BE AN OBJECT with a key `rows`.
`rows` must be an array with EXACTLY one item per input domain, in the SAME ORDER. Do not skip any.
Each item must be an object with fields:
- domain (string): echo the input domain EXACTLY as given.
- news_outlet (string): "Yes" or "No".
- short_description (string): ≤5 words; avoid commas (use hyphens if needed).
- type_of_content (string): choose exactly one of:
  General content; Business/Finance; Technology;
  Health/Science; Sports; Entertainment (music/film/TV/gaming/celebrity);
  Lifestyle/Travel; Corporate/Press releases; Trade/Industry; Other.
  Branded topical subdomains count as that topic (sports.yahoo.com → Sports); paths do not.
- confidence (number): 0–1 model certainty that “News outlet” is correct.

Rules:
- News outlet: Yes if primarily publishes/broadcasts news; No otherwise.
  Yes examples: national daily newspapers (e.g., manilatimes.net, usatoday.com), local news broadcasters (e.g., fox5atlanta.com, hindustantimes.com).
  No examples: government websites (e.g., nih.gov, blogs.cdc.gov), intergovernmental organization websites (e.g., who.int, paho.org), research institute websites (e.g., pewresearch.org, pasteur.fr), university websites (e.g., publichealth.jhu.edu,
           urmc.rochester.edu), scientific journal websites (e.g., nature.com, bmcinfectdis.biomedcentral.com), magazine websites (e.g., scientificamerican.com, wanderlustmagazine.com),
           tabloid websites (e.g., tmz.com, dailymail.co.uk).
- Output MUST strictly conform to the JSON Schema provided by the API.
- No explanations or extra text—only the required JSON object.
"""

# Reads domains from the input file
def read_domains(path):
    # Read the file and split it into lines. "utf-8-sig" removes a hidden
    # character Excel sometimes adds at the start of a CSV.
    lines = Path(path).read_text(encoding="utf-8-sig").splitlines()
    domains = []
    for i, line in enumerate(lines): # i = line number (0 = first line)
        if not line.strip(): # empty line -> skip
            continue
        first = line.split(",", 1)[0].strip() # the text before the first comma
        if i == 0 and first.lower() in {"domain"}: # skip if column title 
            continue
        domains.append(first)
    return domains

# Describe the exact answer format the model must use 
def make_schema(n_items: int):
    item_schema = {
        "type": "object",
        "additionalProperties": False, # no extra fields allowed
        "properties": {
            "domain": {"type": "string"}, # text
            "news_outlet": {"type": "string", "enum": ["Yes", "No"]}, # must be exactly yes or no
            "short_description": {"type": "string"}, # text
            "type_of_content": {"type": "string", "enum": TYPE_OPTIONS}, # must be one from the list
            "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0}, # a number from 0 to 1
        },
        "required": ["domain", "news_outlet", "short_description", "type_of_content", "confidence"], # all five are compulsory
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "rows": {
                "type": "array",
                "minItems": n_items,
                "maxItems": n_items,
                "items": item_schema,
            }
        },
        "required": ["rows"],
    }

# Sends domains to OpenAI
def classify_domain(client, domain):
    resp = client.responses.create(
        model=MODEL,
        input=[
            {"role": "system", "content": SYSTEM_INSTRUCTIONS},
            {"role": "user", "content": "Domains (one per line):\n" + domain},
        ],
        text={"format": {"type": "json_schema", "name": "domain_classifications",
                         "schema": make_schema(1), "strict": True}},
    )
    answer = json.loads(resp.output_text)["rows"][0]
 
    # make sure commas are converted to hyphens (a comma would split it into two CSV columns)
    # make sure spaces are removed at the start and end
    # make sure only the first 5 words retained
    short = answer["short_description"].replace(",", "-").strip()
    short = " ".join(short.split()[:5])

    # Build the CSV line (the five answers, separated by commas)
    # The domain is taken from input file, not the model's copy of it.
    # float() makes sure confidence is always written as a decimal (e.g. 1.0) 
    return f"{domain},{answer['news_outlet']},{short},{answer['type_of_content']},{float(answer['confidence'])}\n"


# Run all steps in order 
def main():

    # Check that the input file exists
    if not Path(INPUT_FILE).exists():
        print(f"Missing {INPUT_FILE}")
        sys.exit(1)

    # Load the domains
    domains = read_domains(INPUT_FILE)
    if LIMIT is not None:
        domains = domains[:LIMIT]

    # If there are no domains it will stop
    if not domains:
        print("No domains to process.")
        return

    print(f"Loaded {len(domains)} domains. Model: {MODEL}")

    # Connect to OpenAI using API key
    client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

    # Create output file with only the column names in it
    Path(OUTPUT_FILE).write_text(HEADER + "\n", encoding="utf-8")

    # Go through the domains
    failed = 0 # counts domains that did not work
    for n, domain in enumerate(domains, start=1): 

        # 'try' and if issue arises go to 'except' instead of stopping command
        try:
            line = classify_domain(client, domain)
            # Add the line to the BOTTOM of the output file straight away
            # ("a" = add to the end), so finished work is never lost.
            with open(OUTPUT_FILE, "a", encoding="utf-8", newline="") as f:
                f.write(line)
        except Exception as e:
            # Print why failed and continue to the next domain.
            print(f"FAILED {domain}: {e}", flush=True)
            failed += 1

        # Every 50 domains, print progress
        if n % PROGRESS_EVERY == 0:
            print(f"processed {n} of {len(domains)} domains", flush=True)

    # States how many worked vs failed
    print(f"Done. Saved {len(domains) - failed} domains, {failed} failed.")


# Start the script by running main() 
if __name__ == "__main__":
    main()
