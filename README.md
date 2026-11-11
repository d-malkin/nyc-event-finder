# NYC Event Finder

A mobile-friendly event browser for turning a long list of possibilities into a small set of plans. Built with HTML, CSS, vanilla JavaScript and Python's standard library.

**The included demo contains eight fictional events.** It is a working product demonstration, not a current NYC events feed. Its sample calendar is fixed to November 11, 2026 so the past-event filter remains reproducible.

## Try it

Open `index.html` in a browser. No installation, account, backend or network connection is needed for the demo.

To serve it locally:

```sh
python3 -m http.server 8000
```

Then open http://localhost:8000. Use Python 3.9 or later with the system time-zone database.

## What it does

- Searches event names, organizers, venues and descriptions.
- Filters by category, free admission, shortlist/candidates and past dates.
- Groups events by date and flags two shortlisted events on the same day.
- Shows unknown admission and missing start times explicitly.
- Adapts to narrow screens and the device's light or dark appearance.
- Keeps collection separate from human review: collected events are candidates until someone checks them.

The interface uses system fonts, semantic headings, labeled controls, keyboard focus states and an announced result count. It makes no external requests, loads no third-party images and includes no analytics. Real organizer links, when supplied, open only after a click.

## How it is built

```text
public-schema CSV → scripts/build.py → standalone HTML
public search metadata → scripts/collect.py → local candidate CSV → human review
```

`web/` holds the readable HTML template, CSS and JavaScript. The builder embeds those files and the event data into one HTML file. The checked-in `index.html` is generated only from `data/demo.csv`. Custom builds use `dist/`, which Git ignores.

The demo has a fixed sample clock. Custom builds calculate the current date in `America/New_York` in the browser, including after a tab resumes or crosses midnight. Events are not refreshed automatically.

## Rebuild the demo

```sh
python3 scripts/build.py
```

## Use your own event data locally

Create `data/local/events.csv` using the headers in `data/demo.csv`:

```text
name,date,time,organizer,category,venue,source,url,admission,registration,description,verified,pool
```

Dates must be `YYYY-MM-DD`; use New York local times, preferably `HH:MM`. `pool` must be `candidate` or `shortlist`. Use `Unknown` when admission is unconfirmed. Only exactly `Free`, `$0` or `$0.00` qualifies for the free-only filter; a mixed free/paid range does not.

The builder rejects missing, duplicate or extra columns, invalid dates and unsafe link schemes. It has no fields for personal attendance or private notes. A schema check cannot detect sensitive text placed inside a permitted field: review the entire CSV before sharing any output.

```sh
python3 scripts/build.py --csv data/local/events.csv
python3 -m http.server 8000 --directory dist
```

Every row is embedded in the generated page. Filters hide rows visually; they do not restrict access. Local datasets and generated custom pages are ignored by Git. Within this repository, the builder restricts custom output to `dist/`, and the collector restricts CSV output to `data/local/`. Explicit output paths outside the repository are also supported. These safeguards do not replace reviewing content before sharing it.

## Optional candidate collection

The collector reads structured metadata from Eventbrite's public NYC search pages. It is an on-demand helper, not an official integration or a complete event directory. Search layouts, coverage and access can change; an empty result is not proof there are no events. Check source terms before use and verify dates, venues, admission and cancellations with organizers.

```sh
# Preview candidates without writing a file.
python3 scripts/collect.py --query "design" --days 30

# Save candidates locally for review.
python3 scripts/collect.py --query "books" --append
```

Without `--query`, it searches design, books and art. `--query` can be repeated; `--days` accepts 1–90. `--append` saves to `data/local/candidates.csv`, or an explicit `--output` path. It deduplicates event links, preserves existing rows and never auto-promotes a candidate. It uses no credentials, copies no event descriptions or images, and stops on access restrictions without retries or bypasses. Collected metadata still needs review before publication.

No scheduler or automatic collection is configured. The collector is covered by offline fixtures; current live source access is not guaranteed.

## Verification

```sh
python3 -m unittest discover -s tests -v
node --check web/app.js  # optional JavaScript syntax check
```

Tests cover CSV boundaries, unsafe URLs, embedded-data escaping, date handling, metadata parsing, deduplication, access-restriction handling and preview mode. The demo can be rebuilt deterministically and is checked against its source.

## Project scope

An independent portfolio project developed with AI assistance. The focus is the complete workflow: event discovery, explicit uncertainty, human curation, data handling and a usable mobile interface. The public repository contains fictional fixtures and standalone source; it does not include a production dataset or backend. No affiliation with or endorsement by event platforms or organizers is implied.
