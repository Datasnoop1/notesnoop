from __future__ import annotations

import os
from functools import lru_cache

from dotenv import load_dotenv
from pydantic import BaseModel, Field


load_dotenv()


class Settings(BaseModel):
    database_url: str = Field(default_factory=lambda: os.getenv("NOTESNOOP_DATABASE_URL") or os.getenv("DATABASE_URL", ""))
    worker_database_url: str = Field(
        default_factory=lambda: os.getenv("NOTESNOOP_WORKER_DATABASE_URL")
        or os.getenv("NOTESNOOP_DATABASE_URL")
        or os.getenv("DATABASE_URL", "")
    )
    frontend_base_url: str = Field(default_factory=lambda: os.getenv("NOTESNOOP_FRONTEND_BASE_URL", "https://notesnoop.app"))
    backend_base_url: str = Field(default_factory=lambda: os.getenv("NOTESNOOP_BACKEND_BASE_URL", "https://api.notesnoop.app"))
    inbound_domain: str = Field(default_factory=lambda: os.getenv("NOTESNOOP_INBOUND_DOMAIN", "in.notesnoop.app"))
    email_ai_default: str = Field(default_factory=lambda: os.getenv("NOTESNOOP_EMAIL_AI_DEFAULT", "manual"))
    postmark_server_token: str = Field(default_factory=lambda: os.getenv("NOTESNOOP_POSTMARK_SERVER_TOKEN", ""))
    postmark_message_stream: str = Field(default_factory=lambda: os.getenv("NOTESNOOP_POSTMARK_MESSAGE_STREAM", "outbound"))
    postmark_from: str = Field(default_factory=lambda: os.getenv("NOTESNOOP_POSTMARK_FROM", "NoteSnoop <hello@notesnoop.app>"))
    postmark_morning_template_alias: str = Field(default_factory=lambda: os.getenv("NOTESNOOP_MORNING_BRIEFING_TEMPLATE_ALIAS", "notesnoop-morning-briefing-v1"))
    postmark_dry_run: bool = Field(default_factory=lambda: os.getenv("NOTESNOOP_POSTMARK_DRY_RUN", "").lower() in {"1", "true", "yes"})
    morning_briefing_hour: int = Field(default_factory=lambda: int(os.getenv("NOTESNOOP_MORNING_BRIEFING_HOUR", "8")))
    unsubscribe_secret: str = Field(default_factory=lambda: os.getenv("NOTESNOOP_UNSUBSCRIBE_SECRET", ""))
    dev_auth: bool = Field(default_factory=lambda: os.getenv("NOTESNOOP_DEV_AUTH", "").lower() in {"1", "true", "yes"})
    clerk_issuer: str = Field(default_factory=lambda: os.getenv("NOTESNOOP_CLERK_ISSUER") or os.getenv("CLERK_ISSUER", ""))
    clerk_jwks_url: str = Field(default_factory=lambda: os.getenv("NOTESNOOP_CLERK_JWKS_URL") or os.getenv("CLERK_JWKS_URL", ""))
    clerk_authorized_party: str = Field(default_factory=lambda: os.getenv("NOTESNOOP_CLERK_AUTHORIZED_PARTY") or os.getenv("CLERK_AUTHORIZED_PARTY", ""))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    if settings.email_ai_default not in {"manual", "auto"}:
        raise RuntimeError("NOTESNOOP_EMAIL_AI_DEFAULT must be manual or auto")
    if not 0 <= settings.morning_briefing_hour <= 23:
        raise RuntimeError("NOTESNOOP_MORNING_BRIEFING_HOUR must be between 0 and 23")
    return settings
