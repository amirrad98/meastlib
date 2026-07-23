#!/usr/bin/env python3
"""Idempotently index one bibliographic item document and its ALTO page documents."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import requests


DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def year_number(value: Any) -> int | None:
    text = str(value or "").translate(DIGITS)
    digits = "".join(character for character in text if character.isdigit())
    if len(digits) < 4:
        return None
    year = int(digits[:4])
    return year if 1 <= year <= 9999 else None


def names(values: list[Any]) -> list[str]:
    result = []
    for value in values or []:
        if isinstance(value, dict):
            text = value.get("name") or value.get("value")
        else:
            text = str(value)
        if text:
            result.append(str(text))
    return result


def identifier_values(values: list[Any]) -> list[str]:
    result: list[str] = []
    for value in values or []:
        if isinstance(value, dict):
            scheme = value.get("scheme", "")
            identifier = value.get("value", "")
            candidates = [identifier, f"{scheme}:{identifier}" if scheme else ""]
        else:
            candidates = [str(value)]
        for text in candidates:
            if text and text not in result:
                result.append(text)
    return result


def item_document(meta: dict[str, Any]) -> dict[str, Any]:
    item_id = meta["id"]
    document = {
        "id": item_id,
        "doc_type": "item",
        "item_id": item_id,
        "page": "page-0001",
        "title": meta.get("title", "") or item_id,
        "title_sort": (meta.get("title", "") or item_id).casefold(),
        "title_original_script": meta.get("title_original_script", ""),
        "alternative_titles": meta.get("alternative_titles", []),
        "creator": meta.get("creator", ""),
        "creator_facet": meta.get("creator", ""),
        "creators": names(meta.get("creators", [])) or ([meta["creator"]] if meta.get("creator") else []),
        "contributors": names(meta.get("contributors", [])),
        "publisher": meta.get("publisher", ""),
        "publisher_facet": meta.get("publisher", ""),
        "place_published": meta.get("place_published", ""),
        "date_published": meta.get("date_published", ""),
        "date_sort": meta.get("date_published", ""),
        "date_year": year_number(meta.get("date_published")),
        "date_calendar": meta.get("date_calendar", ""),
        "edition": meta.get("edition", ""),
        "series_title": meta.get("series_title", ""),
        "collection_id": meta.get("collection_id", ""),
        "volume_number": meta.get("volume_number"),
        "issue_number": meta.get("issue_number", ""),
        "identifiers": identifier_values(meta.get("identifiers", [])),
        "subjects": names(meta.get("subjects", [])),
        "subjects_facet": names(meta.get("subjects", [])),
        "temporal_coverage": names(meta.get("temporal_coverage", [])),
        "language": meta.get("language", ""),
        "type": meta.get("type", ""),
        "rights": meta.get("rights", "unknown"),
        "public": bool(meta.get("public", False)),
        "processing_status": meta.get("processing_status", ""),
        "ocr_confidence": meta.get("ocr_confidence"),
    }
    return {key: value for key, value in document.items() if value is not None and value != []}


def page_document(meta: dict[str, Any], alto: Path) -> dict[str, Any]:
    item_id = meta["id"]
    page = alto.name.replace(".alto.xml", "")
    return {
        "id": f"{item_id}/{page}",
        "doc_type": "page",
        "item_id": item_id,
        "page": page,
        "title_display": meta.get("title", "") or item_id,
        "title_sort": (meta.get("title", "") or item_id).casefold(),
        "creator_display": meta.get("creator", ""),
        "creator_facet": meta.get("creator", ""),
        "publisher": meta.get("publisher", ""),
        "publisher_facet": meta.get("publisher", ""),
        "date_display": meta.get("date_published", ""),
        "date_sort": meta.get("date_published", ""),
        "date_year": year_number(meta.get("date_published")),
        "series_display": meta.get("series_title", ""),
        "volume_display": str(meta.get("volume_number") or ""),
        "issue_number": meta.get("issue_number", ""),
        "language": meta.get("language", ""),
        "type": meta.get("type", ""),
        "rights": meta.get("rights", "unknown"),
        "collection_id": meta.get("collection_id", ""),
        "subjects_facet": names(meta.get("subjects", [])),
        "public": bool(meta.get("public", False)),
        "ocr_text": f"/data/items/{item_id}/ocr/{'corrected/' if alto.parent.name == 'corrected' else ''}{alto.name}",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("item", type=Path)
    parser.add_argument("--solr", default="http://localhost:8983/solr/meastlib")
    args = parser.parse_args()

    metadata = json.loads((args.item / "metadata.json").read_text(encoding="utf-8"))
    item_id = metadata["id"]
    altos = sorted((args.item / "ocr").glob("page-*.alto.xml"))
    provenance_path = args.item / "ocr" / "provenance.json"
    if provenance_path.exists():
        try:
            provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
            page_records = provenance.get("pages", {})
            altos = [
                alto for alto in altos
                if page_records.get(alto.name.replace(".alto.xml", ""), {}).get("status") == "ok"
            ]
        except (OSError, json.JSONDecodeError):
            pass
    corrected_dir = args.item / "ocr" / "corrected"
    altos = [(corrected_dir / alto.name) if (corrected_dir / alto.name).exists() else alto for alto in altos]
    documents = [item_document(metadata)]
    documents.extend(page_document(metadata, alto) for alto in altos)

    try:
        schema = requests.get(f"{args.solr}/schema/fields", params={"wt": "json"}, timeout=30)
        schema.raise_for_status()
        known_fields = {field["name"] for field in schema.json().get("fields", [])}
        documents = [{key: value for key, value in document.items() if key in known_fields} for document in documents]
    except (requests.RequestException, KeyError, ValueError):
        pass

    delete = requests.post(
        f"{args.solr}/update",
        json={"delete": {"query": f'item_id:"{item_id}"'}},
        timeout=120,
    )
    if not delete.ok:
        raise SystemExit(f"Solr delete failed ({delete.status_code}): {delete.text}")
    update = requests.post(
        f"{args.solr}/update?commit=true", json=documents, timeout=180
    )
    if not update.ok:
        raise SystemExit(f"Solr indexing failed ({update.status_code}): {update.text}")
    print(f"Indexed 1 item record and {len(altos)} page records for {item_id}")


if __name__ == "__main__":
    main()
