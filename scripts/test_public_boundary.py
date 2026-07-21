#!/usr/bin/env python3
"""Verify that a guessed restricted identifier is unavailable from the public portal."""

from __future__ import annotations

import argparse
import urllib.error
import urllib.parse
import urllib.request


def status(url: str) -> int:
    try:
        with urllib.request.urlopen(url, timeout=20) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base_url")
    parser.add_argument("restricted_item_id")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    item = urllib.parse.quote(args.restricted_item_id, safe="")
    probes = {
        "catalog": f"{base}/api/catalog/items/{item}",
        "metadata": f"{base}/data/items/{item}/metadata.json",
        "manifest": f"{base}/data/items/{item}/iiif/manifest.json",
        "OCR": f"{base}/data/items/{item}/ocr/page-0001.txt",
        "PDF": f"{base}/data/items/{item}/derivatives/searchable.pdf",
        "IIIF image": f"{base}/iiif/3/{item}%2Faccess%2Fpage-0001.jpg/full/max/0/default.jpg",
    }
    failures = []
    for label, url in probes.items():
        code = status(url)
        print(f"{label}: {code}")
        if 200 <= code < 400:
            failures.append(f"{label} returned {code}")
    if failures:
        raise SystemExit("Public boundary failed: " + "; ".join(failures))
    print("Public boundary passed: no restricted resource was retrievable.")


if __name__ == "__main__":
    main()
