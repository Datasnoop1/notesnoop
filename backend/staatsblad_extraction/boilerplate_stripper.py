"""Strip Belgian Staatsblad boilerplate from extracted text before LLM input.

Pure-Python regex pass. Designed to reduce token count by 10-20% without
removing any content a downstream admin/M&A/capital event extractor would
need. Safe to call on arbitrary text; returns the input unchanged if no
patterns match.
"""

from __future__ import annotations

import re
from typing import Callable


# Each pattern is a (regex, replacement) pair. Order matters only in that
# we strip whole-line patterns first, then inline patterns, then finally
# collapse whitespace.  All patterns are case-insensitive.
_PATTERNS: list[tuple[re.Pattern, str]] = [
    # "Bijlagen bij het Belgisch Staatsblad - 25/10/2024 - Annexes du Moniteur belge"
    # variants (sometimes the date is missing, sometimes doubled, sometimes
    # the two halves sit on separate lines).
    (re.compile(r"Bijlagen\s+bij\s+het\s+Belgisch\s+Staatsblad\s*-?\s*(\d{1,4}[/\-]\d{1,2}[/\-]\d{2,4})?\s*-?\s*Annexes?\s+du\s+Moniteur\s+belge\s*",
                re.IGNORECASE), " "),
    # Each half on its own (rare but observed in OCR'd headers)
    (re.compile(r"Bijlagen\s+bij\s+het\s+Belgisch\s+Staatsblad", re.IGNORECASE), " "),
    (re.compile(r"Annexes?\s+du\s+Moniteur\s+belge", re.IGNORECASE), " "),
    (re.compile(r"Moniteur\s+belge", re.IGNORECASE), " "),
    (re.compile(r"Belgisch\s+Staatsblad", re.IGNORECASE), " "),

    # "--- OCR BODY ---" separator inserted by the fitz→easyocr pipeline
    (re.compile(r"-{3,}\s*OCR\s*BODY\s*-{3,}", re.IGNORECASE), " "),

    # "Copie à publier aux annexes au Moniteur belge" cover-page boilerplate
    (re.compile(r"Copie\s+à\s+publier\s+aux\s+annexes\s+au\s+Moniteur\s+belge.*",
                re.IGNORECASE), " "),
    # "Volet A" / "Volet B" sheet labels
    (re.compile(r"\bVolet\s+[AB]\b", re.IGNORECASE), " "),
    # "Mod PDF 19.01" or "Mod DOC 19.01" cover-page form ID
    (re.compile(r"Mod\.?\s*(?:PDF|DOC)\s*\d+\.?\d*", re.IGNORECASE), " "),
    # "Réservé au Moniteur belge" tagline
    (re.compile(r"R[ée]serv[ée]\s+au\s+Moniteur\s+belge", re.IGNORECASE), " "),

    # Reference numbers at line start (the 10-13 digit ejustice ID)
    (re.compile(r"(?m)^\s*\d{10,13}\s*$"), ""),
    # Stand-alone reference quotes like "*24154134*" or N° 24154134
    (re.compile(r"\*?\d{8,12}\*?", re.IGNORECASE), " "),

    # Page numbers ("Pagina X van Y" / "Page X sur Y" / "— X —")
    (re.compile(r"\bPagina\s+\d+\s+van\s+\d+\b", re.IGNORECASE), " "),
    (re.compile(r"\bPage\s+\d+\s+sur\s+\d+\b", re.IGNORECASE), " "),
    (re.compile(r"\bPage\s+\d+\s*/\s*\d+\b", re.IGNORECASE), " "),
    (re.compile(r"—\s*\d+\s*—"), " "),

    # URL and email footers
    (re.compile(r"https?://\S+"), " "),
    (re.compile(r"www\.\S+"), " "),
    (re.compile(r"\S+@\S+\.\S+"), " "),

    # "N° d'entreprise:" label variants (the CBE is already known out-of-
    # band to the caller — stripping the label saves tokens, not signal).
    (re.compile(r"N\u00b0\s*d['’]entreprise\s*:?", re.IGNORECASE), " "),
    (re.compile(r"Ondernemingsnummer\s*:?", re.IGNORECASE), " "),

    # Copyright stubs
    (re.compile(r"©\s*\d{4}(?:\s*-\s*\d{4})?\s*[^\n]*", re.IGNORECASE), " "),
]


_REPEATED_WHITESPACE = re.compile(r"[ \t]+")
_REPEATED_NEWLINES = re.compile(r"\n{3,}")


