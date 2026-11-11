#!/usr/bin/env python3
"""Build an offline-capable event finder from an explicit public CSV schema."""

import argparse
import csv
import json
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
COLUMNS = [
    "name", "date", "time", "organizer", "category", "venue", "source", "url",
    "admission", "registration", "description", "verified", "pool",
]
DEMO_DATE = "2026-11-11"


def safe_url(value):
    if not value:
        return ""
    parsed = urlsplit(value)
    if (parsed.scheme not in ("https", "http") or not parsed.hostname
            or parsed.username or parsed.password or any(c.isspace() for c in value)
            or "\\" in value):
        raise ValueError("Event URLs must be http(s), without credentials or whitespace")
    return value


def validate_custom_output(output):
    resolved = Path(output).resolve()
    # Within this repository, custom datasets may only be written to ignored dist/.
    if ROOT in resolved.parents and not (ROOT / "dist") in resolved.parents:
        raise ValueError("Custom data inside this repository must be written under dist/")
    if resolved == ROOT:
        raise ValueError("Output must be an HTML file")


def load_events(path):
    events = []
    with Path(path).open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if (not reader.fieldnames or len(reader.fieldnames) != len(COLUMNS)
                or set(reader.fieldnames) != set(COLUMNS)):
            raise ValueError("CSV headers must match the public schema exactly; extra fields are rejected")
        for line, row in enumerate(reader, 2):
            if None in row or any(v is None for v in row.values()):
                raise ValueError(f"Row {line}: incorrect number of fields")
            event = {key: row[key].strip() for key in COLUMNS}
            if not event["name"]:
                raise ValueError(f"Row {line}: event name is required")
            try:
                parsed_date = date.fromisoformat(event["date"])
                if parsed_date.isoformat() != event["date"]:
                    raise ValueError()
            except ValueError:
                raise ValueError(f"Row {line}: date must be YYYY-MM-DD") from None
            if event["pool"] not in ("shortlist", "candidate"):
                raise ValueError(f"Row {line}: pool must be shortlist or candidate")
            event["url"] = safe_url(event["url"])
            events.append(event)
    return sorted(events, key=lambda event: (event["date"], event["time"], event["name"]))


def render(events, demo=False):
    # Escape '<' so an imported value cannot terminate the JSON script element.
    data = json.dumps({"events": events, "demo": demo, "demoDate": DEMO_DATE},
                      ensure_ascii=True).replace("<", "\\u003c")
    template = (ROOT / "web/template.html").read_text(encoding="utf-8")
    style = (ROOT / "web/style.css").read_text(encoding="utf-8")
    script = (ROOT / "web/app.js").read_text(encoding="utf-8")
    # Replace content last, so CSV strings cannot collide with template markers.
    return template.replace("__STYLE__", style).replace("__SCRIPT__", script).replace("__DATA__", data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, help="Explicitly chosen public-schema CSV")
    parser.add_argument("--output", type=Path, help="Defaults to index.html for demo, dist/index.html for custom data")
    args = parser.parse_args()
    demo = args.csv is None
    output = args.output or ROOT / ("index.html" if demo else "dist/index.html")
    try:
        if not demo:
            validate_custom_output(output)
        events = load_events(args.csv or ROOT / "data/demo.csv")
        page = render(events, demo)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(page, encoding="utf-8")
    print(f"Built {len(events)} {'fictional demo' if demo else 'local'} events → {output.name}")


if __name__ == "__main__":
    main()
