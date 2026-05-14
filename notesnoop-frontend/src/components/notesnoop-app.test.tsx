import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { NoteSnoopApp } from "./notesnoop-app";
import { ServiceWorkerRegistration } from "./service-worker-registration";

vi.mock("@clerk/nextjs", () => ({
  SignInButton: ({ children }: { children: ReactNode }) => <>{children}</>,
  UserButton: () => <button aria-label="User menu">User</button>,
  useAuth: () => ({
    getToken: vi.fn().mockResolvedValue("test-token"),
    isSignedIn: true,
    isLoaded: true,
  }),
}));

const workspace = {
  id: "workspace-1",
  name: "Test workspace",
  email_ai_mode: "manual",
  morning_briefing_optin: false,
};
const projects = [
  { id: "inbox-1", name: "Inbox", kind: "inbox", color_hex: "#0f766e" },
  { id: "personal-1", name: "Personal", kind: "personal", color_hex: "#7c3aed" },
  { id: "project-1", name: "Apollo", kind: "user", color_hex: "#e85d4f" },
];
const people = [
  { id: "person-1", name: "Morgan Lee", confirmed_note_count: 2 },
  { id: "person-2", name: "Jordan Kim", confirmed_note_count: 1 },
];
const pending = [
  { id: "review-1", entity_kind: "person", payload: { name: "Morgan Lee", confidence: 0.82 } },
  { id: "review-2", entity_kind: "project", payload: { name: "Apollo", confidence: 0.79 } },
];
const note = {
  id: "note-1",
  title: "Apollo update",
  title_is_derived: false,
  body: "Morgan mentioned Apollo follow-up.",
  note_kind: "email",
  projects: [projects[0]],
  people: [],
  versions: [{ version: 1 }],
  raw_email_metadata: { sender: "sender@example.test", subject: "Forwarded diligence note" },
  ai_processing_status: "skipped",
  project_nudge: { inbox_only: true, matched_projects: [projects[2]], can_create_project: true },
  review_suggestions: [{ id: "review-2", entity_kind: "project", reason: "ai_suggestion", payload: { name: "Apollo", confidence: 0.79 } }],
  memory_links: [
    { id: "task-1", kind: "task", section_id: "tasks", title: "Prepare Apollo follow-up", subtitle: "Ask Morgan for the revised timeline.", status: "todo" },
    { id: "company-1", kind: "company", section_id: "companies", title: "Northstar", subtitle: "northstar.example" },
  ],
};
const taskNote = {
  ...note,
  id: "note-task-1",
  title: "Send Apollo follow-up",
  body: "Ask Morgan for the revised diligence timeline.",
  note_kind: "task",
  status: "todo",
  due_at: "2026-05-15T12:00:00Z",
  reminders: [{ id: "reminder-1", remind_at: "2026-05-15T12:00:00Z", state: "pending", attention_at: "2026-05-15T12:00:00Z" }],
  raw_email_metadata: undefined,
  project_nudge: undefined,
};
const meetingNote = {
  ...note,
  id: "note-meeting-1",
  title: "Morgan kickoff call",
  body: "Jordan needs the call recap before Friday.",
  note_kind: "call",
  raw_email_metadata: undefined,
  project_nudge: undefined,
};
const reportNote = {
  ...note,
  id: "note-report-1",
  title: "Apollo weekly brief",
  body: "Progress, blockers, and next decisions for Apollo.",
  note_kind: "report",
  raw_email_metadata: undefined,
  project_nudge: undefined,
};
const personTimeline = {
  person: people[0],
  events: [
    { id: "meeting-1", kind: "meeting", section_id: "meetings", title: "Morgan kickoff call", subtitle: "Discussed Apollo timeline.", event_at: "2026-05-10T09:00:00Z", project_name: "Apollo" },
    { id: "task-1", kind: "task", section_id: "tasks", title: "Send Apollo follow-up", subtitle: "Ask Morgan for the revised diligence timeline.", status: "todo", event_at: "2026-05-15T12:00:00Z", project_name: "Apollo" },
    { id: "note-1", note_id: "note-1", kind: "note", section_id: "notes", title: "Apollo update", subtitle: "Morgan mentioned Apollo follow-up.", status: "email", event_at: "2026-05-09T08:00:00Z" },
  ],
  projects: [{ ...projects[2], mention_count: 1 }],
  notes: [{ ...note, created_at: "2026-05-09T08:00:00Z" }],
};
const projectTimeline = {
  project: projects[2],
  events: [
    { id: "report-1", kind: "report", section_id: "reports", title: "Apollo weekly brief", subtitle: "Progress and blockers.", status: "draft", event_at: "2026-05-11T09:00:00Z" },
    { id: "meeting-1", kind: "meeting", section_id: "meetings", title: "Morgan kickoff call", subtitle: "Discussed Apollo timeline.", event_at: "2026-05-10T09:00:00Z" },
    { id: "note-1", note_id: "note-1", kind: "note", section_id: "notes", title: "Apollo update", subtitle: "Morgan mentioned Apollo follow-up.", status: "email", event_at: "2026-05-09T08:00:00Z" },
  ],
  members: [{ clerk_user_id: "dev_user", display_name: "Dev User" }],
  invites: [{ id: "invite-1", email: "pending@example.test", status: "pending" }],
  people: [{ ...people[0], mention_count: 1 }],
  notes: [{ ...note, created_at: "2026-05-09T08:00:00Z" }],
};

function json(data: unknown) {
  return new Response(JSON.stringify(data), { status: 200, headers: { "Content-Type": "application/json" } });
}

function streamResponse() {
  return new Response(
    new ReadableStream({
      start(controller) {
        controller.close();
      },
    }),
    { status: 200 },
  );
}