def strip_staatsblad_boilerplate(text: str) -> str:
    """Remove predictable Staatsblad boilerplate + collapse whitespace.

    Returns text unchanged in length if nothing matched.  Safe to call on
    empty / None-ish inputs.
    """
    if not text:
        return text or ""
    out = text
    for pat, repl in _PATTERNS:
        out = pat.sub(repl, out)
    # Collapse runs of spaces/tabs on a single line, keep paragraph breaks.
    out = _REPEATED_WHITESPACE.sub(" ", out)
    # Trim per-line whitespace.
    out = "\n".join(line.strip() for line in out.splitlines())
    # Collapse 3+ blank lines to 2.
    out = _REPEATED_NEWLINES.sub("\n\n", out)
    return out.strip()


# ── Aggressive sectioner ────────────────────────────────────


# Additional strip patterns (applied AFTER strip_staatsblad_boilerplate).
# All case-insensitive regexes. Each is tuned to remove content that
# carries no admin/capital/M&A signal for the extractor.

_AGGRESSIVE_PATTERNS: list[tuple[re.Pattern, str]] = [
    # Repeated big-caps "BIJLAGEN BIJ HET BELGISCH STAATSBLAD" / "ANNEXES
    # DU MONITEUR BELGE" that re-appear on every page of a multi-page
    # filing (the base stripper removes one occurrence per line pattern,
    # but OCR sometimes splits them into multi-word runs the base regex
    # doesn't match).
    (re.compile(r"BIJLAGEN\s+BIJ\s+HET\s+BELGISCH\s+STAATSBLAD", re.IGNORECASE), " "),
    (re.compile(r"ANNEXES?\s+DU\s+MONITEUR\s+BELGE", re.IGNORECASE), " "),

    # Page markers that the base stripper partially handles.  Catch
    # OCR variants: "— 2 / 7 —" / "Pag. 2 / 7" / "[2/7]" / "2 van 7".
    (re.compile(r"\b(?:Pag\.?|Pagina|Page|P\.)\s*\d+\s*(?:/|van|sur|of)\s*\d+\b", re.IGNORECASE), " "),
    (re.compile(r"\[\s*\d+\s*/\s*\d+\s*\]"), " "),
    (re.compile(r"—\s*\d+\s*/\s*\d+\s*—"), " "),

    # Numac reference lines (e.g. "19-11-2024 — Numac: 2024154134" /
    # "Numac : 2025123456").
    (re.compile(r"\bNumac\s*[:=]?\s*\d{9,}\b", re.IGNORECASE), " "),
    # Loose "DD-MM-YYYY — N: nnnn" patterns at line start.
    (re.compile(r"(?m)^\s*\d{1,2}[-/\.]\d{1,2}[-/\.]\d{2,4}\s*[—\-–]\s*N[°:]?\s*\d+\s*$", re.IGNORECASE), ""),

    # Certification / signature-of-authenticity blocks at end-of-document.
    # We remove the line + up to the next blank line / paragraph break.
    (re.compile(
        r"(?:Pour\s+copie\s+conforme|Voor\s+eensluidend\s+afschrift|Verklaring\s+van\s+echtheid|Certifi[ée]\s+conforme)"
        r"[^\n]{0,400}?(?=\n\s*\n|\Z)",
        re.IGNORECASE | re.DOTALL,
    ), " "),

    # "Le greffier" / "De griffier" signature attributions — always
    # trailing metadata.
    (re.compile(r"\b(?:Le|La)\s+(?:greffier|greffi[èe]re|secrétaire)(?:[^\n]{0,120})?", re.IGNORECASE), " "),
    (re.compile(r"\b(?:De|Het)\s+griffier(?:[^\n]{0,120})?", re.IGNORECASE), " "),

    # Notary attribution in trailing position (standalone line starting
    # "Notaire" / "Notaris" followed by a name, no verbs).
    (re.compile(r"(?m)^\s*(?:Notaire|Notaris)\s+[A-Z][^\n]{0,100}$"), ""),

    # Repeated "Mod PDF 19.01" / "Mod DOC 19.01" form markers.
    (re.compile(r"\bMod\.?\s*(?:PDF|DOC|WORD)\s*\d+[\.\-]?\d*", re.IGNORECASE), " "),
]


