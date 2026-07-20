# meastlib — Middle East Digital Library

A solo-operable pipeline for digitizing, OCR-ing, and publishing Arabic and Persian books, newspapers, and historical documents — built on preservation standards (IIIF, ALTO, immutable masters) so it can later scale into an institutional, federated archive without a rebuild.

## Architecture (v1 — solo-scale)

```
collected files (PDFs / scans)
        |
   pipeline/ingest.py      normalize into per-item folders, immutable originals, checksums
        |
   pipeline/ocr.py         Kraken (OpenITI models) / Tesseract / VLM -> ALTO XML + text + provenance
        |
   pipeline/manifest.py    IIIF Presentation v3 manifests
        |
   pipeline/index.py       push ALTO to Solr (solr-ocrhighlighting)
        |
   docker-compose up       Solr 9 + Cantaloupe IIIF image server + viewer (TIFY / Mirador)
```

Deliberately deferred until institutional scale: Kitodo.Production, OCR-D, Archivematica, Fedora/OCFL, Kitodo.Presentation. See `docs/DECISIONS.md`. The data formats produced here (ALTO, IIIF, METS-compatible layout, immutable TIFF/originals) are the same ones those systems consume, so migration later is an import, not a rewrite.

## Upstream projects used

| Component | Repo | Role |
|---|---|---|
| Kraken | https://github.com/mittagessen/kraken | Arabic/Persian OCR engine (RTL-aware, trainable) |
| OpenITI OCR models | https://github.com/OpenITI/ocr_with_kraken_public | Pretrained Arabic/Persian recognition models |
| solr-ocrhighlighting | https://github.com/dbmdz/solr-ocrhighlighting | Page/word-coordinate search hits inside OCR |
| Cantaloupe | https://github.com/cantaloupe-project/cantaloupe | Dynamic IIIF Image API server |
| TIFY | https://github.com/tify-iiif-viewer/tify | Lightweight IIIF book reader |
| Mirador | https://github.com/ProjectMirador/mirador | Research viewer (comparison, annotation) |
| eScriptorium | https://gitlab.com/scripta/escriptorium | Later: OCR correction + model training UI |

## Quickstart

```bash
# 1. Python environment
python3 -m venv .venv && source .venv/bin/activate
pip install -r pipeline/requirements.txt

# 2. Fetch the Solr OCR highlighting plugin jar (one time)
./scripts/setup_solr_plugin.sh

# 3. Build the React site, then start services (Solr :8983, Cantaloupe :8182, site :8080)
cd web && npm install && npm run build && cd ..
docker compose up -d --build

# 4. Ingest a PDF or a folder of page images
python pipeline/ingest.py path/to/book.pdf --id my-first-book --title "..." --lang ara

# 5. OCR it (see benchmark/ first to pick your engine)
python pipeline/ocr.py data/items/my-first-book --engine kraken

# 6. Build IIIF manifest + index into Solr
python pipeline/manifest.py data/items/my-first-book
python pipeline/index.py data/items/my-first-book

# 7. Open http://localhost:8080 and search
```

### Administration dashboard

Open `http://localhost:8080/admin` to upload PDF books and control processing
without running pipeline commands by hand. The dashboard can:

- analyze a selected PDF locally and suggest the title, creator, publication
  date, language, item type, and permanent item ID;
- ingest an uploaded PDF and its metadata;
- run Arabic/Persian Tesseract OCR;
- build or rebuild the IIIF viewer manifest;
- index or reindex the book in Solr;
- show persistent job status and logs, and cancel an active job;
- report the health of OCR, Solr, IIIF, and local storage.

Administration state is stored as JSON under `data/admin/`; no SQL service is
required. Metadata analysis reads embedded PDF information and examines the
first six pages. Image-only opening pages are OCRed locally (up to four pages),
and the dashboard shows confidence and evidence so every suggestion can be
reviewed before upload. No PDF content is sent to a cloud service. The dashboard
has no authentication in this local version, so do not expose `/admin` or
`/api` directly to the public internet.

### Front-end development

```bash
cd web
npm run dev        # hot-reloading dev server on http://localhost:5173
```

The dev server proxies `/solr`, `/iiif`, and `/data` to the docker services, so
run `docker compose up -d` first. `npm run build` produces `web/dist`, which the
`web` nginx container serves on :8080 (only Solr's `/select` endpoint is proxied
through — the Solr admin UI is never exposed).

### GitHub Pages

The workflow in `.github/workflows/pages.yml` builds and deploys the React site
to GitHub Pages after every push to `main`. It can also be started manually from
the Actions tab. The build uses GitHub's detected Pages base path, so repository
subpaths and custom domains work without editing the Vite configuration.

GitHub Pages is static hosting: it cannot run the Python administration API,
Tesseract, Solr, or Cantaloupe. Without a public backend, the deployed site is a
clearly labeled project preview and does not expose the Admin route. To connect
an independently hosted backend later, create an Actions repository variable
named `MEASTLIB_SERVICE_URL` containing its origin, such as
`https://library-api.example.org`. That service must expose `/api`, `/solr`, and
`/data` with suitable CORS and authentication controls.

## First milestone: the OCR benchmark

Before processing the whole collection, run `benchmark/` on ~20 representative pages (clean book, poor scan, newspaper column, typewritten document). It compares Kraken+OpenITI, Tesseract, and a VLM on character error rate and cost. **The winner determines the default engine for the collection.**

## Repository layout

```
pipeline/     ingest -> ocr -> manifest -> index scripts
benchmark/    OCR engine comparison harness (CER, cost, speed)
solr/         Solr 9 configset with ocr-highlighting field types (Arabic/Persian analyzers)
web/          React site (Vite): search + IIIF book reader, nginx config for production
scripts/      Setup helpers
data/         Items live here (gitignored) — layout contract in data/README.md
docs/         Architecture decisions, roadmap, rights policy
```

## Principles (non-negotiable from day one)

1. **Originals are immutable.** Ingest copies them, checksums them, and never touches them again.
2. **Every OCR result records its provenance** — engine, model, version, date, confidence — so bad batches can be found and rerun.
3. **Every page has a stable, citable identifier** (`item-id/page-0001`) — historians must be able to cite you.
4. **Standards over platforms** — ALTO, IIIF, and the folder layout are the contract; every service behind them is replaceable.
5. **Rights are checked before publishing** — see `docs/RIGHTS.md`. Public-domain items are open; everything else stays dark until cleared.
