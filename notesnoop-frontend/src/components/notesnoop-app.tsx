"use client";

/* eslint-disable react-hooks/set-state-in-effect, @next/next/no-img-element */

import {
  Archive,
  Bell,
  CalendarDays,
  Check,
  ClipboardList,
  Copy,
  FileText,
  Flag,
  Inbox,
  Lightbulb,
  Menu,
  Plus,
  Search,
  Send,
  Settings,
  Sparkles,
  UserRound,
  Users,
  X,
} from "lucide-react";
import { SignInButton, UserButton, useAuth } from "@clerk/nextjs";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

type ApiState = {
  user?: any;
  workspace?: any;
  workspaces?: any[];
  projects: any[];
  people: any[];
  inbound_address?: string;
};

type HomeState = {
  pending_review: any[];
  recent_projects: any[];
  recent_people: any[];
  flagged: any[];
  recent_notes: any[];
  open_tasks?: any[];
  tasks?: any[];
  meetings_calls?: any[];
  meetings?: any[];
  calls?: any[];
  reports_briefs?: any[];
  reports?: any[];
  briefs?: any[];
  project_intelligence?: any[];
};

type SearchFilters = {
  person_id?: string;
  date_from?: string;
  date_to?: string;
  flagged_only?: boolean;
};

const API_BASE = process.env.NEXT_PUBLIC_NOTESNOOP_API_URL || "";
const DEV_AUTH = process.env.NEXT_PUBLIC_NOTESNOOP_DEV_AUTH === "true";
const NOTE_KIND_LABELS: Record<string, string> = {
  note: "Note",
  meeting: "Meeting",
  call: "Call",
  email: "Email",
  task: "Task",
  report: "Report",
};

function inputDate(value?: string | null) {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "" : date.toISOString().slice(0, 10);
}

function eventDate(value?: string | null) {
  if (!value) return null;
  return `${value}T12:00:00`;
}

