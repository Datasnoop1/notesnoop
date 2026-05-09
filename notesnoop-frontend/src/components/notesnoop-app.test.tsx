import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { NoteSnoopApp } from "./notesnoop-app";

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
  projects: [projects[0]],
  people: [],
  versions: [{ version: 1 }],
  raw_email_metadata: { sender: "sender@example.test", subject: "Forwarded diligence note" },
  ai_processing_status: "skipped",
  project_nudge: { inbox_only: true, matched_projects: [projects[2]], can_create_project: true },
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

function installFetch() {
  const calls: string[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    calls.push(`${init?.method || "GET"} ${url}`);
    if (url.includes("/api/events/")) return streamResponse();
    if (url.endsWith("/api/me")) {
      return json({ data: { bootstrapped: true, workspace, projects, people, inbound_address: "dev@in.notesnoop.app" } });
    }
    if (url.includes("/api/workspaces/workspace-1/home")) {
      return json({
        data: {
          pending_review: pending,
          recent_projects: [projects[2]],
          recent_people: people,
          flagged: [{ id: "flag-1", label: "Apollo update", target_kind: "note", note_id: "note-1" }],
          recent_notes: [note],
        },
      });
    }
    if (url.includes("/api/workspaces/workspace-1/notes") && init?.method === "POST") {
      return json({ data: { ...note, title: "Fresh note", body: JSON.parse(String(init.body)).body } });
    }
    if (url.includes("/api/workspaces/workspace-1/projects") && init?.method === "POST") {
      return json({ data: { id: "project-created", name: JSON.parse(String(init.body)).name, kind: "user", color_hex: "#e85d4f" } });
    }
    if (url.includes("/api/workspaces/workspace-1/notes")) return json({ data: [note] });
    if (url.includes("/api/workspaces/workspace-1/people")) return json({ data: people });
    if (url.includes("/api/workspaces/workspace-1/projects")) return json({ data: projects });
    if (url.includes("/api/projects/project-1/invites")) {
      return json({ data: { id: "invite-created", email: JSON.parse(String(init?.body)).email, status: "pending" } });
    }
    if (url.includes("/api/projects/project-1/timeline")) return json({ data: projectTimeline });
    if (url.includes("/api/people/person-1/timeline")) return json({ data: personTimeline });
    if (url.includes("/api/people/person-1/merge")) return json({ data: { undo_id: "undo-1" } });
    if (url.includes("/api/person-merges/undo-1/undo")) return json({ data: { undone: true } });
    if (url.includes("/api/briefs/")) return json({ data: { markdown: "Brief markdown" } });
    if (url.includes("/api/flags")) return json({ data: { flagged: true } });
    if (url.includes("/api/notes/note-1/process-with-ai")) return json({ data: { queued: true } });
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

  it("renders workspace data and toggles Morning briefing", async () => {
    const { calls } = installFetch();
    render(<NoteSnoopApp quickCapture={false} />);

    expect(await screen.findByText("NoteSnoop")).toBeInTheDocument();
    expect(await screen.findByText("dev@in.notesnoop.app")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Briefing off/i }));

    expect(await screen.findByText("Morning briefing is on.")).toBeInTheDocument();
    expect(calls.some((call) => call.includes("PATCH /api/workspaces/workspace-1/settings"))).toBe(true);
  });

  it("saves a quick capture note and opens the linked-entities sheet", async () => {
    installFetch();
    render(<NoteSnoopApp quickCapture />);

    const textarea = await screen.findByPlaceholderText(/Dump a note/i);
    fireEvent.change(textarea, { target: { value: "Fresh note about Morgan and Apollo" } });
    fireEvent.click(screen.getByRole("button", { name: /Save/i }));

    expect(await screen.findByText("Fresh note")).toBeInTheDocument();
    expect(await screen.findByText("Quick brief")).toBeInTheDocument();
  });

  it("opens the mobile review sheet and accepts a suggestion", async () => {
    const { calls } = installFetch();
    render(<NoteSnoopApp quickCapture={false} />);

    fireEvent.click(await screen.findByRole("button", { name: /Review \(2\)/i }));
    expect(await screen.findByRole("heading", { name: /Review \(2\)/i })).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: /Accept/i })[2]);

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

    await waitFor(() => {
      expect(calls.some((call) => call.includes("GET /api/workspaces/workspace-1/search?q=Apollo"))).toBe(true);
      expect(calls.some((call) => call.includes("POST /api/workspaces/workspace-1/projects"))).toBe(true);
      expect(calls.some((call) => call.includes("POST /api/workspaces/workspace-1/people"))).toBe(true);
      expect(calls.some((call) => call.includes("POST /api/workspaces/workspace-1/send-test-email"))).toBe(true);
    });
  });
});
