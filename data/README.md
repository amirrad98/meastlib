# Data layout contract

Every item is one folder under `data/items/`. Services may change; this
standards-oriented artifact layout is the permanent contract.

```
data/items/<item-id>/
    metadata.json               descriptive metadata v3
    metadata-provenance.json    field evidence, confidence, conflicts, catalog sources
    originals/                  IMMUTABLE; exactly as received
        <received-name>.pdf
        checksums.sha256
    access/                     web-optimized JPEGs for IIIF
        page-0001.jpg
    ocr/
        page-0001.alto.xml      OCR text and word coordinates
        page-0001.txt           plain UTF-8 text
        layers/
            page-0001.text.pdf  text-only layer for the portable PDF
        provenance.json         engine/configuration signature and per-page results
        corrections/            versioned human correction ledgers
        corrected/              corrected ALTO/text derivatives; original OCR remains unchanged
    derivatives/
        searchable.pdf          original visible pages with OCR text beneath
        provenance.json         derivative method, checksum, and validation
    iiif/
        manifest.json           IIIF Presentation v3 manifest
```

## metadata.json fields (schema v3)

The original scalar fields remain for compatibility while role-aware and
preservation fields provide a fuller catalog record.

```json
{
  "schema_version": 3,
  "id": "permanent-item-id",
  "title": "",
  "title_original_script": "",
  "alternative_titles": [],
  "creator": "",
  "creators": [{"name": "", "role": "author"}],
  "contributors": [{"name": "", "role": "editor"}],
  "publisher": "",
  "place_published": "",
  "date_published": "",
  "date_display": "",
  "date_calendar": "solar-hijri | gregorian | unknown",
  "edition": "",
  "series_title": "",
  "collection_id": "",
  "volume_number": null,
  "volume_label": "",
  "identifiers": [{"scheme": "ISBN", "value": "", "scope": "volume | set"}],
  "subjects": [],
  "temporal_coverage": [],
  "language": "fas",
  "script": "Arab",
  "type": "book | newspaper | document",
  "pages": 0,
  "source": "relative inbox path or source note",
  "source_file": {
    "name": "source.pdf",
    "mime_type": "application/pdf",
    "bytes": 0,
    "sha256": ""
  },
  "rights": "public-domain | unknown | in-copyright",
  "rights_basis": "",
  "rights_reviewed_at": "",
  "rights_reviewed_by": "",
  "public": false,
  "cover_page": 1,
  "ingested": "ISO date",
  "notes": "",
  "processing_status": "analyzed | ingested | metadata_ready | ocr_complete | ready | partial | failed",
  "metadata_warnings": [],
  "ocr_confidence": 0.0,
  "ocr_pages": 0,
  "searchable_pdf": "derivatives/searchable.pdf"
}
```

`public` is derived rather than independently edited. It is true only when `rights` is
`public-domain` and both a review basis and review date are recorded. Unknown and in-copyright
items remain private.

## Provenance requirements

`metadata-provenance.json` records the page/source, extracted value, confidence,
catalog provider, conflict, and warning for every available field.

`ocr/provenance.json` records engine and trained-data versions, language,
rendering DPI, source and configuration signatures, attempts, output checksums,
word count, blank-page classification, elapsed time, and mean word confidence
for every page. These records make selective reprocessing and auditing possible.