export function NoteSnoopApp({ quickCapture }: { quickCapture: boolean }) {
  const { getToken, isSignedIn, isLoaded } = useAuth();
  const [state, setState] = useState<ApiState | null>(null);
  const [home, setHome] = useState<HomeState | null>(null);
  const [notes, setNotes] = useState<any[]>([]);
  const [requestedWorkspaceId, setRequestedWorkspaceId] = useState<string | null>(() => {
    if (typeof window === "undefined") return null;
    return new URLSearchParams(window.location.search).get("workspace_id");
  });
  const [landingProjectId, setLandingProjectId] = useState<string | null>(() => {
    if (typeof window === "undefined") return null;
    return new URLSearchParams(window.location.search).get("project_id");
  });
  const [selectedNote, setSelectedNote] = useState<any | null>(null);
  const [body, setBody] = useState("");
  const [title, setTitle] = useState("");
  const [noteKind, setNoteKind] = useState("note");
  const [occurredAt, setOccurredAt] = useState("");
  const [query, setQuery] = useState("");
  const [searchFilters, setSearchFilters] = useState<SearchFilters>({});
  const [searchMeta, setSearchMeta] = useState<any | null>(null);
  const [personName, setPersonName] = useState("");
  const [personRole, setPersonRole] = useState("");
  const [personCompany, setPersonCompany] = useState("");
  const [personEmail, setPersonEmail] = useState("");
  const [seedPeopleDrafts, setSeedPeopleDrafts] = useState(["", ""]);
  const [warmStartDismissed, setWarmStartDismissed] = useState(false);
  const [projectName, setProjectName] = useState("");
  const [inviteEmail, setInviteEmail] = useState("");
  const [activeProject, setActiveProject] = useState<string | null>(null);
  const [personTimeline, setPersonTimeline] = useState<any | null>(null);
  const [projectTimeline, setProjectTimeline] = useState<any | null>(null);
  const [activity, setActivity] = useState<any[]>([]);
  const [reviewCount, setReviewCount] = useState(0);
  const [mergeUndoId, setMergeUndoId] = useState("");
  const [selectedProjectIds, setSelectedProjectIds] = useState<string[]>([]);
  const [mobileNav, setMobileNav] = useState(false);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [reviewSheetOpen, setReviewSheetOpen] = useState(false);
  const [activeMemoryTab, setActiveMemoryTab] = useState("tasks");
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState("");
  const searchDebounceRef = useRef<number | null>(null);

  const api = useCallback(
    async (path: string, init: RequestInit = {}) => {
      const token = isSignedIn ? await getToken() : null;
      const headers: Record<string, string> = {
        "Content-Type": "application/json",
        ...(init.headers as Record<string, string> | undefined),
      };
      if (token) headers.Authorization = `Bearer ${token}`;
      if (DEV_AUTH && !token) {
        headers["x-notesnoop-user-id"] = "dev_user";
        headers["x-notesnoop-email"] = "dev@example.test";
        headers["x-notesnoop-name"] = "Dev User";
      }
      const res = await fetch(`${API_BASE}${path}`, { ...init, headers });
      if (!res.ok) {
        const retry = res.headers.get("Retry-After");
        throw new Error(res.status === 429 ? `AI is catching up. Try again in ${retry || "a few"} seconds.` : await res.text());
      }
      return res.json();
    },
    [getToken, isSignedIn],
  );

  const workspaceId = state?.workspace?.id;
  const inbox = useMemo(() => state?.projects.find((p) => p.kind === "inbox"), [state]);
  const personal = useMemo(() => state?.projects.find((p) => p.kind === "personal"), [state]);
  const saveProjectIds = selectedProjectIds.length ? selectedProjectIds : activeProject ? [activeProject] : [];
  const activityByProject = useMemo(() => new Map(activity.map((item) => [item.project_id, item])), [activity]);
  const seededPeople = useMemo(() => (state?.people || []).filter((person) => !person.clerk_user_id), [state]);
  const showWarmStart = !quickCapture && !warmStartDismissed && !!state?.workspace && !notes.length && seededPeople.length < 2;

  const buildSearchParams = useCallback(
    (nextQuery: string, filters: SearchFilters) => {
      const params = new URLSearchParams({ q: nextQuery });
      if (activeProject) params.set("project_id", activeProject);
      if (filters.person_id) params.set("person_id", filters.person_id);
      if (filters.date_from) params.set("date_from", filters.date_from);
      if (filters.date_to) params.set("date_to", filters.date_to);
      if (filters.flagged_only) params.set("flagged_only", "true");
      return params.toString();
    },
    [activeProject],
  );

  const refresh = useCallback(async () => {
    const me = await api(`/api/me${requestedWorkspaceId ? `?workspace_id=${encodeURIComponent(requestedWorkspaceId)}` : ""}`);
    if (!me.data.bootstrapped) {
      const boot = await api("/api/bootstrap", {
        method: "POST",
        body: JSON.stringify({ workspace_name: "My NoteSnoop workspace", inbox_mode: "per_user_private" }),
      });
      setState(boot.data);
      return;
    }
    setState({
      workspace: me.data.workspace,
      workspaces: me.data.workspaces || [],
      projects: me.data.projects || [],
      people: me.data.people || [],
      inbound_address: me.data.inbound_address,
    });
    if (me.data.accepted_invites?.length) {
      const invite = me.data.accepted_invites.at(-1);
      if (invite?.project_id) setLandingProjectId(String(invite.project_id));
      setToast(`Joined ${me.data.accepted_invites.length} shared project${me.data.accepted_invites.length > 1 ? "s" : ""}.`);
    }
  }, [api, requestedWorkspaceId]);

  const refreshWorkspaceData = useCallback(async () => {
    if (!workspaceId) return;
    const [homeRes, notesRes, peopleRes, projectsRes] = await Promise.all([
      api(`/api/workspaces/${workspaceId}/home`),
      api(`/api/workspaces/${workspaceId}/notes${activeProject ? `?project_id=${activeProject}` : ""}`),
      api(`/api/workspaces/${workspaceId}/people`),
      api(`/api/workspaces/${workspaceId}/projects`),
    ]);
    setHome(homeRes.data);
    setNotes(notesRes.data);
    setState((prev) => (prev ? { ...prev, people: peopleRes.data, projects: projectsRes.data } : prev));
  }, [activeProject, api, workspaceId]);

  const refreshSignals = useCallback(async () => {
    if (!workspaceId) return;
    const [countRes, activityRes] = await Promise.all([
      api(`/api/review-queue/count?workspace_id=${workspaceId}`),
      api(`/api/collaborator-activity/${workspaceId}`),
    ]);
    setReviewCount(countRes.data.count || 0);
    setActivity(activityRes.data || []);
  }, [api, workspaceId]);

  useEffect(() => {
    if (isSignedIn || DEV_AUTH) refresh().catch((err) => setToast(err.message));
  }, [isSignedIn, refresh]);

  useEffect(() => {
    refreshWorkspaceData().catch((err) => setToast(err.message));
  }, [refreshWorkspaceData]);

  useEffect(
    () => () => {
      if (searchDebounceRef.current) {
        window.clearTimeout(searchDebounceRef.current);
      }
    },
    [],
  );

  useEffect(() => {
    refreshSignals().catch((err) => setToast(err.message));
    const interval = window.setInterval(() => {
      refreshSignals().catch((err) => setToast(err.message));
    }, 30000);
    return () => window.clearInterval(interval);
  }, [refreshSignals]);

  useEffect(() => {
    if (!workspaceId) return;
    const controller = new AbortController();
    let cancelled = false;
    async function connect() {
      const token = isSignedIn ? await getToken() : null;
      const headers: Record<string, string> = {};
      if (token) headers.Authorization = `Bearer ${token}`;
      if (DEV_AUTH && !token) {
        headers["x-notesnoop-user-id"] = "dev_user";
        headers["x-notesnoop-email"] = "dev@example.test";
        headers["x-notesnoop-name"] = "Dev User";
      }
      const response = await fetch(`${API_BASE}/api/events/${workspaceId}`, { headers, signal: controller.signal });
      if (!response.body) return;
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (!cancelled) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const chunks = buffer.split("\n\n");
        buffer = chunks.pop() || "";
        for (const chunk of chunks) {
          if (chunk.includes("event: review_queue") || chunk.includes("event: collaborator_activity")) {
            refreshSignals().catch((err) => setToast(err.message));
          }
        }
      }
    }
    connect().catch(() => undefined);
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [getToken, isSignedIn, refreshSignals, workspaceId]);

  async function saveNote() {
    if (!workspaceId || !body.trim()) return;
    setBusy(true);
    try {
      const projectIds = saveProjectIds.length ? saveProjectIds : undefined;
      const res = await api(`/api/workspaces/${workspaceId}/notes`, {
        method: "POST",
        body: JSON.stringify({
          title: title || null,
          body,
          project_ids: projectIds,
          note_kind: noteKind,
          occurred_at: eventDate(occurredAt),
        }),
      });
      setSelectedNote(res.data);
      setBody("");
      setTitle("");
      setNoteKind("note");
      setOccurredAt("");
      setSelectedProjectIds([]);
      setSheetOpen(true);
      setToast("Saved. AI structuring is queued when allowed.");
      await refreshWorkspaceData();
    } catch (err) {
      setToast(err instanceof Error ? err.message : "Could not save note");
    } finally {
      setBusy(false);
    }
  }

  async function openNote(noteId: string) {
    const res = await api(`/api/notes/${noteId}`);
    setSelectedNote(res.data);
    setSheetOpen(true);
  }

  async function updateNote(noteId: string, nextTitle: string, nextBody: string, nextKind: string, nextOccurredAt: string) {
    const res = await api(`/api/notes/${noteId}`, {
      method: "PATCH",
      body: JSON.stringify({ title: nextTitle || null, body: nextBody, note_kind: nextKind, occurred_at: eventDate(nextOccurredAt) }),
    });
    setSelectedNote(res.data);
    await refreshWorkspaceData();
    setToast("Note saved.");
  }

  async function setNoteProjects(note: any, projectIds: string[], confirmPersonalMove = false) {
    const res = await api(`/api/notes/${note.id}/projects`, {
      method: "PUT",
      body: JSON.stringify({ project_ids: projectIds, confirm_personal_move: confirmPersonalMove }),
    });
    setSelectedNote(res.data);
    await refreshWorkspaceData();
  }

  async function createPerson() {
    if (!workspaceId || !personName.trim()) return;
    await api(`/api/workspaces/${workspaceId}/people`, {
      method: "POST",
      body: JSON.stringify({
        name: personName,
        role: personRole || null,
        company: personCompany || null,
        email: personEmail || null,
      }),
    });
    setPersonName("");
    setPersonRole("");
    setPersonCompany("");
    setPersonEmail("");
    await refreshWorkspaceData();
  }

  function updateSeedPerson(index: number, value: string) {
    setSeedPeopleDrafts((current) => current.map((name, i) => (i === index ? value : name)));
  }

  async function seedPeopleFromOnboarding() {
    if (!workspaceId) return;
    const existing = new Set((state?.people || []).map((person) => String(person.name || "").trim().toLowerCase()));
    const names = seedPeopleDrafts
      .map((name) => name.trim())
      .filter((name, index, all) => name && all.findIndex((candidate) => candidate.toLowerCase() === name.toLowerCase()) === index)
      .filter((name) => !existing.has(name.toLowerCase()));
    if (!names.length) return;
    setBusy(true);
    try {
      for (const name of names) {
        await api(`/api/workspaces/${workspaceId}/people`, {
          method: "POST",
          body: JSON.stringify({ name }),
        });
      }
      setSeedPeopleDrafts(["", ""]);
      setWarmStartDismissed(true);
      setToast("People added.");
      await refreshWorkspaceData();
    } catch (err) {
      setToast(err instanceof Error ? err.message : "Could not add people");
    } finally {
      setBusy(false);
    }
  }

  async function createProject() {
    if (!workspaceId || !projectName.trim()) return;
    const res = await api(`/api/workspaces/${workspaceId}/projects`, {
      method: "POST",
      body: JSON.stringify({ name: projectName, color_hex: "#e85d4f" }),
    });
    setProjectName("");
    setActiveProject(res.data.id);
    await refreshWorkspaceData();
  }

  async function toggleEmailAI() {
    if (!workspaceId || !state?.workspace) return;
    const nextMode = state.workspace.email_ai_mode === "auto" ? "manual" : "auto";
    const res = await api(`/api/workspaces/${workspaceId}/settings`, {
      method: "PATCH",
      body: JSON.stringify({ email_ai_mode: nextMode }),
    });
    setState(res.data);
    setToast(`Email AI is ${nextMode === "auto" ? "Auto" : "Manual"}.`);
  }

  async function toggleMorningBriefing() {
    if (!workspaceId || !state?.workspace) return;
    const nextOptIn = !state.workspace.morning_briefing_optin;
    const res = await api(`/api/workspaces/${workspaceId}/settings`, {
      method: "PATCH",
      body: JSON.stringify({ morning_briefing_optin: nextOptIn }),
    });
    setState(res.data);
    setToast(nextOptIn ? "Morning briefing is on." : "Morning briefing is off.");
  }

  async function sendTestEmail() {
    if (!workspaceId) return;
    const res = await api(`/api/workspaces/${workspaceId}/send-test-email`, { method: "POST" });
    setToast(res.data.outcome === "saved" ? "Test email saved to Inbox." : "Test email was not saved.");
    await refreshWorkspaceData();
  }

  function toggleComposerProject(project: any) {
    setSelectedProjectIds((current) => {
      if (current.includes(project.id)) return current.filter((id) => id !== project.id);
      if (project.kind === "personal") return [project.id];
      return [...current.filter((id) => id !== personal?.id), project.id];
    });
  }

  async function runSearch(nextQuery: string, filters = searchFilters) {
    setQuery(nextQuery);
    if (!workspaceId) return;
    const res = await api(`/api/workspaces/${workspaceId}/search?${buildSearchParams(nextQuery, filters)}`);
    setNotes(res.data);
    setSearchMeta(res.meta || null);
  }

  function clearSearchDebounce() {
    if (searchDebounceRef.current) {
      window.clearTimeout(searchDebounceRef.current);
      searchDebounceRef.current = null;
    }
  }

  function scheduleSearch(nextQuery: string) {
    setQuery(nextQuery);
    clearSearchDebounce();
    searchDebounceRef.current = window.setTimeout(() => {
      runSearch(nextQuery).catch((err) => setToast(err.message));
      searchDebounceRef.current = null;
    }, 350);
  }

  async function applySearchFilters(nextFilters: SearchFilters) {
    setSearchFilters(nextFilters);
    clearSearchDebounce();
    await runSearch(query, nextFilters);
  }

  function selectWorkspace(nextWorkspaceId: string) {
    setRequestedWorkspaceId(nextWorkspaceId);
    setActiveProject(null);
    setSelectedProjectIds([]);
    setPersonTimeline(null);
    setProjectTimeline(null);
    setSelectedNote(null);
    setSheetOpen(false);
    setHome(null);
    setNotes([]);
    setReviewCount(0);
    if (typeof window !== "undefined") {
      const url = new URL(window.location.href);
      url.searchParams.set("workspace_id", nextWorkspaceId);
      url.searchParams.delete("project_id");
      window.history.replaceState({}, "", `${url.pathname}?${url.searchParams.toString()}`);
    }
  }

  const openProject = useCallback(async (project: any) => {
    setActiveProject(project.id);
    setSelectedProjectIds([]);
    setPersonTimeline(null);
    const res = await api(`/api/projects/${project.id}/timeline`);
    setProjectTimeline(res.data);
  }, [api]);

  async function inviteProjectMember(project: any, email: string) {
    if (!email.trim()) return;
    const res = await api(`/api/projects/${project.id}/invites`, {
      method: "POST",
      body: JSON.stringify({ email }),
    });
    setInviteEmail("");
    setToast(`Invite ready for ${res.data.email}.`);
    await openProject(project);
  }

  async function openPerson(person: any) {
    setProjectTimeline(null);
    const res = await api(`/api/people/${person.id}/timeline`);
    setPersonTimeline(res.data);
  }

  async function flag(target: { note_id?: string; project_id?: string; person_id?: string }) {
    await api("/api/flags", { method: "POST", body: JSON.stringify(target) });
    await refreshWorkspaceData();
  }

  async function processWithAI(noteId: string) {
    try {
      await api(`/api/notes/${noteId}/process-with-ai`, { method: "POST" });
      setToast("Queued for AI processing.");
      await refreshWorkspaceData();
    } catch (err) {
      setToast(err instanceof Error ? err.message : "Could not queue AI processing");
    }
  }

  async function blockSender(note: any) {
    await api("/api/email-blocks", {
      method: "POST",
      body: JSON.stringify({ note_id: note.id }),
    });
    setSheetOpen(false);
    setSelectedNote(null);
    setToast("Sender blocked and email removed.");
    await refreshWorkspaceData();
  }

  async function mergePerson(sourcePersonId: string, targetPersonId: string) {
    const res = await api(`/api/people/${sourcePersonId}/merge`, {
      method: "POST",
      body: JSON.stringify({ target_person_id: targetPersonId }),
    });
    setMergeUndoId(res.data.undo_id);
    setPersonTimeline(null);
    setToast("People merged.");
    await refreshWorkspaceData();
  }

  async function undoMerge() {
    if (!mergeUndoId) return;
    await api(`/api/person-merges/${mergeUndoId}/undo`, { method: "POST" });
    setMergeUndoId("");
    setToast("Merge undone.");
    await refreshWorkspaceData();
  }

  async function copyBrief(kind: "note" | "project" | "person", item: any, variant: "quick" | "full" = "quick") {
    const res = await api(`/api/briefs/${kind}/${item.id}?variant=${variant}`);
    await navigator.clipboard.writeText(res.data.markdown);
    setToast(`${variant === "full" ? "Full" : "Quick"} brief copied.`);
  }

  async function decideReview(reviewId: string, decision: "accept" | "reject") {
    await api(`/api/review-queue/${reviewId}/${decision}`, {
      method: "POST",
      body: JSON.stringify({}),
    });
    setToast(decision === "accept" ? "Suggestion accepted." : "Suggestion rejected.");
    await refreshWorkspaceData();
  }

  useEffect(() => {
    if (!landingProjectId || !state?.projects?.length) return;
    const project = state.projects.find((item) => item.id === landingProjectId);
    if (!project) return;
    setLandingProjectId(null);
    openProject(project).catch((err) => setToast(err.message));
  }, [landingProjectId, openProject, state?.projects]);

  const activeProjectRecord = state?.projects.find((project) => project.id === activeProject) || null;
  const dashboardReviewItems = home?.pending_review || [];
  const dashboardReviewCount = reviewCount || dashboardReviewItems.length;
  const dashboardFlagged = home?.flagged || [];
  const dashboardNotes = home?.recent_notes?.length ? home.recent_notes : notes;
  const dashboardProjects = home?.recent_projects?.length
    ? home.recent_projects
    : (state?.projects || []).filter((project) => project.kind === "user");
  const dashboardPeople = home?.recent_people?.length ? home.recent_people : state?.people || [];
  const dashboardTitle = activeProjectRecord ? `${activeProjectRecord.name} dashboard` : "Dashboard";
  const openTasks = (home?.open_tasks?.length ? home.open_tasks : home?.tasks?.length ? home.tasks : dashboardNotes.filter((note) => note.note_kind === "task"));
  const meetingsCalls = (
    home?.meetings_calls?.length
      ? home.meetings_calls
      : [...(home?.meetings || []), ...(home?.calls || [])].length
        ? [...(home?.meetings || []), ...(home?.calls || [])]
        : dashboardNotes.filter((note) => ["meeting", "call"].includes(note.note_kind))
  );
  const reportsBriefs = (
    home?.reports_briefs?.length
      ? home.reports_briefs
      : [...(home?.reports || []), ...(home?.briefs || [])].length
        ? [...(home?.reports || []), ...(home?.briefs || [])]
        : dashboardNotes.filter((note) => note.note_kind === "report")
  );
  const projectIntelligence = home?.project_intelligence?.length
    ? home.project_intelligence
    : dashboardProjects.map((project) => ({
        ...project,
        title: project.name,
        subtitle: project.latest_signal || project.summary || (project.mention_count ? `${project.mention_count} captured memories` : "Waiting for enough project memory"),
      }));
  const memorySections = [
    {
      id: "tasks",
      title: "Open tasks",
      icon: ClipboardList,
      items: openTasks,
      empty: "No open tasks found. Capture follow-ups as Task memories.",
    },
    {
      id: "meetings",
      title: "Meetings/calls",
      icon: CalendarDays,
      items: meetingsCalls,
      empty: "No meetings or calls yet. Capture conversations as Meeting or Call memories.",
    },
    {
      id: "reports",
      title: "Reports/briefs",
      icon: FileText,
      items: reportsBriefs,
      empty: "No reports or briefs yet. Report memories will collect here.",
    },
    {
      id: "intel",
      title: "Project intelligence",
      icon: Lightbulb,
      items: projectIntelligence,
      empty: "Project signals will appear once memories start linking to projects.",
    },
  ];
  const activeMemorySection = memorySections.find((section) => section.id === activeMemoryTab) || memorySections[0];

  const composerSection = (
    <section className={`composer ${quickCapture ? "" : "dashboard-composer"}`}>
      <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Optional title" />
      <div className="context-picker" aria-label="Memory context">
        <select value={noteKind} onChange={(e) => setNoteKind(e.target.value)} aria-label="Memory type">
          {Object.entries(NOTE_KIND_LABELS).map(([value, label]) => (
            <option key={value} value={value}>{label}</option>
          ))}
        </select>
        <label>
          <CalendarDays size={15} />
          <input type="date" value={occurredAt} onChange={(e) => setOccurredAt(e.target.value)} aria-label="Occurred date" />
        </label>
      </div>
      <textarea
        value={body}
        onChange={(e) => setBody(e.target.value)}
        placeholder="Dump a note. Names, projects, rough thoughts, half-sentences all belong here."
        rows={quickCapture ? 9 : 5}
      />
      <div className="project-picker" aria-label="Save note to projects">
        {(state?.projects || []).map((project) => {
          const selected = saveProjectIds.includes(project.id);
          return (
            <button
              type="button"
              key={project.id}
              className={selected ? "selected" : ""}
              onClick={() => toggleComposerProject(project)}
              title={project.kind === "personal" ? "Personal notes cannot be mixed with other projects" : project.name}
            >
              <span className="dot" style={{ background: project.color_hex || "#7c3aed" }} />
              {project.name}
            </button>
          );
        })}
      </div>
      <div className="composer-actions">
        <span>{saveProjectIds.length ? `Saving to ${saveProjectIds.length} project${saveProjectIds.length > 1 ? "s" : ""}` : "Saving to Inbox"}</span>
        <button onClick={saveNote} disabled={busy || !body.trim()}>
          <Send size={17} /> Save
        </button>
      </div>
    </section>
  );

  const appBody = (
    <main className={`app-shell ${quickCapture ? "quick-mode" : ""}`}>
      <aside className={`sidebar ${mobileNav ? "open" : ""}`}>
        <div className="brand-row">
          <img src="/icon.svg" alt="" />
          <strong>NoteSnoop</strong>
          <button className="icon-btn hide-desktop" onClick={() => setMobileNav(false)} aria-label="Close navigation">
            <X size={18} />
          </button>
        </div>
        <button className={`nav-item ${!activeProject ? "active" : ""}`} onClick={() => { setActiveProject(null); setSelectedProjectIds([]); setPersonTimeline(null); setProjectTimeline(null); }}>
          <Archive size={17} /> Home
        </button>
        {inbox && (
          <button className={`nav-item ${activeProject === inbox.id ? "active" : ""}`} onClick={() => openProject(inbox)}>
            <Inbox size={17} /> Inbox
          </button>
        )}
        {personal && (
          <button className={`nav-item ${activeProject === personal.id ? "active" : ""}`} onClick={() => openProject(personal)}>
            <UserRound size={17} /> Personal
          </button>
        )}
        <div className="sidebar-label">Projects</div>
        {state?.projects
          .filter((p) => p.kind === "user")
          .map((project) => (
            <button key={project.id} className={`nav-item ${activeProject === project.id ? "active" : ""}`} onClick={() => openProject(project)}>
              <span className="dot" style={{ background: project.color_hex || "#7c3aed" }} /> {project.name}
              {activityByProject.has(project.id) && <span className="activity-dot" title="Collaborator active" />}
            </button>
          ))}
        <div className="sidebar-create">
          <input value={projectName} onChange={(e) => setProjectName(e.target.value)} placeholder="New project" />
          <button className="icon-btn" onClick={createProject} aria-label="Create project">
            <Plus size={18} />
          </button>
        </div>
        <div className="inbound">
          <span>Inbound</span>
          <button onClick={() => state?.inbound_address && navigator.clipboard.writeText(state.inbound_address)}>
            <Copy size={15} /> {state?.inbound_address || "Loading"}
          </button>
          <button onClick={sendTestEmail}>
            <Send size={15} /> Send test email
          </button>
        </div>
      </aside>

      <section className="main-pane">
        <header className="topbar">
          <button className="icon-btn hide-desktop" onClick={() => setMobileNav(true)} aria-label="Open navigation">
            <Menu size={20} />
          </button>
          <div className="search-box">
            <Search size={18} />
            <input value={query} onChange={(e) => scheduleSearch(e.target.value)} placeholder="Search notes, people, projects..." />
          </div>
          {!!state?.workspaces?.length && state.workspaces.length > 1 && (
            <select
              className="workspace-switcher"
              value={workspaceId || ""}
              onChange={(event) => selectWorkspace(event.target.value)}
              aria-label="Workspace"
            >
              {state.workspaces.map((workspace) => (
                <option key={workspace.id} value={workspace.id}>{workspace.name}</option>
              ))}
            </select>
          )}
          <button className="mode-btn" onClick={toggleEmailAI} title="Email AI default is Manual for v1">
            <Settings size={18} />
            {state?.workspace?.email_ai_mode === "auto" ? "Auto" : "Manual"}
          </button>
          <button className="mode-btn" onClick={toggleMorningBriefing} title="Daily count-only morning briefing">
            <Bell size={18} />
            {state?.workspace?.morning_briefing_optin ? "Briefing on" : "Briefing off"}
          </button>
          <UserButton />
        </header>

        {!quickCapture && (
          <div className="search-filter-row">
            <select
              value={searchFilters.person_id || ""}
              onChange={(e) => applySearchFilters({ ...searchFilters, person_id: e.target.value || undefined })}
              aria-label="Filter by person"
            >
              <option value="">All people</option>
              {state?.people.map((person) => <option key={person.id} value={person.id}>{person.name}</option>)}
            </select>
            <label>
              <CalendarDays size={15} />
              <input
                type="date"
                value={searchFilters.date_from || ""}
                onChange={(e) => applySearchFilters({ ...searchFilters, date_from: e.target.value || undefined })}
                aria-label="Search from date"
              />
            </label>
            <label>
              <CalendarDays size={15} />
              <input
                type="date"
                value={searchFilters.date_to || ""}
                onChange={(e) => applySearchFilters({ ...searchFilters, date_to: e.target.value || undefined })}
                aria-label="Search to date"
              />
            </label>
            <button
              className={searchFilters.flagged_only ? "filter-toggle active" : "filter-toggle"}
              onClick={() => applySearchFilters({ ...searchFilters, flagged_only: !searchFilters.flagged_only })}
            >
              <Flag size={15} /> Flagged
            </button>
            {!!searchMeta?.semantic_excluded && <span>{searchMeta.semantic_excluded} unindexed</span>}
          </div>
        )}

        {quickCapture ? (
          composerSection
        ) : (
          <section className="dashboard" aria-label="Memory dashboard">
            <div className="dashboard-head">
              <div>
                <span className="dashboard-kicker">{activeProjectRecord ? "Project memory" : "Workspace memory"}</span>
                <h1>{dashboardTitle}</h1>
                <p>{activeProjectRecord ? "Open loops, people, and notes in this project." : "Open loops, recent movement, and capture."}</p>
              </div>
              <div className="dashboard-actions">
                <button type="button" onClick={() => setReviewSheetOpen(true)}>
                  <Bell size={16} /> Review{dashboardReviewCount ? ` (${dashboardReviewCount})` : ""}
                </button>
                {inbox && (
                  <button type="button" onClick={() => openProject(inbox)} aria-label="Open Inbox project">
                    <Inbox size={16} /> Inbox
                  </button>
                )}
              </div>
            </div>

            <div className="dashboard-metrics">
              <button className="metric-card metric-button" type="button" onClick={() => setReviewSheetOpen(true)} aria-label={`Open review queue with ${dashboardReviewCount} items`}>
                <span><Bell size={16} /> Review queue</span>
                <strong>{dashboardReviewCount}</strong>
                <small>{dashboardReviewCount ? "needs decisions" : "clear"}</small>
              </button>
              <div className="metric-card">
                <span><Archive size={16} /> Memory items</span>
                <strong>{dashboardNotes.length}</strong>
                <small>{activeProjectRecord ? "in context" : "latest"}</small>
              </div>
              <div className="metric-card">
                <span><ClipboardList size={16} /> Open tasks</span>
                <strong>{openTasks.length}</strong>
                <small>{openTasks.length ? "active loops" : "none open"}</small>
              </div>
              <div className="metric-card">
                <span><Lightbulb size={16} /> Intelligence</span>
                <strong>{projectIntelligence.length}</strong>
                <small>{activeProjectRecord ? "project signals" : "project views"}</small>
              </div>
            </div>

            <div className="dashboard-grid">
              <section className="dashboard-panel memory-system-panel">
                <div className="panel-head">
                  <h2>Memory system</h2>
                  <Sparkles size={18} />
                </div>
                <div className="memory-tabs" role="tablist" aria-label="Memory categories">
                  {memorySections.map((section) => {
                    const Icon = section.icon;
                    const selected = section.id === activeMemorySection.id;
                    return (
                      <button
                        key={section.id}
                        type="button"
                        role="tab"
                        aria-selected={selected}
                        className={selected ? "active" : ""}
                        onClick={() => setActiveMemoryTab(section.id)}
                      >
                        <Icon size={15} />
                        <span>{section.title}</span>
                        <strong>{section.items.length}</strong>
                      </button>
                    );
                  })}
                </div>
                <div className="memory-card-grid" role="tabpanel" aria-label={activeMemorySection.title}>
                  {activeMemorySection.items.length ? (
                    activeMemorySection.items.slice(0, 4).map((item) => (
                      <MemoryCard
                        key={`${activeMemorySection.id}-${item.id || item.note_id || item.project_id || item.title || item.name}`}
                        item={item}
                        sectionId={activeMemorySection.id}
                        onOpenNote={openNote}
                        onOpenProject={(projectId) => {
                          const project = (state?.projects || []).find((candidate) => candidate.id === projectId);
                          if (project) openProject(project);
                        }}
                      />
                    ))
                  ) : (
                    <p className="dashboard-empty memory-empty">{activeMemorySection.empty}</p>
                  )}
                </div>
              </section>

              <section className="dashboard-panel attention-panel">
                <div className="panel-head">
                  <h2>Needs attention</h2>
                  <Bell size={18} />
                </div>
                {dashboardReviewItems.length || dashboardFlagged.length ? (
                  <div className="dashboard-list">
                    {dashboardReviewItems.slice(0, 3).map((item) => (
                      <button key={item.id} className="dashboard-row" type="button" onClick={() => setReviewSheetOpen(true)}>
                        <span className="row-icon"><Bell size={15} /></span>
                        <span>
                          <strong>{item.payload?.name || item.entity_kind}</strong>
                          <small>Review suggestion</small>
                        </span>
                      </button>
                    ))}
                    {dashboardFlagged.slice(0, 3).map((item) => (
                      <button key={item.id} className="dashboard-row" type="button" onClick={() => item.note_id && openNote(item.note_id)}>
                        <span className="row-icon warning"><Flag size={15} /></span>
                        <span>
                          <strong>{item.label || item.target_kind}</strong>
                          <small>Flagged {item.target_kind}</small>
                        </span>
                      </button>
                    ))}
                  </div>
                ) : (
                  <p className="dashboard-empty">Caught up.</p>
                )}
              </section>

              <section className="dashboard-panel capture-panel">
                <div className="panel-head">
                  <h2>Capture</h2>
                  <Send size={18} />
                </div>
                {composerSection}
              </section>

              <section className="dashboard-panel">
                <div className="panel-head">
                  <h2>Active projects</h2>
                  <Archive size={18} />
                </div>
                {dashboardProjects.length ? (
                  <div className="dashboard-list">
                    {dashboardProjects.slice(0, 5).map((project) => (
                      <button key={project.id} className="dashboard-row" type="button" onClick={() => openProject(project)} aria-label={`Open project ${project.name}`}>
                        <span className="dot" style={{ background: project.color_hex || "#7c3aed" }} />
                        <span>
                          <strong>{project.name}</strong>
                          <small>{project.mention_count ? `${project.mention_count} notes` : project.kind === "inbox" ? "Inbox" : "Project"}</small>
                        </span>
                      </button>
                    ))}
                  </div>
                ) : (
                  <p className="dashboard-empty">No active projects yet.</p>
                )}
              </section>

              <section className="dashboard-panel">
                <div className="panel-head">
                  <h2>People</h2>
                  <Users size={18} />
                </div>
                {dashboardPeople.length ? (
                  <div className="dashboard-list">
                    {dashboardPeople.slice(0, 5).map((person) => (
                      <button key={person.id} className="dashboard-row" type="button" onClick={() => openPerson(person)} aria-label={`Open ${person.name} timeline`}>
                        <span className="row-icon"><UserRound size={15} /></span>
                        <span>
                          <strong>{person.name}</strong>
                          <small>{person.company || `${person.confirmed_note_count || 0} notes`}</small>
                        </span>
                      </button>
                    ))}
                  </div>
                ) : (
                  <p className="dashboard-empty">No people yet.</p>
                )}
              </section>

              <section className="dashboard-panel recent-memory">
                <div className="panel-head">
                  <h2>Recent memory</h2>
                  <Sparkles size={18} />
                </div>
                {dashboardNotes.length ? (
                  <div className="dashboard-list">
                    {dashboardNotes.slice(0, 4).map((note) => (
                      <button key={note.id} className="dashboard-row memory-row" type="button" onClick={() => openNote(note.id)}>
                        <span>
                          <strong>{note.title}</strong>
                          <small>{NOTE_KIND_LABELS[note.note_kind || "note"] || "Note"} - {note.body}</small>
                        </span>
                      </button>
                    ))}
                  </div>
                ) : (
                  <p className="dashboard-empty">No notes yet.</p>
                )}
              </section>
            </div>
          </section>
        )}

        {showWarmStart && (
          <section className="warm-start" aria-label="Pre-seed people">
            <div>
              <span><Users size={16} /> Warm start</span>
              <strong>Add 1-2 people you work with.</strong>
            </div>
            <div className="warm-start-inputs">
              <input
                value={seedPeopleDrafts[0]}
                onChange={(event) => updateSeedPerson(0, event.target.value)}
                placeholder="Person name"
                aria-label="First person name"
              />
              <input
                value={seedPeopleDrafts[1]}
                onChange={(event) => updateSeedPerson(1, event.target.value)}
                placeholder="Another person"
                aria-label="Second person name"
              />
              <button onClick={seedPeopleFromOnboarding} disabled={busy || !seedPeopleDrafts.some((name) => name.trim())}>
                <Check size={16} /> Add
              </button>
              <button className="icon-btn" onClick={() => setWarmStartDismissed(true)} aria-label="Skip warm start">
                <X size={17} />
              </button>
            </div>
          </section>
        )}

        {!quickCapture && (
          <div className="content-grid">
            <section className="list-pane">
              {!!home?.flagged?.length && (
                <div className="flagged-strip">
                  <div className="section-head">
                    <h2>Flagged</h2>
                    <Flag size={18} />
                  </div>
                  {home.flagged.map((item) => (
                    <button key={item.id} onClick={() => item.note_id && openNote(item.note_id)}>
                      <Flag size={15} />
                      <span>{item.label || item.target_kind}</span>
                    </button>
                  ))}
                </div>
              )}
              <div className="section-head">
                <h2>Notes</h2>
                <Sparkles size={18} />
              </div>
              {notes.map((note) => (
                <article key={note.id} className="note-row" onClick={() => openNote(note.id)}>
                  <div>
                    <h3 className={note.title_is_derived ? "derived" : ""}>
                      {note.title}
                      <span className="kind-badge">{NOTE_KIND_LABELS[note.note_kind || (note.raw_email_metadata ? "email" : "note")] || "Note"}</span>
                    </h3>
                    <p>{note.body}</p>
                  </div>
                  <button className="icon-btn" onClick={(e) => { e.stopPropagation(); flag({ note_id: note.id }); }} aria-label="Flag note">
                    <Flag size={17} />
                  </button>
                </article>
              ))}
            </section>

            <section className="entity-pane">
              <div className="section-head">
                <h2>{personTimeline?.person?.name || projectTimeline?.project?.name || "People"}</h2>
                {projectTimeline ? <Archive size={18} /> : <Users size={18} />}
              </div>
              {personTimeline ? (
                <TimelinePanel
                  timeline={personTimeline}
                  kind="person"
                  people={state?.people || []}
                  onOpenNote={openNote}
                  onCopy={() => copyBrief("person", personTimeline.person)}
                  onFlag={() => flag({ person_id: personTimeline.person.id })}
                  onMerge={mergePerson}
                  onBack={() => setPersonTimeline(null)}
                />
              ) : projectTimeline ? (
                <TimelinePanel
                  timeline={projectTimeline}
                  kind="project"
                  people={state?.people || []}
                  onOpenNote={openNote}
                  onCopy={() => copyBrief("project", projectTimeline.project)}
                  onFlag={() => flag({ project_id: projectTimeline.project.id })}
                  onMerge={mergePerson}
                  inviteEmail={inviteEmail}
                  onInviteEmailChange={setInviteEmail}
                  onInvite={inviteProjectMember}
                  onBack={() => setProjectTimeline(null)}
                />
              ) : (
                <>
                  <div className="person-create-grid">
                    <input value={personName} onChange={(e) => setPersonName(e.target.value)} placeholder="Quick-add person" />
                    <input value={personRole} onChange={(e) => setPersonRole(e.target.value)} placeholder="Role" />
                    <input value={personCompany} onChange={(e) => setPersonCompany(e.target.value)} placeholder="Company" />
                    <input value={personEmail} onChange={(e) => setPersonEmail(e.target.value)} placeholder="Email" type="email" />
                    <button className="icon-btn" onClick={createPerson} aria-label="Add person">
                      <Plus size={18} />
                    </button>
                  </div>
                  {state?.people.map((person) => (
                    <div className="entity-row" key={person.id} onClick={() => openPerson(person)}>
                      <UserRound size={17} />
                      <div>
                        <strong>{person.name}</strong>
                        <span>{person.role || person.company || person.email || `${person.confirmed_note_count || 0} notes`}</span>
                      </div>
                      <button className="icon-btn" onClick={(e) => { e.stopPropagation(); copyBrief("person", person); }} aria-label="Copy person brief">
                        <Copy size={16} />
                      </button>
                    </div>
                  ))}
                </>
              )}
            </section>
          </div>
        )}
      </section>

      {toast && (
        <div className="toast">
          <button onClick={() => setToast("")}>
            <Check size={16} /> {toast}
          </button>
          {mergeUndoId && <button onClick={undoMerge}>Undo merge</button>}
        </div>
      )}

      <ReviewSheet
        open={reviewSheetOpen}
        items={home?.pending_review || []}
        reviewCount={reviewCount}
        onClose={() => setReviewSheetOpen(false)}
        onDecide={decideReview}
      />

      <LinkedSheet
        open={sheetOpen}
        note={selectedNote}
        projects={state?.projects || []}
        people={state?.people || []}
        onClose={() => setSheetOpen(false)}
        onCopy={() => selectedNote && copyBrief("note", selectedNote)}
        onFullCopy={() => selectedNote && copyBrief("note", selectedNote, "full")}
        onFlag={() => selectedNote && flag({ note_id: selectedNote.id })}
        onProcess={() => selectedNote && processWithAI(selectedNote.id)}
        onBlockSender={() => selectedNote && blockSender(selectedNote)}
        onUpdate={updateNote}
        onSetProjects={setNoteProjects}
        onSuggestionQueued={() => setToast("Suggestion sent to Review.")}
        createProject={async (name) => {
          if (!workspaceId) throw new Error("Workspace is not ready");
          const res = await api(`/api/workspaces/${workspaceId}/projects`, {
            method: "POST",
            body: JSON.stringify({ name, color_hex: "#e85d4f" }),
          });
          await refreshWorkspaceData();
          return res.data;
        }}
        api={api}
        refresh={refreshWorkspaceData}
      />
    </main>
  );

  if (!DEV_AUTH && (!isLoaded || !isSignedIn)) {
    return (
      <div className="signin-shell">
        <img src="/icon.svg" alt="" />
        <h1>NoteSnoop</h1>
        <SignInButton mode="modal">
          <button>Sign in</button>
        </SignInButton>
      </div>
    );
  }

  return appBody;
}

