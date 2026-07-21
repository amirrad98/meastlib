import tempfile
import unittest
from pathlib import Path

from backend.metadata import (
    find_creator,
    find_date,
    detect_language,
    find_edition,
    find_contributors,
    find_identifiers,
    find_publisher,
    find_subjects,
    find_title,
    find_volume,
    isbn_checksum_valid,
    looks_like_garbage,
    normalize_publisher,
    filename_title,
    parse_newspaper_filename,
    suggested_item_id,
)


class MetadataTests(unittest.TestCase):
    def setUp(self):
        self.pages = [{
            "page": 3,
            "text": """
            فهرست برگه
            عنوان و پدیدآور : یادداشتهای علم / متن کامل دست نوشته امیراسدالله علم؛ ویرایش از علیقلی عالیخانی
            نوشته امیراسدالله علم
            مشخصات نشر : تهران: کتاب‌سرا، ۱۳۹۰
            شابک: 978-964-5840-40-6
            شابک: 978-964-5840-44-9 (دوره)
            موضوع : سیاستمداران ایرانی -- سرگذشتنامه
            جلد اول
            """,
        }]

    def test_rejects_corrupt_embedded_metadata(self):
        self.assertTrue(looks_like_garbage("<EDC7CFC7D4CAE5C7ED20DAE1E32D31333437>"))
        self.assertTrue(looks_like_garbage("it2", field="creator"))

    def test_accession_prefix_is_removed_from_filename_title(self):
        self.assertEqual(
            filename_title("87021-دموکراسی، خدای شکست خورده.pdf"),
            "دموکراسی، خدای شکست خورده",
        )

    def test_conservative_fallbacks_do_not_treat_body_text_as_metadata(self):
        pages = [{
            "page": 1,
            "text": """
            یادداشت مترجم: در باب شکستن بت دموکراسی
            کاربست: گذار از پادشاهی به دموکراسی 1789
            چاپ پول کاغذی بدون افزایش ثروت واقعی
            """,
        }]
        title, confidence, evidence = find_title(
            {}, "87021-دموکراسی، خدای شکست خورده.pdf", [], pages
        )
        self.assertEqual(title, "دموکراسی، خدای شکست خورده")
        self.assertEqual(evidence["source"], "Accession filename")
        self.assertGreater(confidence, 0.6)
        self.assertEqual(find_date(pages)[:2], ("", ""))
        self.assertEqual(find_edition(pages)[0], "")
        self.assertEqual(find_contributors(pages)[0], [])

    def test_body_citation_is_not_mistaken_for_a_volume(self):
        pages = [{"page": 2, "text": "A reference to Iwersen, 2005: vol. 8, 5450-5451"}]
        self.assertIsNone(find_volume("87023-مفهوم نور.pdf", pages)[0])

    def test_filename_can_confirm_persian_language(self):
        self.assertEqual(detect_language("چگونه عهد عتیق را بخوانیم")[0], "fas")

    def test_body_prose_is_not_mistaken_for_an_author(self):
        pages = [{"page": 8, "text": "اگر راهنمایی ایشان نبود این نوشته به این صورت در نمی‌آمد"}]
        self.assertEqual(find_creator({}, pages)[0], "")

    def test_ocr_leading_zero_is_removed_from_publication_year(self):
        pages = [{"page": 3, "text": "مشخصات نشر: تهران: نشر آتیه، ۰۱۳۷۸"}]
        self.assertEqual(find_date(pages)[:2], ("1378", "solar-hijri"))

    def test_late_body_citation_is_not_a_publication_date(self):
        pages = [{"page": 10, "text": "ترجمه بنداری، چاپ دوم - تهران ۱۹۷۰"}]
        self.assertEqual(find_date(pages)[:2], ("", ""))

    def test_extracts_persian_bibliographic_fields(self):
        title, confidence, _ = find_title(
            {"title": "<EDC7CFC7D4CAE5C7ED20DAE1E32D31333437>"},
            "یادداشتهای امیر اسدالله علم ۱.pdf",
            [],
            self.pages,
        )
        creator, creator_confidence, _ = find_creator({"author": "it2"}, self.pages)
        published, calendar, _, _ = find_date(self.pages)
        publisher, place, _ = find_publisher(self.pages)
        identifiers, _ = find_identifiers(self.pages)
        subjects, _ = find_subjects(self.pages)
        volume, _, _ = find_volume("یادداشتهای امیر اسدالله علم ۱.pdf", self.pages)
        self.assertEqual(title, "یادداشتهای علم")
        self.assertGreater(confidence, 0.8)
        self.assertIn("امیراسدالله علم", creator)
        self.assertGreater(creator_confidence, 0.7)
        self.assertEqual((published, calendar), ("1390", "solar-hijri"))
        self.assertEqual(publisher, "کتاب‌سرا")
        self.assertEqual(place, "تهران")
        self.assertEqual(volume, 1)
        self.assertEqual(len(identifiers), 2)
        self.assertEqual({item["scope"] for item in identifiers}, {"volume", "set"})
        self.assertEqual(subjects, ["سیاستمداران ایرانی -- سرگذشتنامه"])

    def test_ids_are_stable_and_url_safe(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "book.pdf"
            source.write_bytes(b"same-source")
            first = suggested_item_id("یادداشتهای علم", "1390", source, "fas", "book", 1)
            second = suggested_item_id("یادداشتهای علم", "1390", source, "fas", "book", 1)
        self.assertEqual(first, second)
        self.assertRegex(first, r"^fas-book-v01-[a-f0-9]{10}$")

    def test_publisher_authority_repairs_conservative_ocr_noise(self):
        self.assertEqual(normalize_publisher("کتا ب سرلا"), "کتاب‌سرا")
        self.assertEqual(normalize_publisher("کتا ب سرل"), "کتاب‌سرا")
        self.assertEqual(normalize_publisher("تهران: کتاب‌سر"), "کتاب‌سرا")
        self.assertEqual(normalize_publisher("کتاب‌سرا AVY"), "کتاب‌سرا")
        self.assertEqual(normalize_publisher("انتشارات مثال"), "انتشارات مثال")

    def test_isbn_validation(self):
        self.assertTrue(isbn_checksum_valid("9780306406157"))
        self.assertFalse(isbn_checksum_valid("9789645840406"))

    def test_parses_newspaper_issue_filename(self):
        value = parse_newspaper_filename("1357-بهمن-18__Kayhan_(10632)__226603.pdf")
        self.assertEqual(value["publication_title"], "کیهان")
        self.assertEqual(value["date_published"], "1357-11-18")
        self.assertEqual(value["date_display"], "18 بهمن 1357")
        self.assertEqual(value["issue_number"], "10632")
        self.assertEqual(value["accession_number"], "226603")
        self.assertEqual(value["collection_id"], "newspaper-kayhan")
        self.assertEqual(value["suggested_id"], "kayhan-1357-11-18-10632")

    def test_ignores_ordinary_book_filename_as_newspaper(self):
        self.assertIsNone(parse_newspaper_filename("87021-دموکراسی، خدای شکست خورده.pdf"))


if __name__ == "__main__":
    unittest.main()
