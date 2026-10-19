# 13) Extract up to 5 events, + their location and time, and a main event from articles

import json, argparse 
# json for writing the request files and reading the model's answers
# argeparse for submitting commands in the terminal
from pathlib import Path # handle file and folder paths
import pandas as pd # read the articles and save results as excel
from openai import OpenAI # connect to OpenAI

# Instructions sent to the model with every article
SYSTEM_INSTRUCTIONS = """You extract explicit real-world events from a news article.

Task:
1) Read the entire text for context.
2) Identify up to 5 events that best capture the main message.
   - Each event should be actor + action + outcome.
   - Max 10 words per event.
   - Do NOT include location or time inside the event text.
3) For each event, provide:
   - location: explicit location in text (max 5 words) or 'NA'
   - time: explicit time in text (max 5 words) or 'NA'
4) Select the single main event (max 10 words) as main_event.

Rules:
- Exclude predicted events (expected, projected, forecast).
- Exclude hypothetical/conditional events (might, could, would, if).
- Include planned events only if definite/officially scheduled.
- Do not infer or assume anything not explicitly stated.
- If no explicit events exist, return events=[] and main_event='NA'.
"""

# The answer form the model must follow
EVENT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["events", "main_event"],
    "properties": {
        "events": {"type": "array", "maxItems": 5, "items": {
            "type": "object", "additionalProperties": False,
            "required": ["event", "location", "time"],
            "properties": {k: {"type": "string"} for k in ["event", "location", "time"]},
        }},
        "main_event": {"type": "string"},
    },
}

NEW_COLS = ["Events", "Event Location", "Event Time", "Main Event"]

# Read a csv file, numbers rows
def read_table(path, max_rows=None):
    if path.suffix.lower() == ".csv":
        df = pd.read_csv(path, encoding="utf-8", on_bad_lines="warn", engine="python")
    else:
        df = pd.read_excel(path)
    df = df.reset_index(drop=True)
    if max_rows is not None:
        df = df.head(max_rows)
        print(f"Limited to first {max_rows} rows")
    return df

# Prepare - JSONL files containing requests for a later batch submission
# JSONL means each line in the file contains one complete JSON object
# Each article with usable text gets one request
# Its custom_id links the eventual response back to the article's df row

def prepare(
    input_file, # Path to the input file
    out_dir, # Path to the folder where output files will be saves
    text_col, # Name of the column containing the article text
    model, # Model that should process the requests
    max_output_tokens, # Output token budget for each model response
    max_rows=None, # Optional row limit
    max_requests_per_file=20000, # Maximum number of requests to put in each file
    max_file_mb=190 # File-size threshold, keep below 200mb openai limit for batch api input files
):

    # Read the input file into a pandas df
    df = read_table(input_file, max_rows)

    # Create the output folder
    # parents=True also creates any missing folders in the path
    # exist_ok=True allows the folder to already exist without causing an error
    out_dir.mkdir(parents=True, exist_ok=True)

    # Create an empty list to hold the JSON request strings
    lines = []

    # Loop through the df one row at a time
    # i is the row's index; row contains that row's column names and values
    for i, row in df.iterrows():

        # Get this row's value from the column named by text_col
        text = row.get(text_col, "")

        # If the value is missing, replace with an empty string or convert it to a string and remove whitespace from both ends
        text = "" if pd.isna(text) else str(text).strip()

        # Continue only if some text remains
        if text:

            # Put the article, instructions, and settings together in the required JSON string format
            # Preserve paragraph breaks using markers so the whole request stays on one file line
            # The final "\n" separates a request from the next one
            # Add this completed request to the list that will be saved to a file
  
            lines.append(
                json.dumps({

                    "custom_id": f"row-{i}", # identify the request using its df row index
                    "method": "POST",  # specify the HTTP method to use when this request is submitted
                    "url": "/v1/responses", # specify the API endpoint that will process the request
                    "body": {   # store the settings and messages for this individual request

                        "model": model,  # select the model using the function's model argument

                        "input": [ # provide the instruction message and the article message

                            # Supply the instructions
                            {
                                "role": "system",
                                "content": SYSTEM_INSTRUCTIONS
                            },

                            # Supply the article as the user message, the f-string inserts the article after "Text:" and a newline (line break)
                            {
                                "role": "user",
                                "content": f"Text:\n{text}"
                            }
                        ],

                        "max_output_tokens": max_output_tokens,  # set the output token budget for this request

                        # Configure the structure requested for the model's response
                        "text": {
                            "format": {
                                # Request a response structured according to a JSON schema
                                "type": "json_schema",
                                # Give this response format a name
                                "name": "event_extraction",
                                # Request strict adherence to the schema's structure
                                "strict": True,
                                # Use the defined schema
                                "schema": EVENT_SCHEMA
                            }
                        }
                    }
                }) + "\n"
            )

    # Group requests by output file, starting with one empty group
    files = [[]]
    # Track the number of requests in the current group
    current = 0
    # Track the size of the current group
    size = 0
    # Process each prepared request string
    for line in lines:

        # Calculate this request's size when encoded as UTF-8 (including newline at end)
        n = len(line.encode("utf-8"))
        # Start a new group if the current group has reached its request limit
        if current >= max_requests_per_file or size + n > max_file_mb * 1024 * 1024:

            # Add a new empty group to represent the next output file
            files.append([])
            # Reset the request count and byte count for the new group
            current, size = 0, 0

        # Add the request to the most recent group, files[-1] means the last item in the files list
        files[-1].append(line)
        # Increase the current group's request count by one
        current += 1
        # Add this request's byte size to the current group's total
        size += n

    # Write each group of requests to its own JSONL file; k is the file number, starting at 1; chunk is the list of request strings belonging to that file
    for k, chunk in enumerate(files, start=1):

        # Build a filename such as batch_input_001.jsonl
        # {k:03d} formats the number with at least three digits, adding leading zeros
        # The / operator joins the output folder and filename
        # "".join(chunk) combines the request strings, which already end in newlines
        # write_text saves the combined text as UTF-8
        (out_dir / f"batch_input_{k:03d}.jsonl").write_text(
            "".join(chunk),
            encoding="utf-8"
        )

    # Find and sort all matching batch input files in the output folder
    # The * matches any characters between "batch_input_" and ".jsonl"
    for p in sorted(out_dir.glob("batch_input_*.jsonl")):

        # p is the file's path
        # p.stat().st_size gives its actual size in bytes
        # Dividing by 1024 twice converts bytes to MB
        # :.2f displays the size with two decimal places
        print(f"  - {p} ({p.stat().st_size/1024/1024:.2f} MB)")