def _strip_header_prefix(text: str, entity_name: str | None = None,
                        cbe: str | None = None) -> str:
    """If the filing opens with company-identification boilerplate that
    we already know out-of-band (CBE + address + entity name), strip it.

    The prefix usually runs from the start to the first occurrence of
    "Objet de l'acte" / "Voorwerp van de akte" / "Démission" /
    "Ontslag" / "Nomination" etc.  If such a marker isn't found in the
    first ~700 chars, leave the text alone.
    """
    markers = (
        r"Objet\s+de\s+l['’]acte",
        r"Voorwerp\s+van\s+de\s+akte",
        r"Beslissingen?\s+van",
        r"D[ée]cisions?\s+(?:du|de|des)",
        r"Il\s+r[ée]sulte",
        r"Het\s+blijkt",
        r"Résolutions\b",
        r"Resoluties\b",
        r"Ontslag\b",
        r"Benoeming\b",
        r"D[ée]mission\b",
        r"Nomination\b",
        r"Verklaringen\b",
    )
    pat = re.compile(r"\b(?:" + "|".join(markers) + r")\b", re.IGNORECASE)
    m = pat.search(text[:1200])
    if not m or m.start() < 30:
        return text
    # Only strip if the prefix really does look like boilerplate — check
    # for presence of N° d'entreprise / Ondernemingsnummer / Forme légale
    # tokens in the candidate prefix.
    prefix = text[: m.start()]
    prefix_signals = (
        "N° d'entreprise", "Ondernemingsnummer", "Forme légale",
        "Rechtsvorm", "Adresse complète du siège", "Maatschappelijke zetel",
        "Enterprise", "entreprise", "onderneming",
    )
    hit = sum(1 for s in prefix_signals if s.lower() in prefix.lower())
    if hit < 2:
        return text
    return text[m.start():]


def aggressive_section(text: str, entity_name: str | None = None,
                       cbe: str | None = None) -> str:
    """Aggressive sectioner: strip everything `strip_staatsblad_boilerplate`
    handles, plus repeated headers / page markers / certification blocks /
    greffier-notary attributions, plus the cover-page identification prefix
    if present.

    Always a strict superset of `strip_staatsblad_boilerplate` — safe to
    call as the single pre-processing step.
    """
    if not text:
        return text or ""
    # Start from the base-stripper output so we don't duplicate work.
    out = strip_staatsblad_boilerplate(text)
    # Apply aggressive patterns.
    for pat, repl in _AGGRESSIVE_PATTERNS:
        out = pat.sub(repl, out)
    # Strip the cover-page identification prefix if it precedes an "Objet"
    # / "Voorwerp" / "Beslissingen" marker and contains entity-id signals.
    out = _strip_header_prefix(out, entity_name=entity_name, cbe=cbe)
    # Collapse whitespace one more time.
    out = _REPEATED_WHITESPACE.sub(" ", out)
    out = "\n".join(line.strip() for line in out.splitlines())
    out = _REPEATED_NEWLINES.sub("\n\n", out)
    return out.strip()


# ── Self-test / validation ──────────────────────────────────


def _sample_filings(n: int = 3) -> list[tuple[str, str]]:
    """Pick n substantive v2_fixed cache files for the validation pass."""
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    cache_dir = root / "scripts" / "pilot_results_v2_fixed" / "pdf_cache"
    candidates = sorted(cache_dir.glob("*.txt"))
    picks: list[tuple[str, str]] = []
    for p in candidates:
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if len(text) < 1500:
            continue  # skip tiny files
        picks.append((p.stem, text))
        if len(picks) >= n:
            break
    return picks


def _contains_admin_signal(text: str) -> bool:
    """A quick check that the stripper didn't delete obvious admin content.

    We want to see at least one of these tokens survive the strip in any
    filing that actually contains admin content.
    """
    markers = (
        "Bestuurder", "Administrateur", "Gérant", "Zaakvoerder",
        "benoemd", "nommé", "ontslag", "démission", "Commissaris",
    )
    return any(m.lower() in text.lower() for m in markers)


if __name__ == "__main__":
    print("== boilerplate_stripper self-test ==")
    picks = _sample_filings(3)
    if not picks:
        print("No cached files found — run Phase C first.")
        raise SystemExit(1)
    total_before = 0
    total_after = 0
    for ref, text in picks:
        before = len(text)
        after_text = strip_staatsblad_boilerplate(text)
        after = len(after_text)
        signal_before = _contains_admin_signal(text)
        signal_after = _contains_admin_signal(after_text)
        reduction = 100.0 * (before - after) / before if before else 0.0
        print(f"  {ref}: {before} → {after} chars  (−{reduction:.1f}%)  "
              f"admin-signal before={signal_before} after={signal_after}")
        total_before += before
        total_after += after
    overall = 100.0 * (total_before - total_after) / total_before if total_before else 0.0
    print(f"== Overall: {total_before} → {total_after}  (−{overall:.1f}%) ==")
