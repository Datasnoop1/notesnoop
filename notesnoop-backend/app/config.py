from __future__ import annotations

import os
from functools import lru_cache

from dotenv import load_dotenv
from pydantic import BaseModel


load_dotenv()


class Settings(BaseModel):
    database_url: str = os.getenv("NOTESNOOP_DATABASE_URL") or os.getenv("DATABASE_URL", "")
    frontend_base_url: str = os.getenv("NOTESNOOP_FRONTEND_BASE_URL", "https://notesnoop.app")
    inbound_domain: str = os.getenv("NOTESNOOP_INBOUND_DOMAIN", "in.notesnoop.app")
    email_ai_default: str = os.getenv("NOTESNOOP_EMAIL_AI_DEFAULT", "manual")
    dev_auth: bool = os.getenv("NOTESNOOP_DEV_AUTH", "").lower() in {"1", "true", "yes"}
    clerk_issuer: str = os.getenv("NOTESNOOP_CLERK_ISSUER") or os.getenv("CLERK_ISSUER", "")
    clerk_jwks_url: str = os.getenv("NOTESNOOP_CLERK_JWKS_URL") or os.getenv("CLERK_JWKS_URL", "")
    clerk_authorized_party: str = os.getenv("NOTESNOOP_CLERK_AUTHORIZED_PARTY") or os.getenv("CLERK_AUTHORIZED_PARTY", "")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    if settings.email_ai_default not in {"manual", "auto"}:
        raise RuntimeError("NOTESNOOP_EMAIL_AI_DEFAULT must be manual or auto")
    return settings
