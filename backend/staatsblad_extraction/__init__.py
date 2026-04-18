"""Staatsblad extraction pipeline.

Pipeline: staatsblad_publication → PDF → fitz→OCR fallback →
boilerplate stripper → aggressive sectioner → Haiku 4.5 tool-use →
staatsblad_event + staatsblad_publication_text.

Entry points:
    extractor.extract_one(pub_row)     — regular-API (single-filing) path,
                                         used by the daily incremental.
    extractor.build_batch_request(pub_row) — build one Anthropic batch
                                         request; used by the backfill.
    extractor.persist_events(...)      — write parsed events + body text
                                         to Postgres, idempotent.

Constants:
    STAATSBLAD_EXTRACTION_V3_SYSTEM_V5  — finalised system prompt.
    STAATSBLAD_TOOL_DEFINITION_V3       — tool definition with strict
                                          enum + summary length cap.
"""

from .prompt_v3 import (  # noqa: F401
    STAATSBLAD_EXTRACTION_V3_SYSTEM_V5,
    STAATSBLAD_EXTRACTION_V3_USER,
)
from .tool_v3 import STAATSBLAD_TOOL_DEFINITION_V3  # noqa: F401