function MemoryCard({
  item,
  sectionId,
  onOpenNote,
  onOpenProject,
}: {
  item: any;
  sectionId: string;
  onOpenNote: (noteId: string) => Promise<void>;
  onOpenProject: (projectId: string) => void;
}) {
  const title = item.title || item.label || item.name || item.project_name || "Untitled memory";
  const subtitle = item.subtitle || item.summary || item.body || item.status || item.next_step || "Awaiting more context";
  const owner = item.owner_name || item.assignee_name || item.person_name || item.company || item.kind || NOTE_KIND_LABELS[item.note_kind || ""] || "Memory";
  const date = item.due_at || item.due_date || item.occurred_at || item.created_at || item.updated_at;
  const noteId = item.note_id || (sectionId !== "intel" ? item.id : null);
  const projectId = item.project_id || (sectionId === "intel" ? item.id : null);
  const canOpen = Boolean(noteId || projectId);
  return (
    <button
      type="button"
      className="memory-card"
      disabled={!canOpen}
      onClick={() => {
        if (noteId) {
          onOpenNote(noteId);
          return;
        }
        if (projectId) onOpenProject(projectId);
      }}
    >
      <span className="memory-card-meta">
        <strong>{owner}</strong>
        {date && <small>{new Date(date).toLocaleDateString()}</small>}
      </span>
      <span className="memory-card-title">{title}</span>
      <span className="memory-card-body">{subtitle}</span>
    </button>
  );
}

