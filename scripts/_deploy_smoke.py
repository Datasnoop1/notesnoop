"""Deploy smoke test — fails non-zero if any cron-invoked module is unimportable.

Run after `docker compose up -d --build` to catch path / import drift the
moment a deploy lands, instead of waiting for the next 06:00 cron tick to
fail silently into a log file. Triggered by scripts/deploy.sh and
scripts/deploy_staging.sh.

Each entry below is the dotted-module name a cron actually invokes (or
imports). Every name must remain importable inside the freshly-built
backend container — that's the contract: if you add a cron, add the
module here too.

Import-only — does not call main(). Module-level side effects (logging
config, constant evaluation) are fine; DB or HTTP I/O at import time would
make the smoke test flaky and should be moved into a function.
"""
from __future__ import annotations

import importlib
import sys

# Modules that live at /app/<name>.py (the backend Dockerfile copies the
# `backend/` directory there). These are the heavy daily/batch pipelines.
BACKEND_MODULES = [
    "kbo_daily_update",
    "nbb_batch_pipeline",
]

# Modules that live at /app/scripts/<name>.py (mounted from the repo's
# scripts/ directory). These are the shorter cron-invoked utilities and
# the daily monitoring digest.
SCRIPT_MODULES = [
    "alert_digest",
    "backfill_affiliation",
    "generate_valuation_commentary",
    "invoice_ingest",
    "nightly_health_report",
    "open_data_ted",
    "refresh_popularity",
    "staatsblad_batch_every_2d",
    "staatsblad_embed",
]


def _import_each(modules: list[str]) -> list[str]:
    """Return a list of '<name>: <error>' strings for every failure."""
    failures: list[str] = []
    for name in modules:
        try:
            importlib.import_module(name)
        except Exception as e:  # noqa: BLE001 — we want to report any import-time crash
            failures.append(f"{name}: {type(e).__name__}: {e}")
    return failures


def main() -> int:
    # /app and /app/scripts both need to be importable.
    sys.path.insert(0, "/app")
    sys.path.insert(0, "/app/scripts")

    failures: list[str] = []
    failures += _import_each(BACKEND_MODULES)
    failures += _import_each(SCRIPT_MODULES)

    total = len(BACKEND_MODULES) + len(SCRIPT_MODULES)
    if failures:
        print(f"SMOKE FAIL — {len(failures)}/{total} modules failed to import:")
        for f in failures:
            print(f"  {f}")
        return 1

    print(f"SMOKE OK — {total} modules imported clean.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
