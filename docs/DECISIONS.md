# Architecture decisions

## ADR-001: Standards now, platforms later (2026-07-17)

**Context.** The long-term vision is an institutional, federated Middle East digital library (reference architecture: Kitodo.Production, OCR-D, Archivematica, Fedora/OCFL, Cantaloupe, Solr, Kitodo.Presentation). Today the project is one person with a collection of already-digitized files.

**Decision.** Build v1 with only the irreplaceable components and adopt the *standards* of the institutional stack as contracts:

- Keep: immutable originals + checksums, per-item folder layout, ALTO XML with word coordinates, OCR provenance records, IIIF Image + Presentation APIs, stable citable page identifiers.
- Run: Solr 9 + solr-ocrhighlighting, Cantaloupe, static viewer (TIFY), Python pipeline scripts.
- Defer: Kitodo.Production (manages scanning projects — we are not scanning), OCR-D (framework overhead; Tesseract is called directly), Archivematica + Fedora (institutional preservation; rsync + checksums + offsite copy suffice solo), Kitodo.Presentation (TYPO3 stack).

**Consequences.** One person can run the whole system (3 containers + scripts). Because outputs are ALTO/IIIF/standard layouts, a later migration into Kitodo/Fedora is an import job. Revisit when: a second full-time person joins, a partner institution contributes content, or the collection exceeds what one Solr node handles.

## ADR-002: Books first, newspapers second, gov documents third (2026-07-17)

Books are the simplest end-to-end path and validate the pipeline. Newspapers (multi-column layout, article segmentation) reuse the pipeline once it works and are the highest-value corpus for historians/journalists. Typewritten/handwritten government documents need HTR (eScriptorium + trained Kraken models) — deferred until the print pipeline is proven.

## ADR-003: OCR engine chosen by benchmark, recorded per page (2026-07-17)

`benchmark/` compares Kraken+OpenITI, Tesseract, and a VLM on representative
pages (CER, speed, cost). Tesseract is the current unattended default because it
can emit ALTO, text, and a PDF text layer in one local pass. Every OCR run writes
provenance (engine, model, version, configuration, date, and confidence), so a
batch can be found and re-run when a better model wins the benchmark.

## ADR-004: Read-only inbox and resumable local batches (2026-07-20)

**Context.** Multi-volume collections are too large for repeated browser uploads.
OCR may run for hours and must survive a laptop or container restart.

**Decision.** Mount a host inbox read-only, fingerprint PDFs before ingest, and
persist batch/page state as atomic JSON. Ingest publishes atomically from a
staging folder. OCR output is keyed by a source/configuration signature so a
resume skips completed pages. Metadata and OCR confidence are not publication
gates; unresolved rights always remain private.

**Consequences.** Folder processing is unattended and idempotent without adding
a database. The same Tesseract pass produces ALTO, plain text, and a text-only
PDF layer; placing that layer beneath the immutable original preserves the scan
while adding portable search. JSON state can later migrate to a queue/database
without changing item artifacts.

## ADR-005: Collection authority harmonization after ingest (2026-07-20)

**Context.** A multi-volume work may use Persian spacing variants, a translated
catalog title, or a weak OCR name on one volume. Treating each spelling as a new
series fragments browsing and search.

**Decision.** Preserve field-level extraction evidence, then run a conservative
final authority pass across the completed batch. Explicit title/publisher aliases
normalize known variants. A creator or contributor is borrowed from another
volume only when the local field is missing or demonstrably low-confidence.
Changed records are regenerated and reindexed together.

**Consequences.** Related volumes share one collection identifier without hiding
the original evidence or catalog conflict warnings. The authority map remains a
small, auditable code/configuration surface rather than opaque fuzzy merging.
