"""Offline collector regression tests using entirely fictional events."""

import csv
import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from datetime import date
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError


spec = importlib.util.spec_from_file_location("collect", Path(__file__).resolve().parents[1] / "scripts" / "collect.py")
collect = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collect)


def event(**changes):
    record = {
        "@type": "Event", "name": 'Sample talk: [type] and "letters"',
        "startDate": "2030-04-03T23:00:00Z", "url": "https://example.com/events/type?ref=demo",
        "organizer": {"name": "Example organizer"}, "location": {"name": "Example venue"},
    }
    record.update(changes)
    return record


class CollectorTests(unittest.TestCase):
    def test_embedded_json_handles_brackets_and_escaped_quotes(self):
        html = "window.data={\"jsonld\": " + json.dumps([event()]) + ",\"tail\":true};"
        self.assertEqual(collect.extract_events(html)[0]["name"], event()["name"])

    def test_json_ld_graph_and_event_subtypes(self):
        payload = {"@graph": [event(**{"@type": ["Thing", "https://schema.org/MusicEvent"]})]}
        html = "<script type='application/ld+json'>" + json.dumps(payload) + "</script>"
        self.assertEqual(len(collect.extract_events(html)), 1)
        self.assertEqual(collect.extract_events('<script type="application/ld+json">{bad}</script>'), [])

    def test_invalid_and_unsafe_urls_are_rejected(self):
        for url in ["javascript:alert(1)", "data:text/html,x", "https://u:p@example.com/a",
                    "https://example.com/a\n", "https://example.com:bad/a", "//example.com/a",
                    "https://example.com\\@other.example/a"]:
            with self.subTest(url=url):
                # Whitespace around a safe URL is harmless and stripped.
                if url.endswith("\n"):
                    url = "https://example.com/a\nb"
                self.assertEqual(collect.safe_url(url), "")

    def test_date_window_dedup_and_no_automatic_promotion(self):
        events = [event(), event(url="https://example.com/events/type/?other=value"),
                  event(url="https://example.com/past", startDate="2029-01-01"),
                  event(url="https://example.com/later", startDate="2031-01-01"),
                  event(url="https://example.com/invalid", startDate="2030-02-30"),
                  event(url="javascript:alert(1)"), event(name="")]
        rows = collect.candidate_rows(events, "Design", date(2030, 4, 1), 7)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["pool"], "candidate")
        self.assertEqual(rows[0]["verified"], "Needs review")
        self.assertEqual(rows[0]["description"], "")
        self.assertEqual(rows[0]["time"], "19:00")
        self.assertEqual(set(rows[0]), set(collect.COLUMNS))

    def test_nyc_timezone_uses_local_day(self):
        self.assertEqual(collect.event_start("2030-04-04T01:30:00Z"), (date(2030, 4, 3), "21:30"))
        self.assertEqual(collect.event_start("2030-04-04"), (date(2030, 4, 4), ""))
        self.assertIsNone(collect.event_start("not a date"))

    def test_prices_stay_unknown_without_evidence(self):
        self.assertEqual(collect.admission(event()), "Unknown")
        self.assertEqual(collect.admission(event(isAccessibleForFree=True)), "Free")
        self.assertEqual(collect.admission(event(offers={"price": "0", "priceCurrency": "USD"})), "Free")
        self.assertEqual(collect.admission(event(offers={"lowPrice": "0", "highPrice": "20", "priceCurrency": "USD"})), "Free–$20")
        self.assertEqual(collect.admission(event(offers={"price": "NaN"})), "Unknown")
        self.assertEqual(collect.admission(event(offers={"price": "20", "priceCurrency": "EUR"})), "Unknown")
        self.assertEqual(collect.admission(event(offers={"price": "20"})), "Unknown")

    def test_append_deduplicates_and_retains_reviewed_rows(self):
        rows = collect.candidate_rows([event()], "Design", date(2030, 4, 1), 7)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "candidates.csv"
            self.assertEqual(collect.append_candidates(path, rows), 1)
            self.assertEqual(collect.append_candidates(path, rows), 0)
            self.assertEqual(len(collect.read_existing(path)), 1)
            with path.open("w", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=collect.COLUMNS)
                writer.writeheader()
                writer.writerow({**rows[0], "pool": "shortlist"})
            self.assertEqual(collect.append_candidates(path, rows), 0)
            self.assertEqual(collect.read_existing(path)[0]["pool"], "shortlist")

    def test_schema_mismatch_and_symlink_never_written(self):
        rows = collect.candidate_rows([event()], "Design", date(2030, 4, 1), 7)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "unrelated.csv"
            original = "name,private_notes\nSample,do not import\n"
            path.write_text(original)
            with self.assertRaises(collect.CollectionError):
                collect.append_candidates(path, rows)
            self.assertEqual(path.read_text(), original)
            link = Path(folder) / "symlink.csv"
            link.symlink_to(path)
            with self.assertRaises(collect.CollectionError):
                collect.read_existing(link)

    def test_append_handles_missing_final_newline(self):
        rows = collect.candidate_rows([event()], "Design", date(2030, 4, 1), 7)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "candidates.csv"
            path.write_text(",".join(collect.COLUMNS))
            self.assertEqual(collect.append_candidates(path, rows), 1)
            self.assertEqual(collect.read_existing(path)[0]["name"], event()["name"])

    def test_output_guard_protects_demo_and_resolved_aliases(self):
        rows = collect.candidate_rows([event()], "Design", date(2030, 4, 1), 7)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "repository"
            data = root / "data"
            data.mkdir(parents=True)
            demo = data / "demo.csv"
            original = ",".join(collect.COLUMNS) + "\n"
            demo.write_text(original)
            alias = Path(folder) / "alias.csv"
            alias.symlink_to(demo)
            directory_alias = Path(folder) / "data-alias"
            directory_alias.symlink_to(data, target_is_directory=True)
            with patch.object(collect, "ROOT", root):
                for output in [demo, data / "local" / ".." / "demo.csv", alias,
                               directory_alias / "demo.csv", data / "events.csv",
                               root / "events.csv"]:
                    with self.subTest(output=output.name), self.assertRaises(collect.CollectionError):
                        collect.append_candidates(output, rows)
            self.assertEqual(demo.read_text(), original)
            self.assertFalse((root / "events.csv").exists())

    def test_output_guard_allows_local_and_external_csv(self):
        rows = collect.candidate_rows([event()], "Design", date(2030, 4, 1), 7)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "repository"
            with patch.object(collect, "ROOT", root):
                for output in [root / "data" / "local" / "candidates.csv",
                               Path(folder) / "external.csv"]:
                    self.assertEqual(collect.append_candidates(output, rows), 1)
                with self.assertRaises(collect.CollectionError):
                    collect.append_candidates(Path(folder) / "external.html", rows)

    def test_append_demo_rejected_before_network_access(self):
        with patch.object(collect, "fetch_search") as fetch, redirect_stderr(io.StringIO()):
            self.assertEqual(collect.main(["--append", "--output", str(collect.ROOT / "data" / "demo.csv")]), 1)
            fetch.assert_not_called()

    def test_access_restriction_stops_without_retry(self):
        with patch.object(collect.urllib.request, "build_opener") as opener:
            opener.return_value.open.side_effect = HTTPError("https://example.com", 403, "Forbidden", {}, None)
            with self.assertRaisesRegex(collect.CollectionError, "restricted access"):
                collect.fetch_search("art")
            self.assertEqual(opener.return_value.open.call_count, 1)

    def test_preview_does_not_create_output(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "missing" / "candidates.csv"
            with patch.object(collect, "fetch_search", return_value=""), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(collect.main(["--query", "art", "--output", str(output)]), 0)
            self.assertFalse(output.exists())
            self.assertFalse(output.parent.exists())

    def test_access_failure_leaves_existing_file_untouched(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "candidates.csv"
            original = ",".join(collect.COLUMNS) + "\n"
            output.write_text(original)
            with patch.object(collect, "fetch_search", side_effect=collect.CollectionError("restricted")), redirect_stderr(io.StringIO()):
                self.assertEqual(collect.main(["--append", "--query", "art", "--output", str(output)]), 1)
            self.assertEqual(output.read_text(), original)


if __name__ == "__main__":
    unittest.main()
