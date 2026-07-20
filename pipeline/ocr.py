#!/usr/bin/env python3
"""OCR all pages of an ingested item. Writes ALTO XML + plain text per page,
plus ocr/provenance.json recording engine/model/version/confidence.

Engines:
  kraken     - Kraken with an Arabic/Persian model (default: OpenITI generalized).
               Install: pip install kraken
               Models:  https://github.com/OpenITI/ocr_with_kraken_public
                        put .mlmodel files in data/models/
  tesseract  - Tesseract with ara/fas traineddata (baseline comparison).
  vlm        - Vision-language model via API (see benchmark/ for cost analysis).
               Produces plain text only (no word coordinates) — fine for search
               of born-digital-quality scans, insufficient for highlight overlay.

Usage:
    python pipeline/ocr.py data/items/my-book --engine kraken --model data/models/arabPers.mlmodel
"""
import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def ocr_kraken(page: Path, out_dir: Path, model: str) -> dict:
    stem = page.stem
    alto = out_dir / f"{stem}.alto.xml"
    cmd = [
        "kraken", "-i", str(page), str(alto),
        "-a",                      # ALTO output
        "segment", "-bl",         # baseline segmentation (RTL-aware)
        "ocr", "-m", model,
    ]
    subprocess.run(cmd, check=True)
    txt = extract_text_from_alto(alto)
    (out_dir / f"{stem}.txt").write_text(txt, encoding="utf-8")
    return {"page": stem, "alto": alto.name}


def ocr_tesseract(page: Path, out_dir: Path, langs: str) -> dict:
    stem = page.stem
    base = out_dir / stem
    subprocess.run(
        ["tesseract", str(page), str(base), "-l", langs, "alto", "txt"],
        check=True,
    )
    xml = base.with_suffix(".xml")
    if xml.exists():
        xml.rename(out_dir / f"{stem}.alto.xml")
    return {"page": stem, "alto": f"{stem}.alto.xml"}


def extract_text_from_alto(alto_path: Path) -> str:
    from lxml import etree

    tree = etree.parse(str(alto_path))
    ns = {"a": tree.getroot().nsmap.get(None, "")}
    lines = []
    for tl in tree.iter("{*}TextLine"):
        words = [s.get("CONTENT", "") for s in tl.iter("{*}String")]
        lines.append(" ".join(w for w in words if w))
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("item", type=Path)
    ap.add_argument("--engine", default="kraken", choices=["kraken", "tesseract"])
    ap.add_argument("--model", default="", help="kraken .mlmodel path")
    ap.add_argument("--langs", default="ara+fas", help="tesseract languages")
    args = ap.parse_args()

    access = args.item / "access"
    if not access.is_dir():
        sys.exit(f"No access/ images in {args.item} — run ingest.py first.")
    out_dir = args.item / "ocr"
    out_dir.mkdir(exist_ok=True)

    pages = sorted(access.glob("page-*.jpg"))
    results, failed = [], []
    for page in pages:
        try:
            if args.engine == "kraken":
                if not args.model:
                    sys.exit("kraken engine requires --model path/to/model.mlmodel")
                results.append(ocr_kraken(page, out_dir, args.model))
            else:
                results.append(ocr_tesseract(page, out_dir, args.langs))
            print(f"  ok  {page.name}")
        except subprocess.CalledProcessError as e:
            failed.append(page.name)
            print(f"  FAIL {page.name}: {e}", file=sys.stderr)

    provenance = {
        "engine": args.engine,
        "model": args.model or args.langs,
        "date": datetime.now(timezone.utc).isoformat(),
        "pages_ok": len(results),
        "pages_failed": failed,
        "human_reviewed": False,
    }
    (out_dir / "provenance.json").write_text(json.dumps(provenance, indent=2), encoding="utf-8")
    print(f"OCR done: {len(results)} ok, {len(failed)} failed. Provenance written.")
    print("Next: python pipeline/manifest.py", args.item, "&& python pipeline/index.py", args.item)


if __name__ == "__main__":
    main()
