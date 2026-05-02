"""Runtime feature flags.

Flags read os.environ on every call so an env-file flip plus container
recreate changes behavior without a code deploy.
"""

from __future__ import annotations

import os


_TRUE_VALUES = {"1", "true", "t", "yes", "y", "on"}


def env_flag_enabled(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in _TRUE_VALUES


def person_public_url_enabled() -> bool:
    return env_flag_enabled("PERSON_PUBLIC_URL_ENABLED", False)
