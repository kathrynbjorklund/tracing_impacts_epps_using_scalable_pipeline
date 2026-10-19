# 11) Classify Articles As Relevant (Containing targeted EPPs)

import os # find API key
import time # pause between requests 
from openai import OpenAI 
import json # reads model's answers
import pandas as pd # read and write csv table
from typing import List # for "List[str]" or list of strings labels

MODEL       = "gpt-5-nano"
INPUT_FILE  = "Sampled500ForNanoClassification.csv"        
OUTPUT_FILE = "500SampleNanoClass.csv"           
BATCH_SIZE  = 1                   
SLEEP_SEC   = 0.2                   

SYSTEM_PROMPT = """You are a strict binary classifier for article relevance.

Task: Fill a column 'RelevantYN'.
For each article in the 'full.text' field, label as:
- Yes = The article contains information about one or more of the following emerging pests and pathogens (EPPs):
  • Screwworm / screw worm (Cochliomyia hominivorax)
  • Desert locust (Schistocerca gregaria)
  • Dengue virus
  • Ebola virus
  • Zika virus
- No = The article does not contain information about these EPPs.

Important rules:
1) Focus on the main body text.
   - Headlines or link lists at the bottom that mention EPPs are NOT part of the main article → code No.

Output format:
- For each text, return only a single field 'relevant' with value "Yes" or "No".
- Do not output anything else.
"""  # CHANGED: REMOVED the line 'If uncertain after best effort, default to "Yes".'

def _schema(n: int) -> dict:
    # ADDED: factored schema to a function (no behavior change)
    return {
        "type": "object",
        "additionalProperties": False, # no extra fields allowed
        "properties": {
            "rows": {
                "type": "array", # a list 
                "minItems": n, # with exactly n entries
                "maxItems": n,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "relevant": {"type": "string", "enum": ["Yes", "No"]} # only yes or no
                    },
                    "required": ["relevant"] # the answer must be present
                }
            }
        },
        "required": ["rows"]
    }

# Check model's answer 
def _validate_labels(raw: dict, n: int) -> List[str]:
    """Validate and return exactly n labels, each 'Yes' or 'No'; else raise."""
    # Answer must contain a list called rows
    if not isinstance(raw, dict) or "rows" not in raw or not isinstance(raw["rows"], list):
        raise ValueError("Missing or invalid 'rows' array in model output.")
    rows = raw["rows"]
   # Must be exactly 1 answer per article 
    if len(rows) != n:
        raise ValueError(f"Expected {n} rows, got {len(rows)}.")
      # Make sure each answer is exactly 'Yes' or 'No'
    labels = []
    for i, r in enumerate(rows, start=1): 
        if not isinstance(r, dict) or "relevant" not in r:
            raise ValueError(f"Row {i} missing 'relevant' field.")
        v = r["relevant"]
        if v not in ("Yes", "No"):
            raise ValueError(f"Row {i} has invalid value '{v}'.")
        labels.append(v)
    return labels

# Sends article to OpenAI, waits for answer, checks, and gives back answer 
def classify_batch(client: OpenAI, texts: List[str]) -> List[str]:
    """Single try. No defaults. Raises on any invalid/malformed response."""
    n = len(texts)
    schema = _schema(n)

  #write the message to the model
    msgs = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content":
            "Classify the following texts. For each, return an object with a single field 'relevant'.\n\n" +
            "\n\n".join([f"Text {i+1}: {t}" for i, t in enumerate(texts, start=1)])
        },
    ]

  # Send the request 
    resp = client.responses.create(
        model=MODEL,
        input=msgs,
        text={
            "format": {
                "type": "json_schema",
                "name": "relevance",
                "schema": schema,
                "strict": True
            }
        },
    )

    
    # Turn answer into something readable in python
    raw = json.loads(resp.output_text or "{}")
    return _validate_labels(raw, n)

# Runs everything in order 
# Get API key
def main():
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY environment variable not set.")
    client = OpenAI(api_key=api_key)

  # Read input file 
    df = pd.read_csv(INPUT_FILE)
    if "full.text" not in df.columns:
        raise ValueError("Input CSV must contain a 'full.text' column.")

  # Take article texts out as plain list 
    texts = df["full.text"].astype(str).tolist()
    results: List[str] = [] # empty list where answers are added 

    total = len(texts)
    print(f"Loaded {total} rows from {INPUT_FILE}")

  # Go through articles 
    for start in range(0, total, BATCH_SIZE): # start = position of first article in this batch
        end = min(start + BATCH_SIZE, total) # position aftter last article 
        batch = texts[start:end] # take out the article text for this batch 
        print(f"Processing {start+1}–{end} / {total}") # Show progress

      # Ask the model
        labels = classify_batch(client, batch)  
      # Must be 1 answer per article, stop if not
        if len(labels) != len(batch):
            raise RuntimeError(f"Got {len(labels)} labels for a {len(batch)}-item batch.")

        results.extend(labels) # add this batch's answer to the list of results
        time.sleep(SLEEP_SEC) # short pause before next request

    df["RelevantYN"] = results
    df.to_csv(OUTPUT_FILE, index=False)
    print(f"Saved → {OUTPUT_FILE} (rows: {len(df)})")

# Start script by running main()
if __name__ == "__main__":
    main()
