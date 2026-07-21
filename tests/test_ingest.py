import argparse
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pipeline import ingest as ingest_module


class IngestTests(unittest.TestCase):
    def test_zero_page_pdf_is_rejected_without_publishing_item(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "truncated.pdf"
            source.write_bytes(b"%PDF-1.7\ntruncated")
            items = root / "items"
            args = argparse.Namespace(
                source=source,
                id="truncated-book",
                metadata_file=None,
                title="",
                creator="",
                pub_date="",
                lang="fas",
                type="book",
                source_note="",
                rights="unknown",
            )

            with (
                patch.object(ingest_module, "DATA_DIR", items),
                patch.object(ingest_module, "ingest_pdf", return_value=0),
                self.assertRaisesRegex(ValueError, "no readable pages"),
            ):
                ingest_module.ingest(args)

            self.assertFalse((items / "truncated-book").exists())
            self.assertEqual(list(items.glob(".staging-truncated-book-*")), [])


if __name__ == "__main__":
    unittest.main()
