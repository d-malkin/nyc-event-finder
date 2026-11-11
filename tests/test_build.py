import csv
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("build", ROOT / "scripts/build.py")
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


class BuildTests(unittest.TestCase):
    def write_csv(self, folder, fields, row):
        path = Path(folder) / "input.csv"
        with path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerow(row)
        return path

    def event(self):
        return dict.fromkeys(build.COLUMNS, "") | {
            "name":"Example", "date":"2026-11-12", "pool":"candidate"
        }

    def test_demo_has_only_public_fields(self):
        events = build.load_events(ROOT / "data/demo.csv")
        self.assertEqual(len(events), 8)
        self.assertTrue(all(set(e) == set(build.COLUMNS) for e in events))
        self.assertTrue(all(not e["url"] for e in events))

    def test_extra_private_column_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            fields = build.COLUMNS + ["private_notes"]
            path = self.write_csv(folder, fields, self.event() | {"private_notes":"Do not export"})
            with self.assertRaisesRegex(ValueError, "extra fields"):
                build.load_events(path)

    def test_invalid_date_and_pool_are_rejected(self):
        for changes in [{"date":"2026-02-30"}, {"date":"20261112"}, {"pool":"private"}]:
            with self.subTest(changes=changes), tempfile.TemporaryDirectory() as folder:
                path = self.write_csv(folder, build.COLUMNS, self.event() | changes)
                with self.assertRaises(ValueError):
                    build.load_events(path)

    def test_unsafe_urls_are_rejected(self):
        for url in ["javascript:alert(1)", "data:text/html,test", "file:///tmp/example", "https://user:secret@example.org", "https://example.org/\nprivate", "https://example.org\\@other.test"]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                build.safe_url(url)
        self.assertEqual(build.safe_url("https://example.org/event"), "https://example.org/event")

    def test_script_terminator_is_data_not_markup(self):
        event = self.event() | {"name":"</script><script>alert(1)</script>", "category":"</script>"}
        page = build.render([event])
        raw = page.split('<script type="application/json" id="data">',1)[1].split('</script>',1)[0]
        self.assertNotIn("<", raw)
        self.assertEqual(json.loads(raw)["events"][0]["name"], event["name"])

    def test_checked_in_demo_matches_builder(self):
        expected = build.render(build.load_events(ROOT / "data/demo.csv"), demo=True)
        self.assertEqual((ROOT / "index.html").read_text(), expected)

    def test_custom_output_cannot_enter_tracked_tree(self):
        for output in [ROOT / "index.html", ROOT / "preview.html", ROOT / "web/preview.html", ROOT / "dist/../index.html"]:
            with self.subTest(output=output), self.assertRaises(ValueError):
                build.validate_custom_output(output)
        build.validate_custom_output(ROOT / "dist/index.html")


if __name__ == "__main__":
    unittest.main()