function installFetch(options: { people?: any[]; notes?: any[]; home?: Record<string, unknown>; pendingItems?: any[]; projects?: any[]; projectTimeline?: Record<string, unknown> } = {}) {
  const calls: string[] = [];
  const responsePeople = options.people ?? people;
  const responseNotes = options.notes ?? [note, taskNote, meetingNote, reportNote];
  const responsePending = options.pendingItems ?? pending;
  const responseProjects = options.projects ?? projects;
  const responseProjectTimeline = options.projectTimeline ?? projectTimeline;
  let sourceProjectMerged = false;
  let noteProcessingQueued = false;
  const memoryResults = [
    { id: "task-1", kind: "task", title: "Send Apollo diligence follow-up", subtitle: "Ask Morgan for the revised timeline." },
    { id: "company-1", kind: "company", title: "Northstar", subtitle: "northstar.example" },
  ];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    calls.push(`${init?.method || "GET"} ${url}`);
    if (sourceProjectMerged && url.includes("project_id=project-1")) {
      return new Response("Project not found", { status: 404 });
    }
    if (url.includes("/api/events/")) return streamResponse();
    if (url.includes("/api/me")) {
      return json({
        data: {
          bootstrapped: true,
          workspace,
          workspaces: [{ id: workspace.id, name: workspace.name, role: "admin" }],
          projects: responseProjects,
          people: responsePeople,
          inbound_address: "dev@in.notesnoop.app",
        },
      });
    }
    if (url.includes("/api/workspaces/workspace-1/home")) {
      return json({
        data: {
          pending_review: responsePending,
          recent_projects: [responseProjects[2]],
          recent_people: responsePeople,
          companies: [{ id: "company-1", name: "Northstar", domain: "northstar.example" }],
          workflows: [
            { id: "workflow-1", name: "Diligence loop", status: "active", updated_at: "2026-05-10T10:00:00Z" },
            { id: "workflow-2", name: "Paused outreach", status: "paused", updated_at: "2026-05-09T10:00:00Z" },
          ],
          flagged: [{ id: "flag-1", label: "Apollo update", target_kind: "note", note_id: "note-1" }],
          recent_notes: responseNotes,
          ...options.home,
        },
      });
    }
    if (url.includes("/api/workspaces/workspace-1/memory-graph")) {
      return json({
        data: {
          nodes: [
            { id: "note-1", kind: "note", title: "Apollo update" },
            { id: "person-1", kind: "person", title: "Morgan Lee" },
            { id: "project-1", kind: "project", title: "Apollo" },
            { id: "note-task-1", kind: "task", title: "Send Apollo follow-up" },
            { id: "workflow-1", kind: "workflow", title: "Diligence loop", status: "active" },
            { id: "company-1", kind: "company", title: "Northstar", domain: "northstar.example" },
          ],
          edges: [
            { from_kind: "note", from_id: "note-1", to_kind: "person", to_id: "person-1", relation: "mentions" },
            { from_kind: "task", from_id: "note-task-1", to_kind: "note", to_id: "note-1", relation: "sourced_from" },
            { from_kind: "workflow", from_id: "workflow-1", to_kind: "task", to_id: "note-task-1", relation: "contains" },
          ],
        },
      });
    }
    if (url.includes("/api/workspaces/workspace-1/review-queue")) {
      return json({
        data: responsePending.map((item) => ({
          ...item,
          source_note_title: "Apollo update",
          source_snippet: "Morgan mentioned Apollo follow-up.",
          projects: [responseProjects[2]],
        })),
        meta: { count: responsePending.length },
      });
    }
    if (url.includes("/api/workspaces/workspace-1/search")) {
      return json({
        data: responseNotes,
        meta: { semantic_enabled: false, semantic_excluded: 0, memory_results: memoryResults },
      });
    }
    if (url.includes("/api/workspaces/workspace-1/triage/process") && init?.method === "POST") {
      const ids = JSON.parse(String(init.body))?.note_ids || [];
      return json({ data: { queued: ids, skipped: [] }, meta: { count: ids.length } });
    }
    if (url.includes("/api/workspaces/workspace-1/triage/archive") && init?.method === "POST") {
      const ids = JSON.parse(String(init.body))?.note_ids || [];
      return json({ data: { archived: ids }, meta: { count: ids.length } });
    }
    if (url.includes("/api/workspaces/workspace-1/triage")) {
      return json({
        data: [
          {
            id: "triage-note-1",
            title: "Forwarded diligence note",
            body_preview: "Morgan asked about Apollo timeline.",
            note_kind: "email",
            raw_email_metadata: { sender: "sender@example.test", subject: "Forwarded diligence note" },
            projects: [],
          },
        ],
        meta: { count: 1 },
      });
    }
    if (url.includes("/api/workspaces/workspace-1/ask/report") && init?.method === "POST") {
      return json({ data: { id: "report-created", ...JSON.parse(String(init.body)), status: "draft", projects: [responseProjects[2]] } });
    }
    if (url.includes("/api/workspaces/workspace-1/ask/task") && init?.method === "POST") {
      return json({ data: { id: "task-created", ...JSON.parse(String(init.body)), status: "todo", projects: [responseProjects[2]] } });
    }
    if (url.includes("/api/workspaces/workspace-1/companies") && init?.method === "POST") {
      const body = JSON.parse(String(init.body));
      return json({ data: { id: "company-1", name: body.name, people: body.person_ids?.map((id: string) => ({ id })) || [] } });
    }
    if (url.includes("/api/workspaces/workspace-1/ask")) {
      return json({
        data: {
          answer: "### Answer\n- Apollo has a blocked pricing loop [N1].\n- Morgan owns the next follow-up [M1].",
          confidence: 0.74,
          citations: [
            { kind: "note", id: "note-1", title: "Apollo update", label: "N1" },
            { kind: "task", id: "note-task-1", title: "Send Apollo follow-up", label: "M1" },
          ],
          source_counts: { notes: 1, memory: 1 },
        },
      });
    }
    if (url.includes("/api/workspaces/workspace-1/notes") && init?.method === "POST") {
      return json({ data: { ...note, title: "Fresh note", body: JSON.parse(String(init.body)).body } });
    }
    if (url.includes("/api/notes/processing-note")) {
      return json({
        data: {
          ...note,
          id: "processing-note",
          title: "Processing note",
          ai_processing_status: "processed",
          review_suggestions: [],
        },
      });
    }
    if (url.includes("/api/workspaces/workspace-1/tasks") && init?.method === "POST") {
      return json({ data: { id: "task-created", ...JSON.parse(String(init.body)) } });
    }
    if (url.includes("/api/workspaces/workspace-1/meetings") && init?.method === "POST") {
      return json({ data: { id: "meeting-created", ...JSON.parse(String(init.body)) } });
    }
    if (url.includes("/api/workspaces/workspace-1/reports") && init?.method === "POST") {
      return json({ data: { id: "report-created", ...JSON.parse(String(init.body)) } });
    }
    if (url.includes("/api/workspaces/workspace-1/workflows") && init?.method === "POST") {
      return json({ data: { id: "workflow-created", ...JSON.parse(String(init.body)) } });
    }
    if (url.includes("/api/workspaces/workspace-1/companies") && init?.method === "POST") {
      return json({ data: { id: "company-created", ...JSON.parse(String(init.body)) } });
    }
    if (url.includes("/api/workspaces/workspace-1/projects") && init?.method === "POST") {
      return json({ data: { id: "project-created", name: JSON.parse(String(init.body)).name, kind: "user", color_hex: "#e85d4f" } });
    }
    if (url.includes("/api/workspaces/workspace-1/notes")) return json({ data: responseNotes });
    if (url.includes("/api/workspaces/workspace-1/people") && init?.method === "POST") {
      return json({ data: { id: `person-created-${calls.length}`, ...JSON.parse(String(init.body)), confirmed_note_count: 0 } });
    }
    if (url.includes("/api/workspaces/workspace-1/people")) return json({ data: responsePeople });
    if (url.includes("/api/workspaces/workspace-1/projects")) return json({ data: responseProjects });
    if (url.includes("/api/projects/project-1/invites")) {
      return json({ data: { id: "invite-created", email: JSON.parse(String(init?.body)).email, status: "pending" } });
    }
    if (url.includes("/api/projects/project-1/merge")) {
      sourceProjectMerged = true;
      return json({ data: { merged: true, target_project_id: "project-2", target_project: responseProjects[3] } });
    }
    if (url.includes("/api/projects/project-1/reports/generate")) {
      return json({
        data: {
          id: "report-generated",
          title: "Apollo generated report",
          body: "# Apollo generated report\n\n## Executive summary\n- Grounded in memory.",
          status: "draft",
          projects: [responseProjects[2]],
          people,
          notes: [note],
          tasks: [{ id: "task-1", title: "Send diligence pack", status: "todo" }],
          companies: [{ id: "company-1", name: "Northstar" }],
          generation_confidence: 0.82,
          source_counts: { notes: 1, tasks: 1, meetings: 0, reports: 0, people: 2, companies: 1 },
        },
      });
    }
    if (url.includes("/api/projects/project-1/timeline")) return json({ data: responseProjectTimeline });
    if (url.includes("/api/projects/project-created/timeline")) {
      return json({
        data: {
          ...projectTimeline,
          project: { id: "project-created", name: "New Deal", kind: "user", color_hex: "#e85d4f" },
          events: [],
          members: [],
          people: [],
          notes: [],
        },
      });
    }
    if (url.includes("/api/projects/project-2/timeline")) {
      return json({ data: { ...projectTimeline, project: responseProjects[3] } });
    }
    if (url.includes("/api/people/person-1/timeline")) return json({ data: personTimeline });
    if (url.includes("/api/people/person-1") && init?.method === "PATCH") {
      const body = JSON.parse(String(init.body));
      return json({ data: { ...people[0], ...body } });
    }
    if (url.includes("/api/people/person-1/merge")) return json({ data: { undo_id: "undo-1" } });
    if (url.includes("/api/person-merges/undo-1/undo")) return json({ data: { undone: true } });
    if (url.includes("/api/briefs/")) return json({ data: { markdown: "Brief markdown" } });
    if (url.includes("/api/flags")) return json({ data: { flagged: true } });
    if (url.includes("/api/notes/note-1/process-with-ai")) {
      noteProcessingQueued = true;
      return json({ data: { queued: true } });
    }
    if (url.includes("/api/tasks/note-task-1") && (!init?.method || init.method === "GET")) {
      return json({ data: { ...taskNote, id: "note-task-1", projects: [responseProjects[2]], people: [people[0]], notes: [note] } });
    }
    if (url.includes("/api/reports/report-1") && (!init?.method || init.method === "GET")) {
      return json({
        data: {
          id: "report-1",
          title: "Apollo weekly brief",
          body: "# Apollo weekly brief\n\nProgress and blockers.",
          status: "draft",
          projects: [responseProjects[2]],
          people,
          notes: [note],
          tasks: [{ id: "task-1", title: "Send diligence pack", status: "todo" }],
          companies: [{ id: "company-1", name: "Northstar" }],
          source_counts: { notes: 1, tasks: 1, meetings: 0, reports: 0, people: 2, companies: 1 },
        },
      });
    }
    if (url.includes("/api/task-reminders/reminder-1") && init?.method === "PATCH") {
      return json({ data: { id: "reminder-1", remind_at: "2026-05-15T12:00:00Z", ...JSON.parse(String(init.body)) } });
    }
    if (url.includes("/api/tasks/") && init?.method === "PATCH") {
      const payload = JSON.parse(String(init.body));
      return json({
        data: {
          ...taskNote,
          ...payload,
          id: url.split("/api/tasks/")[1]?.split("?")[0] || "note-task-1",
          projects: responseProjects.filter((project) => payload.project_ids?.includes(project.id)),
          people: people.filter((person) => payload.person_ids?.includes(person.id)),
          companies: [{ id: "company-1", name: "Northstar", domain: "northstar.example" }]
            .filter((company) => payload.company_ids?.includes(company.id)),
          notes: [note],
        },
      });
    }
    if (url.includes("/api/email-blocks")) return json({ data: { deleted_note_id: "note-1" } });
    if (url.includes("/api/notes/note-1/people")) return json({ data: note });
    if (url.includes("/api/notes/note-1/projects")) return json({ data: note });
    if (url.includes("/api/notes/note-1") && init?.method === "PATCH") {
      return json({ data: { ...note, title: JSON.parse(String(init.body)).title, body: JSON.parse(String(init.body)).body } });
    }
    if (url.includes("/api/review-queue/count")) return json({ data: { count: responsePending.length } });
    if (url.includes("/api/collaborator-activity/")) return json({ data: [] });
    if (url.includes("/api/workspaces/workspace-1/settings")) {
      return json({ data: { workspace: { ...workspace, morning_briefing_optin: true }, projects, people, inbound_address: "dev@in.notesnoop.app" } });
    }
    if (url.includes("/api/review-queue/review-1/accept")) return json({ data: { accepted: true } });
    if (url.includes("/api/review-queue/review-2/accept")) return json({ data: { accepted: true } });
    if (url.includes("/api/review-queue/review-2/reject")) return json({ data: { rejected: true } });
    if (url.includes("/api/review-queue/")) return json({ data: { accepted: true } });
    if (url.includes("/api/notes/note-1")) {
      return json({
        data: {
          ...note,
          ai_processing_status: noteProcessingQueued ? "processing" : note.ai_processing_status,
          review_suggestions: noteProcessingQueued ? [] : note.review_suggestions,
        },
      });
    }
    return json({ data: {} });
  });
  vi.stubGlobal("fetch", fetchMock);
  return { fetchMock, calls };
}

