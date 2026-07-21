import unittest

from pipeline.index import identifier_values, item_document


class IndexTests(unittest.TestCase):
    def test_item_document_includes_searchable_bibliographic_fields(self):
        document = item_document({
            "id": "book-1",
            "title": "یادداشتهای علم",
            "alternative_titles": ["خاطرات علم"],
            "creator": "اسدالله علم",
            "place_published": "تهران",
            "date_published": "1390",
            "edition": "چاپ دوم",
            "temporal_coverage": ["1352-1353"],
        })
        self.assertEqual(document["alternative_titles"], ["خاطرات علم"])
        self.assertEqual(document["creator"], "اسدالله علم")
        self.assertEqual(document["place_published"], "تهران")
        self.assertEqual(document["temporal_coverage"], ["1352-1353"])

    def test_identifiers_are_searchable_with_or_without_scheme(self):
        self.assertEqual(
            identifier_values([{"scheme": "ISBN", "value": "9645840422"}]),
            ["9645840422", "ISBN:9645840422"],
        )


if __name__ == "__main__":
    unittest.main()
