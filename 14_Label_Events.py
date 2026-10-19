# 14) Label events 

# Setting how python handles type hints
from __future__ import annotations

# Setting up printed messages 
import sys # gives access to python's normal output and error output
import io # provides tools for reading and writing text

if sys.stdout.encoding != 'utf-8':  # keep printed special characters readable
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
if sys.stderr.encoding != 'utf-8':
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

import argparse # reads options entered in terminal
import json
from pathlib import Path # for finding files and folders
from typing import Any, Dict, List, Optional # provides names used to describe expected data types

import pandas as pd # for working with tables
from openai import OpenAI

API_KEY    = "XX" 
MODEL      = "gpt-5-nano"  
EVENTS_COL = "Events"  # column containing the events to label
SEPARATOR  = " | "  # place this between labels when saving results

SYSTEM_INSTRUCTIONS = """You are a labeling assistant.

Task:
- Read the single event description provided.
- Assign a subgroup: a short 1-3 word label.

Rules:
- Respond with ONLY the JSON output. No explanation, no extra text.
- Only return subgroup: "NA" if the input is literally "NA" or empty.
- Never return NA for a real event description.
"""

SUBGROUP_SCHEMA: Dict[str, Any] = {  # Require one text field called subgroup.
    "type": "object",
    "additionalProperties": False,
    "required": ["subgroup"],
    "properties": {
        "subgroup": {"type": "string"},
    },
}

# set up access to OpenAI using API key
def get_client() -> OpenAI:
    return OpenAI(api_key=API_KEY)

# Load file
def read_table(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".csv":
        return pd.read_csv(
            path, encoding='utf-8', on_bad_lines='warn',
            engine='python', quotechar='"', doublequote=True,
        )
    return pd.read_excel(path)

# Turn None/NaN into empty text; convert other values to text
def safe_str(x: Any) -> str:
    if x is None:
        return ""
    if isinstance(x, float) and pd.isna(x):
        return ""
    return str(x)

# Treat blank text and NA (in any letter case) as missing
def is_na(value: str) -> bool:
    return value.strip().upper() == "NA" or value.strip() == ""

# Split a cell at each | and trim spaces around each event
def split_events(cell: str) -> List[str]:
    return [e.strip() for e in cell.split("|")]

# Package one event and its labeling instructions as one request
def build_request_line(custom_id: str, event_text: str) -> str:
    req = {
        "custom_id": custom_id,
        "method": "POST",
        "url": "/v1/responses",
        "body": {
            "model": MODEL,
            "input": [
                {"role": "system", "content": SYSTEM_INSTRUCTIONS},
                {"role": "user",   "content": event_text},
            ],
            "max_output_tokens": 5000,  # Output token budget for each event.
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "subgroup_label",
                    "strict": True,
                    "schema": SUBGROUP_SCHEMA,
                }
            },
        },
    }
    return json.dumps(req, ensure_ascii=True) + "\n"  # one request per file line

# Find the first answer text
def extract_output_text(body: Dict[str, Any]) -> Optional[str]:
    for item in body.get("output", []):
        if item.get("type") == "message":
            for block in item.get("content", []):
                if block.get("type") == "output_text":
                    return block.get("text")
    return None

# Write numbered request files, starting a new file at either limit
def write_jsonl_files(lines: List[str], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)  # Create the output folder if needed.
    max_bytes = 190 * 1024 * 1024  # Size threshold of 190 MiB (about 199 MB).
    max_requests = 20000  # Request-count limit for each file.
    file_idx = req_count = byte_count = 0  # Track file number, requests, and bytes.
    f = None

    for line in lines:
        size = len(line.encode("utf-8"))  # measure this request in bytes
        if f is None or req_count >= max_requests or byte_count + size > max_bytes:
            if f:
                f.close()
            file_idx += 1
            f = (out_dir / f"batch_input_{file_idx:03d}.jsonl").open("w", encoding="utf-8")
            req_count = byte_count = 0
        f.write(line)
        req_count += 1
        byte_count += size

    if f:
        f.close()

    print(f"  Wrote {file_idx} JSONL file(s), {len(lines)} request(s) total")
    for p in sorted(out_dir.glob("batch_input_*.jsonl")):  # includes any files left from earlier runs
        print(f"    - {p} ({p.stat().st_size/1024/1024:.2f} MB)")


