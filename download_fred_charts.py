#!/usr/bin/env python3
"""Download the supplied saved FRED graphs as CSV and PNG, retaining transformations.

Run: python3 download_fred_charts.py --output-dir fred_charts
The saved graph export endpoint applies its own formulas and unit transformations.
This script never substitutes a download of the underlying raw series.
Uses only the Python standard library; no API key is required.
"""

from __future__ import annotations

import argparse
import csv
from datetime import date, datetime, timezone
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import struct
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import zlib


BASE = "https://fred.stlouisfed.org/graph/"
DEFAULT_CONFIG = Path(__file__).with_name("fred_graphs.json")


def atomic_write(path: Path, payload: bytes) -> None:
    """Replace one completed artifact; never leave a partially downloaded CSV."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=".fred-", dir=path.parent)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(payload)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def fetch(url: str, timeout: float = 30, attempts: int = 3) -> bytes:
    request = Request(url)
    for attempt in range(attempts):
        try:
            with urlopen(request, timeout=timeout) as response:
                payload = response.read(25_000_001)
                if len(payload) > 25_000_000:
                    raise ValueError("FRED export exceeded the 25 MB download limit")
                return payload
        except (HTTPError, URLError, TimeoutError, OSError):
            if attempt + 1 == attempts:
                raise
            time.sleep(2 ** attempt)
    raise RuntimeError("Download did not return data")


def inspect_csv(payload: bytes) -> dict:
    """Reject errors/HTML and capture the actual observation range per column."""
    reader = csv.reader(io.StringIO(payload.decode("utf-8-sig")))
    header = next(reader, [])
    if len(header) < 2 or header[0].lower() not in ("observation_date", "date"):
        raise ValueError("Response is not a FRED CSV with a date column")
    if len(header) != len(set(header)):
        raise ValueError("FRED export contains duplicate column labels")
    stats = {column: {"first_observation": None, "last_observation": None, "observations": 0, "missing": 0} for column in header[1:]}
    rows = 0
    previous_date = None
    first_date = None
    for row in reader:
        if not row:
            continue
        if len(row) != len(header):
            raise ValueError(f"CSV row {rows + 2} has an unexpected column count")
        observation_date = date.fromisoformat(row[0])
        if previous_date is not None and observation_date <= previous_date:
            raise ValueError("FRED observation dates are duplicated or out of order")
        if first_date is None:
            first_date = observation_date
        previous_date = observation_date
        for column, cell in zip(header[1:], row[1:]):
            record = stats[column]
            if cell.strip() in ("", "."):
                record["missing"] += 1
                continue
            value = float(cell)
            if not math.isfinite(value):
                raise ValueError(f"Non-finite value in {column} on {row[0]}")
            if record["first_observation"] is None:
                record["first_observation"] = row[0]
            record["last_observation"] = row[0]
            record["observations"] += 1
        rows += 1
    if not rows or not any(item["observations"] for item in stats.values()):
        raise ValueError("FRED export has no numeric observations")
    return {"columns": header[1:], "rows": rows, "first_date": str(first_date), "last_date": str(previous_date), "series": stats}


def inspect_png(payload: bytes) -> dict:
    """Check native FRED PNG structure and reject its occasional blank render."""
    if payload[:8] != b"\x89PNG\r\n\x1a\n" or len(payload) < 33:
        raise ValueError("FRED did not return a PNG image")
    width, height, depth, color_type, compression, filtering, interlace = struct.unpack(">IIBBBBB", payload[16:29])
    if not (100 <= width <= 5000 and 100 <= height <= 5000):
        raise ValueError("Unexpected PNG dimensions")
    if depth != 8 or color_type not in (2, 6) or compression or filtering or interlace:
        raise ValueError("Unexpected FRED PNG format; cannot verify the rendered chart")
    channels = 3 if color_type == 2 else 4
    chunks, position = [], 8
    while position + 12 <= len(payload):
        length = struct.unpack(">I", payload[position:position + 4])[0]
        if position + length + 12 > len(payload):
            raise ValueError("Truncated PNG chunk")
        if payload[position + 4:position + 8] == b"IDAT":
            chunks.append(payload[position + 8:position + 8 + length])
        position += length + 12
    stride = width * channels
    expected = height * (stride + 1)
    pixels = zlib.decompressobj().decompress(b"".join(chunks), expected + 1)
    if len(pixels) != expected:
        raise ValueError("PNG pixel data are incomplete")
    previous = bytearray(stride)
    colors = set()
    for y in range(height):
        start = y * (stride + 1)
        filter_type = pixels[start]
        row = bytearray(pixels[start + 1:start + stride + 1])
        if filter_type not in range(5):
            raise ValueError("Invalid PNG scanline filter")
        for x in range(stride):
            left = row[x - channels] if x >= channels else 0
            above = previous[x]
            upper_left = previous[x - channels] if x >= channels else 0
            if filter_type == 1:
                predictor = left
            elif filter_type == 2:
                predictor = above
            elif filter_type == 3:
                predictor = (left + above) // 2
            elif filter_type == 4:
                prediction = left + above - upper_left
                distances = (abs(prediction - left), abs(prediction - above), abs(prediction - upper_left))
                predictor = (left, above, upper_left)[distances.index(min(distances))]
            else:
                predictor = 0
            row[x] = (row[x] + predictor) & 255
        colors.update(bytes(row[x:x + 3]) for x in range(0, stride, channels))
        if len(colors) > 16:
            return {"width": width, "height": height, "validation": "PNG decoded; nonblank content confirmed"}
        previous = row
    raise ValueError("FRED returned a blank graph image; CSV remains available")


def download_graphs(output_dir: str | Path, config_path: str | Path = DEFAULT_CONFIG, selected: list[str] | None = None, timeout: float = 30, include_png: bool = True) -> dict:
    output_dir = Path(output_dir).resolve()
    configuration = json.loads(Path(config_path).read_text(encoding="utf-8"))
    graphs = configuration["graphs"]
    keys = [graph["key"] for graph in graphs]
    if len(keys) != len(set(keys)):
        raise ValueError("Graph configuration has duplicate keys")
    if selected:
        unknown = set(selected) - set(keys)
        if unknown:
            raise ValueError("Unknown graph key(s): " + ", ".join(sorted(unknown)))
        graphs = [graph for graph in graphs if graph["key"] in selected]
    report = {"fetched_at_utc": datetime.now(timezone.utc).isoformat(), "output_dir": str(output_dir), "graphs": [], "errors": []}
    for graph in graphs:
        key, graph_id = graph["key"], graph["graph_id"]
        try:
            if not re.fullmatch(r"[a-zA-Z0-9_-]+", key) or not re.fullmatch(r"[a-zA-Z0-9]+", graph_id):
                raise ValueError("Graph key or ID contains invalid characters")
            url = BASE + "fredgraph.csv?" + urlencode({"g": graph_id})
            payload = fetch(url, timeout=timeout)
            details = inspect_csv(payload)
            expected = graph.get("expected_columns")
            if expected is not None and details["columns"] != expected:
                raise ValueError("Saved graph columns changed; review configuration before replacing the prior export. Received: " + ", ".join(details["columns"]))
            metadata = {**graph, **details, "download_url": url, "fetched_at_utc": datetime.now(timezone.utc).isoformat(), "sha256": hashlib.sha256(payload).hexdigest(), "csv_file": key + ".csv", "note": "Data are exported by saved graph ID. FRED applies the saved graph's transformations; missing data remain missing. Dates report observations, not publication dates."}
            atomic_write(output_dir / (key + ".csv"), payload)
            if include_png:
                # Native dimensions retain the saved graph settings. Overriding
                # width/height can cause FRED to return a blank image with HTTP 200.
                png_url = BASE + "fredgraph.png?" + urlencode({"g": graph_id})
                try:
                    png_payload = fetch(png_url, timeout=timeout)
                    png_details = inspect_png(png_payload)
                    atomic_write(output_dir / (key + ".png"), png_payload)
                    metadata["png"] = {**png_details, "file": key + ".png", "download_url": png_url, "sha256": hashlib.sha256(png_payload).hexdigest()}
                except (OSError, ValueError, struct.error, zlib.error) as error:
                    metadata["png_error"] = str(error)
                    report["errors"].append({"key": key, "graph_id": graph_id, "artifact": "PNG", "error": str(error)})
            atomic_write(output_dir / (key + ".metadata.json"), (json.dumps(metadata, indent=2) + "\n").encode())
            report["graphs"].append(metadata)
        except (OSError, ValueError, KeyError, csv.Error) as error:
            report["errors"].append({"key": key, "graph_id": graph_id, "error": str(error)})
    atomic_write(output_dir / "download_report.json", (json.dumps(report, indent=2) + "\n").encode())
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).with_name("fred_charts"))
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--graph", action="append", help="Download only this configured key; may be repeated")
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--csv-only", action="store_true", help="Skip native PNG chart downloads")
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    try:
        report = download_graphs(args.output_dir, args.config, args.graph, args.timeout, include_png=not args.csv_only)
    except (OSError, ValueError, KeyError) as error:
        parser.exit(2, f"Error: {error}\n")
    for graph in report["graphs"]:
        formats = "CSV + PNG" if "png" in graph else "CSV"
        print(f"Downloaded {graph['key']} ({formats}): {graph['rows']} rows, {len(graph['columns'])} series, through {graph['last_date']}")
    for error in report["errors"]:
        print(f"FAILED {error['key']}: {error['error']}")
    print(f"Saved in {report['output_dir']}")
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
