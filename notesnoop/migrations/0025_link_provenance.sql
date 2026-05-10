-- @migration: tx
-- @migration: lock_timeout=5s
-- @migration: statement_timeout=120s

-- Add a per-link provenance column ("linked_via") to the entity-people
-- relation tables so the UI can render evidence badges (AI / Manual /
-- Email / Collaborator) on entity-detail relationship rows.

ALTER TABLE task_people
  ADD COLUMN IF NOT EXISTS linked_via TEXT;

ALTER TABLE meeting_people
  ADD COLUMN IF NOT EXISTS linked_via TEXT;

ALTER TABLE report_people
  ADD COLUMN IF NOT EXISTS linked_via TEXT;

ALTER TABLE workflow_people
  ADD COLUMN IF NOT EXISTS linked_via TEXT;

ALTER TABLE company_people
  ADD COLUMN IF NOT EXISTS linked_via TEXT;

-- Same for the company-link tables so company chips can carry a badge too.
ALTER TABLE task_companies
  ADD COLUMN IF NOT EXISTS linked_via TEXT;

ALTER TABLE meeting_companies
  ADD COLUMN IF NOT EXISTS linked_via TEXT;

ALTER TABLE workflow_companies
  ADD COLUMN IF NOT EXISTS linked_via TEXT;

-- And the project-link tables.
ALTER TABLE task_projects
  ADD COLUMN IF NOT EXISTS linked_via TEXT;

ALTER TABLE meeting_projects
  ADD COLUMN IF NOT EXISTS linked_via TEXT;

ALTER TABLE workflow_projects
  ADD COLUMN IF NOT EXISTS linked_via TEXT;

ALTER TABLE report_projects
  ADD COLUMN IF NOT EXISTS linked_via TEXT;

ALTER TABLE company_projects
  ADD COLUMN IF NOT EXISTS linked_via TEXT;