function ReviewSheet({
  open,
  items,
  reviewCount,
  onClose,
  onDecide,
}: {
  open: boolean;
  items: any[];
  reviewCount: number;
  onClose: () => void;
  onDecide: (reviewId: string, decision: "accept" | "reject") => Promise<void>;
}) {
  if (!open) return null;
  return (
    <div className="sheet-backdrop review-backdrop" onClick={onClose}>
      <aside className="review-sheet" onClick={(e) => e.stopPropagation()}>
        <div className="sheet-handle" />
        <div className="section-head">
          <h2>Review{reviewCount ? ` (${reviewCount})` : ""}</h2>
          <button className="icon-btn" onClick={onClose} aria-label="Close review">
            <X size={18} />
          </button>
        </div>
        <div className="review-sheet-list">
          {items.slice(0, 5).map((item) => (
            <article key={item.id}>
              <strong>{item.payload?.name || item.entity_kind}</strong>
              <span>{item.entity_kind}</span>
              <div>
                <button onClick={() => onDecide(item.id, "accept")}><Check size={15} /> Accept</button>
                <button onClick={() => onDecide(item.id, "reject")}><X size={15} /> Reject</button>
              </div>
            </article>
          ))}
          {!items.length && <p className="muted">Caught up.</p>}
        </div>
      </aside>
    </div>
  );
}

