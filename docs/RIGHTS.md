# Rights policy

A reliable source is one that stays online. Publishing in-copyright material invites takedowns and destroys credibility with the institutions we eventually want as partners.

## Rules

1. Every item gets a `rights` value at ingest: `public-domain`, `unknown`, or `in-copyright`.
2. Only `public-domain` items get `public: true`. Everything else is a dark archive: preserved, OCR'd, indexed locally — not exposed on a public portal.
3. `unknown` is the default. Resolve it before flipping `public`.

## Rough guidance (verify per jurisdiction — this is not legal advice)

- Copyright terms in the region vary (commonly life of author + 25 to + 50 years, depending on country; some have moved toward +50/+70).
- Pre-1920s publications are very likely safe. Mid-20th-century material frequently is not.
- Government/official documents: some jurisdictions exclude official texts from copyright, but treat as `unknown` until checked.
- Newspapers: copyright typically belongs to the publisher; defunct publishers make clearance hard, not automatic.

## Practical queue

Keep a running list of `unknown` items sorted by value; clear rights in batches. Record the basis for each `public-domain` determination in `metadata.json` `notes`.
