# OCR benchmark

Decides the default engine for the collection. Run this before bulk processing.

## 1. Pick ~20 representative pages

Put JPEG/PNG page images in `samples/`. Cover the hard cases, not just clean ones:
clean modern book print, old/degraded print, newspaper column, table or index page,
typewritten document, stained/damaged page. Both Arabic and Persian.

## 2. Create ground truth

For each sample, type the correct text into `samples/<name>.gt.txt` (same stem).
Tedious but essential — 20 pages of ground truth is a few hours and decides
everything downstream. eScriptorium can help produce these later.

## 3. Get models/engines

- Kraken: `pip install kraken`, download OpenITI models
  (https://github.com/OpenITI/ocr_with_kraken_public) into `../data/models/`
- Tesseract: install with `ara` and `fas` traineddata
- VLM: set ANTHROPIC_API_KEY (or adapt `vlm_ocr` for another provider)

## 4. Run

```bash
python benchmark_ocr.py --engines kraken,tesseract,vlm --kraken-model ../data/models/<model>.mlmodel
```

Outputs `results/report.md` with per-page and mean CER/WER, seconds per page,
and estimated cost per 1000 pages for the VLM.

## Interpreting

- CER < 5%: good enough for search without correction
- CER 5–15%: searchable but expect missed hits; consider correction for key items
- CER > 15%: wrong model or the page class needs its own model (eScriptorium training)

Remember VLMs return plain text only — fine for "find the page", but no word
coordinates means no highlight overlay in the viewer. Kraken/Tesseract ALTO gives
both. A hybrid (Kraken for coordinates + VLM for text quality) is possible later.
