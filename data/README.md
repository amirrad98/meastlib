# Data layout contract

Every item (book, newspaper issue, document) is one folder under `data/items/`.
This layout is the permanent contract — services may change, this may not.

```
data/items/<item-id>/
    metadata.json               descriptive metadata (title, creator, date, lang, source, rights)
    originals/                  IMMUTABLE. As received. Never modified after ingest.
        source.pdf              (or page-0001.tif, ...)
        checksums.sha256
    access/                     web-optimized derivatives (JPEG), one per page
        page-0001.jpg
        page-0002.jpg
    ocr/                        one ALTO XML + plain text per page
        page-0001.alto.xml
        page-0001.txt
        provenance.json         engine, model, version, date, per-page confidence
    iiif/
        manifest.json           IIIF Presentation v3 manifest
```

## metadata.json fields

```json
{
  "id": "item-id",
  "title": "",
  "title_original_script": "",
  "creator": "",
  "date_published": "",
  "language": "ara",
  "script": "Arab",
  "type": "book | newspaper | document",
  "source": "where the file came from",
  "rights": "public-domain | unknown | in-copyright",
  "public": false,
  "ingested": "ISO date",
  "notes": ""
}
```

`rights: unknown` items must keep `public: false` until cleared (see docs/RIGHTS.md).

## ocr/provenance.json fields

engine, engine_version, model, model_version, date, language, script,
mean_confidence per page, human_reviewed flag. Required — without this you
cannot later find and rerun the books processed with a bad model.
