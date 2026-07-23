# meastlib — Middle East Digital Library

A solo-operable pipeline for digitizing, OCR-ing, and publishing Arabic and Persian books, newspapers, and historical documents — built on preservation standards (IIIF, ALTO, immutable masters) so it can later scale into an institutional, federated archive without a rebuild.

## Architecture (v1 — solo-scale)

```
collected files (PDFs / scans)
        |
   pipeline/ingest.py      normalize into per-item folders, immutable originals, checksums
        |
   pipeline/ocr.py         Tesseract -> ALTO XML + text + searchable-PDF layer + provenance
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

# 5. OCR it and create the searchable-PDF derivative
python pipeline/ocr.py data/items/my-first-book --engine tesseract --langs ara --workers 2

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

### Automatic folder batches

Set `MEASTLIB_INBOX_DIR` to a host folder containing PDFs, then rebuild and
start the stack. The folder is mounted read-only; source files are never moved
or modified.

```bash
cp .env.example .env
# Edit MEASTLIB_INBOX_DIR in .env, then:
docker compose up -d --build
```

Open `http://localhost:8080/admin`, scan the batch inbox, and choose **Process
new PDFs**. The pipeline fingerprints every file, skips exact duplicates,
extracts and enriches metadata, transactionally ingests the original, runs
resumable OCR, creates a visually unchanged searchable PDF, builds IIIF, and
indexes both the catalog record and searchable pages. Batch and per-page state
survive service restarts. One failed book does not stop the rest of the folder.
Only one folder batch runs at a time, preventing two jobs from racing to publish
the same permanent item.

Failed, partial, and canceled batch-history rows can be dismissed from the
dashboard. Removing history never deletes inbox PDFs or completed library items.

Metadata extraction examines the first twelve and last five pages, rejects
common corrupt scanner metadata, understands Persian/Arabic bibliographic
labels and digits, and records evidence/confidence in
`metadata-provenance.json`. ISBN lookups use Open Library and optionally Google
Books when `GOOGLE_BOOKS_API_KEY` is configured. No page image is sent to a
catalog service. A final collection-authority pass groups known title variants,
normalizes conservative publisher aliases, and lets a low-confidence volume
reuse a stronger creator/name form from another volume in the same set. Rights
always default to `unknown` and private.

Administration and batch state is stored as JSON under `data/admin/`; no SQL service is
required. Metadata analysis reads embedded PDF information and samples opening
and closing bibliographic pages with local OCR. The dashboard shows confidence
and evidence for manual uploads, while folder batches continue automatically.
No PDF content is sent to a cloud service. The dashboard
has no authentication in this local version, so do not expose `/admin` or
`/api` directly to the public internet.

### Reader-facing library

The local site now includes an English/Persian public interface:

- `/` presents recently added books and featured multi-volume collections;
- `/browse` filters catalog records by language, type, collection, creator, publisher, and subject;
- `/archive` is a research-grade, collection-wide index of authors, publishers, collections, works, and pages;
- `/authors/<authority-id>` and `/publishers/<authority-id>` cross-reference every visible work associated with that authority;
- `/search` groups full-text page hits by work, preserves searches in the URL, and exposes facets;
- `/item/<id>` is a catalog record, while `/item/<id>/<page>` is the scan reader;
- `/newspapers` groups issue records by publication and filters them by issue number or Solar Hijri date;
- search links retain OCR coordinates so the reader can zoom to and highlight the matching words;
- the reader includes in-book search, matching-page navigation, a windowed thumbnail strip, page jump,
  citations, OCR text, ALTO, IIIF, and searchable-PDF links.

The language switch changes public navigation between English and Persian. Administration remains English.

The archive page also exposes `/api/catalog/dataset`, a downloadable JSON catalog containing the complete
visible metadata record for every item, stable author and publisher authority IDs, item membership lists,
and navigable catalog, reader, IIIF, metadata, and collection links. The local portal includes the full local
catalog; the public portal automatically contains only rights-reviewed public-domain records.

### Newspaper issues

Store one newspaper issue per PDF/item. Related issues share `series_title` (the publication name) and
`collection_id`; each issue has its own `issue_number`, normalized sortable date, immutable source PDF,
page images, ALTO/text OCR, searchable PDF, and IIIF manifest. Filenames in this form are recognized
automatically:

```text
1357-بهمن-18__Kayhan_(10632)__226603.pdf
```

This becomes publication `کیهان`, issue `10632`, Solar Hijri date `1357-11-18`, and permanent ID
`kayhan-1357-11-18-10632`. Newspaper OCR keeps Tesseract's automatic layout analysis and uses a
column-preserving fallback for low-confidence pages.

### Metadata review, OCR correction, and fixity

Metadata schema v3 makes public access depend on a recorded public-domain basis and review date. Existing
v2 records can be inspected and migrated idempotently:

```bash
python pipeline/migrate_metadata.py --dry-run
python pipeline/migrate_metadata.py
```

The Admin quality queue groups rights, metadata, low-confidence OCR, failed-page, page-count, and index
exceptions. Its word editor writes versioned correction overlays and corrected ALTO/text derivatives while
leaving the original OCR untouched. Run a checksum audit from the dashboard or command line:

```bash
python pipeline/fixity.py data/items --json data/admin/fixity.json
```

The current Solr schema remains usable without rebuilding. To enable the new creator/publisher/subject facets and true
title/date sorting on an existing disposable Solr index, recreate its Docker volume and reindex derived data:

```bash
docker compose down
docker volume rm meastlib_solr-data
docker compose up -d solr
python scripts/migrate_solr_schema.py --reindex
docker compose up -d
```

Never remove `data/items`; Solr contains only a rebuildable index.

### Public-domain-only publication

The public stack is deliberately separate from administration. It mounts only an atomic export containing
reviewed public-domain access images, OCR, manifests, and derivatives; originals and restricted items are absent.

```bash
# 1. Start the separate public search core.
docker compose -f docker-compose.public.yml up -d public-solr

# 2. Build the rights-filtered export and index it.
python pipeline/publish.py \
  --output data/public/items \
  --portal-base https://library.example.org \
  --solr http://localhost:8984/solr/meastlib

# 3. Start the read-only portal on localhost:8081.
docker compose -f docker-compose.public.yml up -d --build

# 4. Prove a known restricted identifier cannot be retrieved directly.
python scripts/test_public_boundary.py http://localhost:8081 <restricted-item-id>
```

Place TLS termination (for example Caddy, nginx, or a managed load balancer) in front of port 8081. The public
nginx configuration proxies only read-only health, catalog, search, IIIF Content Search, image, and data routes;
admin and mutation routes return 404. See `docs/OPERATIONS.md` before exposing it to the internet.

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

## Verification

```bash
docker compose run --rm -T --no-deps \
  -v "$PWD/tests:/app/tests:ro" admin-api \
  python -m unittest discover -s tests -v

cd web
npm run build
npm test

# Optional populated-corpus browser checks
MEASTLIB_E2E_ITEM_ID=<item-id> MEASTLIB_E2E_QUERY=<query> npm run test:e2e
```

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