# Upload the prepared files, start their batch jobs, and save the job details
# out_dir is the folder containing your prepared JSONL files & meta_out is the path where the batch IDs and filenames will be saved
def submit(out_dir, meta_out):

    client = OpenAI()

    # Empty list started to store details about the batch jobs submitted
    batches = []

    # Find all files named batch_input_*.jsonl and go through them in filename order
    for p in sorted(out_dir.glob("batch_input_*.jsonl")):

        # Open file for reading
        # "rb" means read the file as bytes; fh refers to the open file; "with" block closes the file automatically after the upload
        with open(p, "rb") as fh:

            # Upload the file to OpenAI and mark it for use in a batch
            # Uploaded holds information about the upload, including its file ID
            uploaded = client.files.create(file=fh, purpose="batch")

        # Create a batch job to process the requests in the uploaded file
        batch = client.batches.create(
            input_file_id=uploaded.id, # identify the uploaded file to process
            endpoint="/v1/responses", # use the Responses API for its requests
            completion_window="24h" # allow a 24-hour processing window
        )

        # Add this job's details to list
        batches.append({
            "batch_id": batch.id, # The ID identifying this batch job
            "input_file_id": uploaded.id, # The ID identifying its uploaded file
            "file": p.name # The original filename
        })

        # Show which file was submitted and the ID of its batch job
        print(f"Submitted {p.name} -> batch {batch.id}")

    # Save the details of all submitted jobs to a JSON file.
    meta_out.write_text(
        json.dumps({"batches": batches}, indent=2),
        encoding="utf-8"
    )

    # Show where the file containing the batch details was saved
    print(f"Saved batch metadata -> {meta_out}")

# Merge 
# Find the model's answer text inside one downloaded result
def answer_text(obj):

    # Look through the output items stored inside "response", then "body"
    for item in obj.get("response", {}).get("body", {}).get("output", []):
        # Look for an item containing a message from the model
        if item.get("type") == "message":
            # Look through the different parts of that message
            for block in item.get("content", []):
                # Look for a part containing the model's written answer
                if block.get("type") == "output_text":
                    # Return the first answer text found
                    return block.get("text")
    # Return None, meaning no answer text was found
    return None

