"""Build stable authority records and a portable, corpus-wide catalog index."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Iterable


def clean_authority_name(value: Any) -> str:
    """Normalize presentation noise without changing a catalogued name form."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(value or ""))).strip()


def authority_id(kind: str, name: str) -> str:
    """Return a readable ID with a hash suffix that prevents slug collisions."""
    clean = clean_authority_name(name)
    key = clean.casefold().replace("\u200c", " ")
    key = re.sub(r"\s+", " ", key).strip()
    slug = re.sub(r"[^\w]+", "-", key, flags=re.UNICODE).strip("-")[:48] or "unnamed"
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:10]
    return f"{kind}-{slug}-{digest}"


def authors_from_metadata(metadata: dict[str, Any]) -> list[dict[str, str]]:
    """Return every distinct creator represented as an author authority."""
    authors: list[dict[str, str]] = []
    seen: set[str] = set()
    creators = metadata.get("creators") or []
    for creator in creators:
        if isinstance(creator, dict):
            name = clean_authority_name(creator.get("name") or creator.get("value"))
            role = clean_authority_name(creator.get("role")) or "author"
        else:
            name, role = clean_authority_name(creator), "author"
        if not name:
            continue
        identifier = authority_id("author", name)
        if identifier not in seen:
            authors.append({
                "id": identifier,
                "name": name,
                "role": role,
                "href": f"/authors/{identifier}",
            })
            seen.add(identifier)
    legacy = clean_authority_name(metadata.get("creator"))
    legacy_id = authority_id("author", legacy) if legacy else ""
    if legacy and legacy_id not in seen:
        authors.append({
            "id": legacy_id,
            "name": legacy,
            "role": "author",
            "href": f"/authors/{legacy_id}",
        })
    return authors


def publisher_from_metadata(metadata: dict[str, Any]) -> dict[str, str] | None:
    name = clean_authority_name(metadata.get("publisher"))
    if not name:
        return None
    identifier = authority_id("publisher", name)
    return {"id": identifier, "name": name, "href": f"/publishers/{identifier}"}


def linked_catalog_record(metadata: dict[str, Any]) -> dict[str, Any]:
    """Augment complete item metadata with navigable, publication-safe links."""
    item_id = str(metadata.get("id") or "")
    collection_id = str(metadata.get("collection_id") or "")
    record = dict(metadata)
    record["authorities"] = {
        "authors": authors_from_metadata(metadata),
        "publisher": publisher_from_metadata(metadata),
    }
    record["links"] = {
        "catalog": f"/item/{item_id}",
        "reader": f"/item/{item_id}/1",
        "iiif_manifest": f"/data/items/{item_id}/iiif/manifest.json",
        "metadata": f"/data/items/{item_id}/metadata.json",
        "collection": f"/collection/{collection_id}" if collection_id else "",
    }
    return record


def build_catalog_dataset(
    records: Iterable[dict[str, Any]], *, scope: str = "local"
) -> dict[str, Any]:
    """Build the complete portable index used by the API and future exports."""
    linked_records = [linked_catalog_record(record) for record in records]
    linked_records.sort(key=lambda record: str(record.get("title") or record.get("id") or "").casefold())
    author_index: dict[str, dict[str, Any]] = {}
    publisher_index: dict[str, dict[str, Any]] = {}
    collection_index: dict[str, dict[str, Any]] = {}
    languages: Counter[str] = Counter()
    item_types: Counter[str] = Counter()

    for record in linked_records:
        item_id = str(record.get("id") or "")
        language = clean_authority_name(record.get("language"))
        item_type = clean_authority_name(record.get("type"))
        if language:
            languages[language] += 1
        if item_type:
            item_types[item_type] += 1
        for author in record["authorities"]["authors"]:
            entry = author_index.setdefault(author["id"], {**author, "item_ids": []})
            if item_id not in entry["item_ids"]:
                entry["item_ids"].append(item_id)
        publisher = record["authorities"]["publisher"]
        if publisher:
            entry = publisher_index.setdefault(publisher["id"], {**publisher, "item_ids": []})
            if item_id not in entry["item_ids"]:
                entry["item_ids"].append(item_id)
        collection_id = clean_authority_name(record.get("collection_id"))
        if collection_id:
            entry = collection_index.setdefault(collection_id, {
                "id": collection_id,
                "title": clean_authority_name(record.get("series_title")) or collection_id,
                "href": f"/collection/{collection_id}",
                "item_ids": [],
            })
            entry["item_ids"].append(item_id)

    def finalize(values: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        result = []
        for value in values:
            entry = dict(value)
            entry["work_count"] = len(entry["item_ids"])
            result.append(entry)
        return sorted(result, key=lambda entry: str(entry.get("name") or entry.get("title") or "").casefold())

    authors = finalize(author_index.values())
    publishers = finalize(publisher_index.values())
    collections = finalize(collection_index.values())
    return {
        "schema": "https://meastlib.org/schemas/catalog-index-v1.json",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": scope,
        "summary": {
            "items": len(linked_records),
            "pages": sum(int(record.get("pages") or 0) for record in linked_records),
            "authors": len(authors),
            "publishers": len(publishers),
            "collections": len(collections),
            "languages": dict(sorted(languages.items())),
            "types": dict(sorted(item_types.items())),
        },
        "authorities": {"authors": authors, "publishers": publishers},
        "collections": collections,
        "records": linked_records,
    }
