"""STAATSBLAD_TOOL_DEFINITION_V3 — final Anthropic tool definition.

Matches STAATSBLAD_EXTRACTION_V3_SYSTEM_V5:
- Drops `publication_nature` from the top-level output (events-only).
- Caps `summary` at 60 chars.
- Only `event_type` and `summary` required per event; all other fields
  optional so the model can omit null values (paired with the
  FIELD-ECONOMY rule in the prompt).
- `event_type` is a strict 8-value enum — the API refuses anything
  else, which is the only reliable way to enforce schema conformance
  on this corpus (prompt-only instructions failed 30/30 in the pilot).

Copied verbatim from the pilot worktree
(`backend/routers/companies/_helpers.py::STAATSBLAD_TOOL_DEFINITION_V3`).
"""

STAATSBLAD_TOOL_DEFINITION_V3 = {
    "name": "emit_staatsblad_events",
    "description": (
        "Emit the structured list of board-relevant events extracted from a "
        "Belgian Staatsblad publication. Call this tool EXACTLY ONCE per "
        "publication. If the publication contains no board-relevant events "
        "of the 8 categories defined in the system prompt (e.g. pure-volmacht "
        "filings), call it with events=[]. Do NOT invent events, do NOT "
        "extract volmachten / bijzondere gevolmachtigden / procurations "
        "spéciales, do NOT extract natural-person representatives of "
        "statutory auditors. Omit optional fields whose value would be null "
        "or not applicable — only `event_type` and `summary` are required on "
        "each event; drop the rest when irrelevant.  `summary` MUST be ≤ 60 "
        "characters; longer values will be rejected downstream."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "events": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "event_type": {
                            "type": "string",
                            "enum": [
                                "admin_event",
                                "capital_event",
                                "share_transfer",
                                "ownership_change",
                                "ma_event",
                                "liquidation_event",
                                "corporate_change",
                                "other_notable",
                            ],
                        },
                        "sub_type": {"type": "string"},
                        "date": {"type": "string"},
                        "person_name": {"type": "string"},
                        "person_role": {"type": "string"},
                        "entity_name": {"type": "string"},
                        "amount_eur": {"type": "number"},
                        "amount_shares": {"type": "number"},
                        "summary": {"type": "string", "maxLength": 60},
                    },
                    "required": ["event_type", "summary"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["events"],
        "additionalProperties": False,
    },
}
