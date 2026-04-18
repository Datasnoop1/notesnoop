"""OCR fallback helper for Belgian Staatsblad PDFs whose body text sits in
scanned images behind a thin digital text-layer header band.

Strategy:

1. Extract text with fitz (PyMuPDF) first — free and fast.
2. If the fitz output, after boilerplate stripping, has fewer than
   MIN_BODY_CHARS characters of content, rasterize each page through fitz
   (no poppler dependency) and feed the page images to EasyOCR with Dutch
   and French language packs.
3. Return whichever source produced usable body text.

EasyOCR is used instead of Tesseract because the Tesseract installer requires
admin rights (UAC) on this host; EasyOCR is pure-Python + PyTorch and
installs cleanly unprivileged. EasyOCR is a traditional CNN-based OCR
system, not a vision LLM — so it satisfies the operator constraint that
vision LLMs must not be used for this step.

Costs: zero LLM spend.  First-use penalty: ~100 MB of PyTorch model weights
download the first time a Reader is instantiated.  Per-page runtime on CPU
is ~5-15 seconds depending on image density at 200 DPI.
"""

from __future__ import annotations

import io
import logging
import re
import unicodedata
from typing import Optional

import fitz  # PyMuPDF


log = logging.getLogger(__name__)


# ── Public API ───────────────────────────────────────────────


# Threshold for "fitz output has enough body to skip OCR".  Chosen from the
# header-only diagnostic — a bare-header cover page clocks in around
# 128-260 chars, while substantive filings start around 1,000+.  Setting the
# gate at 300 catches headers that repeat across multiple pages (which can
# stack to ~260 chars) while still passing genuinely short but real bodies.
MIN_BODY_CHARS = 300

# DPI for page rasterisation.  200 is a tradeoff — 300 is sharper but ~2x
# slower; 150 loses detail on small legal-notice typography.
OCR_DPI = 200


# Boilerplate to remove when measuring body length.  Kept in sync with the
# header-only diagnostic (scripts/header_only_diagnostic.py).
_BOILERPLATE_RES: list[re.Pattern] = [
    re.compile(r"Bijlagen\s+bij\s+het\s+Belgisch\s+Staatsblad", re.IGNORECASE),
    re.compile(r"Annexes?\s+du\s+Moniteur\s+belge", re.IGNORECASE),
    re.compile(r"Moniteur\s+belge", re.IGNORECASE),
    re.compile(r"Belgisch\s+Staatsblad", re.IGNORECASE),
    re.compile(r"Copie\s+à\s+publier\s+aux\s+annexes", re.IGNORECASE),
    re.compile(r"Volet\s+[AB]\b", re.IGNORECASE),
    re.compile(r"Mod\.?\s*PDF\s*\d+\.\d+", re.IGNORECASE),
    re.compile(r"\b\d{1,4}[/\-]\d{1,2}[/\-]\d{2,4}\b"),
    re.compile(r"\b\d{2}\d{6,9}\b"),
    re.compile(r"Page\s+\d+\s*/\s*\d+", re.IGNORECASE),
    re.compile(r"page\s+\d+\s+sur\s+\d+", re.IGNORECASE),
    re.compile(r"—\s*\d+\s*—"),
    re.compile(r"https?://\S+"),
    re.compile(r"www\.\S+"),
]


def strip_boilerplate(text: str) -> str:
    s = text
    for pat in _BOILERPLATE_RES:
        s = pat.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


# EasyOCR reader is expensive to construct (downloads weights, loads models).
# Build lazily and reuse across calls.
_reader: Optional[object] = None


def _get_reader():
    global _reader
    if _reader is not None:
        return _reader
    try:
        import easyocr  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "easyocr is not installed — run `python -m pip install easyocr`"
        ) from exc
    log.info("Initialising EasyOCR reader (nl+fr, CPU)...")
    # gpu=False is explicit so the reader doesn't try to load CUDA on a
    # machine that doesn't have it.  verbose=False silences the "Using CPU"
    # banner for every call.
    _reader = easyocr.Reader(["nl", "fr"], gpu=False, verbose=False)
    return _reader


def extract_with_fitz(pdf_bytes: bytes) -> str:
    """Extract text via fitz across all pages, concatenated with newlines."""
    try:
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            return "\n".join(page.get_text() or "" for page in doc)
    except Exception as e:
        log.warning("fitz failed: %s", e)
        return ""


def extract_with_easyocr(pdf_bytes: bytes) -> str:
    """Rasterize each page via fitz and OCR with EasyOCR (nl+fr)."""
    reader = _get_reader()
    texts: list[str] = []
    try:
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            for i, page in enumerate(doc):
                try:
                    pix = page.get_pixmap(dpi=OCR_DPI, alpha=False)
                    png_bytes = pix.tobytes("png")
                except Exception as e:
                    log.warning("rasterise page %d failed: %s", i, e)
                    continue
                try:
                    result = reader.readtext(png_bytes, detail=0, paragraph=True)
                except Exception as e:
                    log.warning("easyocr page %d failed: %s", i, e)
                    continue
                if result:
                    texts.append("\n".join(result))
    except Exception as e:
        log.warning("OCR pipeline failed: %s", e)
        return ""
    return "\n".join(texts)


def extract_text_with_fallback(pdf_bytes: bytes) -> tuple[str, str]:
    """Return (text, source) where source ∈ {'fitz', 'easyocr', 'both_empty'}.

    fitz is tried first; OCR only runs when the fitz output has fewer than
    MIN_BODY_CHARS of non-boilerplate content.
    """
    fitz_text = extract_with_fitz(pdf_bytes)
    body_len = len(strip_boilerplate(fitz_text))
    if body_len >= MIN_BODY_CHARS:
        return fitz_text, "fitz"

    log.info("fitz body_len=%d < %d → falling back to OCR", body_len, MIN_BODY_CHARS)
    ocr_text = extract_with_easyocr(pdf_bytes)
    ocr_body = len(strip_boilerplate(ocr_text))
    if ocr_body >= MIN_BODY_CHARS:
        # Prepend the fitz-extracted header band so the LLM still sees the
        # publication-date and language signals.
        combined = (fitz_text or "").strip() + "\n\n--- OCR BODY ---\n" + ocr_text
        return combined, "easyocr"

    # Neither source produced usable body text.  Return whichever was longer
    # so the caller can still inspect what came out.
    if len(fitz_text) >= len(ocr_text):
        return fitz_text, "both_empty"
    return ocr_text, "both_empty"


# ── Convenience: a self-test entry point ────────────────────


if __name__ == "__main__":
    import argparse
    import sys
    from pathlib import Path

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    p = argparse.ArgumentParser(description="Run fitz → easyocr fallback on one PDF.")
    p.add_argument("pdf_path", type=Path)
    args = p.parse_args()

    data = args.pdf_path.read_bytes()
    text, source = extract_text_with_fallback(data)
    body = strip_boilerplate(text)
    print(f"source: {source}")
    print(f"raw chars: {len(text)}")
    print(f"body chars (boilerplate-stripped): {len(body)}")
    print("--- first 800 chars of extracted text ---")
    print(text[:800])
