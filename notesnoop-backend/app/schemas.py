from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class BootstrapRequest(BaseModel):
    workspace_name: str | None = None
    inbox_mode: str = Field(default="per_user_private", pattern="^(per_user_private|shared)$")
    timezone: str = "UTC"
    morning_briefing_optin: bool = False


class WorkspaceSettingsUpdate(BaseModel):
    ai_mode: str | None = Field(default=None, pattern="^(on|manual)$")
    email_ai_mode: str | None = Field(default=None, pattern="^(auto|manual)$")
    morning_briefing_optin: bool | None = None


class PersonCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    company: str | None = Field(default=None, max_length=200)
    role: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=320)
    details: str | None = None


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    color_hex: str | None = Field(default=None, max_length=16)
    ai_mode: str = Field(default="on", pattern="^(on|manual)$")


class ProjectInviteCreate(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    display_name: str | None = Field(default=None, max_length=200)


class NoteCreate(BaseModel):
    body: str = Field(min_length=1)
    title: str | None = Field(default=None, max_length=200)
    project_ids: list[str] | None = None
    note_kind: str = Field(default="note", pattern="^(note|meeting|call|email|task|report)$")
    occurred_at: datetime | None = None


class NoteUpdate(BaseModel):
    body: str | None = Field(default=None, min_length=1)
    title: str | None = Field(default=None, max_length=200)
    note_kind: str | None = Field(default=None, pattern="^(note|meeting|call|email|task|report)$")
    occurred_at: datetime | None = None


class NoteProjectSet(BaseModel):
    project_ids: list[str] = Field(min_length=1)
    confirm_personal_move: bool = False


class NoteLinkPerson(BaseModel):
    person_id: str
    state: str = Field(default="confirmed", pattern="^(confirmed|auto_linked|pending)$")
    confidence: float | None = None
    source: str = Field(default="user", pattern="^(user|ai|collaborator_suggestion)$")


class FlagRequest(BaseModel):
    note_id: str | None = None
    project_id: str | None = None
    person_id: str | None = None


class EmailBlockRequest(BaseModel):
    sender_pattern: str | None = Field(default=None, max_length=320)
    note_id: str | None = None


class ReviewDecision(BaseModel):
    confidence: float | None = None


class PersonMergeRequest(BaseModel):
    target_person_id: str


class ApiResponse(BaseModel):
    data: Any
