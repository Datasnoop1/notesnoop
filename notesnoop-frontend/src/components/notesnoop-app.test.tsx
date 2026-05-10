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
};
const taskNote = {
  ...note,
  id: "note-task-1",
  title: "Send Apollo follow-up",
  body: "Ask Morgan for the revised diligence timeline.",
  note_kind: "task",
  status: "todo",
  due_at: "2026-05-15T12:00:00Z",
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
  projects: [{ ...projects[2], mention_count: 1 }],
  notes: [{ ...note, created_at: "2026-05-09T08:00:00Z" }],
};
const projectTimeline = {
  project: projects[2],
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

function installFetch(options: { people?: any[]; notes?: any[]; home?: Record<string, unknown> } = {}) {
  const calls: string[] = [];
  const responsePeople = options.people ?? people;
  const responseNotes = options.notes ?? [note, taskNote, meetingNote, reportNote];
  const memoryResults = [
    { id: "task-1", kind: "task", title: "Send Apollo diligence follow-up", subtitle: "Ask Morgan for the revised timeline." },
    { id: "company-1", kind: "company", title: "Northstar", subtitle: "northstar.example" },
  ];
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
          people: responsePeople,
          inbound_address: "dev@in.notesnoop.app",
        },
      });
    }
    if (url.includes("/api/workspaces/workspace-1/home")) {
      return json({
        data: {
          pending_review: pending,
          recent_projects: [projects[2]],
          recent_people: responsePeople,
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
        data: pending.map((item) => ({
          ...item,
          source_note_title: "Apollo update",
          source_snippet: "Morgan mentioned Apollo follow-up.",
          projects: [projects[2]],
        })),
        meta: { count: pending.length },
      });
    }
    if (url.includes("/api/workspaces/workspace-1/search")) {
      return json({
        data: responseNotes,
        meta: { semantic_enabled: false, semantic_excluded: 0, memory_results: memoryResults },
      });
    }
    if (url.includes("/api/workspaces/workspace-1/notes") && init?.method === "POST") {
      return json({ data: { ...note, title: "Fresh note", body: JSON.parse(String(init.body)).body } });
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
    if (url.includes("/api/workspaces/workspace-1/projects")) return json({ data: projects });
    if (url.includes("/api/projects/project-1/invites")) {
      return json({ data: { id: "invite-created", email: JSON.parse(String(init?.body)).email, status: "pending" } });
    }
    if (url.includes("/api/projects/project-1/reports/generate")) {
      return json({
        data: {
          id: "report-generated",
          title: "Apollo generated report",
          body: "# Apollo generated report\n\n## Executive summary\n- Grounded in memory.",
          status: "draft",
          projects: [projects[2]],
          people,
          notes: [note],
          tasks: [{ id: "task-1", title: "Send diligence pack", status: "todo" }],
          companies: [{ id: "company-1", name: "Northstar" }],
          generation_confidence: 0.82,
          source_counts: { notes: 1, tasks: 1, meetings: 0, reports: 0, people: 2, companies: 1 },
        },
      });
    }
    if (url.includes("/api/projects/project-1/timeline")) return json({ data: projectTimeline });
    if (url.includes("/api/people/person-1/timeline")) return json({ data: personTimeline });
    if (url.includes("/api/people/person-1/merge")) return json({ data: { undo_id: "undo-1" } });
    if (url.includes("/api/person-merges/undo-1/undo")) return json({ data: { undone: true } });
    if (url.includes("/api/briefs/")) return json({ data: { markdown: "Brief markdown" } });
    if (url.includes("/api/flags")) return json({ data: { flagged: true } });
    if (url.includes("/api/notes/note-1/process-with-ai")) return json({ data: { queued: true } });
    if (url.includes("/api/tasks/") && init?.method === "PATCH") {
      return json({ data: { ...taskNote, status: JSON.parse(String(init.body)).status } });
    }
    if (url.includes("/api/email-blocks")) return json({ data: { deleted_note_id: "note-1" } });
    if (url.includes("/api/notes/note-1/people")) return json({ data: note });
    if (url.includes("/api/notes/note-1/projects")) return json({ data: note });
    if (url.includes("/api/notes/note-1") && init?.method === "PATCH") {
      return json({ data: { ...note, title: JSON.parse(String(init.body)).title, body: JSON.parse(String(init.body)).body } });
    }
    if (url.includes("/api/review-queue/count")) return json({ data: { count: pending.length } });
    if (url.includes("/api/collaborator-activity/")) return json({ data: [] });
    if (url.includes("/api/workspaces/workspace-1/settings")) {
      return json({ data: { workspace: { ...workspace, morning_briefing_optin: true }, projects, people, inbound_address: "dev@in.notesnoop.app" } });
    }
    if (url.includes("/api/review-queue/review-1/accept")) return json({ data: { accepted: true } });
    if (url.includes("/api/review-queue/review-2/accept")) return json({ data: { accepted: true } });
    if (url.includes("/api/review-queue/review-2/reject")) return json({ data: { rejected: true } });
    if (url.includes("/api/notes/note-1")) return json({ data: note });
    return json({ data: {} });
  });
  vi.stubGlobal("fetch", fetchMock);
  return { fetchMock, calls };
}

