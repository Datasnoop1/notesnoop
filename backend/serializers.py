"""Shared row serialisers — JSON-safe conversion of psycopg2 RealDictRow.

Most routers had a private `_serialize_row` doing Decimal → float + date →
isoformat. This centralises it. Import from here in new code; existing
copies can migrate opportunistically.
"""

import datetime
import decimal
from typing import Iterable


def serialize_row(row: dict) -> dict:
    """Return a copy of `row` with Decimal → float + (date|datetime) → ISO str."""
    out: dict = {}
    for k, v in row.items():
        if isinstance(v, decimal.Decimal):
            out[k] = float(v)
        elif isinstance(v, (datetime.date, datetime.datetime)):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out


def serialize_rows(rows: Iterable[dict]) -> list[dict]:
    return [serialize_row(r) for r in rows]