# Match the downloaded answers to the original articles and save the results
def merge(input_file, output_xlsx, meta_json, max_rows=None):

    client = OpenAI()

    df = read_table(input_file, max_rows)

    # Go through the result column names defined earlier in NEW_COLS
    for c in NEW_COLS:
        # Check whether this column needs to be added
        if c not in df.columns:
            # Create the missing column and fill it with the text "NA", existing columns and their values are kept
            df[c] = "NA"

    # Start a list to hold the complete downloaded result records
    all_responses = []
    # Read the saved batch details and go through each batch
    # json.loads turns the saved JSON text into Python data
    for b in json.loads(meta_json.read_text())["batches"]:

        # Ask OpenAI for the current details of this batch using its saved ID
        batch = client.batches.retrieve(b["batch_id"])
        # Check whether an output file is available for this batch
        if not batch.output_file_id:

            # Print this message when no output file is available
            print(f"Batch {b['batch_id']} not completed yet")
            # Move to the next batch, leaving the table unchanged for this one
            continue

        # Download the batch's output file and split its text into separate lines
        for line in client.files.content(batch.output_file_id).text.splitlines():

            # Convert this line of JSON text into a Python dictionary
            obj = json.loads(line)
            # Keep the full result record for the separate JSON export
            all_responses.append(obj)
            # Get the label that connects this answer to its original article
            cid = obj.get("custom_id", "")
            # Skip this result if its label does not start with "row-"
            if not cid.startswith("row-") or int(cid.split("-")[1]) >= len(df):
                continue

            # Extract the row number from the label
            idx = int(cid.split("-")[1])

            # Use the helper above to find the model's answer text
            raw = answer_text(obj)

            # If the answer text is missing or empty, move to the next result
            if not raw:
                continue

            # Convert the model's JSON answer into Python data
            data = json.loads(raw)

            # Get the list of extracted events
            events = data.get("events", [])

            # Match each Excel column to the corresponding field in each event
            # col is the table column; key is the field to take from the answer
            for col, key in [
                ("Events", "event"),
                ("Event Location", "location"),
                ("Event Time", "time")
            ]:

                # Collect this field from every event and put the values in one cell
                # Separate multiple values with " | "
                # Keep the same event order across all three columns
                # If there are no events, put "NA" in the cell
                # df.at[idx, col] selects the cell at this row and column
                df.at[idx, col] = " | ".join(e[key] for e in events) if events else "NA"

            # Store the main event in its own column, use "NA" if the answer has no "main_event" field
            df.at[idx, "Main Event"] = data.get("main_event", "NA")

    # Save the updated article table as an Excel file
    # index=False leaves out pandas' extra row-number column
    df.to_excel(output_xlsx, index=False)

    # Show where the Excel file was saved
    print(f"Wrote output -> {output_xlsx}")

    # If at least one result record was downloaded, also save the full records
    if all_responses:

        # Use the Excel file's folder and name, but change the extension to .json
        json_output = output_xlsx.with_suffix(".json")

        # Save the complete result records as readable JSON
        json_output.write_text(
            json.dumps(all_responses, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )

        # Show where the JSON file was saved
        print(f"Saved raw JSON responses -> {json_output}")

# Terminal options (choose which step (prepare, submit, or merge) to run from terminal)
if __name__ == "__main__":

    ap = argparse.ArgumentParser() # set up a reader for the command and options you type in the terminal
    sub = ap.add_subparsers(dest="cmd", required=True) # store the chosen command under "cmd", which later read as a.cmd

   # Prepare command 
    p1 = sub.add_parser("prepare") # set up the options for creating the batch input files
    p1.add_argument("--input_xlsx", required=True, type=Path) # require the path to the article table
    p1.add_argument("--out_dir", required=True, type=Path) # require the folder where the prepared JSONL files should be saved
    p1.add_argument("--text_col", default="FullText") # choose the column containing the article text
    p1.add_argument("--model", default="gpt-5-nano") # choose model that will process articles
    p1.add_argument("--max_output_tokens", type=int, default=10000) # set output token budget 
    p1.add_argument("--max_rows", type=int, default=None) # apply row limit

    # Submit command 
    p2 = sub.add_parser("submit") # set up the options for uploading the prepared files and starting batch jobs
    p2.add_argument("--out_dir", required=True, type=Path) # require the folder containing the batch input files to upload
    p2.add_argument("--meta_out", required=True, type=Path) # require a path for saving the batch IDs and filenames

    # Merge command
    p3 = sub.add_parser("merge") # set up the options for combining the available answers with the article table
    p3.add_argument("--input_xlsx", required=True, type=Path) # require the same original article file used in prepare
    p3.add_argument("--output_xlsx", required=True, type=Path) # require a path for saving the Excel results file
    p3.add_argument("--meta_json", required=True, type=Path) # require the batch-details JSON file saved by the submit step
    p3.add_argument("--max_rows", type=int, default=None) # use the same row limit as in prepare

    # Read the command and options entered in the terminal
    # Store their values in a, so they can be accessed as a.cmd, a.out_dir, etc.
    a = ap.parse_args()

    # If the chosen command is "prepare", run prepare() with its supplied settings
    # The file-size and requests-per-file limits use the defaults in prepare()
    if a.cmd == "prepare":
        prepare(
            a.input_xlsx,
            a.out_dir,
            a.text_col,
            a.model,
            a.max_output_tokens,
            a.max_rows
        )

    # If the chosen command is "submit", upload the files and save the batch details
    elif a.cmd == "submit":
        submit(a.out_dir, a.meta_out)

    # The remaining possible command is "merge"
    # Run merge() to match available answers to articles and save the results
    else:
        merge(a.input_xlsx, a.output_xlsx, a.meta_json, a.max_rows)