describe("NoteSnoopApp", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it("renders dashboard-first workspace data and toggles Morning briefing", async () => {
    const { calls } = installFetch();
    render(<NoteSnoopApp quickCapture={false} />);

    expect(await screen.findByText("NoteSnoop")).toBeInTheDocument();
    expect(await screen.findByText("dev@in.notesnoop.app")).toBeInTheDocument();
    const dashboard = await screen.findByRole("region", { name: "Memory dashboard" });
    expect(within(dashboard).getByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
    expect(within(dashboard).getByText("Workspace memory")).toBeInTheDocument();
    expect(within(dashboard).getByRole("heading", { name: "Needs attention" })).toBeInTheDocument();
    expect(within(dashboard).getByRole("heading", { name: "Capture" })).toBeInTheDocument();
    expect(within(dashboard).getByRole("heading", { name: "Memory system" })).toBeInTheDocument();
    expect(within(dashboard).getByRole("heading", { name: "Memory map" })).toBeInTheDocument();
    expect(within(dashboard).getByRole("group", { name: "Interactive memory graph" })).toBeInTheDocument();
    expect(within(dashboard).getByText(/Reminder due/i)).toBeInTheDocument();
    expect(within(dashboard).getByText("sourced_from")).toBeInTheDocument();
    expect(within(dashboard).getByRole("tab", { name: /Open tasks1/i })).toHaveAttribute("aria-selected", "true");
    expect(within(screen.getByRole("tabpanel", { name: "Open tasks" })).getByText("Send Apollo follow-up")).toBeInTheDocument();
    fireEvent.click(within(screen.getByRole("tabpanel", { name: "Open tasks" })).getByRole("button", { name: /Mark task done/i }));
    await waitFor(() => expect(calls.some((call) => call.includes("PATCH /api/tasks/note-task-1"))).toBe(true));
    fireEvent.click(within(dashboard).getByRole("tab", { name: /Meetings\/calls1/i }));
    expect(within(screen.getByRole("tabpanel", { name: "Meetings/calls" })).getByText("Morgan kickoff call")).toBeInTheDocument();
    fireEvent.click(within(dashboard).getByRole("tab", { name: /Reports\/briefs1/i }));
    expect(within(screen.getByRole("tabpanel", { name: "Reports/briefs" })).getByText("Apollo weekly brief")).toBeInTheDocument();
    fireEvent.click(within(dashboard).getByRole("tab", { name: /Project intelligence1/i }));
    expect(within(screen.getByRole("tabpanel", { name: "Project intelligence" })).getByText("Waiting for enough project memory")).toBeInTheDocument();
    expect(within(dashboard).getByRole("heading", { name: "Active projects" })).toBeInTheDocument();
    const dashboardComposer = dashboard.querySelector(".capture-panel .dashboard-composer");
    expect(dashboardComposer).toContainElement(screen.getByPlaceholderText(/Dump a note/i));
    const contentGrid = document.querySelector(".content-grid");
    expect(contentGrid).toBeTruthy();
    expect(Boolean(dashboard.compareDocumentPosition(contentGrid!) & Node.DOCUMENT_POSITION_FOLLOWING)).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: /Briefing off/i }));

    expect(await screen.findByText("Morning briefing is on.")).toBeInTheDocument();
    expect(calls.some((call) => call.includes("PATCH /api/workspaces/workspace-1/settings"))).toBe(true);
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

  it("creates meetings, reports, workflows, companies, and dated tasks from the dashboard", async () => {
    const { calls } = installFetch();
    render(<NoteSnoopApp quickCapture={false} />);

    const dashboard = await screen.findByRole("region", { name: "Memory dashboard" });
    fireEvent.change(within(dashboard).getByLabelText("New task"), { target: { value: "Send diligence pack" } });
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

  it("generates a grounded project report from project memory", async () => {
    const { calls } = installFetch();
    render(<NoteSnoopApp quickCapture={false} />);

    const dashboard = await screen.findByRole("region", { name: "Memory dashboard" });
    fireEvent.click(within(dashboard).getByRole("button", { name: /Open project Apollo/i }));
    expect(await screen.findByRole("heading", { name: "Apollo" })).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: /Generate report/i })[0]);

    await waitFor(() => expect(calls.some((call) => call.includes("POST /api/projects/project-1/reports/generate"))).toBe(true));
    expect(await screen.findByText("Project report generated from memory.")).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Apollo generated report" })).toBeInTheDocument();
    expect(screen.getByText("82% grounded")).toBeInTheDocument();
    expect(screen.getByDisplayValue(/Grounded in memory/i)).toBeInTheDocument();
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

  it("opens the review sheet and accepts a suggestion", async () => {
    const { calls } = installFetch();
    render(<NoteSnoopApp quickCapture={false} />);

    fireEvent.click(await screen.findByRole("button", { name: /Review \(2\)/i }));
    expect(await screen.findByRole("heading", { name: /Review \(2\)/i })).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: /Accept/i })[0]);

    await waitFor(() => expect(calls.some((call) => call.includes("POST /api/review-queue/review-1/accept"))).toBe(true));
  });

  it("exercises note sheet actions for edit, linking, briefs, AI, flag, and email block", async () => {
    const { calls } = installFetch();
    render(<NoteSnoopApp quickCapture={false} />);

    const noteTitleMatches = await screen.findAllByText("Apollo update");
    const noteRow = noteTitleMatches.map((element) => element.closest(".note-row")).find(Boolean);
    expect(noteRow).toBeTruthy();
    fireEvent.click(noteRow!);
    expect(await screen.findByText("From sender@example.test")).toBeInTheDocument();
    expect(await screen.findByText("AI suggestions")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Accept/i }));

    fireEvent.change(screen.getAllByRole("combobox").at(-1)!, { target: { value: "person-1" } });
    fireEvent.click(screen.getByRole("button", { name: "Link selected person" }));

    fireEvent.click(screen.getByRole("button", { name: /Quick brief/i }));
    fireEvent.click(screen.getByRole("button", { name: /Full brief/i }));
    fireEvent.click(screen.getByRole("button", { name: /^Flag$/i }));
    fireEvent.click(screen.getByRole("button", { name: /Process with AI/i }));

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
    const { calls } = installFetch();
    render(<NoteSnoopApp quickCapture={false} />);

    const projectButtons = await screen.findAllByRole("button", { name: /^Apollo$/i });
    fireEvent.click(projectButtons[0]);
    expect(await screen.findByRole("heading", { name: "Apollo" })).toBeInTheDocument();
    fireEvent.change(screen.getByPlaceholderText("Invite by email"), { target: { value: "peer@example.test" } });
    fireEvent.click(screen.getByRole("button", { name: /^Share$/i }));
    expect(await screen.findByText("Invite ready for peer@example.test.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /^Brief$/i }));
    fireEvent.click(screen.getByRole("button", { name: /^Flag$/i }));
    fireEvent.click(screen.getByRole("button", { name: /^Close$/i }));

    const personNameMatches = await screen.findAllByText("Morgan Lee");
    const personRow = personNameMatches.map((element) => element.closest(".entity-row")).find(Boolean);
    expect(personRow).toBeTruthy();
    fireEvent.click(personRow!);
    expect(await screen.findByRole("heading", { name: "Morgan Lee" })).toBeInTheDocument();
    fireEvent.change(screen.getAllByRole("combobox").at(-1)!, { target: { value: "person-2" } });
    fireEvent.click(screen.getByRole("button", { name: /Merge/i }));
    expect(await screen.findByText("People merged.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Undo merge/i }));

    await waitFor(() => {
      expect(calls.some((call) => call.includes("GET /api/projects/project-1/timeline"))).toBe(true);
      expect(calls.some((call) => call.includes("POST /api/projects/project-1/invites"))).toBe(true);
      expect(calls.some((call) => call.includes("GET /api/people/person-1/timeline"))).toBe(true);
      expect(calls.some((call) => call.includes("POST /api/people/person-1/merge"))).toBe(true);
      expect(calls.some((call) => call.includes("POST /api/person-merges/undo-1/undo"))).toBe(true);
    });
  });

  it("uses search filters, creates entities, and sends a test email", async () => {
    const { calls } = installFetch();
    render(<NoteSnoopApp quickCapture={false} />);

    fireEvent.change(await screen.findByPlaceholderText(/Search notes/i), { target: { value: "Apollo" } });
    fireEvent.change(screen.getByLabelText("Filter by person"), { target: { value: "person-1" } });
    fireEvent.click(screen.getByRole("button", { name: /Flagged/i }));
    fireEvent.change(screen.getByPlaceholderText("New project"), { target: { value: "New Deal" } });
    fireEvent.click(screen.getByRole("button", { name: "Create project" }));
    fireEvent.change(screen.getByPlaceholderText("Quick-add person"), { target: { value: "Avery Chen" } });
    fireEvent.click(screen.getByRole("button", { name: "Add person" }));
    fireEvent.click(screen.getByRole("button", { name: /Send test email/i }));

    expect(await screen.findByText("Memory matches")).toBeInTheDocument();
    expect((await screen.findAllByText("Northstar")).length).toBeGreaterThan(0);
    await waitFor(() => {
      expect(calls.some((call) => call.includes("GET /api/workspaces/workspace-1/search?q=Apollo"))).toBe(true);
      expect(calls.some((call) => call.includes("POST /api/workspaces/workspace-1/projects"))).toBe(true);
      expect(calls.some((call) => call.includes("POST /api/workspaces/workspace-1/people"))).toBe(true);
      expect(calls.some((call) => call.includes("POST /api/workspaces/workspace-1/send-test-email"))).toBe(true);
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