describe("NoteSnoopApp", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
    window.history.replaceState({}, "", "/");
    window.localStorage.clear();
    vi.mocked(navigator.clipboard.writeText).mockClear();
    Object.defineProperty(window.URL, "createObjectURL", {
      value: vi.fn(() => "blob:notesnoop-report"),
      configurable: true,
    });
    Object.defineProperty(window.URL, "revokeObjectURL", {
      value: vi.fn(),
      configurable: true,
    });
  });

  it("renders dashboard-first workspace data and toggles Morning briefing", async () => {
    const { calls, fetchMock } = installFetch();
    render(<NoteSnoopApp quickCapture={false} />);

    expect(await screen.findByText("NoteSnoop")).toBeInTheDocument();
    expect((await screen.findAllByText("dev@in.notesnoop.app")).length).toBeGreaterThan(0);
    const dashboard = await screen.findByRole("region", { name: "Memory dashboard" });
    expect(screen.getByRole("button", { name: /Workspace overview/i })).toHaveClass("active");
    expect(within(dashboard).getByRole("heading", { name: "Workspace overview" })).toBeInTheDocument();
    expect(within(dashboard).getByText("Workspace memory")).toBeInTheDocument();
    expect(within(dashboard).getByRole("heading", { name: "Needs attention" })).toBeInTheDocument();
    expect(within(dashboard).getByRole("heading", { name: "Capture" })).toBeInTheDocument();
    expect(within(dashboard).getByRole("heading", { name: "Active work" })).toBeInTheDocument();
    expect(within(dashboard).queryByRole("heading", { name: "Processing lane" })).not.toBeInTheDocument();
    expect(within(dashboard).queryByRole("heading", { name: "Loose ends" })).not.toBeInTheDocument();
    expect(within(dashboard).queryByRole("button", { name: /Open Inbox project/i })).not.toBeInTheDocument();
    expect(
      within(dashboard).getByRole("heading", { name: "Capture" }).compareDocumentPosition(
        within(dashboard).getByRole("region", { name: "Ask memory" }),
      ) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(within(dashboard).getByRole("heading", { name: "Needs attention" })).toBeInTheDocument();
    expect(within(dashboard).getByText("Reminders")).toBeInTheDocument();
    expect(within(dashboard).getAllByText(/^Due /i).length).toBeGreaterThan(0);
    // Memory map is hidden until graph has 12+ nodes; relation labels appear in graph view, not asserted here.
    fireEvent.change(within(dashboard).getByLabelText("Ask memory question"), { target: { value: "What is blocked on Apollo?" } });
    fireEvent.click(within(dashboard).getByRole("button", { name: /^Ask$/i }));
    expect(await within(dashboard).findByText("74% grounded")).toBeInTheDocument();
    expect(within(dashboard).getByRole("group", { name: "Answer citations" })).toBeInTheDocument();
    fireEvent.click(within(dashboard).getByRole("button", { name: /Copy answer/i }));
    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith(expect.stringContaining("What is blocked on Apollo?")));
    fireEvent.click(within(dashboard).getByRole("button", { name: /Save report/i }));
    await waitFor(() => expect(calls.some((call) => call.includes("POST /api/workspaces/workspace-1/ask/report"))).toBe(true));
    const reportCall = fetchMock.mock.calls.find(([input, init]) => (
      String(input).includes("/api/workspaces/workspace-1/ask/report") && init?.method === "POST"
    ));
    expect(JSON.parse(String(reportCall?.[1]?.body))).toMatchObject({
      query: "What is blocked on Apollo?",
      title: "What is blocked on Apollo?",
      confidence: 0.74,
      citations: [
        { kind: "note", id: "note-1", title: "Apollo update", label: "N1" },
        { kind: "task", id: "note-task-1", title: "Send Apollo follow-up", label: "M1" },
      ],
      source_counts: { notes: 1, memory: 1 },
    });
    fireEvent.click(await screen.findByRole("button", { name: /Close memory/i }));
    fireEvent.click(within(dashboard).getByRole("button", { name: /Create task/i }));
    await waitFor(() => expect(calls.some((call) => call.includes("POST /api/workspaces/workspace-1/ask/task"))).toBe(true));
    expect(within(dashboard).getByRole("tab", { name: /Open tasks1/i })).toHaveAttribute("aria-selected", "true");
    expect(within(screen.getByRole("tabpanel", { name: "Open tasks" })).getByText("Send Apollo follow-up")).toBeInTheDocument();
    fireEvent.click(within(screen.getByRole("tabpanel", { name: "Open tasks" })).getByRole("button", { name: /Mark task done/i }));
    await waitFor(() => expect(calls.some((call) => call.includes("PATCH /api/tasks/note-task-1"))).toBe(true));
    fireEvent.click(within(screen.getByRole("tabpanel", { name: "Open tasks" })).getByText("Send Apollo follow-up"));
    const memorySheet = await waitFor(() => {
      const el = document.querySelector(".memory-detail-sheet") as HTMLElement | null;
      if (!el) throw new Error("memory sheet not mounted");
      if (!within(el).queryByText("Reminders")) throw new Error("memory sheet not ready");
      return el;
    });
    fireEvent.click(within(memorySheet).getByRole("button", { name: /Quick brief/i }));
    fireEvent.click(within(memorySheet).getByRole("button", { name: /Full brief/i }));
    const jordanCheckbox = within(memorySheet).getByLabelText("Jordan Kim") as HTMLInputElement;
    const northstarCheckbox = within(memorySheet).getByLabelText("Northstar") as HTMLInputElement;
    fireEvent.click(jordanCheckbox);
    fireEvent.click(northstarCheckbox);
    await waitFor(() => {
      expect(jordanCheckbox).toBeChecked();
      expect(northstarCheckbox).toBeChecked();
    });
    fireEvent.click(within(memorySheet).getByRole("button", { name: /Save memory/i }));
    await waitFor(() => {
      const relationPatch = fetchMock.mock.calls.filter(([input, init]) => (
        String(input).includes("/api/tasks/note-task-1")
        && init?.method === "PATCH"
        && String(init.body).includes("person_ids")
      )).at(-1);
      expect(JSON.parse(String(relationPatch?.[1]?.body))).toMatchObject({
        project_ids: ["project-1"],
        person_ids: ["person-1", "person-2"],
        company_ids: ["company-1"],
      });
    });
    fireEvent.click(await screen.findByRole("button", { name: /Snooze 1 day/i }));
    await waitFor(() => {
      expect(calls.some((call) => call.includes("GET /api/briefs/task/note-task-1?variant=quick"))).toBe(true);
      expect(calls.some((call) => call.includes("GET /api/briefs/task/note-task-1?variant=full"))).toBe(true);
      expect(calls.some((call) => call.includes("PATCH /api/task-reminders/reminder-1"))).toBe(true);
    });
    fireEvent.click(within(dashboard).getByRole("tab", { name: /Meetings\/calls1/i }));
    expect(within(screen.getByRole("tabpanel", { name: "Meetings/calls" })).getByText("Morgan kickoff call")).toBeInTheDocument();
    fireEvent.click(within(dashboard).getByRole("tab", { name: /Reports\/briefs1/i }));
    expect(within(screen.getByRole("tabpanel", { name: "Reports/briefs" })).getByText("Apollo weekly brief")).toBeInTheDocument();
    fireEvent.click(within(dashboard).getByRole("tab", { name: /Project intelligence1/i }));
    expect(within(screen.getByRole("tabpanel", { name: "Project intelligence" })).getByText("Waiting for enough project memory")).toBeInTheDocument();
    expect(within(dashboard).getByRole("heading", { name: "Active projects" })).toBeInTheDocument();
    const dashboardComposer = dashboard.querySelector(".capture-panel .dashboard-composer");
    expect(dashboardComposer).toContainElement(screen.getByPlaceholderText(/Dump a note/i));
    expect(document.querySelector(".content-grid")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Workspace settings" }));
    const settingsMenu = await waitFor(() => {
      const el = document.querySelector(".topbar-settings-popover") as HTMLElement | null;
      if (!el) throw new Error("settings menu not mounted");
      return el;
    });
    fireEvent.click(within(settingsMenu).getByRole("button", { name: /Briefing/i }));

    expect(await screen.findByText("Morning briefing is on.")).toBeInTheDocument();
    expect(calls.some((call) => call.includes("PATCH /api/workspaces/workspace-1/settings"))).toBe(true);
  });

  it("keeps future tasks and meetings out of today buckets", async () => {
    vi.spyOn(Date, "now").mockReturnValue(new Date("2026-05-13T10:00:00Z").getTime());
    installFetch({
      home: {
        open_tasks: [
          { id: "task-today", title: "Send today update", status: "todo", due_at: "2026-05-13T12:00:00Z" },
          { id: "task-friday", title: "Friday board packet", status: "todo", due_at: "2026-05-15T12:00:00Z" },
        ],
        meetings_calls: [
          { id: "meeting-today", title: "Today pilot sync", note_kind: "meeting", occurred_at: "2026-05-13T09:00:00Z" },
          { id: "meeting-friday", title: "Friday planning call", note_kind: "meeting", occurred_at: "2026-05-15T09:00:00Z" },
        ],
      },
    });
    render(<NoteSnoopApp quickCapture={false} />);

    const dashboard = await screen.findByRole("region", { name: "Memory dashboard" });
    const dueTodayGroup = (await within(dashboard).findByText("Due today")).closest(".attention-group") as HTMLElement;
    expect(within(dueTodayGroup).getByText("Send today update")).toBeInTheDocument();
    expect(within(dueTodayGroup).queryByText("Friday board packet")).not.toBeInTheDocument();

    const meetingsTodayGroup = (await within(dashboard).findByText("Meetings today")).closest(".attention-group") as HTMLElement;
    expect(within(meetingsTodayGroup).getByText("Today pilot sync")).toBeInTheDocument();
    expect(within(meetingsTodayGroup).queryByText("Friday planning call")).not.toBeInTheDocument();
  });

  it("pre-seeds first-run people from the warm start panel", async () => {
    const selfOnly = [{ id: "person-self", name: "Dev User", clerk_user_id: "dev_user", confirmed_note_count: 0 }];
    const { fetchMock } = installFetch({
      people: selfOnly,
      notes: [],
      home: { recent_people: selfOnly, recent_notes: [] },
    });
    render(<NoteSnoopApp quickCapture={false} />);

    expect(await screen.findByText("Warm start")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("First person name"), { target: { value: "Avery Chen" } });
    fireEvent.change(screen.getByLabelText("Second person name"), { target: { value: "Morgan Lee" } });
    fireEvent.click(screen.getByRole("button", { name: /^Add$/i }));

    await waitFor(() => {
      const createdNames = fetchMock.mock.calls
        .filter(([input, init]) => String(input).includes("/api/workspaces/workspace-1/people") && init?.method === "POST")
        .map(([, init]) => JSON.parse(String(init?.body)).name);
      expect(createdNames).toEqual(["Avery Chen", "Morgan Lee"]);
    });
    expect(await screen.findByText("People added.")).toBeInTheDocument();
  });

  it("guides a fresh workspace into a starter capture", async () => {
    const selfOnly = [{ id: "person-self", name: "Dev User", clerk_user_id: "dev_user", confirmed_note_count: 0 }];
    const { fetchMock, calls } = installFetch({
      people: selfOnly,
      notes: [],
      pendingItems: [],
      home: { recent_people: selfOnly, recent_notes: [], pending_review: [] },
    });
    render(<NoteSnoopApp quickCapture={false} />);

    const dashboard = await screen.findByRole("region", { name: "Memory dashboard" });
    expect(await screen.findByRole("region", { name: "First capture" })).toBeInTheDocument();
    expect(dashboard.querySelector(".dashboard-actions")).toBeNull();
    expect(screen.getByRole("region", { name: "First capture composer" })).toContainElement(screen.getByPlaceholderText(/Dump a note/i));
    expect(screen.getByText("Capture")).toBeInTheDocument();
    expect(screen.getByText("Extract")).toBeInTheDocument();
    expect(screen.getByText("Accept all")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Capture" })).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Ask memory" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Active work" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Processing lane" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Recent memory" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Loose ends" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Edit starter note/i }));
    expect((screen.getByPlaceholderText(/Dump a note/i) as HTMLTextAreaElement).value).toContain("Project Meridian");
    fireEvent.click(screen.getByRole("button", { name: /^Save$/i }));

    await waitFor(() => {
      const notePost = fetchMock.mock.calls.find(([input, init]) => (
        String(input).includes("/api/workspaces/workspace-1/notes") && init?.method === "POST"
      ));
      expect(notePost).toBeTruthy();
      expect(JSON.parse(String(notePost?.[1]?.body))).toMatchObject({
        note_kind: "meeting",
        body: expect.stringContaining("Northstar Robotics"),
      });
    });
    expect(await screen.findByText("Saved. Memory extraction is queued when allowed.")).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Fresh note" })).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.queryByRole("region", { name: "First capture" })).not.toBeInTheDocument();
    });
    expect(await screen.findByText("Starter note captured")).toBeInTheDocument();
    expect(screen.getByText("Extract memory to turn the starter note into reviewable people, tasks, projects, and companies.")).toBeInTheDocument();

    const sheet = document.querySelector(".linked-sheet") as HTMLElement;
    fireEvent.click(within(sheet).getAllByRole("button", { name: /Extract memory/i })[0]);

    await waitFor(() => expect(calls.some((call) => call.includes("POST /api/notes/note-1/process-with-ai"))).toBe(true));
    await waitFor(() => expect(calls.some((call) => call === "GET /api/notes/note-1")).toBe(true));
    expect(await screen.findByText(/Building your first workspace memory/i)).toBeInTheDocument();
  });

  it("keeps a dismissed sparse workspace focused on capture instead of empty panels", async () => {
    installFetch({
      notes: [],
      pendingItems: [],
      home: {
        recent_notes: [],
        pending_review: [],
        recent_projects: [projects[2]],
        recent_people: people,
        companies: [],
        workflows: [],
        flagged: [],
        open_tasks: [],
        tasks: [],
        meetings: [],
        calls: [],
        meetings_calls: [],
        reports: [],
        briefs: [],
        reports_briefs: [],
        reminders: [],
        loose_ends: {
          notes_without_project: [],
          tasks_without_owner: [],
          people_without_company: [],
          stale_reviews_count: 0,
        },
        pipeline_counts: { received: 0, processing: 0, needs_review: 0, accepted: 8, failed: 0 },
        pipeline_recent_received: [],
        pipeline_recent_failed: [],
      },
    });
    render(<NoteSnoopApp quickCapture={false} />);

    fireEvent.click(await screen.findByRole("button", { name: /Edit starter note/i }));
    fireEvent.click(screen.getByRole("button", { name: /^Save$/i }));
    expect(await screen.findByRole("heading", { name: "Fresh note" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Close" }));

    const dashboard = await screen.findByRole("region", { name: "Memory dashboard" });
    expect(dashboard.querySelector(".dashboard-actions")).toBeNull();
    expect(within(dashboard).getByRole("heading", { name: "Capture" })).toBeInTheDocument();
    expect(within(dashboard).queryByRole("region", { name: "Ask memory" })).not.toBeInTheDocument();
    expect(within(dashboard).queryByRole("heading", { name: "Needs attention" })).not.toBeInTheDocument();
    expect(within(dashboard).queryByRole("heading", { name: "Active work" })).not.toBeInTheDocument();
    expect(within(dashboard).queryByRole("heading", { name: "Processing lane" })).not.toBeInTheDocument();
    expect(within(dashboard).queryByRole("heading", { name: "Active projects" })).not.toBeInTheDocument();
    expect(within(dashboard).queryByRole("heading", { name: "People" })).not.toBeInTheDocument();
    expect(within(dashboard).queryByRole("heading", { name: "Recent memory" })).not.toBeInTheDocument();
    expect(within(dashboard).queryByRole("heading", { name: "Loose ends" })).not.toBeInTheDocument();
  });

  it("creates meetings, reports, workflows, companies, and dated tasks from the dashboard", async () => {
    const { calls } = installFetch();
    render(<NoteSnoopApp quickCapture={false} />);

    const dashboard = await screen.findByRole("region", { name: "Memory dashboard" });
    fireEvent.change(await within(dashboard).findByLabelText("New task"), { target: { value: "Send diligence pack" } });
    fireEvent.change(within(dashboard).getByLabelText("Task due date"), { target: { value: "2026-05-15" } });
    fireEvent.click(within(dashboard).getByRole("button", { name: /Add task/i }));
    await waitFor(() => expect(calls.some((call) => call.includes("POST /api/workspaces/workspace-1/tasks"))).toBe(true));

    fireEvent.click(within(dashboard).getByRole("tab", { name: /Meetings\/calls/i }));
    fireEvent.change(within(dashboard).getByLabelText("New meeting"), { target: { value: "Apollo partner call" } });
    fireEvent.click(within(dashboard).getByRole("button", { name: /Add meeting/i }));
    await waitFor(() => expect(calls.some((call) => call.includes("POST /api/workspaces/workspace-1/meetings"))).toBe(true));

    fireEvent.click(within(dashboard).getByRole("tab", { name: /Reports\/briefs/i }));
    fireEvent.change(within(dashboard).getByLabelText("New report"), { target: { value: "Apollo weekly report" } });
    fireEvent.click(within(dashboard).getByRole("button", { name: /Add report/i }));
    await waitFor(() => expect(calls.some((call) => call.includes("POST /api/workspaces/workspace-1/reports"))).toBe(true));

    fireEvent.click(within(dashboard).getByRole("tab", { name: /Workflows/i }));
    fireEvent.change(within(dashboard).getByLabelText("New workflow"), { target: { value: "IC memo loop" } });
    fireEvent.click(within(dashboard).getByRole("button", { name: /Add workflow/i }));
    await waitFor(() => expect(calls.some((call) => call.includes("POST /api/workspaces/workspace-1/workflows"))).toBe(true));

    fireEvent.click(within(dashboard).getByRole("tab", { name: /Companies/i }));
    fireEvent.change(within(dashboard).getByLabelText("New company"), { target: { value: "Northstar" } });
    fireEvent.click(within(dashboard).getByRole("button", { name: /Add company/i }));
    await waitFor(() => expect(calls.some((call) => call.includes("POST /api/workspaces/workspace-1/companies"))).toBe(true));
  });

  it("resolves loose ends from the dashboard controls", async () => {
    const { fetchMock } = installFetch({
      home: {
        loose_ends: {
          notes_without_project: [{ id: "note-1", title: "Apollo update", note_kind: "note" }],
          tasks_without_owner: [{ id: "note-task-1", title: "Send Apollo follow-up", status: "todo" }],
          people_without_company: [{ id: "person-1", name: "Morgan Lee" }],
          stale_reviews_count: 0,
        },
      },
    });
    render(<NoteSnoopApp quickCapture={false} />);

    const dashboard = await screen.findByLabelText("Memory dashboard");
    const noteProjectSelect = await within(dashboard).findByLabelText("Tag Apollo update to project");
    fireEvent.change(noteProjectSelect, { target: { value: "project-1" } });
    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([input, init]) => String(input).includes("/api/notes/note-1/projects") && init?.method === "PUT");
      expect(call).toBeTruthy();
      expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({ project_ids: ["project-1"], confirm_personal_move: false });
    });

    fireEvent.change(await within(dashboard).findByLabelText("Assign Send Apollo follow-up to owner"), { target: { value: "person-1" } });
    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([input, init]) => String(input).includes("/api/tasks/note-task-1") && init?.method === "PATCH");
      expect(call).toBeTruthy();
      expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({ assignee_id: "person-1" });
    });

    fireEvent.change(await within(dashboard).findByLabelText("Link Morgan Lee to company"), { target: { value: "company-1" } });
    await waitFor(() => {
      const companyCall = fetchMock.mock.calls.find(([input, init]) => String(input).includes("/api/workspaces/workspace-1/companies") && init?.method === "POST");
      expect(companyCall).toBeTruthy();
      expect(JSON.parse(String(companyCall?.[1]?.body))).toMatchObject({ name: "Northstar", person_ids: ["person-1"] });
      const personCall = fetchMock.mock.calls.find(([input, init]) => String(input).includes("/api/people/person-1") && init?.method === "PATCH");
      expect(personCall).toBeTruthy();
      expect(JSON.parse(String(personCall?.[1]?.body))).toMatchObject({ company: "Northstar" });
    });
  });

  it("asks before tagging a Personal loose note to a project", async () => {
    const { fetchMock } = installFetch({
      home: {
        loose_ends: {
          notes_without_project: [{ id: "note-1", title: "Personal memo", note_kind: "note", is_personal: true }],
          tasks_without_owner: [],
          people_without_company: [],
          stale_reviews_count: 0,
        },
      },
    });
    render(<NoteSnoopApp quickCapture={false} />);

    const dashboard = await screen.findByLabelText("Memory dashboard");
    const noteProjectSelect = await within(dashboard).findByLabelText("Tag Personal memo to project");
    const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true);

    fireEvent.change(noteProjectSelect, { target: { value: "project-1" } });
    await waitFor(() => expect(confirm).toHaveBeenCalledTimes(1));
    expect(fetchMock.mock.calls.some(([input, init]) => String(input).includes("/api/notes/note-1/projects") && init?.method === "PUT")).toBe(false);

    fireEvent.change(noteProjectSelect, { target: { value: "project-1" } });
    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([input, init]) => String(input).includes("/api/notes/note-1/projects") && init?.method === "PUT");
      expect(call).toBeTruthy();
      expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({ project_ids: ["project-1"], confirm_personal_move: true });
    });
  });

  it("generates a grounded project report from project memory", async () => {
    const { calls } = installFetch();
    render(<NoteSnoopApp quickCapture={false} />);

    const dashboard = await screen.findByRole("region", { name: "Memory dashboard" });
    fireEvent.click(await within(dashboard).findByRole("button", { name: /Open project Apollo/i }));
    const scopedProject = await screen.findByRole("region", { name: "Project memory" });
    expect(screen.queryByRole("region", { name: "Memory dashboard" })).not.toBeInTheDocument();
    expect(within(scopedProject).getByRole("heading", { name: "Apollo" })).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: /Generate report/i })[0]);

    await waitFor(() => expect(calls.some((call) => call.includes("POST /api/projects/project-1/reports/generate"))).toBe(true));
    expect(await screen.findByText("Project report generated from memory.")).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Apollo generated report" })).toBeInTheDocument();
    expect(screen.getByText("82% grounded")).toBeInTheDocument();
    expect(screen.getByDisplayValue(/Grounded in memory/i)).toBeInTheDocument();
  });

  it("hints how to seed an empty project timeline", async () => {
    installFetch({
      projectTimeline: {
        project: projects[2],
        events: [],
        members: [],
        invites: [],
        people: [],
        notes: [],
      },
    });
    render(<NoteSnoopApp quickCapture={false} />);

    const dashboard = await screen.findByRole("region", { name: "Memory dashboard" });
    fireEvent.click(await within(dashboard).findByRole("button", { name: /Open project Apollo/i }));
    const scopedProject = await screen.findByRole("region", { name: "Project memory" });
    expect(within(scopedProject).getByText("No memory linked to this project yet.")).toBeInTheDocument();
    expect(
      within(scopedProject).getByText(/Capture a note tagged to this project/i),
    ).toBeInTheDocument();
  });

  it("opens a project from a durable route and copies its link", async () => {
    const { calls } = installFetch();
    window.history.replaceState({}, "", "/projects/project-1?workspace_id=workspace-1");
    render(<NoteSnoopApp quickCapture={false} initialRoute={{ kind: "project", id: "project-1" }} />);

    const scopedProject = await screen.findByRole("region", { name: "Project memory" });
    expect(screen.queryByRole("region", { name: "Memory dashboard" })).not.toBeInTheDocument();
    expect(within(scopedProject).getByRole("heading", { name: "Apollo" })).toBeInTheDocument();
    expect(screen.getByLabelText("Current memory scope")).toHaveTextContent("Project: Apollo");
    expect(screen.getByPlaceholderText("Search memory in the Apollo project...")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /^Copy link$/i }));

    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith("http://localhost:3000/projects/project-1?workspace_id=workspace-1"));
    expect(calls.some((call) => call.includes("GET /api/projects/project-1/timeline"))).toBe(true);

    const searchInput = screen.getByPlaceholderText(/Search memory/i);
    fireEvent.change(searchInput, { target: { value: "Apollo" } });
    await waitFor(() => {
      const searchCall = calls.find((call) => call.includes("GET /api/workspaces/workspace-1/search?q=Apollo"));
      expect(searchCall).toBeTruthy();
      expect(searchCall).toContain("project_id=project-1");
    });
    expect(await screen.findByRole("region", { name: "Memory dashboard" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Current memory scope")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Project search scope: Apollo")).toHaveTextContent("Project: Apollo");
    fireEvent.change(searchInput, { target: { value: "" } });
    await waitFor(() => {
      const searchCalls = calls.filter((call) => call.includes("GET /api/workspaces/workspace-1/search?q="));
      expect(searchCalls.at(-1)).not.toContain("project_id=");
    });
    expect(screen.queryByText(/Project: Apollo/i)).not.toBeInTheDocument();
    fireEvent.change(searchInput, { target: { value: "Apollo" } });
    await waitFor(() => {
      const searchCalls = calls.filter((call) => call.includes("GET /api/workspaces/workspace-1/search?q=Apollo"));
      expect(searchCalls.at(-1)).not.toContain("project_id=");
    });
    fireEvent.click((await screen.findAllByRole("button", { name: /^Apollo$/i }))[0]);
    const scopedProjectAgain = await screen.findByRole("region", { name: "Project memory" });
    expect(within(scopedProjectAgain).getByRole("heading", { name: "Apollo" })).toBeInTheDocument();
    fireEvent.change(searchInput, { target: { value: "Apollo project" } });
    await waitFor(() => {
      const searchCalls = calls.filter((call) => call.includes("GET /api/workspaces/workspace-1/search?q=Apollo+project"));
      expect(searchCalls.at(-1)).toContain("project_id=project-1");
    });
    fireEvent.click(screen.getByRole("button", { name: "Search workspace" }));
    await waitFor(() => {
      const searchCalls = calls.filter((call) => call.includes("GET /api/workspaces/workspace-1/search?q=Apollo+project"));
      expect(searchCalls.at(-1)).not.toContain("project_id=");
    });
  });

  it("does not show a project dashboard while scoped project memory is loading", async () => {
    let releaseTimeline: (() => void) | undefined;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/api/events/")) return streamResponse();
      if (url.includes("/api/me")) {
        return json({
          data: {
            bootstrapped: true,
            workspace,
            workspaces: [{ id: workspace.id, name: workspace.name, role: "admin" }],
            projects,
            people,
            inbound_address: "dev@in.notesnoop.app",
          },
        });
      }
      if (url.includes("/api/workspaces/workspace-1/home")) return json({ data: { recent_notes: [note], pending_review: [] } });
      if (url.includes("/api/workspaces/workspace-1/memory-graph")) return json({ data: { nodes: [], edges: [] } });
      if (url.includes("/api/workspaces/workspace-1/review-queue")) return json({ data: [], meta: { count: 0 } });
      if (url.includes("/api/workspaces/workspace-1/notes")) return json({ data: [note] });
      if (url.includes("/api/workspaces/workspace-1/people")) return json({ data: people });
      if (url.includes("/api/workspaces/workspace-1/projects")) return json({ data: projects });
      if (url.includes("/api/projects/project-1/timeline")) {
        await new Promise<void>((resolve) => { releaseTimeline = resolve; });
        return json({ data: projectTimeline });
      }
      return json({ data: [] });
    });
    global.fetch = fetchMock as any;
    render(<NoteSnoopApp quickCapture={false} />);

    const dashboard = await screen.findByRole("region", { name: "Memory dashboard" });
    fireEvent.click(await within(dashboard).findByRole("button", { name: /Open project Apollo/i }));

    expect(await screen.findByRole("region", { name: "Project memory loading" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Memory dashboard" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Apollo dashboard" })).not.toBeInTheDocument();

    releaseTimeline?.();
    const scopedProject = await screen.findByRole("region", { name: "Project memory" });
    expect(within(scopedProject).getByRole("heading", { name: "Apollo" })).toBeInTheDocument();
  });

  it("search exits a pending project scoped load without trusting the pending project id", async () => {
    let releaseTimeline: (() => void) | undefined;
    const calls: string[] = [];
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      calls.push(`${init?.method || "GET"} ${url}`);
      if (url.includes("/api/events/")) return streamResponse();
      if (url.includes("/api/me")) {
        return json({
          data: {
            bootstrapped: true,
            workspace,
            workspaces: [{ id: workspace.id, name: workspace.name, role: "admin" }],
            projects,
            people,
            inbound_address: "dev@in.notesnoop.app",
          },
        });
      }
      if (url.includes("/api/workspaces/workspace-1/home")) return json({ data: { recent_notes: [note], pending_review: [] } });
      if (url.includes("/api/workspaces/workspace-1/memory-graph")) return json({ data: { nodes: [], edges: [] } });
      if (url.includes("/api/workspaces/workspace-1/review-queue")) return json({ data: [], meta: { count: 0 } });
      if (url.includes("/api/workspaces/workspace-1/search")) return json({ data: [note], meta: { memory_results: [] } });
      if (url.includes("/api/workspaces/workspace-1/notes")) return json({ data: [note] });
      if (url.includes("/api/workspaces/workspace-1/people")) return json({ data: people });
      if (url.includes("/api/workspaces/workspace-1/projects")) return json({ data: projects });
      if (url.includes("/api/projects/project-1/timeline")) {
        await new Promise<void>((resolve) => { releaseTimeline = resolve; });
        return json({ data: projectTimeline });
      }
      return json({ data: [] });
    });
    global.fetch = fetchMock as any;
    render(<NoteSnoopApp quickCapture={false} />);

    const dashboard = await screen.findByRole("region", { name: "Memory dashboard" });
    fireEvent.click(await within(dashboard).findByRole("button", { name: /Open project Apollo/i }));
    expect(await screen.findByRole("region", { name: "Project memory loading" })).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText(/Search memory/i), { target: { value: "Apollo" } });
    await waitFor(() => {
      const searchCall = calls.find((call) => call.includes("GET /api/workspaces/workspace-1/search?q=Apollo"));
      expect(searchCall).toBeTruthy();
      expect(searchCall).not.toContain("project_id=");
    });
    expect(await screen.findByRole("region", { name: "Memory dashboard" })).toBeInTheDocument();
    expect(screen.queryByText(/Project: Apollo/i)).not.toBeInTheDocument();

    releaseTimeline?.();
    await new Promise((resolve) => window.setTimeout(resolve, 0));
    expect(screen.queryByRole("region", { name: "Project memory" })).not.toBeInTheDocument();
  });

  it("does not reuse a previous project search scope during a new pending project load", async () => {
    let releaseProjectTwoTimeline: (() => void) | undefined;
    const calls: string[] = [];
    const projectTwo = { id: "project-2", name: "Hermes", kind: "user", color_hex: "#2563eb" };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      calls.push(`${init?.method || "GET"} ${url}`);
      if (url.includes("/api/events/")) return streamResponse();
      if (url.includes("/api/me")) {
        return json({
          data: {
            bootstrapped: true,
            workspace,
            workspaces: [{ id: workspace.id, name: workspace.name, role: "admin" }],
            projects: [...projects, projectTwo],
            people,
            inbound_address: "dev@in.notesnoop.app",
          },
        });
      }
      if (url.includes("/api/workspaces/workspace-1/home")) return json({ data: { recent_notes: [note], pending_review: [], recent_projects: [projects[2], projectTwo] } });
      if (url.includes("/api/workspaces/workspace-1/memory-graph")) return json({ data: { nodes: [], edges: [] } });
      if (url.includes("/api/workspaces/workspace-1/review-queue")) return json({ data: [], meta: { count: 0 } });
      if (url.includes("/api/workspaces/workspace-1/search")) return json({ data: [note], meta: { memory_results: [] } });
      if (url.includes("/api/workspaces/workspace-1/notes")) return json({ data: [note] });
      if (url.includes("/api/workspaces/workspace-1/people")) return json({ data: people });
      if (url.includes("/api/workspaces/workspace-1/projects")) return json({ data: [...projects, projectTwo] });
      if (url.includes("/api/projects/project-1/timeline")) return json({ data: projectTimeline });
      if (url.includes("/api/projects/project-2/timeline")) {
        await new Promise<void>((resolve) => { releaseProjectTwoTimeline = resolve; });
        return json({ data: { ...projectTimeline, project: projectTwo, events: [], people: [], notes: [] } });
      }
      return json({ data: [] });
    });
    global.fetch = fetchMock as any;
    render(<NoteSnoopApp quickCapture={false} />);

    const dashboard = await screen.findByRole("region", { name: "Memory dashboard" });
    fireEvent.click(await within(dashboard).findByRole("button", { name: /Open project Apollo/i }));
    expect(await screen.findByRole("region", { name: "Project memory" })).toBeInTheDocument();
    fireEvent.change(screen.getByPlaceholderText(/Search memory/i), { target: { value: "Apollo" } });
    await waitFor(() => {
      const apolloSearch = calls.find((call) => call.includes("GET /api/workspaces/workspace-1/search?q=Apollo"));
      expect(apolloSearch).toContain("project_id=project-1");
    });

    fireEvent.click((await screen.findAllByRole("button", { name: /^Hermes$/i }))[0]);
    expect(await screen.findByRole("region", { name: "Project memory loading" })).toBeInTheDocument();
    fireEvent.change(screen.getByPlaceholderText(/Search memory/i), { target: { value: "Hermes" } });
    await waitFor(() => {
      const hermesSearch = calls.find((call) => call.includes("GET /api/workspaces/workspace-1/search?q=Hermes"));
      expect(hermesSearch).toBeTruthy();
      expect(hermesSearch).not.toContain("project_id=project-1");
      expect(hermesSearch).not.toContain("project_id=project-2");
    });

    releaseProjectTwoTimeline?.();
    await new Promise((resolve) => window.setTimeout(resolve, 0));
    expect(screen.queryByRole("region", { name: "Project memory" })).not.toBeInTheDocument();
  });

  it("search exits a pending person scoped load and ignores the stale response", async () => {
    let releasePersonTimeline: (() => void) | undefined;
    const calls: string[] = [];
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      calls.push(`${init?.method || "GET"} ${url}`);
      if (url.includes("/api/events/")) return streamResponse();
      if (url.includes("/api/me")) {
        return json({
          data: {
            bootstrapped: true,
            workspace,
            workspaces: [{ id: workspace.id, name: workspace.name, role: "admin" }],
            projects,
            people,
            inbound_address: "dev@in.notesnoop.app",
          },
        });
      }
      if (url.includes("/api/workspaces/workspace-1/home")) return json({ data: { recent_notes: [note], recent_people: people, pending_review: [] } });
      if (url.includes("/api/workspaces/workspace-1/memory-graph")) return json({ data: { nodes: [], edges: [] } });
      if (url.includes("/api/workspaces/workspace-1/review-queue")) return json({ data: [], meta: { count: 0 } });
      if (url.includes("/api/workspaces/workspace-1/search")) return json({ data: [note], meta: { memory_results: [] } });
      if (url.includes("/api/workspaces/workspace-1/notes")) return json({ data: [note] });
      if (url.includes("/api/workspaces/workspace-1/people")) return json({ data: people });
      if (url.includes("/api/workspaces/workspace-1/projects")) return json({ data: projects });
      if (url.includes("/api/people/person-1/timeline")) {
        await new Promise<void>((resolve) => { releasePersonTimeline = resolve; });
        return json({ data: personTimeline });
      }
      return json({ data: [] });
    });
    global.fetch = fetchMock as any;
    render(<NoteSnoopApp quickCapture={false} />);

    fireEvent.click((await screen.findAllByRole("button", { name: /Open Morgan Lee timeline/i }))[0]);
    expect(await screen.findByRole("region", { name: "Person memory loading" })).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText(/Search memory/i), { target: { value: "Apollo" } });
    await waitFor(() => {
      const searchCall = calls.find((call) => call.includes("GET /api/workspaces/workspace-1/search?q=Apollo"));
      expect(searchCall).toBeTruthy();
      expect(searchCall).not.toContain("person_id=");
    });
    expect(await screen.findByRole("region", { name: "Memory dashboard" })).toBeInTheDocument();
    expect(screen.queryByText(/Person: Morgan Lee/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Person memory loading" })).not.toBeInTheDocument();

    releasePersonTimeline?.();
    await new Promise((resolve) => window.setTimeout(resolve, 0));
    expect(screen.queryByRole("region", { name: "Person memory" })).not.toBeInTheDocument();
  });

  it("searches within a person after the person timeline is loaded", async () => {
    const { calls } = installFetch();
    render(<NoteSnoopApp quickCapture={false} />);

    fireEvent.click((await screen.findAllByRole("button", { name: /Open Morgan Lee timeline/i }))[0]);
    const personScope = await screen.findByRole("region", { name: "Person memory" });
    expect(within(personScope).getByRole("heading", { name: "Morgan Lee" })).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText(/Search memory/i), { target: { value: "Morgan" } });
    await waitFor(() => {
      const searchCall = calls.find((call) => call.includes("GET /api/workspaces/workspace-1/search?q=Morgan"));
      expect(searchCall).toBeTruthy();
      expect(searchCall).toContain("person_id=person-1");
    });
    expect(await screen.findByRole("region", { name: "Memory dashboard" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Current memory scope")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Person search scope: Morgan Lee")).toHaveTextContent("Person: Morgan Lee");
  });

  it("ignores stale search responses after the query changes during debounce", async () => {
    let releaseApolloSearch: (() => void) | undefined;
    const staleNote = { ...note, id: "note-stale", title: "Stale Apollo result", body: "Old result" };
    const freshNote = { ...note, id: "note-fresh", title: "Fresh Morgan result", body: "New result" };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/api/events/")) return streamResponse();
      if (url.includes("/api/me")) {
        return json({
          data: {
            bootstrapped: true,
            workspace,
            workspaces: [{ id: workspace.id, name: workspace.name, role: "admin" }],
            projects,
            people,
            inbound_address: "dev@in.notesnoop.app",
          },
        });
      }
      if (url.includes("/api/workspaces/workspace-1/home")) return json({ data: { recent_notes: [note], pending_review: [] } });
      if (url.includes("/api/workspaces/workspace-1/memory-graph")) return json({ data: { nodes: [], edges: [] } });
      if (url.includes("/api/workspaces/workspace-1/review-queue")) return json({ data: [], meta: { count: 0 } });
      if (url.includes("/api/workspaces/workspace-1/search?q=Apollo")) {
        await new Promise<void>((resolve) => { releaseApolloSearch = resolve; });
        return json({ data: [staleNote], meta: { memory_results: [] } });
      }
      if (url.includes("/api/workspaces/workspace-1/search?q=Morgan")) return json({ data: [freshNote], meta: { memory_results: [] } });
      if (url.includes("/api/workspaces/workspace-1/notes")) return json({ data: [note] });
      if (url.includes("/api/workspaces/workspace-1/people")) return json({ data: people });
      if (url.includes("/api/workspaces/workspace-1/projects")) return json({ data: projects });
      return json({ data: [] });
    });
    global.fetch = fetchMock as any;
    render(<NoteSnoopApp quickCapture={false} />);

    const searchInput = await screen.findByPlaceholderText(/Search memory/i);
    fireEvent.change(searchInput, { target: { value: "Apollo" } });
    await new Promise((resolve) => window.setTimeout(resolve, 380));
    await waitFor(() => expect(fetchMock.mock.calls.some(([input]) => String(input).includes("search?q=Apollo"))).toBe(true));

    fireEvent.change(searchInput, { target: { value: "Morgan" } });
    releaseApolloSearch?.();
    await new Promise((resolve) => window.setTimeout(resolve, 120));
    expect(screen.queryByText("Stale Apollo result")).not.toBeInTheDocument();

    await new Promise((resolve) => window.setTimeout(resolve, 380));
    await waitFor(() => expect(fetchMock.mock.calls.some(([input]) => String(input).includes("search?q=Morgan"))).toBe(true));

    await new Promise((resolve) => window.setTimeout(resolve, 0));
    expect(await screen.findByText("Fresh Morgan result")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText("Stale Apollo result")).not.toBeInTheDocument());
  });

  it("ignores stale search failures after the query changes", async () => {
    let releaseApolloSearch: (() => void) | undefined;
    const freshNote = { ...note, id: "note-fresh", title: "Fresh Morgan result", body: "New result" };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/api/events/")) return streamResponse();
      if (url.includes("/api/me")) {
        return json({
          data: {
            bootstrapped: true,
            workspace,
            workspaces: [{ id: workspace.id, name: workspace.name, role: "admin" }],
            projects,
            people,
            inbound_address: "dev@in.notesnoop.app",
          },
        });
      }
      if (url.includes("/api/workspaces/workspace-1/home")) return json({ data: { recent_notes: [note], pending_review: [] } });
      if (url.includes("/api/workspaces/workspace-1/memory-graph")) return json({ data: { nodes: [], edges: [] } });
      if (url.includes("/api/workspaces/workspace-1/review-queue")) return json({ data: [], meta: { count: 0 } });
      if (url.includes("/api/workspaces/workspace-1/search?q=Apollo")) {
        await new Promise<void>((resolve) => { releaseApolloSearch = resolve; });
        throw new Error("Apollo search failed");
      }
      if (url.includes("/api/workspaces/workspace-1/search?q=Morgan")) return json({ data: [freshNote], meta: { memory_results: [] } });
      if (url.includes("/api/workspaces/workspace-1/notes")) return json({ data: [note] });
      if (url.includes("/api/workspaces/workspace-1/people")) return json({ data: people });
      if (url.includes("/api/workspaces/workspace-1/projects")) return json({ data: projects });
      return json({ data: [] });
    });
    global.fetch = fetchMock as any;
    render(<NoteSnoopApp quickCapture={false} />);

    const searchInput = await screen.findByPlaceholderText(/Search memory/i);
    fireEvent.change(searchInput, { target: { value: "Apollo" } });
    await new Promise((resolve) => window.setTimeout(resolve, 380));
    await waitFor(() => expect(fetchMock.mock.calls.some(([input]) => String(input).includes("search?q=Apollo"))).toBe(true));

    fireEvent.change(searchInput, { target: { value: "Morgan" } });
    releaseApolloSearch?.();
    await new Promise((resolve) => window.setTimeout(resolve, 120));
    expect(screen.queryByText("Apollo search failed")).not.toBeInTheDocument();

    await new Promise((resolve) => window.setTimeout(resolve, 380));
    expect(await screen.findByText("Fresh Morgan result")).toBeInTheDocument();
    expect(screen.queryByText("Apollo search failed")).not.toBeInTheDocument();
  });

  it("opens a note from a durable route and returns to the dashboard URL on close", async () => {
    installFetch();
    window.history.replaceState({}, "", "/notes/note-1");
    render(<NoteSnoopApp quickCapture={false} initialRoute={{ kind: "note", id: "note-1" }} />);

    expect(await screen.findByRole("heading", { name: "Apollo update" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /^Copy link$/i }));
    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith("http://localhost:3000/notes/note-1"));
    fireEvent.click(screen.getByRole("button", { name: "Close" }));

    await waitFor(() => expect(window.location.pathname).toBe("/"));
  });

  it("opens a report from a durable route and exports markdown", async () => {
    const { calls } = installFetch();
    window.history.replaceState({}, "", "/reports/report-1?workspace_id=workspace-1");
    render(<NoteSnoopApp quickCapture={false} initialRoute={{ kind: "report", id: "report-1" }} />);

    expect(await screen.findByRole("heading", { name: "Apollo weekly brief" })).toBeInTheDocument();
    const memorySheet = document.querySelector(".memory-detail-sheet") as HTMLElement;
    fireEvent.click(within(memorySheet).getByRole("button", { name: /^Copy link$/i }));
    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith("http://localhost:3000/reports/report-1?workspace_id=workspace-1"));
    fireEvent.click(within(memorySheet).getByRole("button", { name: /Copy markdown/i }));
    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith(expect.stringContaining("# Apollo weekly brief")));
    fireEvent.click(within(memorySheet).getByRole("button", { name: /Download \.md/i }));

    expect(calls.some((call) => call.includes("GET /api/reports/report-1"))).toBe(true);
    expect(window.URL.createObjectURL).toHaveBeenCalled();
    expect(window.URL.revokeObjectURL).toHaveBeenCalledWith("blob:notesnoop-report");
  });

  it("saves a quick capture note and opens the linked-entities sheet", async () => {
    installFetch();
    render(<NoteSnoopApp quickCapture />);

    const textarea = await screen.findByPlaceholderText(/Dump a note/i);
    const quickComposer = textarea.closest(".composer");
    expect(screen.queryByRole("region", { name: "Memory dashboard" })).not.toBeInTheDocument();
    expect(document.querySelector(".capture-panel")).not.toBeInTheDocument();
    expect(quickComposer).toBeTruthy();
    expect(quickComposer).not.toHaveClass("dashboard-composer");
    fireEvent.change(textarea, { target: { value: "Fresh note about Morgan and Apollo" } });
    fireEvent.click(screen.getByRole("button", { name: /Save/i }));

    expect(await screen.findByText("Fresh note")).toBeInTheDocument();
    expect(await screen.findByText("Quick brief")).toBeInTheDocument();
  });

  it("does not reopen a closed processing note after polling returns", async () => {
    const processingNote = {
      ...note,
      id: "processing-note",
      title: "Processing note",
      ai_processing_status: "processing",
    };
    installFetch({ notes: [processingNote] });
    render(<NoteSnoopApp quickCapture={false} />);

    fireEvent.click(await screen.findByText("Processing note"));
    expect(await screen.findByRole("heading", { name: "Processing note" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("heading", { name: "Processing note" })).not.toBeInTheDocument();

    await new Promise((resolve) => window.setTimeout(resolve, 1000));
    expect(screen.queryByRole("heading", { name: "Processing note" })).not.toBeInTheDocument();
  }, 10000);

  it("opens the review sheet and accepts a suggestion", async () => {
    const { calls } = installFetch();
    render(<NoteSnoopApp quickCapture={false} />);

    fireEvent.click(await screen.findByRole("button", { name: /Review \(2\)/i }));
    expect(await screen.findByRole("heading", { name: /Review \(2\)/i })).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: /Accept/i })[0]);

    await waitFor(() => expect(calls.some((call) => call.includes("POST /api/review-queue/review-1/accept"))).toBe(true));
  });

  it("exposes a persistent Review queue sidebar entry and opens the sheet", async () => {
    installFetch();
    render(<NoteSnoopApp quickCapture={false} />);

    await screen.findByRole("region", { name: "Memory dashboard" });
    const sidebarReview = screen.getByRole("button", { name: /Open review queue/i });
    expect(sidebarReview.textContent || "").toContain("Review queue");
    expect(await within(sidebarReview).findByLabelText(/2 pending review/i)).toBeInTheDocument();

    fireEvent.click(sidebarReview);
    expect(await screen.findByRole("heading", { name: /Review \(2\)/i })).toBeInTheDocument();
  });

  it("shows the Review queue sidebar entry without a badge and explains the empty state", async () => {
    installFetch({ pendingItems: [] });
    render(<NoteSnoopApp quickCapture={false} />);

    await screen.findByRole("region", { name: "Memory dashboard" });
    const sidebarReview = screen.getByRole("button", { name: /Open review queue/i });
    await waitFor(() =>
      expect(within(sidebarReview).queryByLabelText(/pending review/i)).not.toBeInTheDocument(),
    );

    fireEvent.click(sidebarReview);
    expect(await screen.findByText("No suggestions waiting.")).toBeInTheDocument();
    expect(screen.getByText(/extracts people, projects, tasks, and meetings/i)).toBeInTheDocument();
  });

  it("renders an empty-state message when search returns no notes", async () => {
    installFetch({ notes: [] });
    render(<NoteSnoopApp quickCapture={false} />);

    await screen.findByRole("region", { name: "Memory dashboard" });
    fireEvent.change(screen.getByPlaceholderText(/Search memory/i), { target: { value: "zzzzzzz" } });

    expect(await screen.findByText(/No notes match/i)).toBeInTheDocument();
  });

  it("edits and accepts a structured task review item with payload", async () => {
    const taskReview = {
      id: "review-task-1",
      entity_kind: "task",
      payload: {
        title: "Send Apollo follow-up",
        status: "todo",
        due_at: "2026-05-15",
        assignee_name: "Morgan Lee",
        summary: "Ask Morgan for the revised diligence timeline.",
        confidence: 0.86,
      },
    };
    const { fetchMock } = installFetch({ pendingItems: [taskReview] });
    render(<NoteSnoopApp quickCapture={false} />);

    fireEvent.click(await screen.findByRole("button", { name: /Review \(1\)/i }));
    const reviewSheet = document.querySelector(".review-sheet") as HTMLElement;
    expect(await within(reviewSheet).findByLabelText("Task title")).toHaveValue("Send Apollo follow-up");
    expect(within(reviewSheet).getByLabelText("Task status")).toHaveValue("todo");
    expect(within(reviewSheet).getByLabelText("Task due date")).toHaveValue("2026-05-15");
    fireEvent.change(within(reviewSheet).getByLabelText("Task title"), { target: { value: "Send Apollo diligence pack" } });
    fireEvent.change(within(reviewSheet).getByLabelText("Task due date"), { target: { value: "2026-05-20" } });
    fireEvent.change(within(reviewSheet).getByLabelText("Task summary"), { target: { value: "Send the final pack after Morgan confirms timing." } });
    fireEvent.click(within(reviewSheet).getByRole("button", { name: /^Accept$/i }));

    await waitFor(() => {
      const acceptCall = fetchMock.mock.calls.find(([input, init]) => (
        String(input).includes("/api/review-queue/review-task-1/accept") && init?.method === "POST"
      ));
      expect(acceptCall).toBeTruthy();
      expect(JSON.parse(String(acceptCall?.[1]?.body))).toMatchObject({
        payload: {
          title: "Send Apollo diligence pack",
          status: "todo",
          due_at: "2026-05-20",
          assignee_name: "Morgan Lee",
          summary: "Send the final pack after Morgan confirms timing.",
          confidence: 0.86,
        },
      });
      const acceptedPayload = JSON.parse(String(acceptCall?.[1]?.body)).payload;
      expect(Array.isArray(acceptedPayload.project_ids)).toBe(true);
      expect(Array.isArray(acceptedPayload.person_ids)).toBe(true);
      expect(Array.isArray(acceptedPayload.company_ids)).toBe(true);
    });
  });

  it("exercises note sheet actions for edit, linking, briefs, AI, flag, and email block", async () => {
    const { calls } = installFetch();
    render(<NoteSnoopApp quickCapture={false} />);

    const dashboard = await screen.findByRole("region", { name: "Memory dashboard" });
    const noteButtons = await within(dashboard).findAllByRole("button", { name: /Apollo update/i });
    fireEvent.click(noteButtons[0]);
    expect(await screen.findByText("sender@example.test")).toBeInTheDocument();
    expect(await screen.findByText("Forwarded diligence note")).toBeInTheDocument();
    const workbench = await screen.findByLabelText("Memory workbench");
    expect(within(workbench).getByText("Manual")).toBeInTheDocument();
    expect(within(workbench).getByText("1 task / 1 company")).toBeInTheDocument();
    expect((await screen.findAllByText("AI suggestions")).length).toBeGreaterThan(0);
    expect(await screen.findByText("Structured memory from this note")).toBeInTheDocument();
    expect(await screen.findByText("Prepare Apollo follow-up")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Accept/i }));

    fireEvent.change(screen.getAllByRole("combobox").at(-1)!, { target: { value: "person-1" } });
    fireEvent.click(screen.getByRole("button", { name: "Link selected person" }));

    fireEvent.click(screen.getByRole("button", { name: /Quick brief/i }));
    fireEvent.click(screen.getByRole("button", { name: /Full brief/i }));
    fireEvent.click(screen.getByRole("button", { name: /^Flag$/i }));
    fireEvent.click(screen.getAllByRole("button", { name: /Extract memory/i })[0]);

    fireEvent.click(screen.getByRole("button", { name: /Edit/i }));
    fireEvent.change(screen.getByLabelText("Note title"), { target: { value: "Edited title" } });
    fireEvent.change(screen.getByLabelText("Note body"), { target: { value: "Edited body" } });
    fireEvent.click(screen.getByRole("button", { name: /Save changes/i }));

    fireEvent.click(await screen.findByRole("button", { name: /Block sender/i }));

    await waitFor(() => {
      expect(calls.some((call) => call.includes("POST /api/notes/note-1/people"))).toBe(true);
      expect(calls.some((call) => call.includes("GET /api/briefs/note/note-1?variant=quick"))).toBe(true);
      expect(calls.some((call) => call.includes("GET /api/briefs/note/note-1?variant=full"))).toBe(true);
      expect(calls.some((call) => call.includes("POST /api/review-queue/review-2/accept"))).toBe(true);
      expect(calls.some((call) => call.includes("PATCH /api/notes/note-1"))).toBe(true);
      expect(calls.some((call) => call.includes("POST /api/email-blocks"))).toBe(true);
    });
  });

  it("opens project and person timelines, then merges and undoes people", async () => {
    const duplicateProjects = [
      ...projects,
      { id: "project-2", name: "Apollo duplicate", kind: "user", color_hex: "#2563eb" },
    ];
    const { calls } = installFetch({ projects: duplicateProjects });
    render(<NoteSnoopApp quickCapture={false} />);

    const projectButtons = await screen.findAllByRole("button", { name: /^Apollo$/i });
    fireEvent.click(projectButtons[0]);
    const projectScope = await screen.findByRole("region", { name: "Project memory" });
    expect(screen.queryByRole("region", { name: "Memory dashboard" })).not.toBeInTheDocument();
    expect(within(projectScope).getByRole("heading", { name: "Apollo" })).toBeInTheDocument();
    expect(await screen.findByText("Interaction history")).toBeInTheDocument();
    expect((await screen.findAllByText("Apollo weekly brief")).length).toBeGreaterThan(0);
    fireEvent.change(screen.getByPlaceholderText("Invite by email"), { target: { value: "peer@example.test" } });
    fireEvent.click(screen.getByRole("button", { name: /^Share$/i }));
    expect(await screen.findByText("Invite ready for peer@example.test.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /^Brief$/i }));
    fireEvent.click(screen.getByRole("button", { name: /^Flag$/i }));
    fireEvent.change(screen.getByLabelText("Merge target project"), { target: { value: "project-2" } });
    fireEvent.click(screen.getByRole("button", { name: /Merge project/i }));
    await waitFor(() => expect(calls.some((call) => call.includes("GET /api/projects/project-2/timeline"))).toBe(true));
    window.dispatchEvent(new Event("notesnoop:refresh"));
    await new Promise((resolve) => window.setTimeout(resolve, 0));
    expect(screen.getByLabelText("Merge target project")).toHaveValue("");
    expect(screen.getByRole("button", { name: /Merge project/i })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: /^Close$/i }));
    expect(await screen.findByRole("region", { name: "Memory dashboard" })).toBeInTheDocument();

    fireEvent.click((await screen.findAllByRole("button", { name: /Open Morgan Lee timeline/i }))[0]);
    const personScope = await screen.findByRole("region", { name: "Person memory" });
    expect(screen.queryByRole("region", { name: "Memory dashboard" })).not.toBeInTheDocument();
    expect(within(personScope).getByRole("heading", { name: "Morgan Lee" })).toBeInTheDocument();
    expect((await screen.findAllByText("Morgan kickoff call")).length).toBeGreaterThan(0);
    fireEvent.change(screen.getAllByRole("combobox").at(-1)!, { target: { value: "person-2" } });
    fireEvent.click(screen.getByRole("button", { name: /Merge/i }));
    expect(await screen.findByText("People merged.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Undo merge/i }));

    await waitFor(() => {
      expect(calls.some((call) => call.includes("GET /api/projects/project-1/timeline"))).toBe(true);
      expect(calls.some((call) => call.includes("POST /api/projects/project-1/invites"))).toBe(true);
      expect(calls.some((call) => call.includes("POST /api/projects/project-1/merge"))).toBe(true);
      expect(calls.some((call) => call.includes("GET /api/projects/project-2/timeline"))).toBe(true);
      expect(calls.some((call) => call.includes("GET /api/people/person-1/timeline"))).toBe(true);
      expect(calls.some((call) => call.includes("POST /api/people/person-1/merge"))).toBe(true);
      expect(calls.some((call) => call.includes("POST /api/person-merges/undo-1/undo"))).toBe(true);
    });
  });

  it("uses search filters and creates entities", async () => {
    const { calls } = installFetch();
    render(<NoteSnoopApp quickCapture={false} />);

    fireEvent.change(await screen.findByPlaceholderText(/Search memory/i), { target: { value: "Apollo" } });
    expect(await screen.findByRole("heading", { name: "Notes" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Filter by person"), { target: { value: "person-1" } });
    const filters = document.querySelector(".search-filter-row") as HTMLElement;
    fireEvent.click(within(filters).getByRole("button", { name: /Flagged/i }));
    expect(await screen.findByText("Memory matches")).toBeInTheDocument();
    expect((await screen.findAllByText("Northstar")).length).toBeGreaterThan(0);
    fireEvent.change(screen.getByPlaceholderText("Quick-add person"), { target: { value: "Avery Chen" } });
    fireEvent.click(screen.getByRole("button", { name: "Add person" }));
    fireEvent.change(screen.getByPlaceholderText("New project"), { target: { value: "New Deal" } });
    fireEvent.click(screen.getByRole("button", { name: "Create project" }));
    const projectScope = await screen.findByRole("region", { name: "Project memory" });
    expect(screen.queryByRole("region", { name: "Memory dashboard" })).not.toBeInTheDocument();
    expect(within(projectScope).getByRole("heading", { name: "New Deal" })).toBeInTheDocument();
    await waitFor(() => {
      expect(calls.some((call) => call.includes("GET /api/workspaces/workspace-1/search?q=Apollo"))).toBe(true);
      expect(calls.some((call) => call.includes("POST /api/workspaces/workspace-1/projects"))).toBe(true);
      expect(calls.some((call) => call.includes("POST /api/workspaces/workspace-1/people"))).toBe(true);
    });
  });

  it("opens the Inbox Triage sheet and bulk-processes selected notes", async () => {
    const { calls } = installFetch({ home: { pipeline_counts: { received: 1, processing: 0, needs_review: 0, accepted: 0, failed: 0 } } });
    render(<NoteSnoopApp quickCapture={false} />);

    const triageBtn = await screen.findByRole("button", { name: /Triage unprocessed notes/i });
    fireEvent.click(triageBtn);

    await screen.findByRole("dialog", { name: /Inbox triage/i });
    const selectAll = await screen.findByRole("button", { name: "Select all" });
    fireEvent.click(selectAll);

    const processBtn = screen.getByRole("button", { name: /Process selected/i });
    fireEvent.click(processBtn);

    await waitFor(() => {
      expect(calls.some((call) => call.startsWith("POST /api/workspaces/workspace-1/triage/process"))).toBe(true);
    });
  });

  it("toggles tasks board mode and renders status columns", async () => {
    installFetch();
    render(<NoteSnoopApp quickCapture={false} />);

    await screen.findByPlaceholderText(/Search memory/i);

    const boardToggle = await screen.findByRole("tab", { name: "Board" });
    fireEvent.click(boardToggle);

    expect(await screen.findByRole("tabpanel", { name: /Tasks by status/i })).toBeInTheDocument();
    expect(screen.getByText("To do")).toBeInTheDocument();
    expect(screen.getByText("Doing")).toBeInTheDocument();
    expect(screen.getByText("Blocked")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Move .* to Doing/i })).toBeInTheDocument();
  });

  it("renders Workflows as a first-class sidebar section, active first", async () => {
    installFetch();
    render(<NoteSnoopApp quickCapture={false} />);

    await screen.findByPlaceholderText(/Search memory/i);
    const diligence = await screen.findByRole("button", { name: /Open workflow Diligence loop/i });
    const paused = await screen.findByRole("button", { name: /Open workflow Paused outreach/i });
    const sidebar = document.querySelector(".sidebar") as HTMLElement;
    const order = Array.from(sidebar.querySelectorAll(".nav-item")).map((el) => el.textContent || "");
    const diligenceIdx = order.findIndex((t) => t.includes("Diligence loop"));
    const pausedIdx = order.findIndex((t) => t.includes("Paused outreach"));
    expect(diligenceIdx).toBeLessThan(pausedIdx);
    expect(within(paused).getByText("paused")).toBeInTheDocument();
    expect(diligence).toBeInTheDocument();
  });

  it("edits a person's contact info from the timeline profile card", async () => {
    const { calls } = installFetch();
    render(<NoteSnoopApp quickCapture={false} />);

    await screen.findByPlaceholderText(/Search memory/i);
    fireEvent.click((await screen.findAllByRole("button", { name: /Open Morgan Lee timeline/i }))[0]);

    const editBtn = await screen.findByRole("button", { name: /Edit contact/i });
    fireEvent.click(editBtn);

    const form = document.querySelector(".person-contact-editor") as HTMLElement;
    fireEvent.change(within(form).getByLabelText("Role"), { target: { value: "Operating Partner" } });
    fireEvent.change(within(form).getByLabelText("Company"), { target: { value: "Northstar Advisory" } });
    fireEvent.click(within(form).getByRole("button", { name: "Save" }));

    await waitFor(() => {
      expect(calls.some((call) => call.startsWith("PATCH /api/people/person-1") && !call.includes("merge"))).toBe(true);
    });
  });

  it("shows notification bell with overdue tasks when home has them", async () => {
    installFetch({
      home: {
        open_tasks: [
          {
            id: "task-overdue-1",
            title: "Past-due Apollo deliverable",
            status: "todo",
            due_at: "2020-01-01T12:00:00Z",
            people: [],
            projects: [],
            companies: [],
          },
        ],
        pipeline_recent_failed: [
          { id: "note-failed-1", title: "Failed extraction note", ai_processing_error: "ollama timeout" },
        ],
        loose_ends: { stale_reviews_count: 2 },
      },
    });
    render(<NoteSnoopApp quickCapture={false} />);

    const bell = await screen.findByRole("button", { name: /Notifications \(/i });
    fireEvent.click(bell);

    const panel = await screen.findByRole("heading", { name: /Notifications/i });
    const container = panel.closest(".notif-panel") as HTMLElement;
    expect(within(container).getByText("Past-due Apollo deliverable")).toBeInTheDocument();
    expect(within(container).getByText("Failed extraction note")).toBeInTheDocument();
    expect(within(container).getByText(/2 reviews pending more than 3 days/i)).toBeInTheDocument();
  });

  it("keeps workspace toggles reachable from the compact settings menu", async () => {
    const { calls } = installFetch();
    render(<NoteSnoopApp quickCapture={false} />);

    const settings = await screen.findByRole("button", { name: "Workspace settings" });
    fireEvent.click(settings);
    const menu = await waitFor(() => {
      const el = document.querySelector(".topbar-settings-popover") as HTMLElement | null;
      if (!el) throw new Error("settings menu not mounted");
      return el;
    });
    fireEvent.click(within(menu).getByRole("button", { name: /Briefing/i }));

    expect(await screen.findByText("Morning briefing is on.")).toBeInTheDocument();
    expect(calls.some((call) => call.includes("PATCH /api/workspaces/workspace-1/settings"))).toBe(true);
  });

  it("opens the keyboard shortcuts cheat sheet on ? and closes on Esc", async () => {
    installFetch();
    render(<NoteSnoopApp quickCapture={false} />);

    await screen.findByPlaceholderText(/Search memory/i);

    fireEvent.keyDown(window, { key: "?", shiftKey: true });
    const dialog = await screen.findByRole("dialog", { name: /Keyboard shortcuts/i });
    expect(within(dialog).getByText("Save note in the composer")).toBeInTheDocument();

    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: /Keyboard shortcuts/i })).not.toBeInTheDocument();
    });
  });

  it("opens the Cmd-K palette, searches, and routes to a memory item", async () => {
    const { calls } = installFetch();
    render(<NoteSnoopApp quickCapture={false} />);

    await screen.findByPlaceholderText(/Search memory/i);

    fireEvent.keyDown(window, { key: "k", code: "KeyK", metaKey: true });
    const paletteInput = await screen.findByPlaceholderText(/Jump to a note, person, project, task/i);
    fireEvent.change(paletteInput, { target: { value: "Apollo" } });

    await waitFor(() => {
      expect(calls.some((call) => call.includes("GET /api/workspaces/workspace-1/search?q=Apollo"))).toBe(true);
    });

    const taskRow = await screen.findByRole("option", { name: /Send Apollo follow-up/i });
    fireEvent.click(taskRow);

    await waitFor(() => {
      expect(screen.queryByPlaceholderText(/Jump to a note, person, project, task/i)).not.toBeInTheDocument();
    });
  });

  it("registers the quick-capture service worker on localhost", async () => {
    const register = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "serviceWorker", {
      configurable: true,
      value: { register },
    });
    Object.defineProperty(window, "isSecureContext", {
      configurable: true,
      value: false,
    });

    render(<ServiceWorkerRegistration />);

    await waitFor(() => expect(register).toHaveBeenCalledWith("/sw.js"));
  });
});
