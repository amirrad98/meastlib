import tempfile
import unittest
from pathlib import Path

import fitz
from pypdf import PdfReader

from pipeline.ocr import alto_stats, merge_searchable_pdf, page_signature


class OcrTests(unittest.TestCase):
    def test_alto_confidence(self):
        xml = b'''<alto xmlns="http://www.loc.gov/standards/alto/ns-v4#"><Layout><Page><PrintSpace><TextBlock><TextLine><String CONTENT="one" WC="0.8"/><String CONTENT="two" WC="0.6"/></TextLine></TextBlock></PrintSpace></Page></Layout></alto>'''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "page.xml"
            path.write_bytes(xml)
            confidence, words = alto_stats(path)
        self.assertEqual(words, 2)
        self.assertAlmostEqual(confidence, 0.7)

    def test_signature_changes_with_configuration(self):
        first = page_signature("abc", 1, "fas", 300, "tesseract 5")
        second = page_signature("abc", 1, "ara", 300, "tesseract 5")
        self.assertNotEqual(first, second)

    def test_searchable_pdf_keeps_page_count_and_text(self):
        with tempfile.TemporaryDirectory() as directory:
            item = Path(directory)
            originals = item / "originals"
            layers = item / "ocr" / "layers"
            originals.mkdir(parents=True)
            layers.mkdir(parents=True)
            source_path = originals / "source.pdf"
            layer_path = layers / "page-0001.text.pdf"

            source = fitz.open()
            page = source.new_page(width=300, height=400)
            page.insert_text((40, 60), "VISIBLE SOURCE")
            source.save(source_path)
            source.close()

            layer = fitz.open()
            page = layer.new_page(width=300, height=400)
            page.insert_text((40, 80), "SEARCHABLE LAYER")
            layer.save(layer_path)
            layer.close()

            result = merge_searchable_pdf(item, source_path, 1)
            output = PdfReader(str(item / result["file"]))
            extracted = output.pages[0].extract_text() or ""
            self.assertEqual(len(output.pages), 1)
            self.assertIn("VISIBLE SOURCE", extracted)
            self.assertIn("SEARCHABLE LAYER", extracted)


if __name__ == "__main__":
    unittest.main()
