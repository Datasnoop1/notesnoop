from __future__ import annotations

from datetime import date, datetime
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


class CompanyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    domain: str | None = Field(default=None, max_length=240)
    description: str | None = None
    person_ids: list[str] | None = None
    project_ids: list[str] | None = None
    note_ids: list[str] | None = None


class CompanyUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    domain: str | None = Field(default=None, max_length=240)
    description: str | None = None
    person_ids: list[str] | None = None
    project_ids: list[str] | None = None
    note_ids: list[str] | None = None


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


class MemoryAskRequest(BaseModel):
    query: str = Field(min_length=3, max_length=500)
    project_id: str | None = None
    person_id: str | None = None
    date_from: str | None = None
    date_to: str | None = None


class MemoryAskCitation(BaseModel):
    kind: str = Field(pattern="^(note|task|meeting|report|workflow|company|person|project)$")
    id: str = Field(min_length=1)
    title: str | None = None
    label: str | None = None


class MemoryAskSaveReportRequest(BaseModel):
    query: str = Field(min_length=3, max_length=500)
    answer: str = Field(min_length=1)
    title: str | None = Field(default=None, max_length=240)
    confidence: float | None = Field(default=None, ge=0, le=1)
    citations: list[MemoryAskCitation] = Field(default_factory=list)
    source_counts: dict[str, Any] = Field(default_factory=dict)
    project_id: str | None = None
    person_id: str | None = None


class MemoryAskSaveTaskRequest(BaseModel):
    query: str = Field(min_length=3, max_length=500)
    answer: str = Field(min_length=1)
    title: str | None = Field(default=None, max_length=240)
    confidence: float | None = Field(default=None, ge=0, le=1)
    citations: list[MemoryAskCitation] = Field(default_factory=list)
    project_id: str | None = None
    person_id: str | None = None
    due_at: datetime | None = None


class NoteProjectSet(BaseModel):
    project_ids: list[str] = Field(min_length=1)
    confirm_personal_move: bool = False


class NoteLinkPerson(BaseModel):
    person_id: str
    state: str = Field(default="confirmed", pattern="^(confirmed|auto_linked|pending)$")
    confidence: float | None = None
    source: str = Field(default="user", pattern="^(user|ai|collaborator_suggestion)$")


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    description: str | None = None
    status: str = Field(default="todo", pattern="^(todo|doing|blocked|done|archived)$")
    priority: int = Field(default=3, ge=1, le=5)
    due_at: datetime | None = None
    project_ids: list[str] | None = None
    person_ids: list[str] | None = None
    company_ids: list[str] | None = None
    note_ids: list[str] | None = None
    assignee_id: str | None = None


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=240)
    description: str | None = None
    status: str | None = Field(default=None, pattern="^(todo|doing|blocked|done|archived)$")
    priority: int | None = Field(default=None, ge=1, le=5)
    due_at: datetime | None = None
    project_ids: list[str] | None = None
    person_ids: list[str] | None = None
    company_ids: list[str] | None = None
    note_ids: list[str] | None = None
    assignee_id: str | None = None


class TaskReminderUpdate(BaseModel):
    remind_at: datetime | None = None
    state: str | None = Field(default=None, pattern="^(pending|sent|dismissed|snoozed)$")
    snoozed_until: datetime | None = None


class MeetingCreate(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    occurred_at: datetime | None = None
    location: str | None = Field(default=None, max_length=240)
    summary: str | None = None
    project_ids: list[str] | None = None
    person_ids: list[str] | None = None
    company_ids: list[str] | None = None
    note_ids: list[str] | None = None


class MeetingUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=240)
    occurred_at: datetime | None = None
    location: str | None = Field(default=None, max_length=240)
    summary: str | None = None
    project_ids: list[str] | None = None
    person_ids: list[str] | None = None
    company_ids: list[str] | None = None
    note_ids: list[str] | None = None


class ReportCreate(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    body: str | None = None
    status: str = Field(default="draft", pattern="^(draft|published|archived)$")
    period_start: date | None = None
    period_end: date | None = None
    project_ids: list[str] | None = None
    person_ids: list[str] | None = None
    company_ids: list[str] | None = None
    note_ids: list[str] | None = None
    task_ids: list[str] | None = None
    meeting_ids: list[str] | None = None
    report_ids: list[str] | None = None
    workflow_ids: list[str] | None = None


class ProjectReportGenerateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=240)
    variant: str = Field(default="full", pattern="^(quick|full)$")


class ReportUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=240)
    body: str | None = None
    status: str | None = Field(default=None, pattern="^(draft|published|archived)$")
    period_start: date | None = None
    period_end: date | None = None
    project_ids: list[str] | None = None
    person_ids: list[str] | None = None
    company_ids: list[str] | None = None
    note_ids: list[str] | None = None
    task_ids: list[str] | None = None
    meeting_ids: list[str] | None = None
    report_ids: list[str] | None = None
    workflow_ids: list[str] | None = None


class WorkflowCreate(BaseModel):
    name: str = Field(min_length=1, max_length=240)
    description: str | None = None
    status: str = Field(default="active", pattern="^(draft|active|paused|retired)$")
    project_ids: list[str] | None = None
    person_ids: list[str] | None = None
    company_ids: list[str] | None = None
    note_ids: list[str] | None = None
    task_ids: list[str] | None = None


class WorkflowUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=240)
    description: str | None = None
    status: str | None = Field(default=None, pattern="^(draft|active|paused|retired)$")
    project_ids: list[str] | None = None
    person_ids: list[str] | None = None
    company_ids: list[str] | None = None
    note_ids: list[str] | None = None
    task_ids: list[str] | None = None


class FlagRequest(BaseModel):
    note_id: str | None = None
    project_id: str | None = None
    person_id: str | None = None


class EmailBlockRequest(BaseModel):
    sender_pattern: str | None = Field(default=None, max_length=320)
    note_id: str | None = None


class ReviewDecision(BaseModel):
    confidence: float | None = None
    payload: dict[str, Any] | None = None
    materialize: bool = True


class PersonMergeRequest(BaseModel):
    target_person_id: str


class ApiResponse(BaseModel):
    data: Any
