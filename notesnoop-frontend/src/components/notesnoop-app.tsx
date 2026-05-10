"use client";

/* eslint-disable react-hooks/set-state-in-effect, @next/next/no-img-element */

import {
  Archive,
  Bell,
  Building2,
  CalendarDays,
  Check,
  CheckCircle2,
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
  Workflow,
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
  reminders?: any[];
  tasks?: any[];
  meetings_calls?: any[];
  meetings?: any[];
  calls?: any[];
  reports_briefs?: any[];
  reports?: any[];
  briefs?: any[];
  workflows?: any[];
  companies?: any[];
  project_intelligence?: any[];
};

type SearchFilters = {
  person_id?: string;
  date_from?: string;
  date_to?: string;
  flagged_only?: boolean;
};

type MemoryGraphState = {
  nodes: any[];
  edges: any[];
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
  const [memoryGraph, setMemoryGraph] = useState<MemoryGraphState>({ nodes: [], edges: [] });
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
  const [reviewItems, setReviewItems] = useState<any[]>([]);
  const [activeMemoryTab, setActiveMemoryTab] = useState("tasks");
  const [selectedMemory, setSelectedMemory] = useState<{ sectionId: string; item: any } | null>(null);
  const [selectedGraphKind, setSelectedGraphKind] = useState<string | null>(null);
  const [quickTaskTitle, setQuickTaskTitle] = useState("");
  const [quickTaskDue, setQuickTaskDue] = useState("");
  const [quickMeetingTitle, setQuickMeetingTitle] = useState("");
  const [quickMeetingDate, setQuickMeetingDate] = useState("");
  const [quickReportTitle, setQuickReportTitle] = useState("");
  const [quickWorkflowName, setQuickWorkflowName] = useState("");
  const [quickCompanyName, setQuickCompanyName] = useState("");
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
    const projectQuery = activeProject ? `?project_id=${activeProject}` : "";
    const [homeRes, graphRes, notesRes, peopleRes, projectsRes] = await Promise.all([
      api(`/api/workspaces/${workspaceId}/home${projectQuery}`),
      api(`/api/workspaces/${workspaceId}/memory-graph${projectQuery}`),
      api(`/api/workspaces/${workspaceId}/notes${activeProject ? `?project_id=${activeProject}` : ""}`),
      api(`/api/workspaces/${workspaceId}/people`),
      api(`/api/workspaces/${workspaceId}/projects`),
    ]);
    setHome(homeRes.data);
    setMemoryGraph(graphRes.data?.nodes ? graphRes.data : { nodes: [], edges: [] });
    setNotes(notesRes.data);
    setState((prev) => (prev ? { ...prev, people: peopleRes.data, projects: projectsRes.data } : prev));
  }, [activeProject, api, workspaceId]);

  const refreshSignals = useCallback(async () => {
    if (!workspaceId) return;
    const projectQuery = activeProject ? `&project_id=${activeProject}` : "";
    const [countRes, activityRes] = await Promise.all([
      api(`/api/review-queue/count?workspace_id=${workspaceId}${projectQuery}`),
      api(`/api/collaborator-activity/${workspaceId}`),
    ]);
    setReviewCount(countRes.data.count || 0);
    setActivity(activityRes.data || []);
  }, [activeProject, api, workspaceId]);

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

  async function createQuickTask() {
    if (!workspaceId || !quickTaskTitle.trim()) return;
    setBusy(true);
    try {
      const projectIds = activeProject ? [activeProject] : selectedProjectIds.length ? selectedProjectIds : undefined;
      await api(`/api/workspaces/${workspaceId}/tasks`, {
        method: "POST",
        body: JSON.stringify({
          title: quickTaskTitle,
          status: "todo",
          due_at: eventDate(quickTaskDue),
          project_ids: projectIds,
        }),
      });
      setQuickTaskTitle("");
      setQuickTaskDue("");
      setToast("Task added.");
      await refreshWorkspaceData();
    } catch (err) {
      setToast(err instanceof Error ? err.message : "Could not add task");
    } finally {
      setBusy(false);
    }
  }

  async function createQuickMeeting() {
    if (!workspaceId || !quickMeetingTitle.trim()) return;
    setBusy(true);
    try {
      const projectIds = activeProject ? [activeProject] : selectedProjectIds.length ? selectedProjectIds : undefined;
      await api(`/api/workspaces/${workspaceId}/meetings`, {
        method: "POST",
        body: JSON.stringify({
          title: quickMeetingTitle,
          occurred_at: eventDate(quickMeetingDate),
          project_ids: projectIds,
        }),
      });
      setQuickMeetingTitle("");
      setQuickMeetingDate("");
      setToast("Meeting memory added.");
      await refreshWorkspaceData();
    } catch (err) {
      setToast(err instanceof Error ? err.message : "Could not add meeting");
    } finally {
      setBusy(false);
    }
  }

  async function createQuickReport() {
    if (!workspaceId || !quickReportTitle.trim()) return;
    setBusy(true);
    try {
      const projectIds = activeProject ? [activeProject] : selectedProjectIds.length ? selectedProjectIds : undefined;
      await api(`/api/workspaces/${workspaceId}/reports`, {
        method: "POST",
        body: JSON.stringify({
          title: quickReportTitle,
          status: "draft",
          project_ids: projectIds,
        }),
      });
      setQuickReportTitle("");
      setToast("Report draft added.");
      await refreshWorkspaceData();
    } catch (err) {
      setToast(err instanceof Error ? err.message : "Could not add report");
    } finally {
      setBusy(false);
    }
  }

  async function createQuickWorkflow() {
    if (!workspaceId || !quickWorkflowName.trim()) return;
    setBusy(true);
    try {
      const projectIds = activeProject ? [activeProject] : selectedProjectIds.length ? selectedProjectIds : undefined;
      await api(`/api/workspaces/${workspaceId}/workflows`, {
        method: "POST",
        body: JSON.stringify({
          name: quickWorkflowName,
          status: "active",
          project_ids: projectIds,
        }),
      });
      setQuickWorkflowName("");
      setToast("Workflow added.");
      await refreshWorkspaceData();
    } catch (err) {
      setToast(err instanceof Error ? err.message : "Could not add workflow");
    } finally {
      setBusy(false);
    }
  }

  async function createQuickCompany() {
    if (!workspaceId || !quickCompanyName.trim()) return;
    setBusy(true);
    try {
      const projectIds = activeProject ? [activeProject] : selectedProjectIds.length ? selectedProjectIds : undefined;
      await api(`/api/workspaces/${workspaceId}/companies`, {
        method: "POST",
        body: JSON.stringify({
          name: quickCompanyName,
          project_ids: projectIds,
        }),
      });
      setQuickCompanyName("");
      setToast("Company added.");
      await refreshWorkspaceData();
    } catch (err) {
      setToast(err instanceof Error ? err.message : "Could not add company");
    } finally {
      setBusy(false);
    }
  }

  async function updateTaskStatus(taskId: string, status: "todo" | "doing" | "blocked" | "done") {
    const res = await api(`/api/tasks/${taskId}`, {
      method: "PATCH",
      body: JSON.stringify({ status }),
    });
    setSelectedMemory((current) => current?.item?.id === taskId ? { ...current, item: res.data } : current);
    await refreshWorkspaceData();
    setToast(status === "done" ? "Task completed." : `Task moved to ${status}.`);
  }

  async function updateMemoryItem(sectionId: string, itemId: string, payload: Record<string, unknown>) {
    const endpointBySection: Record<string, string> = {
      tasks: `/api/tasks/${itemId}`,
      meetings: `/api/meetings/${itemId}`,
      reports: `/api/reports/${itemId}`,
      workflows: `/api/workflows/${itemId}`,
      companies: `/api/companies/${itemId}`,
    };
    const endpoint = endpointBySection[sectionId];
    if (!endpoint) return;
    const res = await api(endpoint, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
    setSelectedMemory({ sectionId, item: res.data });
    await refreshWorkspaceData();
    setToast("Memory updated.");
  }

  async function openMemoryItem(sectionId: string, item: any) {
    if (!workspaceId) return;
    if (sectionId === "intel") {
      const projectId = item.project_id || item.id;
      const project = (state?.projects || []).find((candidate) => candidate.id === projectId);
      if (project) await openProject(project);
      return;
    }
    const query = activeProject ? `?project_id=${activeProject}` : "";
    const endpointBySection: Record<string, string> = {
      tasks: `/api/workspaces/${workspaceId}/tasks${query}`,
      meetings: `/api/workspaces/${workspaceId}/meetings${query}`,
      reports: `/api/workspaces/${workspaceId}/reports${query}`,
      workflows: `/api/workspaces/${workspaceId}/workflows${query}`,
      companies: `/api/workspaces/${workspaceId}/companies`,
    };
    try {
      const endpoint = endpointBySection[sectionId];
      if (!endpoint) {
        if (item.note_id || item.source_note_id) await openNote(item.note_id || item.source_note_id);
        return;
      }
      const res = await api(endpoint);
      const detail = (res.data || []).find((candidate: any) => candidate.id === item.id) || item;
      setSelectedMemory({ sectionId, item: detail });
    } catch {
      setSelectedMemory({ sectionId, item });
    }
  }

  async function openGraphNode(node: any) {
    if (node.kind === "note") {
      await openNote(node.id);
      return;
    }
    if (node.kind === "project") {
      const project = (state?.projects || []).find((candidate) => candidate.id === node.id);
      if (project) await openProject(project);
      return;
    }
    if (node.kind === "person") {
      const person = (state?.people || []).find((candidate) => candidate.id === node.id) || { id: node.id, name: node.title };
      await openPerson(person);
      return;
    }
    const sectionByKind: Record<string, string> = {
      task: "tasks",
      meeting: "meetings",
      report: "reports",
      workflow: "workflows",
      company: "companies",
    };
    const sectionId = sectionByKind[node.kind];
    if (sectionId) await openMemoryItem(sectionId, node);
  }

  async function openReviewQueue() {
    if (!workspaceId) {
      setReviewSheetOpen(true);
      return;
    }
    setReviewSheetOpen(true);
    try {
      const projectQuery = activeProject ? `?project_id=${activeProject}` : "";
      const res = await api(`/api/workspaces/${workspaceId}/review-queue${projectQuery}`);
      setReviewItems(Array.isArray(res.data) ? res.data : []);
    } catch (err) {
      setReviewItems(home?.pending_review || []);
      setToast(err instanceof Error ? err.message : "Could not load review queue");
    }
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
    setSelectedMemory(null);
    setSheetOpen(false);
    setHome(null);
    setMemoryGraph({ nodes: [], edges: [] });
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
    setSelectedMemory(null);
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

  async function generateProjectReport(project: any) {
    if (!project?.id) return;
    setBusy(true);
    try {
      const res = await api(`/api/projects/${project.id}/reports/generate`, {
        method: "POST",
        body: JSON.stringify({ variant: "full" }),
      });
      await refreshWorkspaceData();
      if (activeProject === project.id) await openProject(project);
      setActiveMemoryTab("reports");
      setSelectedMemory({ sectionId: "reports", item: res.data });
      setToast("Project report generated from memory.");
    } catch (err) {
      setToast(err instanceof Error ? err.message : "Could not generate report");
    } finally {
      setBusy(false);
    }
  }

  async function decideReview(reviewId: string, decision: "accept" | "reject") {
    await api(`/api/review-queue/${reviewId}/${decision}`, {
      method: "POST",
      body: JSON.stringify({}),
    });
    setReviewItems((current) => current.filter((item) => item.id !== reviewId));
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
  const visibleReviewItems = reviewSheetOpen ? reviewItems : dashboardReviewItems;
  const dashboardReviewCount = reviewCount || dashboardReviewItems.length;
  const dashboardFlagged = home?.flagged || [];
  const memorySearchResults = Array.isArray(searchMeta?.memory_results) ? searchMeta.memory_results : [];
  const dashboardNotes = home?.recent_notes?.length ? home.recent_notes : notes;
  const dashboardProjects = home?.recent_projects?.length
    ? home.recent_projects
    : (state?.projects || []).filter((project) => project.kind === "user");
  const dashboardPeople = home?.recent_people?.length ? home.recent_people : state?.people || [];
  const dashboardTitle = activeProjectRecord ? `${activeProjectRecord.name} dashboard` : "Dashboard";
  const openTasks = (home?.open_tasks?.length ? home.open_tasks : home?.tasks?.length ? home.tasks : dashboardNotes.filter((note) => note.note_kind === "task"));
  const upcomingReminders = ((home?.reminders?.length ? home.reminders : openTasks) || [])
    .filter((task) => (task.attention_at || task.remind_at || task.due_at) && task.status !== "done" && task.status !== "archived")
    .slice()
    .sort((a, b) => new Date(a.attention_at || a.remind_at || a.due_at).getTime() - new Date(b.attention_at || b.remind_at || b.due_at).getTime())
    .slice(0, 3);
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
  const workflows = home?.workflows || [];
  const companies = home?.companies || [];
  const projectIntelligence = home?.project_intelligence?.length
    ? home.project_intelligence
    : dashboardProjects.map((project) => ({
        ...project,
        title: project.name,
        subtitle: project.latest_signal || project.summary || (project.mention_count ? `${project.mention_count} captured memories` : "Waiting for enough project memory"),
      }));
  const graphKinds = ["note", "person", "project", "task", "meeting", "report", "workflow", "company"];
  const graphSummary = graphKinds
    .map((kind) => ({ kind, count: memoryGraph.nodes.filter((node) => node.kind === kind).length }))
    .filter((item) => item.count > 0);
  const graphFocusKind = selectedGraphKind || graphSummary[0]?.kind || null;
  const graphFocusNodes = graphFocusKind ? memoryGraph.nodes.filter((node) => node.kind === graphFocusKind).slice(0, 8) : [];
  const graphNodeByKey = new Map(memoryGraph.nodes.map((node) => [`${node.kind}:${node.id}`, node]));
  const graphPreviewNodes = memoryGraph.nodes.slice(0, 8);
  const graphPositions = [
    { x: 50, y: 50 },
    { x: 18, y: 20 },
    { x: 82, y: 20 },
    { x: 20, y: 78 },
    { x: 80, y: 78 },
    { x: 50, y: 16 },
    { x: 50, y: 84 },
    { x: 82, y: 52 },
  ];
  const graphPreviewLayouts = graphPreviewNodes.map((node, index) => ({
    ...node,
    layoutKey: `${node.kind}:${node.id}`,
    x: graphPositions[index % graphPositions.length].x,
    y: graphPositions[index % graphPositions.length].y,
  }));
  const graphPreviewLayoutByKey = new Map(graphPreviewLayouts.map((node) => [node.layoutKey, node]));
  const graphPreviewEdges = memoryGraph.edges
    .map((edge) => ({
      ...edge,
      from: graphNodeByKey.get(`${edge.from_kind}:${edge.from_id}`),
      to: graphNodeByKey.get(`${edge.to_kind}:${edge.to_id}`),
      fromLayout: graphPreviewLayoutByKey.get(`${edge.from_kind}:${edge.from_id}`),
      toLayout: graphPreviewLayoutByKey.get(`${edge.to_kind}:${edge.to_id}`),
    }))
    .filter((edge) => edge.fromLayout && edge.toLayout)
    .slice(0, 12);
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
      id: "workflows",
      title: "Workflows",
      icon: Workflow,
      items: workflows,
      empty: "No workflows yet. Group recurring loops across notes, people, and tasks.",
    },
    {
      id: "companies",
      title: "Companies",
      icon: Building2,
      items: companies,
      empty: "Companies will appear once contacts and projects start linking to organizations.",
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
  const showExplorerGrid = Boolean(query.trim() || personTimeline || projectTimeline);

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
        <button className={`nav-item ${!activeProject ? "active" : ""}`} onClick={() => { setActiveProject(null); setSelectedProjectIds([]); setPersonTimeline(null); setProjectTimeline(null); setSelectedMemory(null); }}>
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
                {activeProjectRecord && (
                  <button type="button" onClick={() => generateProjectReport(activeProjectRecord)} disabled={busy}>
                    <FileText size={16} /> Generate report
                  </button>
                )}
                <button type="button" onClick={openReviewQueue}>
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
              <button className="metric-card metric-button" type="button" onClick={openReviewQueue} aria-label={`Open review queue with ${dashboardReviewCount} items`}>
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
                {activeMemorySection.id === "tasks" && (
                  <div className="quick-task-row task-create-row">
                    <input
                      value={quickTaskTitle}
                      onChange={(event) => setQuickTaskTitle(event.target.value)}
                      placeholder={activeProjectRecord ? `Task for ${activeProjectRecord.name}` : "Add an open loop"}
                      aria-label="New task"
                    />
                    <input
                      type="date"
                      value={quickTaskDue}
                      onChange={(event) => setQuickTaskDue(event.target.value)}
                      aria-label="Task due date"
                    />
                    <button type="button" onClick={createQuickTask} disabled={busy || !quickTaskTitle.trim()}>
                      <Plus size={16} /> Add task
                    </button>
                  </div>
                )}
                {activeMemorySection.id === "meetings" && (
                  <div className="quick-task-row task-create-row">
                    <input
                      value={quickMeetingTitle}
                      onChange={(event) => setQuickMeetingTitle(event.target.value)}
                      placeholder={activeProjectRecord ? `Meeting for ${activeProjectRecord.name}` : "Add a meeting or call"}
                      aria-label="New meeting"
                    />
                    <input
                      type="date"
                      value={quickMeetingDate}
                      onChange={(event) => setQuickMeetingDate(event.target.value)}
                      aria-label="Meeting date"
                    />
                    <button type="button" onClick={createQuickMeeting} disabled={busy || !quickMeetingTitle.trim()}>
                      <Plus size={16} /> Add meeting
                    </button>
                  </div>
                )}
                {activeMemorySection.id === "reports" && (
                  <div className="quick-task-row">
                    <input
                      value={quickReportTitle}
                      onChange={(event) => setQuickReportTitle(event.target.value)}
                      placeholder={activeProjectRecord ? `Report for ${activeProjectRecord.name}` : "Start a report or brief"}
                      aria-label="New report"
                    />
                    <button type="button" onClick={createQuickReport} disabled={busy || !quickReportTitle.trim()}>
                      <Plus size={16} /> Add report
                    </button>
                  </div>
                )}
                {activeMemorySection.id === "workflows" && (
                  <div className="quick-task-row">
                    <input
                      value={quickWorkflowName}
                      onChange={(event) => setQuickWorkflowName(event.target.value)}
                      placeholder={activeProjectRecord ? `Workflow in ${activeProjectRecord.name}` : "Add a workflow"}
                      aria-label="New workflow"
                    />
                    <button type="button" onClick={createQuickWorkflow} disabled={busy || !quickWorkflowName.trim()}>
                      <Plus size={16} /> Add workflow
                    </button>
                  </div>
                )}
                {activeMemorySection.id === "companies" && (
                  <div className="quick-task-row">
                    <input
                      value={quickCompanyName}
                      onChange={(event) => setQuickCompanyName(event.target.value)}
                      placeholder={activeProjectRecord ? `Company in ${activeProjectRecord.name}` : "Add a company"}
                      aria-label="New company"
                    />
                    <button type="button" onClick={createQuickCompany} disabled={busy || !quickCompanyName.trim()}>
                      <Plus size={16} /> Add company
                    </button>
                  </div>
                )}
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
                        onOpenMemory={openMemoryItem}
                        onTaskStatusChange={updateTaskStatus}
                      />
                    ))
                  ) : (
                    <p className="dashboard-empty memory-empty">{activeMemorySection.empty}</p>
                  )}
                </div>
              </section>

              <section className="dashboard-panel memory-map-panel">
                <div className="panel-head">
                  <h2>Memory map</h2>
                  <Workflow size={18} />
                </div>
                {memoryGraph.nodes.length ? (
                  <>
                    <div className="graph-canvas" role="group" aria-label="Interactive memory graph">
                      <svg className="graph-edge-svg" aria-hidden="true" viewBox="0 0 100 100" preserveAspectRatio="none">
                        {graphPreviewEdges.map((edge, index) => {
                          const fromLayout = edge.fromLayout!;
                          const toLayout = edge.toLayout!;
                          return (
                            <g key={`line-${edge.from_kind}-${edge.from_id}-${edge.to_kind}-${edge.to_id}-${index}`}>
                              <line x1={fromLayout.x} y1={fromLayout.y} x2={toLayout.x} y2={toLayout.y} />
                              <text x={(fromLayout.x + toLayout.x) / 2} y={(fromLayout.y + toLayout.y) / 2}>
                                {edge.relation}
                              </text>
                            </g>
                          );
                        })}
                      </svg>
                      {graphPreviewLayouts.map((node) => (
                        <button
                          key={`preview-${node.kind}-${node.id}`}
                          type="button"
                          className={`graph-node graph-node-${node.kind}`}
                          style={{ left: `${node.x}%`, top: `${node.y}%` }}
                          onClick={() => openGraphNode(node)}
                          aria-label={`Open ${node.kind} ${node.title || node.name || node.id}`}
                        >
                          <span>{node.kind}</span>
                          <strong>{node.title || node.name || node.id}</strong>
                        </button>
                      ))}
                    </div>
                    <div className="graph-kind-grid">
                      {graphSummary.map((item) => (
                        <button
                          key={item.kind}
                          type="button"
                          className={graphFocusKind === item.kind ? "active" : ""}
                          onClick={() => setSelectedGraphKind(item.kind)}
                        >
                          <strong>{item.count}</strong>
                          {item.kind}
                        </button>
                      ))}
                    </div>
                    {!!graphFocusNodes.length && (
                      <div className="graph-node-list">
                        {graphFocusNodes.map((node) => (
                          <button key={`${node.kind}-${node.id}`} type="button" onClick={() => openGraphNode(node)}>
                            <span>{node.title || node.name || node.id}</span>
                            <small>{node.status || node.note_kind || node.domain || node.kind}</small>
                          </button>
                        ))}
                      </div>
                    )}
                    <div className="graph-edge-list">
                      {graphPreviewEdges.map((edge, index) => (
                        <span key={`${edge.from_kind}-${edge.from_id}-${edge.to_kind}-${edge.to_id}-${index}`}>
                          {edge.from?.title || edge.from?.name || edge.from_kind} <strong>{edge.relation}</strong> {edge.to?.title || edge.to?.name || edge.to_kind}
                        </span>
                      ))}
                    </div>
                  </>
                ) : (
                  <p className="dashboard-empty">Links appear here once notes connect to people, projects, tasks, meetings, reports, workflows, or companies.</p>
                )}
              </section>

              <section className="dashboard-panel attention-panel">
                <div className="panel-head">
                  <h2>Needs attention</h2>
                  <Bell size={18} />
                </div>
                {dashboardReviewItems.length || dashboardFlagged.length || upcomingReminders.length ? (
                  <div className="dashboard-list">
                    {upcomingReminders.map((task) => (
                      <button key={`reminder-${task.id}`} className="dashboard-row" type="button" onClick={() => openMemoryItem("tasks", task)}>
                        <span className="row-icon"><CalendarDays size={15} /></span>
                        <span>
                          <strong>{task.title}</strong>
                          <small>Reminder due {new Date(task.attention_at || task.remind_at || task.due_at).toLocaleDateString()}</small>
                        </span>
                      </button>
                    ))}
                    {dashboardReviewItems.slice(0, 3).map((item) => (
                      <button key={item.id} className="dashboard-row" type="button" onClick={openReviewQueue}>
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

        {!quickCapture && showExplorerGrid && (
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
              {!!query.trim() && !!memorySearchResults.length && (
                <div className="memory-search-strip">
                  <div className="section-head">
                    <h2>Memory matches</h2>
                    <Search size={18} />
                  </div>
                  <div className="memory-search-grid">
                    {memorySearchResults.slice(0, 6).map((item: any) => (
                      <button key={`${item.kind}-${item.id}`} type="button" onClick={() => openGraphNode(item)}>
                        <span>{item.kind}</span>
                        <strong>{item.title}</strong>
                        {item.subtitle && <small>{item.subtitle}</small>}
                      </button>
                    ))}
                  </div>
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
                  onOpenMemory={openMemoryItem}
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
                  onOpenMemory={openMemoryItem}
                  onCopy={() => copyBrief("project", projectTimeline.project)}
                  onFlag={() => flag({ project_id: projectTimeline.project.id })}
                  onMerge={mergePerson}
                  inviteEmail={inviteEmail}
                  onInviteEmailChange={setInviteEmail}
                  onInvite={inviteProjectMember}
                  onGenerateReport={generateProjectReport}
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
        items={visibleReviewItems}
        reviewCount={reviewCount}
        onClose={() => setReviewSheetOpen(false)}
        onDecide={decideReview}
      />

      <MemoryDetailSheet
        memory={selectedMemory}
        onClose={() => setSelectedMemory(null)}
        onTaskStatusChange={updateTaskStatus}
        onUpdateMemory={updateMemoryItem}
        onOpenNote={openNote}
        onOpenProject={(projectId) => {
          const project = (state?.projects || []).find((candidate) => candidate.id === projectId);
          if (project) openProject(project);
        }}
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
        onReviewDecision={async (reviewId, decision) => {
          await decideReview(reviewId, decision);
          if (selectedNote) await openNote(selectedNote.id);
        }}
        onSuggestionQueued={() => setToast("Suggestion sent to Review.")}
        onOpenMemory={openMemoryItem}
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
  onOpenMemory,
  onTaskStatusChange,
}: {
  item: any;
  sectionId: string;
  onOpenNote: (noteId: string) => Promise<void>;
  onOpenProject: (projectId: string) => void;
  onOpenMemory: (sectionId: string, item: any) => Promise<void>;
  onTaskStatusChange: (taskId: string, status: "todo" | "doing" | "blocked" | "done") => Promise<void>;
}) {
  const title = item.title || item.label || item.name || item.project_name || "Untitled memory";
  const subtitle = item.subtitle || item.summary || item.description || item.body || item.status || item.next_step || "Awaiting more context";
  const people = item.people || [];
  const owner = item.owner_name || item.assignee_name || people[0]?.name || item.person_name || item.company || item.kind || NOTE_KIND_LABELS[item.note_kind || ""] || "Memory";
  const date = item.due_at || item.due_date || item.occurred_at || item.created_at || item.updated_at;
  const noteId = item.note_id || (sectionId !== "intel" ? item.id : null);
  const projectId = item.project_id || (sectionId === "intel" ? item.id : null);
  const isTask = sectionId === "tasks";
  const canOpen = Boolean(isTask || noteId || projectId || ["meetings", "reports", "workflows", "companies"].includes(sectionId));
  async function open() {
    if (["tasks", "meetings", "reports", "workflows", "companies"].includes(sectionId)) {
      await onOpenMemory(sectionId, item);
      return;
    }
    if (noteId) {
      await onOpenNote(noteId);
      return;
    }
    if (projectId) onOpenProject(projectId);
  }
  return (
    <article
      className="memory-card"
      role={canOpen ? "button" : undefined}
      tabIndex={canOpen ? 0 : -1}
      onClick={() => {
        if (canOpen) open();
      }}
      onKeyDown={(event) => {
        if (canOpen && (event.key === "Enter" || event.key === " ")) {
          event.preventDefault();
          open();
        }
      }}
    >
      <span className="memory-card-meta">
        <strong>{owner}</strong>
        {date && <small>{new Date(date).toLocaleDateString()}</small>}
      </span>
      <span className="memory-card-title">{title}</span>
      <span className="memory-card-body">{subtitle}</span>
      {isTask && (
        <span className="task-card-actions" onClick={(event) => event.stopPropagation()}>
          {item.status !== "doing" && item.status !== "done" && (
            <button type="button" onClick={() => onTaskStatusChange(item.id, "doing")}>Doing</button>
          )}
          {item.status !== "blocked" && item.status !== "done" && (
            <button type="button" onClick={() => onTaskStatusChange(item.id, "blocked")}>Block</button>
          )}
          {item.status !== "done" ? (
            <button type="button" aria-label="Mark task done" onClick={() => onTaskStatusChange(item.id, "done")}><CheckCircle2 size={14} /> Done</button>
          ) : (
            <button type="button" onClick={() => onTaskStatusChange(item.id, "todo")}>Reopen</button>
          )}
        </span>
      )}
    </article>
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
  const reviewItems = Array.isArray(items) ? items : [];
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
          {reviewItems.slice(0, 5).map((item) => (
            <article key={item.id}>
              <strong>{item.payload?.name || item.payload?.title || item.entity_kind}</strong>
              <span>
                {item.entity_kind}
                {item.payload?.confidence || item.confidence ? ` - ${Math.round(Number(item.payload?.confidence || item.confidence) * 100)}%` : ""}
              </span>
              {item.source_note_title && <small>{item.source_note_title}</small>}
              {item.source_snippet && <p>{item.source_snippet}</p>}
              {!!item.projects?.length && (
                <div className="review-projects">
                  {item.projects.slice(0, 3).map((project: any) => (
                    <span key={project.id}>
                      <span className="dot" style={{ background: project.color_hex || "#7c3aed" }} />
                      {project.name}
                    </span>
                  ))}
                </div>
              )}
              <div>
                <button onClick={() => onDecide(item.id, "accept")}><Check size={15} /> Accept</button>
                <button onClick={() => onDecide(item.id, "reject")}><X size={15} /> Reject</button>
              </div>
            </article>
          ))}
          {!reviewItems.length && <p className="muted">Caught up.</p>}
        </div>
      </aside>
    </div>
  );
}

function MemoryDetailSheet({
  memory,
  onClose,
  onTaskStatusChange,
  onUpdateMemory,
  onOpenNote,
  onOpenProject,
}: {
  memory: { sectionId: string; item: any } | null;
  onClose: () => void;
  onTaskStatusChange: (taskId: string, status: "todo" | "doing" | "blocked" | "done") => Promise<void>;
  onUpdateMemory: (sectionId: string, itemId: string, payload: Record<string, unknown>) => Promise<void>;
  onOpenNote: (noteId: string) => Promise<void>;
  onOpenProject: (projectId: string) => void;
}) {
  const sectionId = memory?.sectionId || "";
  const item = memory?.item || {};
  const title = item.title || item.name || "Memory";
  const body = item.description || item.summary || item.body || item.subtitle || "";
  const [draftTitle, setDraftTitle] = useState(title);
  const [draftBody, setDraftBody] = useState(body);
  const [draftStatus, setDraftStatus] = useState(item.status || "");
  const [draftDate, setDraftDate] = useState(inputDate(item.due_at || item.occurred_at || null));
  useEffect(() => {
    setDraftTitle(title);
    setDraftBody(body);
    setDraftStatus(item.status || "");
    setDraftDate(inputDate(item.due_at || item.occurred_at || null));
  }, [body, item.due_at, item.id, item.occurred_at, item.status, title]);
  if (!memory) return null;
  const projects = item.projects || [];
  const people = item.people || [];
  const notes = item.notes || [];
  const tasks = item.tasks || [];
  const companies = item.companies || [];
  const sourceCounts = item.source_counts || null;
  const isTask = sectionId === "tasks";
  const sourceNoteFallback = Boolean(item.note_id && item.id === item.note_id && ["meetings", "reports"].includes(sectionId));
  const canEdit = ["tasks", "meetings", "reports", "workflows", "companies"].includes(sectionId) && !sourceNoteFallback;
  async function saveEdits() {
    if (!canEdit || !item.id || !draftTitle.trim()) return;
    const payload: Record<string, unknown> = {};
    if (sectionId === "workflows") payload.name = draftTitle.trim();
    else payload.title = draftTitle.trim();
    if (sectionId === "companies") payload.description = draftBody || null;
    if (sectionId === "tasks") {
      payload.description = draftBody || null;
      payload.due_at = eventDate(draftDate);
      if (draftStatus) payload.status = draftStatus;
    }
    if (sectionId === "meetings") {
      payload.summary = draftBody || null;
      payload.occurred_at = eventDate(draftDate);
    }
    if (sectionId === "reports") {
      payload.body = draftBody || null;
      if (draftStatus) payload.status = draftStatus;
    }
    if (sectionId === "workflows") {
      payload.description = draftBody || null;
      if (draftStatus) payload.status = draftStatus;
    }
    await onUpdateMemory(sectionId, item.id, payload);
  }
  const kindLabel: Record<string, string> = {
    tasks: "Task",
    meetings: "Meeting/call",
    reports: "Report/brief",
    workflows: "Workflow",
    companies: "Company",
  };
  return (
    <div className="sheet-backdrop" onClick={onClose}>
      <aside className="linked-sheet memory-detail-sheet" onClick={(event) => event.stopPropagation()}>
        <div className="sheet-handle" />
        <div className="section-head">
          <h2>{title}</h2>
          <button className="icon-btn" onClick={onClose} aria-label="Close memory">
            <X size={18} />
          </button>
        </div>
        <div className="note-meta-row">
          <span>{kindLabel[sectionId] || "Memory"}</span>
          {item.status && <span>{item.status}</span>}
          {(item.due_at || item.occurred_at || item.created_at) && <span>{new Date(item.due_at || item.occurred_at || item.created_at).toLocaleDateString()}</span>}
          {typeof item.generation_confidence === "number" && <span>{Math.round(item.generation_confidence * 100)}% grounded</span>}
        </div>
        {sourceCounts && (
          <div className="source-count-grid" aria-label="Report sources">
            {Object.entries(sourceCounts).map(([key, value]) => (
              <span key={key}>
                <strong>{String(value)}</strong>
                {key}
              </span>
            ))}
          </div>
        )}
        {canEdit && (
          <div className="memory-edit-grid">
            <input value={draftTitle} onChange={(event) => setDraftTitle(event.target.value)} aria-label="Memory title" />
            {(isTask || sectionId === "meetings") && (
              <input type="date" value={draftDate} onChange={(event) => setDraftDate(event.target.value)} aria-label="Memory date" />
            )}
            {(isTask || sectionId === "reports" || sectionId === "workflows") && (
              <select value={draftStatus} onChange={(event) => setDraftStatus(event.target.value)} aria-label="Memory status">
                {isTask && ["todo", "doing", "blocked", "done", "archived"].map((status) => <option key={status} value={status}>{status}</option>)}
                {sectionId === "reports" && ["draft", "published", "archived"].map((status) => <option key={status} value={status}>{status}</option>)}
                {sectionId === "workflows" && ["draft", "active", "paused", "retired"].map((status) => <option key={status} value={status}>{status}</option>)}
              </select>
            )}
            <textarea value={draftBody} onChange={(event) => setDraftBody(event.target.value)} rows={4} aria-label="Memory body" />
            <button type="button" onClick={saveEdits} disabled={!draftTitle.trim()}>
              <Check size={15} /> Save memory
            </button>
          </div>
        )}
        {!canEdit && body && <p>{body}</p>}
        {isTask && (
          <div className="memory-status-actions">
            <button disabled={item.status === "todo"} onClick={() => onTaskStatusChange(item.id, "todo")}>Todo</button>
            <button disabled={item.status === "doing"} onClick={() => onTaskStatusChange(item.id, "doing")}>Doing</button>
            <button disabled={item.status === "blocked"} onClick={() => onTaskStatusChange(item.id, "blocked")}>Blocked</button>
            <button disabled={item.status === "done"} onClick={() => onTaskStatusChange(item.id, "done")}><CheckCircle2 size={15} /> Done</button>
          </div>
        )}
        {!!projects.length && (
          <div className="mini-section">
            <strong>Projects</strong>
            {projects.map((project: any) => (
              <button key={project.id} type="button" onClick={() => onOpenProject(project.id)}>
                <span className="dot" style={{ background: project.color_hex || "#7c3aed" }} />
                {project.name}
              </button>
            ))}
          </div>
        )}
        {!!people.length && (
          <div className="mini-section">
            <strong>People</strong>
            {people.map((person: any) => (
              <span key={`${person.id}-${person.relation || person.attendance_status || "person"}`}>
                {[person.name, person.role || person.relation || person.attendance_status, person.company].filter(Boolean).join(" - ")}
              </span>
            ))}
          </div>
        )}
        {!!companies.length && (
          <div className="mini-section">
            <strong>Companies</strong>
            {companies.map((company: any) => (
              <span key={company.id}>{[company.name, company.domain].filter(Boolean).join(" - ")}</span>
            ))}
          </div>
        )}
        {!!tasks.length && (
          <div className="timeline-list">
            {tasks.slice(0, 5).map((task: any) => (
              <article key={task.id}>
                <strong>{task.title}</strong>
                <span>{task.status || "todo"}{task.due_at ? ` - due ${new Date(task.due_at).toLocaleDateString()}` : ""}</span>
                {task.description && <p>{task.description}</p>}
              </article>
            ))}
          </div>
        )}
        {!!notes.length && (
          <div className="timeline-list">
            {notes.slice(0, 5).map((note: any) => (
              <article key={note.id} onClick={() => onOpenNote(note.id)}>
                <strong>{note.title}</strong>
                <span>{NOTE_KIND_LABELS[note.note_kind || "note"] || "Note"} - {new Date(note.occurred_at || note.created_at).toLocaleDateString()}</span>
                <p>{note.body}</p>
              </article>
            ))}
          </div>
        )}
        {(item.source_note_id || item.note_id) && !notes.length && (
          <div className="sheet-actions">
            <button onClick={() => onOpenNote(item.source_note_id || item.note_id)}>
              <FileText size={16} /> Source note
            </button>
          </div>
        )}
      </aside>
    </div>
  );
}

function TimelinePanel({
  timeline,
  kind,
  people,
  onOpenNote,
  onOpenMemory,
  onCopy,
  onFlag,
  onMerge,
  inviteEmail = "",
  onInviteEmailChange,
  onInvite,
  onGenerateReport,
  onBack,
}: {
  timeline: any;
  kind: "person" | "project";
  people: any[];
  onOpenNote: (noteId: string) => Promise<void>;
  onOpenMemory: (sectionId: string, item: any) => Promise<void>;
  onCopy: () => void;
  onFlag: () => void;
  onMerge: (sourcePersonId: string, targetPersonId: string) => Promise<void>;
  inviteEmail?: string;
  onInviteEmailChange?: (email: string) => void;
  onInvite?: (project: any, email: string) => Promise<void>;
  onGenerateReport?: (project: any) => Promise<void>;
  onBack: () => void;
}) {
  const [mergeTargetId, setMergeTargetId] = useState("");
  const notes = timeline.notes || [];
  const events = Array.isArray(timeline.events) && timeline.events.length
    ? timeline.events
    : notes.map((note: any) => ({
        id: note.id,
        note_id: note.id,
        kind: "note",
        section_id: "notes",
        title: note.title,
        subtitle: note.body,
        status: note.note_kind || "note",
        event_at: note.occurred_at || note.created_at,
      }));
  const profile = timeline.profile || {};
  const profileStats = kind === "project"
    ? [
        ["Memory", profile.memory_count],
        ["Open loops", profile.open_loop_count],
        ["Blocked", profile.blocked_count],
        ["People", profile.people_count],
        ["Meetings", profile.meeting_count],
        ["Reports", profile.report_count],
      ]
    : [
        ["Open loops", profile.open_loop_count],
        ["Blocked", profile.blocked_count],
        ["Projects", profile.project_count],
        ["Meetings", profile.meeting_count],
        ["Reports", profile.report_count],
      ];
  return (
    <div className="timeline-panel">
      <div className="timeline-actions">
        <button onClick={onCopy}><Copy size={16} /> Brief</button>
        <button onClick={onFlag}><Flag size={16} /> Flag</button>
        {kind === "project" && onGenerateReport && (
          <button onClick={() => onGenerateReport(timeline.project)}><FileText size={16} /> Generate report</button>
        )}
        <button onClick={onBack}><X size={16} /> Close</button>
      </div>
      <div className="memory-profile-card">
        <div>
          <span>{kind === "project" ? "Project profile" : "Person profile"}</span>
          <strong>{profile.headline || (kind === "project" ? timeline.project?.name : timeline.person?.name)}</strong>
          <small>
            {profile.last_touch_at ? `Last touch ${new Date(profile.last_touch_at).toLocaleDateString()}` : "No dated touch yet"}
            {profile.next_action ? ` - Next: ${profile.next_action}` : ""}
          </small>
        </div>
        <div className="profile-stat-grid">
          {profileStats.map(([label, value]) => (
            <span key={label}>
              <strong>{Number(value || 0)}</strong>
              {label}
            </span>
          ))}
        </div>
        {!!profile.companies?.length && <p>{profile.companies.join(" - ")}</p>}
        {!!profile.top_projects?.length && <p>{profile.top_projects.join(" - ")}</p>}
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
      {!!timeline.companies?.length && (
        <div className="mini-section">
          <strong>Companies</strong>
          {timeline.companies.slice(0, 5).map((company: any) => (
            <span key={company.id}>{company.name}{company.role ? ` - ${company.role}` : ""}</span>
          ))}
        </div>
      )}
      {!!timeline.tasks?.length && (
        <div className="mini-section">
          <strong>Tasks</strong>
          {timeline.tasks.slice(0, 6).map((task: any) => (
            <span key={task.id}>{task.status} - {task.title}{task.assignee_name ? ` - ${task.assignee_name}` : ""}</span>
          ))}
        </div>
      )}
      {!!timeline.meetings?.length && (
        <div className="mini-section">
          <strong>Meetings/calls</strong>
          {timeline.meetings.slice(0, 4).map((meeting: any) => (
            <span key={meeting.id}>{meeting.title}</span>
          ))}
        </div>
      )}
      {!!timeline.reports?.length && (
        <div className="mini-section">
          <strong>Reports</strong>
          {timeline.reports.slice(0, 4).map((report: any) => (
            <span key={report.id}>{report.title}</span>
          ))}
        </div>
      )}
      {!!timeline.workflows?.length && (
        <div className="mini-section">
          <strong>Workflows</strong>
          {timeline.workflows.slice(0, 4).map((workflow: any) => (
            <span key={workflow.id}>{workflow.name} - {workflow.status}</span>
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
      <div className="timeline-event-list" aria-label="Interaction history">
        <strong>Interaction history</strong>
        {events.map((event: any) => (
          <button
            key={`${event.kind}-${event.id}`}
            type="button"
            onClick={() => {
              if (event.kind === "note" || event.section_id === "notes") {
                onOpenNote(event.note_id || event.id);
                return;
              }
              onOpenMemory(event.section_id, event);
            }}
          >
            <span className={`event-kind event-kind-${event.kind}`}>{event.kind}</span>
            <span>
              <strong>{event.title}</strong>
              <small>
                {[event.status, event.project_name || event.person_name, event.event_at ? new Date(event.event_at).toLocaleDateString() : null]
                  .filter(Boolean)
                  .join(" - ")}
              </small>
              {event.subtitle && <p>{event.subtitle}</p>}
            </span>
          </button>
        ))}
        {!events.length && <p className="muted">No interaction history yet.</p>}
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
  onReviewDecision,
  onSuggestionQueued,
  onOpenMemory,
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
  onReviewDecision: (reviewId: string, decision: "accept" | "reject") => Promise<void>;
  onSuggestionQueued: () => void;
  onOpenMemory: (sectionId: string, item: any) => Promise<void>;
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
  const structuredMemories = Array.isArray(note.memory_links) ? note.memory_links : [];
  const suggestions = Array.isArray(note.review_suggestions) ? note.review_suggestions : [];
  const memoryCounts = structuredMemories.reduce((counts: Record<string, number>, memory: any) => {
    const key = memory.kind || "memory";
    counts[key] = (counts[key] || 0) + 1;
    return counts;
  }, {});
  const memoryCountLabel = Object.entries(memoryCounts)
    .map(([kind, count]) => `${count} ${kind}${count === 1 ? "" : "s"}`)
    .join(" / ");
  const aiStatusLabel: Record<string, string> = {
    processed: "Processed",
    processing: "Processing",
    pending: "Queued",
    queued: "Queued",
    failed: "Failed",
    skipped: "Manual",
  };

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

  async function decideSuggestions(decision: "accept" | "reject") {
    for (const suggestion of suggestions) {
      await onReviewDecision(suggestion.id, decision);
    }
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
        <div className="memory-workbench" aria-label="Memory workbench">
          <span>
            <Sparkles size={15} />
            <strong>{aiStatusLabel[note.ai_processing_status] || "Captured"}</strong>
            AI
          </span>
          <span>
            <Lightbulb size={15} />
            <strong>{suggestions.length}</strong>
            Review
          </span>
          <span>
            <Workflow size={15} />
            <strong>{structuredMemories.length}</strong>
            Graph
          </span>
          <span>
            <Users size={15} />
            <strong>{(note.people || []).length}/{(note.projects || []).length}</strong>
            Links
          </span>
          {memoryCountLabel && <small>{memoryCountLabel}</small>}
        </div>
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
          {note.ai_processing_status === "failed" && <span className="chip danger-chip">AI failed</span>}
        </div>
        {note.ai_processing_status === "failed" && note.ai_processing_error && (
          <div className="ai-error">
            <strong>AI processing failed</strong>
            <span>{note.ai_processing_error}</span>
          </div>
        )}
        {!!suggestions.length && (
          <div className="suggestion-panel">
            <div className="suggestion-head">
              <strong>AI suggestions</strong>
              {suggestions.length > 1 && (
                <span className="suggestion-bulk">
                  <button type="button" onClick={() => decideSuggestions("accept")}><Check size={15} /> Accept all</button>
                  <button type="button" onClick={() => decideSuggestions("reject")}><X size={15} /> Reject all</button>
                </span>
              )}
            </div>
            {suggestions.map((suggestion: any) => (
              <article key={suggestion.id}>
                <span>
                  {suggestion.entity_kind}
                  {suggestion.payload?.confidence ? ` - ${Math.round(Number(suggestion.payload.confidence) * 100)}%` : ""}
                </span>
                <p>{suggestion.payload?.name || suggestion.payload?.title || suggestion.reason}</p>
                <div>
                  <button type="button" onClick={() => onReviewDecision(suggestion.id, "accept")}><Check size={15} /> Accept</button>
                  <button type="button" onClick={() => onReviewDecision(suggestion.id, "reject")}><X size={15} /> Reject</button>
                </div>
              </article>
            ))}
          </div>
        )}
        {!!structuredMemories.length && (
          <div className="structured-memory-panel">
            <strong>Structured memory from this note</strong>
            <div>
              {structuredMemories.map((memory: any) => (
                <button
                  key={`${memory.kind}-${memory.id}`}
                  type="button"
                  onClick={() => onOpenMemory(memory.section_id, memory)}
                >
                  <span>{memory.kind}</span>
                  <strong>{memory.title}</strong>
                  {(memory.status || memory.subtitle) && (
                    <small>{[memory.status, memory.subtitle].filter(Boolean).join(" - ")}</small>
                  )}
                </button>
              ))}
            </div>
          </div>
        )}
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
