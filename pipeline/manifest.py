#!/usr/bin/env python3
"""Generate a IIIF Presentation v3 manifest for an ingested item.

Image URLs point at Cantaloupe (IIIF Image API), which serves the access JPEGs.

Usage:
    python pipeline/manifest.py data/items/my-book [--base-url http://localhost:8182/iiif/3]
"""
import argparse
import json
from pathlib import Path

from PIL import Image

PORTAL_BASE = "http://localhost:8080"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("item", type=Path)
    ap.add_argument("--base-url", default="http://localhost:8182/iiif/3")
    args = ap.parse_args()

    meta = json.loads((args.item / "metadata.json").read_text(encoding="utf-8"))
    item_id = meta["id"]
    pages = sorted((args.item / "access").glob("page-*.jpg"))

    canvases = []
    for page in pages:
        with Image.open(page) as im:
            w, h = im.size
        # Cantaloupe identifier: <item-id>%2Faccess%2F<file> (slashes URL-encoded)
        img_id = f"{args.base_url}/{item_id}%2Faccess%2F{page.name}"
        canvas_id = f"{PORTAL_BASE}/iiif/{item_id}/canvas/{page.stem}"
        canvases.append({
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
        })

    manifest = {
        "@context": "http://iiif.io/api/presentation/3/context.json",
        "id": f"{PORTAL_BASE}/iiif/{item_id}/manifest.json",
        "type": "Manifest",
        "label": {"none": [meta.get("title") or item_id]},
        "metadata": [
            {"label": {"en": [k]}, "value": {"none": [str(v)]}}
            for k, v in meta.items()
            if v and k in ("creator", "date_published", "language", "type", "source", "rights")
        ],
        "viewingDirection": "right-to-left",
        "items": canvases,
    }

    out = args.item / "iiif"
    out.mkdir(exist_ok=True)
    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Manifest written: {out / 'manifest.json'} ({len(canvases)} canvases)")


if __name__ == "__main__":
    main()
