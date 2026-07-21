#!/usr/bin/env python3
"""Generate a IIIF Presentation v3 manifest for an ingested item.

Image URLs point at Cantaloupe (IIIF Image API), which serves the access JPEGs.

Usage:
    python pipeline/manifest.py data/items/my-book [--base-url /iiif/3]

Image URLs are same-origin (/iiif/...) so the browser reaches Cantaloupe through
the web proxy (nginx in production, Vite dev server in development).
"""
import argparse
import json
from pathlib import Path

from PIL import Image

def display_value(value):
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict):
                parts.append(item.get("name") or item.get("value") or str(item))
            else:
                parts.append(str(item))
        return "; ".join(part for part in parts if part)
    return str(value)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("item", type=Path)
    ap.add_argument("--base-url", default="/iiif/3")
    ap.add_argument("--portal-base", default="", help="Absolute public portal origin, e.g. https://library.example")
    args = ap.parse_args()

    meta = json.loads((args.item / "metadata.json").read_text(encoding="utf-8"))
    item_id = meta["id"]
    portal_base = args.portal_base.rstrip("/")
    image_base = args.base_url if args.base_url.startswith("http") else f"{portal_base}{args.base_url}"
    pages = sorted((args.item / "access").glob("page-*.jpg"))

    canvases = []
    for page in pages:
        with Image.open(page) as im:
            w, h = im.size
        # Cantaloupe identifier: <item-id>%2Faccess%2F<file> (slashes URL-encoded)
        img_id = f"{image_base}/{item_id}%2Faccess%2F{page.name}"
        canvas_id = f"{portal_base}/iiif/{item_id}/canvas/{page.stem}"
        canvas = {
            "id": canvas_id,
            "type": "Canvas",
            "label": {"none": [page.stem.replace("page-", "p. ")]},
            "width": w,
            "height": h,
            "items": [{
                "id": f"{canvas_id}/annopage",
                "type": "AnnotationPage",
                "items": [{
                    "id": f"{canvas_id}/anno",
                    "type": "Annotation",
                    "motivation": "painting",
                    "body": {
                        "id": f"{img_id}/full/max/0/default.jpg",
                        "type": "Image",
                        "format": "image/jpeg",
                        "width": w,
                        "height": h,
                        "service": [{"id": img_id, "type": "ImageService3", "profile": "level2"}],
                    },
                    "target": canvas_id,
                }],
            }],
        }
        text_path = args.item / "ocr" / f"{page.stem}.txt"
        alto_path = args.item / "ocr" / f"{page.stem}.alto.xml"
        see_also = []
        if text_path.exists():
            see_also.append({
                "id": f"{portal_base}/api/catalog/items/{item_id}/ocr/{page.stem}?format=text",
                "type": "Dataset", "format": "text/plain", "label": {"en": ["OCR text"]},
            })
        if alto_path.exists():
            see_also.append({
                "id": f"{portal_base}/api/catalog/items/{item_id}/ocr/{page.stem}?format=alto",
                "type": "Dataset", "format": "application/xml", "profile": "http://www.loc.gov/standards/alto/",
                "label": {"en": ["ALTO OCR"]},
            })
        if see_also:
            canvas["seeAlso"] = see_also
        canvases.append(canvas)

    manifest = {
        "@context": "http://iiif.io/api/presentation/3/context.json",
        "id": f"{portal_base}/data/items/{item_id}/iiif/manifest.json",
        "type": "Manifest",
        "label": {"none": [meta.get("title") or item_id]},
        "metadata": [
            {"label": {"en": [k.replace("_", " ").title()]}, "value": {"none": [display_value(v)]}}
            for k, v in meta.items()
            if v and k in (
                "creator", "contributors", "publisher", "place_published", "date_published",
                "date_calendar", "edition", "series_title", "volume_label", "identifiers", "subjects",
                "language", "type", "source", "rights",
            )
        ],
        "viewingDirection": "right-to-left",
        "thumbnail": [{
            "id": f"{image_base}/{item_id}%2Faccess%2Fpage-{int(meta.get('cover_page') or 1):04d}.jpg/full/360,/0/default.jpg",
            "type": "Image", "format": "image/jpeg",
        }],
        "service": [{
            "id": f"{portal_base}/api/iiif/{item_id}/search",
            "type": "SearchService2", "profile": "level1",
        }],
        "items": canvases,
    }
    if meta.get("rights") == "public-domain" and meta.get("public"):
        manifest["rights"] = "http://creativecommons.org/publicdomain/mark/1.0/"
    if meta.get("source"):
        manifest["requiredStatement"] = {
            "label": {"en": ["Source"]}, "value": {"none": [display_value(meta["source"])]},
        }
    searchable_pdf = args.item / "derivatives" / "searchable.pdf"
    if searchable_pdf.exists():
        manifest["rendering"] = [{
            "id": f"{portal_base}/data/items/{item_id}/derivatives/searchable.pdf",
            "type": "Text",
            "format": "application/pdf",
            "label": {"en": ["Download searchable PDF"]},
        }]

    out = args.item / "iiif"
    out.mkdir(exist_ok=True)
    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Manifest written: {out / 'manifest.json'} ({len(canvases)} canvases)")


if __name__ == "__main__":
    main()
