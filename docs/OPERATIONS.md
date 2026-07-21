# Public operations and preservation

## Publication boundary

Run administration only on the local/private stack. The public stack must mount `data/public`, produced by
`pipeline/publish.py`, rather than the private `data` directory. Test a guessed restricted item URL before every
release; it must return 404 for metadata, manifest, OCR, PDF, and IIIF image requests.

Terminate HTTPS in front of the public web container, redirect HTTP to HTTPS, set HSTS after validating the
domain, and restrict the public Solr port to loopback. Do not expose the local `8080`, `8983`, or `8182` ports.

## Release checklist

1. Review rights evidence and catalog exceptions in `/admin`.
2. Run `python pipeline/fixity.py data/items --json data/admin/fixity.json` and resolve every failure.
3. Run the backend, frontend, and optional populated-corpus browser tests from the README.
4. Export with `pipeline/publish.py`; inspect `data/public/items/publication.json`.
5. Reindex the public core and verify that its document count matches the exported works and pages.
6. Run `scripts/test_public_boundary.py` for at least one unknown or in-copyright item and confirm every probe is denied.
7. Snapshot the public Solr volume only as an operational convenience; it is derived and rebuildable.

## Encrypted offsite backup

Back up the private `data/items` tree, `data/admin`, repository configuration, and environment secrets. Restic is
recommended because it encrypts content before upload and supports S3-compatible, SFTP, and local repositories.
Keep its password outside the repository.

```bash
export RESTIC_REPOSITORY=<offsite-repository>
export RESTIC_PASSWORD_FILE=<protected-password-file>
restic backup data/items data/admin .env docs
restic check
restic forget --keep-daily 7 --keep-weekly 8 --keep-monthly 24 --prune
```

Schedule daily backups and monthly `restic check` plus `pipeline/fixity.py`. Alert on nonzero exit status and keep
the latest fixity JSON with the backup. Perform and document a restore drill at least twice per year.

## OCR benchmark gate

Before changing the default OCR engine or bulk-reprocessing low-confidence material, prepare at least 20
representative ground-truth pages and run `benchmark/benchmark_ocr.py`. Record CER, WER, page class, model version,
and runtime. Adopt a replacement only when it improves the relevant page class; keep every previous OCR output and
its provenance until the replacement has passed search and visual checks.