# Prepare
# Make one request per event and keep its row and event positions
def prepare(input_file: Path, out_dir: Path, max_rows: Optional[int]) -> None:
    print("\n── prepare ──────────────────────────────────────────────")
    df = read_table(input_file).reset_index(drop=True)  # number rows from 0
    if max_rows:  # use the row limit if supplied; 0 also means no limit here
        df = df.head(max_rows)
    print(f"  {len(df)} rows loaded from {input_file.name}")
    # Collect the prepared requests before writing them to files
    lines = []
    total_events = skipped_events = 0

    for i, row in df.iterrows():
        cell = safe_str(row.get(EVENTS_COL, "")).strip()  # read this row's events
        if is_na(cell):
            continue
        for j, event in enumerate(split_events(cell)):  # keep each event's position
            if is_na(event):
                skipped_events += 1  # count NA entries inside nonempty cells
                continue
            lines.append(build_request_line(f"row-{i}-evt-{j}", event))  # save both positions in the ID
            total_events += 1

    print(f"  {total_events} individual event requests to send ({skipped_events} NA events skipped)")
    write_jsonl_files(lines, out_dir)

# Submit
# Upload request files, start batch jobs, and save their IDs
def submit(out_dir: Path, meta_out: Path) -> None:
    print("\n── submit ──")
    client = get_client()
    batches = []

    for p in sorted(out_dir.glob("batch_input_*.jsonl")):  # includes any files left from earlier runs
        with open(str(p), "rb") as fobj:  # open the file as bytes for uploading
            uploaded = client.files.create(file=fobj, purpose="batch")
        batch = client.batches.create(
            input_file_id=uploaded.id,
            endpoint="/v1/responses",
            completion_window="24h",  # processing window
        )
        batches.append({"batch_id": batch.id, "input_file_id": uploaded.id, "file": p.name})
        print(f"  Submitted {p.name} → batch {batch.id}")
    # Save job IDs for the merge step; submitted jobs continue in the background
    with open(str(meta_out), "w", encoding="utf-8") as f:
        json.dump({"batches": batches}, f, indent=2, ensure_ascii=True)
    print(f"  Saved metadata → {meta_out}")


