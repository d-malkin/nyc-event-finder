#!/usr/bin/env python3
"""Collect public NYC event metadata into a local, unreviewed candidate CSV.

The default is a read-only preview. Use --append to save candidates locally.
No credentials, images, descriptions, attendance records, or remote writes are
used. Review source terms before collecting, and confirm each event with its
organizer before changing its pool to shortlist. Search page formats can change.
"""

import argparse
import csv
import io
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = ROOT / "data" / "local" / "candidates.csv"
COLUMNS = [
    "name", "date", "time", "organizer", "category", "venue", "source", "url",
    "admission", "registration", "description", "verified", "pool",
]
DEFAULT_QUERIES = [("design", "Design"), ("books", "Books"), ("art", "Arts")]
SEARCH_URL = "https://www.eventbrite.com/d/ny--new-york/events/?q={}"
USER_AGENT = "NYC-Event-Finder/1.0 (local event metadata collector)"
NYC = ZoneInfo("America/New_York")
PAUSE_SECONDS = 1.5
MAX_RESPONSE_BYTES = 8 * 1024 * 1024


class CollectionError(Exception):
    """An access restriction, source failure, or invalid local file."""


def clean_text(value):
    return value.strip() if isinstance(value, str) else ""


def safe_url(value):
    """Keep HTTP(S) URLs; reject credentials, controls, and non-web schemes."""
    value = clean_text(value)
    if not value or any(ord(c) < 32 or c.isspace() for c in value):
        return ""
    try:
        parsed = urllib.parse.urlsplit(value)
        if (parsed.scheme not in {"https", "http"} or not parsed.hostname
                or parsed.username or parsed.password or "\\" in value):
            return ""
        _ = parsed.port
    except ValueError:
        return ""
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc.lower(),
                                   parsed.path.rstrip("/"), "", ""))


class SameSiteRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow a source redirect to another host or downgrade to HTTP."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urllib.parse.urlsplit(newurl)
        if parsed.scheme != "https" or parsed.hostname not in {
            "eventbrite.com", "www.eventbrite.com"
        }:
            raise CollectionError("Source redirected away from the expected site; stopped.")
        if re.search(r"/(?:signin|login|captcha)(?:/|$)", parsed.path, re.I):
            raise CollectionError("Source requires authentication or a challenge; stopped.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_search(term):
    """One public search request; no retries or challenge-bypass behavior."""
    request = urllib.request.Request(
        SEARCH_URL.format(urllib.parse.quote(term)),
        headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
    )
    try:
        with urllib.request.build_opener(SameSiteRedirect()).open(request, timeout=30) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
            if len(body) > MAX_RESPONSE_BYTES:
                raise CollectionError("Source response exceeded the size limit; stopped.")
            text = body.decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        if exc.code in {401, 403, 429}:
            raise CollectionError(f"Source restricted access (HTTP {exc.code}); stopped.") from exc
        raise CollectionError(f"Source returned HTTP {exc.code}; stopped.") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise CollectionError("Could not read the source; stopped without saving.") from exc
    if re.search(r"<title[^>]*>[^<]*(?:access denied|captcha|just a moment|verif|sign in|log in)", text, re.I):
        raise CollectionError("Source returned an access challenge; stopped.")
    return text


class JsonLdParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.blocks = []
        self.current = None

    def handle_starttag(self, tag, attrs):
        if tag == "script" and dict(attrs).get("type", "").lower() == "application/ld+json":
            self.current = []

    def handle_data(self, data):
        if self.current is not None:
            self.current.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self.current is not None:
            self.blocks.append("".join(self.current))
            self.current = None


def extract_events(html):
    """Read standard JSON-LD and embedded jsonld values with JSON's own parser.

    JSONDecoder.raw_decode handles brackets and escaped quotes inside strings;
    counting bracket characters would incorrectly truncate those event names.
    """
    parser = JsonLdParser()
    parser.feed(html)
    objects = []
    decoder = json.JSONDecoder()
    for block in parser.blocks:
        try:
            objects.append(json.loads(block))
        except (json.JSONDecodeError, RecursionError):
            continue
    for match in re.finditer(r'"jsonld"\s*:\s*', html):
        try:
            objects.append(decoder.raw_decode(html, match.end())[0])
        except (json.JSONDecodeError, RecursionError):
            continue
    events = []
    pending = list(objects)
    while pending:
        node = pending.pop()
        if isinstance(node, dict):
            types = node.get("@type", [])
            types = types if isinstance(types, list) else [types]
            if any(isinstance(t, str) and t.rsplit("/", 1)[-1].endswith("Event") for t in types):
                events.append(node)
            pending.extend(node.values())
        elif isinstance(node, list):
            pending.extend(node)
    return events


def event_start(raw):
    """Return the NYC calendar day and local time, or None for an invalid date."""
    raw = clean_text(raw)
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
            return date.fromisoformat(raw), ""
        if not re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", raw):
            return None
        when = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if when.tzinfo is not None:
            when = when.astimezone(NYC)
        return when.date(), when.strftime("%H:%M")
    except ValueError:
        return None


def admission(event):
    offers = event.get("offers", [])
    offers = offers if isinstance(offers, list) else [offers]
    prices = []
    for offer in offers:
        if not isinstance(offer, dict):
            continue
        currency = clean_text(offer.get("priceCurrency"))
        if currency != "USD":
            continue
        for key in ("price", "lowPrice", "highPrice"):
            try:
                amount = Decimal(str(offer.get(key)))
                if amount.is_finite() and amount >= 0:
                    prices.append(amount)
            except InvalidOperation:
                pass
    if prices:
        def label(amount):
            return "Free" if amount == 0 else "$" + format(amount, ".2f").removesuffix(".00")
        low, high = min(prices), max(prices)
        return label(low) if low == high else f"{label(low)}–{label(high)}"
    return "Free" if event.get("isAccessibleForFree") is True else "Unknown"


def candidate_rows(events, category, today, days, known=None):
    """Normalize bounded, deduplicated metadata; never promote an event."""
    horizon = today + timedelta(days=days)
    seen = set(known or ())
    rows = []
    for event in events:
        url = safe_url(event.get("url"))
        start = event_start(event.get("startDate"))
        name = clean_text(event.get("name"))
        if not url or url in seen or not name or start is None:
            continue
        day, event_time = start
        if not today <= day <= horizon:
            continue
        location = event.get("location")
        venue = clean_text(location.get("name")) if isinstance(location, dict) else clean_text(location)
        organizer = event.get("organizer")
        organizer = clean_text(organizer.get("name")) if isinstance(organizer, dict) else clean_text(organizer)
        row = dict.fromkeys(COLUMNS, "")
        row.update(name=name, date=day.isoformat(), time=event_time,
                   organizer=organizer, category=category, venue=venue,
                   source="Eventbrite public listing", url=url,
                   admission=admission(event), verified="Needs review", pool="candidate")
        rows.append(row)
        seen.add(url)
    return rows


def read_existing(path):
    """Refuse unfamiliar CSVs rather than silently dropping their columns."""
    if path.is_symlink():
        raise CollectionError("Output must be a regular file, not a symlink.")
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != COLUMNS:
            raise CollectionError("Output CSV has an unexpected schema; no changes made.")
        rows = list(reader)
    if any(None in row or any(value is None for value in row.values()) for row in rows):
        raise CollectionError("Output CSV has malformed rows; no changes made.")
    return rows


def validate_output(path):
    """Keep collected data out of the public demo and other repository files."""
    resolved = path.resolve()
    root = ROOT.resolve()
    local_data = root / "data" / "local"
    demo = root / "data" / "demo.csv"
    if resolved.suffix.lower() != ".csv":
        raise CollectionError("Candidate output must be a .csv file.")
    if resolved == demo or (resolved.exists() and demo.exists() and resolved.samefile(demo)):
        raise CollectionError("The public demo cannot receive collected event data.")
    if resolved.is_relative_to(root) and not resolved.is_relative_to(local_data):
        raise CollectionError("Repository output must be inside data/local; choose an external CSV otherwise.")


def append_candidates(path, rows):
    validate_output(path)
    existing = read_existing(path)
    known = {safe_url(row["url"]) for row in existing}
    new = []
    for row in rows:
        if set(row) != set(COLUMNS) or row["pool"] != "candidate":
            raise CollectionError("Only complete candidate rows may be appended.")
        url = safe_url(row["url"])
        if url and url not in known:
            new.append(row)
            known.add(url)
    if not new:
        return 0
    # Validate and serialize first so bad input never leaves a partial append.
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=COLUMNS)
    if not path.exists():
        writer.writeheader()
    writer.writerows(new)
    path.parent.mkdir(parents=True, exist_ok=True)
    needs_newline = False
    if path.exists() and path.stat().st_size:
        with path.open("rb") as handle:
            handle.seek(-1, 2)
            needs_newline = handle.read(1) not in {b"\n", b"\r"}
    with path.open("a", newline="", encoding="utf-8") as handle:
        if needs_newline:
            handle.write("\n")
        handle.write(buffer.getvalue())
    return len(new)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--append", action="store_true", help="save new candidates locally")
    parser.add_argument("--days", type=int, default=30, help="look ahead 1–90 days (default: 30)")
    parser.add_argument("--query", action="append", help="search term; repeat to use multiple terms")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="local candidates CSV")
    args = parser.parse_args(argv)
    if not 1 <= args.days <= 90:
        parser.error("--days must be between 1 and 90")
    queries = [(q.strip(), "Unsorted") for q in args.query] if args.query else DEFAULT_QUERIES
    if any(not q or len(q) > 100 for q, _ in queries):
        parser.error("each --query must contain 1–100 characters")
    try:
        if args.append:
            validate_output(args.output)
        existing = read_existing(args.output)
        known = {safe_url(row["url"]) for row in existing}
        today = datetime.now(NYC).date()
        rows = []
        for index, (term, category) in enumerate(queries):
            if index:
                time.sleep(PAUSE_SECONDS)
            events = extract_events(fetch_search(term))
            if not events:
                print("No readable event records for a query; the source format or access may have changed.", file=sys.stderr)
            new = candidate_rows(events, category, today, args.days, known)
            known.update(row["url"] for row in new)
            rows.extend(new)
        rows.sort(key=lambda row: (row["date"], row["time"], row["name"]))
        for row in rows:
            print(f"{row['date']} {row['time']:5} | {row['name']} | {row['admission']}")
        if args.append:
            print(f"Saved {append_candidates(args.output, rows)} new candidates. Review before shortlisting.")
        else:
            print(f"Preview: {len(rows)} new candidates; no files written. Use --append to save locally.")
    except (CollectionError, OSError, UnicodeError, csv.Error) as exc:
        print(f"Collection stopped: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