function TimelinePanel({
  timeline,
  kind,
  people,
  onOpenNote,
  onCopy,
  onFlag,
  onMerge,
  inviteEmail = "",
  onInviteEmailChange,
  onInvite,
  onBack,
}: {
  timeline: any;
  kind: "person" | "project";
  people: any[];
  onOpenNote: (noteId: string) => Promise<void>;
  onCopy: () => void;
  onFlag: () => void;
  onMerge: (sourcePersonId: string, targetPersonId: string) => Promise<void>;
  inviteEmail?: string;
  onInviteEmailChange?: (email: string) => void;
  onInvite?: (project: any, email: string) => Promise<void>;
  onBack: () => void;
}) {
  const [mergeTargetId, setMergeTargetId] = useState("");
  const notes = timeline.notes || [];
  return (
    <div className="timeline-panel">
      <div className="timeline-actions">
        <button onClick={onCopy}><Copy size={16} /> Brief</button>
        <button onClick={onFlag}><Flag size={16} /> Flag</button>
        <button onClick={onBack}><X size={16} /> Close</button>
      </div>
      {kind === "person" && (
        <div className="merge-row">
          <select value={mergeTargetId} onChange={(event) => setMergeTargetId(event.target.value)}>
            <option value="">Merge with...</option>
            {people
              .filter((person) => person.id !== timeline.person.id)
              .map((person) => <option key={person.id} value={person.id}>{person.name}</option>)}
          </select>
          <button disabled={!mergeTargetId} onClick={() => onMerge(timeline.person.id, mergeTargetId)}>
            <Users size={16} /> Merge
          </button>
        </div>
      )}
      {kind === "person" && !!timeline.projects?.length && (
        <div className="mini-section">
          {(timeline.person.role || timeline.person.company || timeline.person.email) && (
            <strong>{[timeline.person.role, timeline.person.company, timeline.person.email].filter(Boolean).join(" - ")}</strong>
          )}
          <strong>Projects</strong>
          {timeline.projects.slice(0, 5).map((project: any) => (
            <span key={project.id}>{project.name} - {project.mention_count} notes</span>
          ))}
        </div>
      )}
      {kind === "project" && (
        <div className="mini-section">
          <strong>{timeline.members?.length || 0} members</strong>
          {(timeline.people || []).slice(0, 5).map((person: any) => (
            <span key={person.id}>{person.name} - {person.mention_count} mentions</span>
          ))}
        </div>
      )}
      {kind === "project" && (
        <div className="share-panel">
          <div className="share-members">
            {(timeline.members || []).map((member: any) => (
              <span key={member.clerk_user_id}>{member.display_name || member.email || member.clerk_user_id}</span>
            ))}
            {(timeline.invites || [])
              .filter((invite: any) => invite.status === "pending")
              .map((invite: any) => (
                <span key={invite.id} className="pending-invite">{invite.email}</span>
              ))}
          </div>
          <div className="share-row">
            <input
              value={inviteEmail}
              onChange={(event) => onInviteEmailChange?.(event.target.value)}
              placeholder="Invite by email"
              type="email"
            />
            <button disabled={!inviteEmail.trim()} onClick={() => onInvite?.(timeline.project, inviteEmail)}>
              <Users size={16} /> Share
            </button>
          </div>
        </div>
      )}
      <div className="timeline-list">
        {notes.map((note: any) => (
          <article key={note.id} onClick={() => onOpenNote(note.id)}>
            <strong>{note.title}</strong>
            <span>{NOTE_KIND_LABELS[note.note_kind || "note"] || "Note"} - {new Date(note.occurred_at || note.created_at).toLocaleDateString()}</span>
            <p>{note.body}</p>
          </article>
        ))}
        {!notes.length && <p className="muted">No timeline notes yet.</p>}
      </div>
    </div>
  );
}

