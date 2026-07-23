import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz
from PIL import Image

from backend import app as app_module
from backend.app import catalog_archive, catalog_authority, catalog_items, correct_ocr_words, safe_ocr_highlighting, upgraded_metadata
from backend.catalog_index import authority_id, build_catalog_dataset
from pipeline.corrected_pdf import regenerate
from pipeline.fixity import audit_item
from pipeline.manifest import main as manifest_main
from pipeline.publish import publishable


class CatalogTests(unittest.TestCase):
    def test_archive_dataset_cross_references_every_author_and_publisher(self):
        records = [
            {
                "id": "book-1", "title": "Book One", "creator": "Author One",
                "creators": [{"name": "Author One", "role": "author"}, {"name": "Author Two", "role": "editor"}],
                "publisher": "Press One", "collection_id": "set-1", "series_title": "The Set", "pages": 12,
            },
            {"id": "book-2", "title": "Book Two", "creator": "Author One", "publisher": "Press One", "pages": 8},
        ]
        dataset = build_catalog_dataset(records)
        self.assertEqual(dataset["summary"], {
            "items": 2, "pages": 20, "authors": 2, "publishers": 1, "collections": 1,
            "languages": {}, "types": {},
        })
        self.assertEqual(dataset["authorities"]["authors"][0]["work_count"], 2)
        self.assertEqual(dataset["authorities"]["publishers"][0]["item_ids"], ["book-1", "book-2"])
        self.assertEqual(dataset["records"][0]["authorities"]["publisher"]["name"], "Press One")
        self.assertEqual(dataset["records"][0]["links"]["catalog"], "/item/book-1")

    def test_authority_ids_are_stable_and_script_safe(self):
        self.assertEqual(authority_id("author", "  فردوسی  "), authority_id("author", "فردوسی"))
        self.assertEqual(authority_id("publisher", "کتاب‌سرا"), authority_id("publisher", "کتاب سرا"))
        self.assertTrue(authority_id("publisher", "انتشارات مثال").startswith("publisher-انتشارات-مثال-"))

    def test_archive_and_authority_pages_respect_catalog_visibility(self):
        with tempfile.TemporaryDirectory() as directory:
            items = Path(directory)
            for item_id, creator, public in (("visible", "Shared Author", True), ("hidden", "Shared Author", False)):
                item = items / item_id
                item.mkdir()
                metadata = {"id": item_id, "title": item_id, "creator": creator, "publisher": "Shared Press", "rights": "unknown"}
                if public:
                    metadata.update({"rights": "public-domain", "rights_basis": "review", "rights_reviewed_at": "now"})
                (item / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
            with patch.object(app_module, "ITEMS_DIR", items), patch.object(app_module, "SEARCH_VISIBILITY", "public"):
                archive = catalog_archive()
                author = catalog_authority("author", authority_id("author", "Shared Author"))
            self.assertEqual(archive["summary"]["items"], 1)
            self.assertEqual(author["work_count"], 1)
            self.assertEqual(author["items"][0]["id"], "visible")

    def test_v3_requires_documented_public_domain_review(self):
        self.assertFalse(upgraded_metadata({"rights": "public-domain"})["public"])
        value = upgraded_metadata({
            "rights": "public-domain", "rights_basis": "Published before applicable term",
            "rights_reviewed_at": "2026-07-20T00:00:00Z",
        })
        self.assertTrue(value["public"])
        self.assertEqual(value["schema_version"], 3)

    def test_publication_predicate_matches_v3_visibility(self):
        self.assertTrue(publishable({
            "rights": "public-domain", "rights_basis": "Review note", "rights_reviewed_at": "now",
        }))
        self.assertFalse(publishable({"rights": "unknown"}))

    def test_highlight_coordinates_and_safe_markup_are_preserved(self):
        value = safe_ocr_highlighting({"numTotal": 1, "snippets": [{
            "text": '<script>x</script><em>کتاب</em>',
            "pages": [{"width": 100, "height": 200}],
            "regions": [{"ulx": 1, "uly": 2, "lrx": 30, "lry": 40, "text": "<em>کتاب</em>"}],
            "highlights": [[{"ulx": 3, "uly": 4, "lrx": 20, "lry": 15, "text": "کتاب"}]],
        }]})
        self.assertIn("&lt;script&gt;", value["snippets"][0]["text"])
        self.assertIn("<em>کتاب</em>", value["snippets"][0]["text"])
        self.assertEqual(value["snippets"][0]["highlights"][0][0]["ulx"], 3)

    def test_public_catalog_physically_hides_unreviewed_items(self):
        with tempfile.TemporaryDirectory() as directory:
            items = Path(directory)
            for item_id, public in (("visible", True), ("hidden", False)):
                item = items / item_id
                item.mkdir()
                metadata = {"id": item_id, "title": item_id, "rights": "unknown"}
                if public:
                    metadata.update({"rights": "public-domain", "rights_basis": "review", "rights_reviewed_at": "now"})
                (item / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
            with patch.object(app_module, "ITEMS_DIR", items), patch.object(app_module, "SEARCH_VISIBILITY", "public"):
                result = catalog_items()
            self.assertEqual([item["id"] for item in result["items"]], ["visible"])

    def test_public_direct_item_lookup_denies_unreviewed_item(self):
        with tempfile.TemporaryDirectory() as directory:
            items = Path(directory)
            hidden = items / "hidden"
            hidden.mkdir()
            (hidden / "metadata.json").write_text(json.dumps({
                "id": "hidden", "title": "Hidden", "rights": "unknown",
            }), encoding="utf-8")
            with patch.object(app_module, "ITEMS_DIR", items), patch.object(app_module, "SEARCH_VISIBILITY", "public"):
                with self.assertRaises(app_module.HTTPException) as raised:
                    app_module.public_item_path("hidden")
            self.assertEqual(raised.exception.status_code, 404)

    def test_newspaper_catalog_keeps_issue_fields_and_publication_facets(self):
        with tempfile.TemporaryDirectory() as directory:
            items = Path(directory)
            records = [
                {"id": "issue", "title": "کیهان — 18 بهمن 1357", "type": "newspaper", "series_title": "کیهان", "collection_id": "newspaper-kayhan", "issue_number": "10632"},
                {"id": "book", "title": "Book", "type": "book", "series_title": "Books", "collection_id": "books"},
            ]
            for record in records:
                path = items / record["id"]
                path.mkdir()
                (path / "metadata.json").write_text(json.dumps(record), encoding="utf-8")
            with patch.object(app_module, "ITEMS_DIR", items), patch.object(app_module, "SEARCH_VISIBILITY", "all"):
                result = catalog_items(item_type="newspaper")
            self.assertEqual(result["items"][0]["issue_number"], "10632")
            self.assertEqual(result["facets"]["collection"], [{"value": "newspaper-kayhan", "count": 1, "label": "کیهان"}])

    def test_word_corrections_are_versioned_without_touching_source_alto(self):
        alto = '''<?xml version="1.0"?><alto xmlns="http://www.loc.gov/standards/alto/ns-v3#"><Layout><Page><PrintSpace><TextBlock><TextLine><String ID="string_1" HPOS="1" VPOS="2" WIDTH="3" HEIGHT="4" WC="0.5" CONTENT="کتب"/></TextLine></TextBlock></PrintSpace></Page></Layout></alto>'''
        with tempfile.TemporaryDirectory() as directory:
            items = Path(directory)
            ocr = items / "book-1" / "ocr"
            ocr.mkdir(parents=True)
            source = ocr / "page-0001.alto.xml"
            source.write_text(alto, encoding="utf-8")
            request = app_module.CorrectionRequest(corrections=[
                app_module.WordCorrection(word_id="string_1", original="کتب", content="کتاب")
            ])
            with patch.object(app_module, "ITEMS_DIR", items), patch.object(app_module, "jobs", []), patch.object(app_module, "make_job", return_value={"id": "job"}):
                result = correct_ocr_words("book-1", "page-0001", request)
            self.assertEqual(source.read_text(encoding="utf-8"), alto)
            self.assertIn("کتاب", (ocr / "corrected/page-0001.alto.xml").read_text(encoding="utf-8"))
            self.assertEqual(result["current"]["string_1"]["original"], "کتب")

    def test_fixity_detects_changed_original(self):
        with tempfile.TemporaryDirectory() as directory:
            item = Path(directory) / "book"
            originals = item / "originals"
            originals.mkdir(parents=True)
            (originals / "book.pdf").write_bytes(b"changed")
            (originals / "checksums.sha256").write_text(f"{'0' * 64}  book.pdf\n", encoding="utf-8")
            report = audit_item(item)
            self.assertFalse(report["ok"])
            self.assertEqual(report["failures"][0]["error"], "checksum")

    def test_corrected_alto_regenerates_searchable_pdf_without_changing_original(self):
        alto = '''<?xml version="1.0"?><alto xmlns="http://www.loc.gov/standards/alto/ns-v3#"><Layout><Page WIDTH="100" HEIGHT="100"><PrintSpace><TextBlock><TextLine><String ID="word-1" HPOS="10" VPOS="20" WIDTH="50" HEIGHT="10" CONTENT="کتاب"/></TextLine></TextBlock></PrintSpace></Page></Layout></alto>'''
        with tempfile.TemporaryDirectory() as directory:
            item = Path(directory) / "book"
            (item / "originals").mkdir(parents=True)
            (item / "ocr/corrected").mkdir(parents=True)
            (item / "access").mkdir()
            original = item / "originals/source.pdf"
            document = fitz.open()
            document.new_page(width=100, height=100)
            document.save(original)
            document.close()
            before = original.read_bytes()
            Image.new("RGB", (100, 100), "white").save(item / "access/page-0001.jpg")
            (item / "ocr/corrected/page-0001.alto.xml").write_text(alto, encoding="utf-8")
            report = regenerate(item)
            self.assertEqual(report["corrected_pages"], 1)
            self.assertEqual(report["pages"], 1)
            self.assertTrue((item / "derivatives/searchable.pdf").is_file())
            self.assertEqual(original.read_bytes(), before)

    def test_public_manifest_uses_absolute_retrievable_identifiers(self):
        with tempfile.TemporaryDirectory() as directory:
            item = Path(directory) / "book"
            (item / "access").mkdir(parents=True)
            (item / "ocr").mkdir()
            (item / "metadata.json").write_text(json.dumps({
                "id": "book", "title": "Book", "public": True, "rights": "public-domain",
            }), encoding="utf-8")
            Image.new("RGB", (100, 150), "white").save(item / "access/page-0001.jpg")
            (item / "ocr/page-0001.txt").write_text("text", encoding="utf-8")
            (item / "ocr/page-0001.alto.xml").write_text("<alto/>", encoding="utf-8")
            with patch("sys.argv", ["manifest.py", str(item), "--portal-base", "https://library.example.org"]):
                manifest_main()
            manifest = json.loads((item / "iiif/manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["id"], "https://library.example.org/data/items/book/iiif/manifest.json")
            self.assertTrue(manifest["thumbnail"][0]["id"].startswith("https://library.example.org/iiif/3/"))
            self.assertEqual(manifest["service"][0]["id"], "https://library.example.org/api/iiif/book/search")
            self.assertTrue(manifest["items"][0]["seeAlso"][0]["id"].startswith("https://library.example.org/api/catalog/"))


if __name__ == "__main__":
    unittest.main()