# Merge (use the same input, event order, and row limit as in prepare)
def merge(input_file: Path, output_xlsx: Path, meta_json: Path, max_rows: Optional[int]) -> None:
    print("\n── merge ────────────────────────────────────────────────")
    client = get_client()
    df = read_table(input_file).reset_index(drop=True)  # number rows from 0
    if max_rows:  # use the row limit if supplied; 0 also means no limit here
        df = df.head(max_rows)

    df["Subgroups"] = "NA"  # start fresh, replacing any existing subgroup labels

    results: Dict[tuple, str] = {}  # store labels by (row number, event number)
    meta = json.loads(meta_json.read_text())  # read the saved batch IDs
    successful = failed = incomplete = 0  # counts refer to downloaded answers
    all_responses = []
    # Check each saved batch once and collect its available results
    for b in meta["batches"]:
        batch = client.batches.retrieve(b["batch_id"])  # check the batch details
        if not batch.output_file_id:  # skip if no result file is available
            print(f"  Batch {b['batch_id']} not completed yet — skipping")
            continue

        content = client.files.content(batch.output_file_id).text  # download results
        for line in content.splitlines():
            obj = json.loads(line)
            all_responses.append(obj)  # keep the full record for the JSON export
            # Match this answer to its original row and event position
            cid = obj.get("custom_id", "")
            if not cid.startswith("row-"):
                continue
            try:
                parts = cid.split("-")  # row and event positions both start at 0
                row_idx = int(parts[1])
                evt_idx = int(parts[3])
            except (IndexError, ValueError):  # skip IDs that cannot be read
                continue

            if row_idx >= len(df):
                continue

            body = obj.get("response", {}).get("body", {})
            if body.get("status") == "incomplete":  # skip unfinished answers
                incomplete += 1
                continue
            # Find the answer text; missing text is counted as failed
            raw = extract_output_text(body)
            if not raw:
                failed += 1
                continue

            try:
                data = json.loads(raw)  # read the answer as JSON
                results[(row_idx, evt_idx)] = data.get("subgroup", "NA")
                successful += 1
            except json.JSONDecodeError:  # count answers that are not valid JSON
                print(f"  Warning: malformed JSON for {cid}")
                failed += 1

    # Put labels back in event order; keep NA for skipped or missing answers
    for i, row in df.iterrows():
        cell = safe_str(row.get(EVENTS_COL, "")).strip()  # read this row's events
        if is_na(cell):
            continue
        parts = []
        for j, event in enumerate(split_events(cell)):  # keep each event's position
            if is_na(event):
                parts.append("NA")
            else:
                parts.append(results.get((i, j), "NA"))  # NA if no label was found
        df.at[i, "Subgroups"] = SEPARATOR.join(parts)  # one cell, original event order

    print(f"  Successful: {successful} | Incomplete: {incomplete} | Failed: {failed}")

    json_output = output_xlsx.with_suffix(".json")  # same name and folder as Excel
    with open(str(json_output), "w", encoding="utf-8") as f:
        json.dump(all_responses, f, indent=2, ensure_ascii=False)
    print(f"  Wrote raw JSON → {json_output}")

    df.to_excel(output_xlsx, index=False)  # save Excel without the extra row index
    print(f"  Wrote XLSX → {output_xlsx}")

    # List distinct labels, leaving out NA and repeated labels
    all_subgroups = (
        df["Subgroups"].dropna()
        .str.split("|").explode().str.strip()
        .loc[lambda x: x.str.upper() != "NA"]
        .unique()
    )
    print(f"\n  {len(all_subgroups)} unique subgroups found:")
    for s in sorted(all_subgroups):
        print(f"    - {s}")

# Choose prepare, submit, or merge and read its terminal options
def main():
    ap = argparse.ArgumentParser(description="Step 1: Label pipe-separated Events → Subgroups")
    sub = ap.add_subparsers(dest="cmd", required=True)  # require a choice of step

    p1 = sub.add_parser("prepare")
    p1.add_argument("--input_file", required=True, type=Path)  # csv or excel input
    p1.add_argument("--out_dir",    required=True, type=Path)  # folder for request files
    p1.add_argument("--max_rows",   type=int, default=None)  # optional limit for testing

    p2 = sub.add_parser("submit")
    p2.add_argument("--out_dir",  required=True, type=Path)  # folder of files to upload
    p2.add_argument("--meta_out", required=True, type=Path)  # where to save batch IDs

    p3 = sub.add_parser("merge")
    p3.add_argument("--input_file",  required=True, type=Path)  # same input as prepare
    p3.add_argument("--output_xlsx", required=True, type=Path)  # excel results file
    p3.add_argument("--meta_json",   required=True, type=Path)  # batch IDs saved by submit
    p3.add_argument("--max_rows",    type=int, default=None)  # same limit as prepare

    args = ap.parse_args()  # read the command and settings you entered

    if args.cmd == "prepare":
        prepare(args.input_file, args.out_dir, args.max_rows)
    elif args.cmd == "submit":
        submit(args.out_dir, args.meta_out)
    elif args.cmd == "merge":
        merge(args.input_file, args.output_xlsx, args.meta_json, args.max_rows)


if __name__ == "__main__":  # Run main() when this script is started directly.
    main()
