# Architecture decisions

## ADR-001: Standards now, platforms later (2026-07-17)

**Context.** The long-term vision is an institutional, federated Middle East digital library (reference architecture: Kitodo.Production, OCR-D, Archivematica, Fedora/OCFL, Cantaloupe, Solr, Kitodo.Presentation). Today the project is one person with a collection of already-digitized files.

**Decision.** Build v1 with only the irreplaceable components and adopt the *standards* of the institutional stack as contracts:

- Keep: immutable originals + checksums, per-item folder layout, ALTO XML with word coordinates, OCR provenance records, IIIF Image + Presentation APIs, stable citable page identifiers.
- Run: Solr 9 + solr-ocrhighlighting, Cantaloupe, static viewer (TIFY), Python pipeline scripts.
- Defer: Kitodo.Production (manages scanning projects — we are not scanning), OCR-D (framework overhead; Kraken called directly), Archivematica + Fedora (institutional preservation; rsync + checksums + offsite copy suffice solo), Kitodo.Presentation (TYPO3 stack).

**Consequences.** One person can run the whole system (3 containers + scripts). Because outputs are ALTO/IIIF/standard layouts, a later migration into Kitodo/Fedora is an import job. Revisit when: a second full-time person joins, a partner institution contributes content, or the collection exceeds what one Solr node handles.

## ADR-002: Books first, newspapers second, gov documents third (2026-07-17)

Books are the simplest end-to-end path and validate the pipeline. Newspapers (multi-column layout, article segmentation) reuse the pipeline once it works and are the highest-value corpus for historians/journalists. Typewritten/handwritten government documents need HTR (eScriptorium + trained Kraken models) — deferred until the print pipeline is proven.

## ADR-003: OCR engine chosen by benchmark, recorded per page (2026-07-17)

No engine is assumed. `benchmark/` compares Kraken+OpenITI, Tesseract, and a VLM on ~20 representative pages (CER, speed, cost). Every OCR run writes provenance (engine, model, version, date) so any batch can be found and re-run when better models appear.
