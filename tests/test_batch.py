import json
import tempfile
import unittest
from pathlib import Path

from pipeline.batch import (
    atomic_json,
    canonical_series,
    collection_id_for,
    harmonize_collections,
    process_records,
    safe_inbox_path,
    series_title,
)


class BatchTests(unittest.TestCase):
    def test_series_grouping_ignores_spacing_variants(self):
        a = canonical_series("یادداشت های امیر اسدالله علم")
        b = canonical_series("یادداشتهای امیر اسد الله علم")
        self.assertEqual(a, b)
        self.assertEqual(collection_id_for(a), collection_id_for(b))

    def test_series_title_removes_volume_suffix(self):
        self.assertEqual(series_title("یادداشتهای امیر اسدالله علم ۳", 3), "یادداشتهای علم")
        self.assertEqual(series_title("A History Volume 2", 2), "A History")

    def test_inbox_path_cannot_escape_mount(self):
        with tempfile.TemporaryDirectory() as directory:
            inbox = Path(directory)
            book = inbox / "book.pdf"
            book.write_bytes(b"pdf")
            self.assertEqual(safe_inbox_path(inbox, "book.pdf"), book.resolve())
            with self.assertRaises(ValueError):
                safe_inbox_path(inbox, "../outside.pdf")

    def test_one_failed_book_does_not_stop_batch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_path = root / "batch.json"
            state = {
                "id": "batch",
                "files": [
                    {"relative_path": "bad.pdf", "status": "queued"},
                    {"relative_path": "good.pdf", "status": "queued"},
                ],
            }
            atomic_json(state_path, state)
            visited = []

            def processor(record, state, state_path, *_args):
                visited.append(record["relative_path"])
                if record["relative_path"] == "bad.pdf":
                    raise RuntimeError("expected failure")
                record.update({"status": "succeeded", "stage": "Complete"})
                atomic_json(state_path, state)

            failures = process_records(
                state, state_path, root, root, "http://solr", 1, processor=processor
            )
        self.assertEqual(failures, 1)
        self.assertEqual(visited, ["bad.pdf", "good.pdf"])
        self.assertEqual(state["files"][0]["status"], "failed")
        self.assertEqual(state["files"][1]["status"], "succeeded")

    def test_collection_authority_harmonizes_low_confidence_volume(self):
        with tempfile.TemporaryDirectory() as directory:
            items = Path(directory)
            strong = items / "volume-3"
            weak = items / "volume-7"
            for item in (strong, weak):
                item.mkdir()
            (strong / "metadata.json").write_text(json.dumps({
                "id": "volume-3", "title": "یادداشتهای علم", "series_title": "یادداشتهای علم",
                "volume_number": 3, "language": "fas", "creator": "امیر اسد الله علم",
                "creators": [{"name": "امیر اسد الله علم", "role": "author"}],
                "contributors": [{"name": "علینقی‌عالیخانی", "role": "editor"}],
                "publisher": "تهران: کتاب‌سر", "place_published": "‏",
                "date_published": "1390", "date_calendar": "solar-hijri",
            }, ensure_ascii=False), encoding="utf-8")
            (weak / "metadata.json").write_text(json.dumps({
                "id": "volume-7", "title": "یادداشت های امیر اسدالله علم",
                "series_title": "یادداشت های امیر اسدالله علم", "volume_number": 7,
                "language": "fas", "creator": "Asadollah Alam",
                "creators": [{"name": "Asadollah Alam", "role": "author"}],
                "contributors": [
                    {"name": "ede عالیخانی", "role": "editor"},
                    {"name": "علینقی عالیخانی ۱", "role": "editor"},
                ],
                "publisher": "کتاب‌سرا AVY", "date_published": "1298",
                "date_calendar": "solar-hijri",
            }, ensure_ascii=False), encoding="utf-8")
            (strong / "metadata-provenance.json").write_text(
                json.dumps({"confidence": {"creator": 0.78, "date_published": 0.78}}), encoding="utf-8"
            )
            (weak / "metadata-provenance.json").write_text(
                json.dumps({"confidence": {"creator": 0.0, "date_published": 0.38}}), encoding="utf-8"
            )
            harmonize_collections(items, ["volume-3", "volume-7"])
            strong_meta = json.loads((strong / "metadata.json").read_text(encoding="utf-8"))
            weak_meta = json.loads((weak / "metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(strong_meta["publisher"], "کتاب‌سرا")
            self.assertEqual(strong_meta["place_published"], "تهران")
            self.assertEqual(weak_meta["title"], "یادداشتهای علم")
            self.assertEqual(weak_meta["creator"], "امیر اسد الله علم")
            self.assertEqual(weak_meta["publisher"], "کتاب‌سرا")
            self.assertEqual(weak_meta["date_published"], "1390")
            self.assertEqual(weak_meta["contributors"][0]["name"], "علینقی‌عالیخانی")
            self.assertEqual(len(weak_meta["contributors"]), 1)
            self.assertEqual(strong_meta["collection_id"], weak_meta["collection_id"])


if __name__ == "__main__":
    unittest.main()
