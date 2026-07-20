#!/usr/bin/env python3
"""Compare OCR engines on Arabic/Persian sample pages.

Expects samples/<name>.(jpg|png) with ground truth samples/<name>.gt.txt.
Writes results/report.md with CER, WER, time per page, and VLM cost estimate.

Usage:
    python benchmark_ocr.py --engines kraken,tesseract,vlm --kraken-model path/to/model.mlmodel
"""
import argparse
import subprocess
import sys
import time
import unicodedata
from pathlib import Path

import Levenshtein

HERE = Path(__file__).resolve().parent
SAMPLES = HERE / "samples"
RESULTS = HERE / "results"

VLM_PROMPT = (
    "Transcribe ALL text on this scanned page exactly as printed. "
    "The text is Arabic or Persian. Preserve line breaks. "
    "Output ONLY the transcription, no commentary."
)
# rough public API pricing assumption for cost estimate; adjust to your provider
VLM_COST_PER_PAGE_USD = 0.01


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = text.replace("ي", "ی").replace("ك", "ک")  # fold ya/kaf variants
    return " ".join(text.split())


def cer(hyp: str, ref: str) -> float:
    ref_n, hyp_n = normalize(ref), normalize(hyp)
    return Levenshtein.distance(hyp_n, ref_n) / max(len(ref_n), 1)


def wer(hyp: str, ref: str) -> float:
    r, h = normalize(ref).split(), normalize(hyp).split()
    if not r:
        return 0.0
    return _word_dist(h, r) / len(r)


def _word_dist(h: list, r: list) -> int:
    import numpy as np
    d = np.zeros((len(r) + 1, len(h) + 1), dtype=int)
    d[:, 0] = range(len(r) + 1)
    d[0, :] = range(len(h) + 1)
    for i in range(1, len(r) + 1):
        for j in range(1, len(h) + 1):
            cost = 0 if r[i - 1] == h[j - 1] else 1
            d[i, j] = min(d[i - 1, j] + 1, d[i, j - 1] + 1, d[i - 1, j - 1] + cost)
    return int(d[len(r), len(h)])


def run_kraken(img: Path, model: str) -> str:
    out = RESULTS / "tmp" / f"{img.stem}.kraken.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["kraken", "-i", str(img), str(out), "segment", "-bl", "ocr", "-m", model],
        check=True, capture_output=True,
    )
    return out.read_text(encoding="utf-8")


def run_tesseract(img: Path) -> str:
    r = subprocess.run(
        ["tesseract", str(img), "stdout", "-l", "ara+fas"],
        check=True, capture_output=True,
    )
    return r.stdout.decode("utf-8")


def run_vlm(img: Path) -> str:
    import base64
    import anthropic

    client = anthropic.Anthropic()
    media_type = "image/png" if img.suffix.lower() == ".png" else "image/jpeg"
    b64 = base64.standard_b64encode(img.read_bytes()).decode()
    msg = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=4096,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}},
                {"type": "text", "text": VLM_PROMPT},
            ],
        }],
    )
    return msg.content[0].text


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--engines", default="tesseract", help="comma list: kraken,tesseract,vlm")
    ap.add_argument("--kraken-model", default="")
    args = ap.parse_args()
    engines = [e.strip() for e in args.engines.split(",")]

    samples = sorted(p for p in SAMPLES.glob("*") if p.suffix.lower() in (".jpg", ".jpeg", ".png"))
    pairs = [(p, p.with_suffix("").with_suffix(".gt.txt")) for p in samples]
    pairs = [(img, gt) for img, gt in pairs if gt.exists()]
    if not pairs:
        sys.exit(f"No samples with ground truth found in {SAMPLES}. See README.md.")

    RESULTS.mkdir(exist_ok=True)
    rows = []
    for img, gt_path in pairs:
        ref = gt_path.read_text(encoding="utf-8")
        for engine in engines:
            t0 = time.time()
            try:
                if engine == "kraken":
                    if not args.kraken_model:
                        sys.exit("--kraken-model required for kraken")
                    hyp = run_kraken(img, args.kraken_model)
                elif engine == "tesseract":
                    hyp = run_tesseract(img)
                elif engine == "vlm":
                    hyp = run_vlm(img)
                else:
                    continue
                elapsed = time.time() - t0
                rows.append((img.stem, engine, cer(hyp, ref), wer(hyp, ref), elapsed))
                print(f"{img.stem:30s} {engine:10s} CER {rows[-1][2]:.3f}  {elapsed:.1f}s")
            except Exception as e:
                rows.append((img.stem, engine, None, None, None))
                print(f"{img.stem:30s} {engine:10s} FAILED: {e}", file=sys.stderr)

    lines = ["# OCR benchmark report", "", "| page | engine | CER | WER | seconds |", "|---|---|---|---|---|"]
    for stem, engine, c, w, t in rows:
        if c is None:
            lines.append(f"| {stem} | {engine} | FAILED | — | — |")
        else:
            lines.append(f"| {stem} | {engine} | {c:.3f} | {w:.3f} | {t:.1f} |")
    lines.append("")
    for engine in engines:
        vals = [c for s, e, c, w, t in rows if e == engine and c is not None]
        if vals:
            mean = sum(vals) / len(vals)
            lines.append(f"- **{engine}** mean CER: {mean:.3f} over {len(vals)} pages")
            if engine == "vlm":
                lines.append(f"  - est. cost per 1000 pages: ~${VLM_COST_PER_PAGE_USD * 1000:.0f} "
                             "(adjust VLM_COST_PER_PAGE_USD to your provider pricing)")
    (RESULTS / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport: {RESULTS / 'report.md'}")


if __name__ == "__main__":
    main()