function LinkedSheet({
  open,
  note,
  projects,
  people,
  onClose,
  onCopy,
  onFullCopy,
  onFlag,
  onProcess,
  onBlockSender,
  onUpdate,
  onSetProjects,
  onSuggestionQueued,
  createProject,
  api,
  refresh,
}: {
  open: boolean;
  note: any | null;
  projects: any[];
  people: any[];
  onClose: () => void;
  onCopy: () => void;
  onFullCopy: () => void;
  onFlag: () => void;
  onProcess: () => void;
  onBlockSender: () => void;
  onUpdate: (noteId: string, title: string, body: string, noteKind: string, occurredAt: string) => Promise<void>;
  onSetProjects: (note: any, projectIds: string[], confirmPersonalMove?: boolean) => Promise<void>;
  onSuggestionQueued: () => void;
  createProject: (name: string) => Promise<any>;
  api: (path: string, init?: RequestInit) => Promise<any>;
  refresh: () => Promise<void>;
}) {
  const [personId, setPersonId] = useState("");
  const [editMode, setEditMode] = useState(false);
  const [draftTitle, setDraftTitle] = useState("");
  const [draftBody, setDraftBody] = useState("");
  const [draftKind, setDraftKind] = useState("note");
  const [draftOccurredAt, setDraftOccurredAt] = useState("");
  const [newProjectName, setNewProjectName] = useState("");
  useEffect(() => {
    if (!note) return;
    setDraftTitle(note.title || "");
    setDraftBody(note.body || "");
    setDraftKind(note.note_kind || (note.raw_email_metadata ? "email" : "note"));
    setDraftOccurredAt(inputDate(note.occurred_at));
    setEditMode(false);
    setNewProjectName("");
  }, [note]);
  if (!open || !note) return null;

  const currentProjectIds = (note.projects || []).map((project: any) => project.id);

  async function link() {
    if (!personId) return;
    const res = await api(`/api/notes/${note.id}/people`, {
      method: "POST",
      body: JSON.stringify({ person_id: personId, state: "confirmed", source: "user" }),
    });
    if (res.data?.collaborator_suggestion) onSuggestionQueued();
    await refresh();
  }

  async function moveToProject(projectId: string) {
    const confirmMove = note.is_personal ? window.confirm("Move this note out of Personal before linking it to this project?") : false;
    if (note.is_personal && !confirmMove) return;
    await onSetProjects(note, [projectId], confirmMove);
  }

  async function createAndMove() {
    if (!newProjectName.trim()) return;
    const project = await createProject(newProjectName.trim());
    await onSetProjects(note, [project.id], note.is_personal);
    setNewProjectName("");
  }

  return (
    <div className="sheet-backdrop" onClick={onClose}>
      <aside className="linked-sheet" onClick={(e) => e.stopPropagation()}>
        <div className="sheet-handle" />
        <div className="section-head">
          <h2>{note.title}</h2>
          <button className="icon-btn" onClick={onClose} aria-label="Close">
            <X size={18} />
          </button>
        </div>
        {editMode ? (
          <div className="sheet-editor">
            <input value={draftTitle} onChange={(e) => setDraftTitle(e.target.value)} aria-label="Note title" />
            <div className="context-picker">
              <select value={draftKind} onChange={(e) => setDraftKind(e.target.value)} aria-label="Memory type">
                {Object.entries(NOTE_KIND_LABELS).map(([value, label]) => (
                  <option key={value} value={value}>{label}</option>
                ))}
              </select>
              <label>
                <CalendarDays size={15} />
                <input type="date" value={draftOccurredAt} onChange={(e) => setDraftOccurredAt(e.target.value)} aria-label="Occurred date" />
              </label>
            </div>
            <textarea value={draftBody} onChange={(e) => setDraftBody(e.target.value)} rows={7} aria-label="Note body" />
            <div className="sheet-actions">
              <button onClick={() => onUpdate(note.id, draftTitle, draftBody, draftKind, draftOccurredAt)}><Check size={17} /> Save changes</button>
              <button onClick={() => setEditMode(false)}><X size={17} /> Cancel</button>
            </div>
          </div>
        ) : (
          <>
            <div className="note-meta-row">
              <span>{NOTE_KIND_LABELS[note.note_kind || (note.raw_email_metadata ? "email" : "note")] || "Note"}</span>
              <span>{new Date(note.occurred_at || note.created_at).toLocaleDateString()}</span>
            </div>
            <p>{note.body}</p>
          </>
        )}
        {note.raw_email_metadata && (
          <div className="email-meta">
            <span>From {note.raw_email_metadata.sender || "unknown sender"}</span>
            <span>{note.raw_email_metadata.subject || "No subject"}</span>
          </div>
        )}
        <div className="chip-row">
          {(note.projects || []).map((project: any) => (
            <span className="chip project-chip" key={project.id}>
              <span className="dot" style={{ background: project.color_hex || "#7c3aed" }} />
              {project.name}
            </span>
          ))}
          {(note.people || []).map((person: any) => (
            <span className="chip" key={person.id}>{person.name} {person.confidence ? `${Math.round(person.confidence * 100)}%` : ""}</span>
          ))}
          {note.ai_processing_status === "processing" && <span className="chip">Processing...</span>}
          {note.ai_processing_status === "skipped" && <span className="chip">Manual only</span>}
        </div>
        <div className="inline-create">
          <select value={personId} onChange={(e) => setPersonId(e.target.value)}>
            <option value="">Link a person</option>
            {people.map((person) => <option key={person.id} value={person.id}>{person.name}</option>)}
          </select>
          <button className="icon-btn" onClick={link} aria-label="Link selected person">
            <Plus size={18} />
          </button>
        </div>
        {note.project_nudge?.inbox_only && (
          <div className="project-nudge">
            <strong>Move from Inbox</strong>
            <div className="nudge-actions">
              {(note.project_nudge.matched_projects || []).map((project: any) => (
                <button key={project.id} onClick={() => moveToProject(project.id)}>
                  <span className="dot" style={{ background: project.color_hex || "#7c3aed" }} />
                  {project.name}
                </button>
              ))}
            </div>
            <div className="inline-create">
              <input value={newProjectName} onChange={(e) => setNewProjectName(e.target.value)} placeholder="New project for this note" />
              <button className="icon-btn" onClick={createAndMove} aria-label="Create project and move note">
                <Plus size={18} />
              </button>
            </div>
          </div>
        )}
        <div className="project-picker sheet-project-picker" aria-label="Linked projects">
          {projects.map((project) => {
            const selected = currentProjectIds.includes(project.id);
            return (
              <button
                key={project.id}
                className={selected ? "selected" : ""}
                onClick={() => {
                  if (project.kind === "personal") {
                    onSetProjects(note, [project.id], false);
                    return;
                  }
                  const nextIds = selected
                    ? currentProjectIds.filter((id: string) => id !== project.id)
                    : [...currentProjectIds.filter((id: string) => id !== projects.find((p) => p.kind === "personal")?.id), project.id];
                  if (!nextIds.length) return;
                  const confirmMove = note.is_personal && !selected
                    ? window.confirm("Move this note out of Personal before linking it to this project?")
                    : false;
                  if (note.is_personal && !confirmMove && !selected) return;
                  onSetProjects(note, nextIds, confirmMove);
                }}
              >
                <span className="dot" style={{ background: project.color_hex || "#7c3aed" }} />
                {project.name}
              </button>
            );
          })}
        </div>
        {!!note.versions?.length && (
          <div className="version-row">
            {note.versions.map((version: any) => (
              <span key={version.version}>v{version.version}</span>
            ))}
          </div>
        )}
        <div className="sheet-actions">
          <button onClick={onCopy}><Copy size={17} /> Quick brief</button>
          <button onClick={onFullCopy}><Copy size={17} /> Full brief</button>
          <button onClick={onFlag}><Flag size={17} /> Flag</button>
          <button onClick={() => setEditMode(true)}><Settings size={17} /> Edit</button>
          <button onClick={onProcess}><Sparkles size={17} /> Process with AI</button>
          {note.raw_email_metadata && <button onClick={onBlockSender}><X size={17} /> Block sender</button>}
        </div>
      </aside>
    </div>
  );
}
