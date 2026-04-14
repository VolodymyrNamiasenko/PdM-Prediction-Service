#!/usr/bin/env python3
"""
Extract 1-hour windows before each breakdown event from machine telemetry JSON.

Usage:
    python extract_breakdown_windows.py input.json [--output-dir OUTPUT_DIR]

The script:
1. Loads a JSON array of machine events
2. Finds all events where "brake_down": 1
3. For each breakdown, collects all events from the preceding 1 hour (same machine)
4. Saves each chunk as a separate JSON file
"""

import json
import argparse
from datetime import datetime, timedelta
from pathlib import Path


def load_events(filepath: str) -> list[dict]:
    with open(filepath, "r") as f:
        content = f.read().strip()
        # Handle trailing commas (common in pasted snippets)
        if content.endswith(","):
            content = content[:-1]
        # Wrap in array brackets if not already
        if not content.startswith("["):
            content = f"[{content}]"
        return json.loads(content)


def parse_timestamp(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def extract_breakdown_windows(events: list[dict], window_hours: float = 1.0) -> list[list[dict]]:
    """Find breakdown events and collect the preceding window of data per machine."""

    window_delta = timedelta(hours=window_hours)

    # Group events by machine_id
    by_machine: dict[str, list[dict]] = {}
    for ev in events:
        mid = ev["machine_id"]
        by_machine.setdefault(mid, []).append(ev)

    # Sort each machine's events by timestamp
    for mid in by_machine:
        by_machine[mid].sort(key=lambda e: parse_timestamp(e["timestamp"]))

    chunks: list[list[dict]] = []

    for mid, machine_events in by_machine.items():
        for ev in machine_events:
            if ev["features"].get("brake_down") == 1:
                bd_time = parse_timestamp(ev["timestamp"])
                window_start = bd_time - window_delta

                # Collect events in [window_start, bd_time] for this machine
                chunk = [
                    e
                    for e in machine_events
                    if window_start <= parse_timestamp(e["timestamp"]) <= bd_time
                ]

                if chunk:
                    chunks.append(chunk)

    # Sort chunks by the breakdown timestamp (last event in each chunk)
    chunks.sort(key=lambda c: parse_timestamp(c[-1]["timestamp"]))
    return chunks


def main():
    parser = argparse.ArgumentParser(description="Extract pre-breakdown event windows.")
    parser.add_argument("input", help="Path to input JSON file")
    parser.add_argument(
        "--output-dir",
        default="breakdown_chunks",
        help="Output directory (default: breakdown_chunks)",
    )
    parser.add_argument(
        "--window-hours",
        type=float,
        default=1.0,
        help="Hours before breakdown to capture (default: 1.0)",
    )
    args = parser.parse_args()

    events = load_events(args.input)
    print(f"Loaded {len(events)} events")

    chunks = extract_breakdown_windows(events, window_hours=args.window_hours)
    print(f"Found {len(chunks)} breakdown window(s)")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    for i, chunk in enumerate(chunks, start=1):
        machine_id = chunk[-1]["machine_id"]
        bd_ts = chunk[-1]["timestamp"].replace(":", "-")
        filename = f"breakdown_{i:03d}_{machine_id}_{bd_ts}.json"
        filepath = output_dir / filename

        with open(filepath, "w") as f:
            json.dump(chunk, f, indent=2)

        start_ts = chunk[0]["timestamp"]
        end_ts = chunk[-1]["timestamp"]
        print(
            f"  [{i}] {machine_id}: {len(chunk)} events  |  {start_ts} → {end_ts}  →  {filepath}"
        )

    print("Done.")


if __name__ == "__main__":
    main()
