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
  Download,
  FileText,
  Flag,
  Inbox,
  Lightbulb,
  Link,
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

type PipelineCounts = {
  received: number;
  processing: number;
  needs_review: number;
  accepted: number;
  failed: number;
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
  pipeline_counts?: PipelineCounts;
  pipeline_recent_failed?: any[];
  pipeline_recent_received?: any[];
  loose_ends?: {
    notes_without_project?: any[];
    tasks_without_owner?: any[];
    people_without_company?: any[];
    stale_reviews_count?: number;
  };
  today_counts?: {
    new_notes?: number;
    tasks_done?: number;
    reviews_accepted?: number;
  };
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

type RouteTarget = {
  kind: "dashboard" | "project" | "person" | "note" | "task" | "meeting" | "report" | "workflow" | "company";
  id?: string | null;
};

type MemoryBriefKind = "task" | "meeting" | "report" | "workflow" | "company";
type MemoryRouteKind = MemoryBriefKind;

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
const STRUCTURED_REVIEW_KINDS = new Set(["task", "meeting", "report", "workflow", "company"]);
const MEMORY_ROUTE_PATHS: Record<MemoryRouteKind, string> = {
  task: "tasks",
  meeting: "meetings",
  report: "reports",
  workflow: "workflows",
  company: "companies",
};
const MEMORY_ROUTE_TO_SECTION: Record<MemoryRouteKind, string> = {
  task: "tasks",
  meeting: "meetings",
  report: "reports",
  workflow: "workflows",
  company: "companies",
};
const SECTION_TO_MEMORY_ROUTE: Record<string, MemoryRouteKind> = {
  tasks: "task",
  meetings: "meeting",
  reports: "report",
  workflows: "workflow",
  companies: "company",
};
const STRUCTURED_REVIEW_FIELDS: Record<string, { key: string; label: string; multiline?: boolean }[]> = {
  task: [
    { key: "title", label: "Task title" },
    { key: "status", label: "Task status" },
    { key: "due_at", label: "Task due date" },
    { key: "assignee_name", label: "Task assignee" },
    { key: "summary", label: "Task summary", multiline: true },
  ],
  meeting: [
    { key: "title", label: "Meeting title" },
    { key: "occurred_at", label: "Meeting date" },
    { key: "attendees", label: "Meeting attendees" },
    { key: "summary", label: "Meeting summary", multiline: true },
  ],
  report: [
    { key: "title", label: "Report title" },
    { key: "status", label: "Report status" },
    { key: "period_start", label: "Report period start" },
    { key: "period_end", label: "Report period end" },
    { key: "summary", label: "Report summary", multiline: true },
  ],
  workflow: [
    { key: "name", label: "Workflow name" },
    { key: "status", label: "Workflow status" },
    { key: "owner_name", label: "Workflow owner" },
    { key: "description", label: "Workflow description", multiline: true },
  ],
  company: [
    { key: "name", label: "Company name" },
    { key: "domain", label: "Company domain" },
    { key: "role", label: "Company role" },
    { key: "summary", label: "Company summary", multiline: true },
  ],
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

function decodeRouteId(value?: string) {
  if (!value) return null;
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}

function routeFromPath(pathname: string, search = ""): RouteTarget {
  const parts = pathname.split("/").filter(Boolean);
  if (parts[0] === "projects" && parts[1]) return { kind: "project", id: decodeRouteId(parts[1]) };
  if (parts[0] === "people" && parts[1]) return { kind: "person", id: decodeRouteId(parts[1]) };
  if (parts[0] === "notes" && parts[1]) return { kind: "note", id: decodeRouteId(parts[1]) };
  for (const [kind, path] of Object.entries(MEMORY_ROUTE_PATHS)) {
    if (parts[0] === path && parts[1]) return { kind: kind as MemoryRouteKind, id: decodeRouteId(parts[1]) };
  }
  const params = new URLSearchParams(search);
  if (params.get("project_id")) return { kind: "project", id: params.get("project_id") };
  if (params.get("person_id")) return { kind: "person", id: params.get("person_id") };
  if (params.get("note_id")) return { kind: "note", id: params.get("note_id") };
  for (const kind of Object.keys(MEMORY_ROUTE_PATHS) as MemoryRouteKind[]) {
    const id = params.get(`${kind}_id`);
    if (id) return { kind, id };
  }
  return { kind: "dashboard" };
}

function initialRouteTarget(initialRoute?: RouteTarget): RouteTarget {
  if (initialRoute?.kind && initialRoute.kind !== "dashboard") return initialRoute;
  if (typeof window === "undefined") return initialRoute || { kind: "dashboard" };
  return routeFromPath(window.location.pathname, window.location.search);
}

function routePath(target: RouteTarget) {
  if (target.kind === "project" && target.id) return `/projects/${encodeURIComponent(target.id)}`;
  if (target.kind === "person" && target.id) return `/people/${encodeURIComponent(target.id)}`;
  if (target.kind === "note" && target.id) return `/notes/${encodeURIComponent(target.id)}`;
  if (isMemoryRouteKind(target.kind) && target.id) return `/${MEMORY_ROUTE_PATHS[target.kind]}/${encodeURIComponent(target.id)}`;
  return "/";
}

function routeKey(target: RouteTarget) {
  return `${target.kind}:${target.id || ""}`;
}

function memoryBriefKind(sectionId: string): MemoryBriefKind {
  const map: Record<string, MemoryBriefKind> = {
    tasks: "task",
    meetings: "meeting",
    reports: "report",
    workflows: "workflow",
    companies: "company",
  };
  return map[sectionId] || "task";
}

function paletteKindLabel(kind: string): string {
  const map: Record<string, string> = {
    note: "Note",
    task: "Task",
    meeting: "Meeting",
    report: "Report",
    workflow: "Workflow",
    company: "Company",
    person: "Person",
    project: "Project",
  };
  return map[kind] || kind;
}

function isMemoryRouteKind(kind: RouteTarget["kind"]): kind is MemoryRouteKind {
  return kind in MEMORY_ROUTE_PATHS;
}

function memoryRouteTarget(sectionId: string, item: any): RouteTarget | null {
  const kind = SECTION_TO_MEMORY_ROUTE[sectionId];
  if (!kind || !item?.id) return null;
  return { kind, id: item.id };
}

function reportMarkdown(item: any, fallbackTitle: string, fallbackBody: string) {
  const title = String(item?.title || item?.name || fallbackTitle || "Report").trim();
  const body = String(item?.body || fallbackBody || "").trim();
  if (body.startsWith("#")) return body;
  return [`# ${title}`, body].filter(Boolean).join("\n\n");
}

function downloadName(title: string) {
  const slug = title.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "");
  return `${slug || "notesnoop-report"}.md`;
}

function relationIds(values?: any[]) {
  return (values || []).map((item) => String(item.id)).filter(Boolean);
}

function toggleId(values: string[], id: string) {
  return values.includes(id) ? values.filter((value) => value !== id) : [...values, id];
}

function reviewPayloadValue(value: any) {
  if (Array.isArray(value)) return value.join(", ");
  if (value === null || value === undefined) return "";
  return String(value);
}

function nextReviewPayload(current: any, key: string, value: string) {
  if (Array.isArray(current?.[key])) {
    return {
      ...current,
      [key]: value
        .split(",")
        .map((part) => part.trim())
        .filter(Boolean),
    };
  }
  return { ...current, [key]: value };
}

export function NoteSnoopApp({ quickCapture, initialRoute }: { quickCapture: boolean; initialRoute?: RouteTarget }) {
  const { getToken, isSignedIn, isLoaded } = useAuth();
  const [state, setState] = useState<ApiState | null>(null);
  const [home, setHome] = useState<HomeState | null>(null);
  const [memoryGraph, setMemoryGraph] = useState<MemoryGraphState>({ nodes: [], edges: [] });
  const [notes, setNotes] = useState<any[]>([]);
  const [requestedWorkspaceId, setRequestedWorkspaceId] = useState<string | null>(() => {
    if (typeof window === "undefined") return null;
    return new URLSearchParams(window.location.search).get("workspace_id");
  });
  const [routeTarget, setRouteTarget] = useState<RouteTarget>(() => initialRouteTarget(initialRoute));
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
  const [askQuestion, setAskQuestion] = useState("");
  const [askResult, setAskResult] = useState<any | null>(null);
  const [searchFilters, setSearchFilters] = useState<SearchFilters>({});
  const [searchMeta, setSearchMeta] = useState<any | null>(null);
  const [memorySearchKind, setMemorySearchKind] = useState<string>("all");
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
  const [taskAssigneeFilter, setTaskAssigneeFilter] = useState<string>("all");
  const [tasksViewMode, setTasksViewMode] = useState<"cards" | "board">(() => {
    if (typeof window === "undefined") return "cards";
    return (window.localStorage.getItem("notesnoop_tasks_view_mode") as "cards" | "board") || "cards";
  });
  const [recentMemoryKindFilter, setRecentMemoryKindFilter] = useState<string>("all");
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
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [paletteQuery, setPaletteQuery] = useState("");
  const [paletteResults, setPaletteResults] = useState<any[]>([]);
  const [paletteLoading, setPaletteLoading] = useState(false);
  const [paletteIndex, setPaletteIndex] = useState(0);
  const searchDebounceRef = useRef<number | null>(null);
  const paletteDebounceRef = useRef<number | null>(null);
  const paletteInputRef = useRef<HTMLInputElement | null>(null);
  const searchInputRef = useRef<HTMLInputElement | null>(null);
  const appliedRouteRef = useRef("");
  const openProjectRef = useRef<((project: any, options?: { push?: boolean }) => Promise<void>) | null>(null);
  const openMemoryItemRef = useRef<((sectionId: string, item: any, options?: { push?: boolean }) => Promise<void>) | null>(null);

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

  const appRouteUrl = useCallback(
    (target: RouteTarget) => {
      const params = new URLSearchParams();
      const workspaceParam = requestedWorkspaceId
        || (typeof window !== "undefined" ? new URLSearchParams(window.location.search).get("workspace_id") : null);
      if (workspaceParam) params.set("workspace_id", workspaceParam);
      const query = params.toString();
      return `${routePath(target)}${query ? `?${query}` : ""}`;
    },
    [requestedWorkspaceId],
  );

  const writeAppRoute = useCallback(
    (target: RouteTarget, replace = false) => {
      if (typeof window === "undefined") return;
      const next = appRouteUrl(target);
      const current = `${window.location.pathname}${window.location.search}`;
      if (next === current) return;
      window.history[replace ? "replaceState" : "pushState"]({}, "", next);
    },
    [appRouteUrl],
  );

  const copyRouteLink = useCallback(
    async (target: RouteTarget, label: string) => {
      if (typeof window === "undefined") return;
      const origin = window.location.origin;
      await navigator.clipboard.writeText(`${origin}${appRouteUrl(target)}`);
      setToast(`${label} link copied.`);
    },
    [appRouteUrl],
  );

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
    if (typeof window === "undefined") return undefined;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "/" || event.metaKey || event.ctrlKey || event.altKey) return;
      const target = event.target as HTMLElement | null;
      const tag = target?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      if (target?.isContentEditable) return;
      event.preventDefault();
      searchInputRef.current?.focus();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return undefined;
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPaletteOpen((open) => !open);
        return;
      }
      if (event.key === "Escape" && paletteOpen) {
        event.preventDefault();
        setPaletteOpen(false);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [paletteOpen]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    window.localStorage.setItem("notesnoop_tasks_view_mode", tasksViewMode);
  }, [tasksViewMode]);

  useEffect(() => {
    if (!paletteOpen) {
      setPaletteQuery("");
      setPaletteResults([]);
      setPaletteIndex(0);
      setPaletteLoading(false);
      if (paletteDebounceRef.current) {
        window.clearTimeout(paletteDebounceRef.current);
        paletteDebounceRef.current = null;
      }
      return;
    }
    const handle = window.setTimeout(() => paletteInputRef.current?.focus(), 30);
    return () => window.clearTimeout(handle);
  }, [paletteOpen]);

  const runPaletteSearch = useCallback(
    async (rawQuery: string) => {
      if (!workspaceId) return;
      const trimmed = rawQuery.trim();
      if (!trimmed) {
        setPaletteResults([]);
        setPaletteLoading(false);
        return;
      }
      setPaletteLoading(true);
      try {
        const res = await api(`/api/workspaces/${workspaceId}/search?q=${encodeURIComponent(trimmed)}`);
        const noteRows = (res.data || []).slice(0, 8).map((note: any) => ({
          kind: "note",
          id: note.id,
          title: note.title || note.summary || (note.body || "").slice(0, 80) || "Untitled note",
          subtitle: note.note_kind ? NOTE_KIND_LABELS[note.note_kind] || note.note_kind : "Note",
        }));
        const memoryRows = (res.meta?.memory_results || []).map((row: any) => ({
          kind: row.kind,
          id: row.id,
          title: row.title || "Untitled",
          subtitle: row.subtitle || "",
        }));
        setPaletteResults([...memoryRows, ...noteRows]);
        setPaletteIndex(0);
      } catch (err) {
        setPaletteResults([]);
      } finally {
        setPaletteLoading(false);
      }
    },
    [api, workspaceId],
  );

  const schedulePaletteSearch = useCallback(
    (nextQuery: string) => {
      setPaletteQuery(nextQuery);
      if (paletteDebounceRef.current) {
        window.clearTimeout(paletteDebounceRef.current);
        paletteDebounceRef.current = null;
      }
      if (!nextQuery.trim()) {
        setPaletteResults([]);
        setPaletteLoading(false);
        return;
      }
      paletteDebounceRef.current = window.setTimeout(() => {
        runPaletteSearch(nextQuery).catch(() => undefined);
        paletteDebounceRef.current = null;
      }, 180);
    },
    [runPaletteSearch],
  );

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
      setToast("Saved. Memory extraction is queued when allowed.");
      await refreshWorkspaceData();
    } catch (err) {
      setToast(err instanceof Error ? err.message : "Could not save note");
    } finally {
      setBusy(false);
    }
  }

  const openNote = useCallback(async (noteId: string, options: { push?: boolean } = {}) => {
    const res = await api(`/api/notes/${noteId}`);
    setSelectedNote(res.data);
    setSheetOpen(true);
    const target = { kind: "note", id: noteId } as const;
    if (options.push !== false) {
      appliedRouteRef.current = routeKey(target);
      setRouteTarget(target);
      writeAppRoute(target);
    }
  }, [api, writeAppRoute]);

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

  async function updateReminder(reminderId: string, payload: Record<string, unknown>) {
    const res = await api(`/api/task-reminders/${reminderId}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
    const reminder = res.data;
    setSelectedMemory((current) => {
      if (!current || current.sectionId !== "tasks") return current;
      const reminders = Array.isArray(current.item.reminders)
        ? current.item.reminders
        : current.item.reminder_id
          ? [{
              id: current.item.reminder_id,
              remind_at: current.item.remind_at,
              state: current.item.reminder_state,
              snoozed_until: current.item.snoozed_until,
              attention_at: current.item.attention_at,
            }]
          : [];
      const visible = ["pending", "snoozed"].includes(reminder.state);
      const nextReminders = reminders.filter((item: any) => item.id !== reminder.id);
      if (visible) nextReminders.push(reminder);
      return { ...current, item: { ...current.item, reminders: nextReminders } };
    });
    await refreshWorkspaceData();
    setToast(payload.state === "dismissed" ? "Reminder dismissed." : payload.state === "snoozed" ? "Reminder snoozed." : "Reminder updated.");
  }

  async function openMemoryItem(sectionId: string, item: any, options: { push?: boolean } = {}) {
    if (!workspaceId) return;
    if (sectionId === "intel") {
      const projectId = item.project_id || item.id;
      const project = (state?.projects || []).find((candidate) => candidate.id === projectId);
      if (project) await openProjectRef.current?.(project);
      return;
    }
    const routeTargetForItem = memoryRouteTarget(sectionId, item);
    const query = activeProject ? `?project_id=${activeProject}` : "";
    const endpointBySection: Record<string, string> = {
      tasks: item?.id ? `/api/tasks/${item.id}` : `/api/workspaces/${workspaceId}/tasks${query}`,
      meetings: item?.id ? `/api/meetings/${item.id}` : `/api/workspaces/${workspaceId}/meetings${query}`,
      reports: item?.id ? `/api/reports/${item.id}` : `/api/workspaces/${workspaceId}/reports${query}`,
      workflows: item?.id ? `/api/workflows/${item.id}` : `/api/workspaces/${workspaceId}/workflows${query}`,
      companies: item?.id ? `/api/companies/${item.id}` : `/api/workspaces/${workspaceId}/companies`,
    };
    try {
      const endpoint = endpointBySection[sectionId];
      if (!endpoint) {
        if (item.note_id || item.source_note_id) await openNote(item.note_id || item.source_note_id);
        return;
      }
      const res = await api(endpoint);
      const data = res.data || [];
      const detail = Array.isArray(data) ? data.find((candidate: any) => candidate.id === item.id) || item : data || item;
      setSelectedMemory({ sectionId, item: detail });
      if (routeTargetForItem && options.push !== false) {
        appliedRouteRef.current = routeKey(routeTargetForItem);
        setRouteTarget(routeTargetForItem);
        writeAppRoute(routeTargetForItem);
      }
    } catch {
      setSelectedMemory({ sectionId, item });
      if (routeTargetForItem && options.push !== false) {
        appliedRouteRef.current = routeKey(routeTargetForItem);
        setRouteTarget(routeTargetForItem);
        writeAppRoute(routeTargetForItem);
      }
    }
  }

  useEffect(() => {
    openMemoryItemRef.current = openMemoryItem;
  });

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

  async function askMemory() {
    if (!workspaceId || !askQuestion.trim()) return;
    setBusy(true);
    try {
      const res = await api(`/api/workspaces/${workspaceId}/ask`, {
        method: "POST",
        body: JSON.stringify({
          query: askQuestion.trim(),
          project_id: activeProject || undefined,
          person_id: personTimeline?.person?.id || searchFilters.person_id || undefined,
          date_from: searchFilters.date_from,
          date_to: searchFilters.date_to,
        }),
      });
      setAskResult(res.data);
      setToast("Memory answer ready.");
    } catch (err) {
      setToast(err instanceof Error ? err.message : "Could not answer from memory");
    } finally {
      setBusy(false);
    }
  }

  function askBody() {
    const sources = (askResult?.citations || [])
      .slice(0, 12)
      .map((citation: any) => `- ${citation.label || citation.kind}: ${citation.title || citation.id}`)
      .join("\n");
    return [`# ${askQuestion.trim()}`, String(askResult?.answer || "").trim(), sources ? `## Sources\n${sources}` : ""]
      .filter(Boolean)
      .join("\n\n");
  }

  async function saveAskAsReport() {
    if (!workspaceId || !askResult || !askQuestion.trim()) return;
    setBusy(true);
    try {
      const personId = personTimeline?.person?.id || searchFilters.person_id || undefined;
      const res = await api(`/api/workspaces/${workspaceId}/ask/report`, {
        method: "POST",
        body: JSON.stringify({
          query: askQuestion.trim(),
          answer: String(askResult?.answer || "").trim(),
          title: askQuestion.trim().slice(0, 180),
          confidence: askResult.confidence,
          citations: askResult.citations || [],
          source_counts: askResult.source_counts || {},
          project_id: activeProject || undefined,
          person_id: personId,
        }),
      });
      await refreshWorkspaceData();
      setActiveMemoryTab("reports");
      setSelectedMemory({ sectionId: "reports", item: res.data });
      setAskResult((current: any) => ({ ...current, saved_report_id: res.data.id }));
      setToast("Answer saved as report.");
    } catch (err) {
      setToast(err instanceof Error ? err.message : "Could not save report");
    } finally {
      setBusy(false);
    }
  }

  async function createTaskFromAsk() {
    if (!workspaceId || !askResult || !askQuestion.trim()) return;
    setBusy(true);
    try {
      const personId = personTimeline?.person?.id || searchFilters.person_id || undefined;
      const res = await api(`/api/workspaces/${workspaceId}/ask/task`, {
        method: "POST",
        body: JSON.stringify({
          query: askQuestion.trim(),
          answer: String(askResult?.answer || "").trim(),
          title: `Follow up: ${askQuestion.trim()}`.slice(0, 220),
          confidence: askResult.confidence,
          citations: askResult.citations || [],
          project_id: activeProject || undefined,
          person_id: personId,
        }),
      });
      await refreshWorkspaceData();
      setActiveMemoryTab("tasks");
      setSelectedMemory({ sectionId: "tasks", item: res.data });
      setToast("Follow-up task created.");
    } catch (err) {
      setToast(err instanceof Error ? err.message : "Could not create task");
    } finally {
      setBusy(false);
    }
  }

  async function copyAskAnswer() {
    await navigator.clipboard.writeText(askBody());
    setToast("Answer copied.");
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
    appliedRouteRef.current = routeKey({ kind: "dashboard" });
    setRouteTarget({ kind: "dashboard" });
    if (typeof window !== "undefined") {
      const url = new URL(window.location.href);
      url.searchParams.set("workspace_id", nextWorkspaceId);
      url.searchParams.delete("project_id");
      window.history.replaceState({}, "", `${url.pathname}?${url.searchParams.toString()}`);
    }
  }

  function openDashboard() {
    setActiveProject(null);
    setSelectedProjectIds([]);
    setPersonTimeline(null);
    setProjectTimeline(null);
    setSelectedNote(null);
    setSelectedMemory(null);
    setSheetOpen(false);
    const target = { kind: "dashboard" } as const;
    appliedRouteRef.current = routeKey(target);
    setRouteTarget(target);
    writeAppRoute(target);
  }

  const openProject = useCallback(async (project: any, options: { push?: boolean } = {}) => {
    setActiveProject(project.id);
    setSelectedProjectIds([]);
    setPersonTimeline(null);
    setSelectedMemory(null);
    const res = await api(`/api/projects/${project.id}/timeline`);
    setProjectTimeline(res.data);
    const target = { kind: "project", id: project.id } as const;
    if (options.push !== false) {
      appliedRouteRef.current = routeKey(target);
      setRouteTarget(target);
      writeAppRoute(target);
    }
    setMobileNav(false);
  }, [api, writeAppRoute]);

  useEffect(() => {
    openProjectRef.current = openProject;
  }, [openProject]);

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

  const openPerson = useCallback(async (person: any, options: { push?: boolean } = {}) => {
    setProjectTimeline(null);
    const res = await api(`/api/people/${person.id}/timeline`);
    setPersonTimeline(res.data);
    const target = { kind: "person", id: person.id } as const;
    if (options.push !== false) {
      appliedRouteRef.current = routeKey(target);
      setRouteTarget(target);
      writeAppRoute(target);
    }
    setMobileNav(false);
  }, [api, writeAppRoute]);

  function closePersonTimeline() {
    setPersonTimeline(null);
    const target = activeProject ? { kind: "project", id: activeProject } as const : { kind: "dashboard" } as const;
    appliedRouteRef.current = routeKey(target);
    setRouteTarget(target);
    writeAppRoute(target);
  }

  function closeProjectTimeline() {
    setProjectTimeline(null);
  }

  function closeNoteSheet() {
    setSheetOpen(false);
    if (routeTarget.kind !== "note") return;
    const target = activeProject ? { kind: "project", id: activeProject } as const : { kind: "dashboard" } as const;
    appliedRouteRef.current = routeKey(target);
    setRouteTarget(target);
    writeAppRoute(target);
  }

  function closeMemorySheet() {
    setSelectedMemory(null);
    if (!isMemoryRouteKind(routeTarget.kind)) return;
    const target = activeProject ? { kind: "project", id: activeProject } as const : { kind: "dashboard" } as const;
    appliedRouteRef.current = routeKey(target);
    setRouteTarget(target);
    writeAppRoute(target);
  }

  async function copyMemoryLink(sectionId: string, item: any) {
    const target = memoryRouteTarget(sectionId, item);
    if (!target) return;
    await copyRouteLink(target, item.title || item.name || "Memory");
  }

  async function copyReportMarkdown(item: any) {
    await navigator.clipboard.writeText(reportMarkdown(item, item?.title || "Report", item?.body || ""));
    setToast("Report markdown copied.");
  }

  function downloadReportMarkdown(item: any) {
    if (typeof window === "undefined") return;
    const markdown = reportMarkdown(item, item?.title || "Report", item?.body || "");
    const blob = new Blob([markdown], { type: "text/markdown;charset=utf-8" });
    const url = window.URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = downloadName(item?.title || item?.name || "notesnoop-report");
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    window.URL.revokeObjectURL(url);
    setToast("Report downloaded.");
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

  async function copyBrief(kind: "note" | "project" | "person" | "task" | "meeting" | "report" | "workflow" | "company", item: any, variant: "quick" | "full" = "quick") {
    const res = await api(`/api/briefs/${kind}/${item.id}?variant=${variant}`);
    await navigator.clipboard.writeText(res.data.markdown);
    setToast(`${variant === "full" ? "Full" : "Quick"} brief copied.`);
  }

  async function renameProject(projectId: string, nextName: string) {
    if (!nextName.trim()) return;
    try {
      const res = await api(`/api/projects/${projectId}`, {
        method: "PATCH",
        body: JSON.stringify({ name: nextName.trim() }),
      });
      setToast("Project renamed.");
      await refreshWorkspaceData();
      if (projectTimeline?.project?.id === projectId) {
        await openProject(res.data || projectTimeline.project);
      }
    } catch (err) {
      setToast(err instanceof Error ? err.message : "Could not rename project");
    }
  }

  async function renamePerson(personId: string, nextName: string) {
    if (!nextName.trim()) return;
    try {
      const res = await api(`/api/people/${personId}`, {
        method: "PATCH",
        body: JSON.stringify({ name: nextName.trim() }),
      });
      setToast("Person renamed.");
      await refreshWorkspaceData();
      if (personTimeline?.person?.id === personId) {
        await openPerson(res.data || personTimeline.person);
      }
    } catch (err) {
      setToast(err instanceof Error ? err.message : "Could not rename person");
    }
  }

  async function createTaskForAnchor(input: { title: string; due_at?: string | null; project_id?: string | null; assignee_id?: string | null }) {
    if (!workspaceId || !input.title.trim()) return;
    const body: Record<string, unknown> = { title: input.title.trim() };
    if (input.due_at) body.due_at = input.due_at;
    if (input.project_id) body.project_ids = [input.project_id];
    if (input.assignee_id) {
      body.person_ids = [input.assignee_id];
      body.assignee_id = input.assignee_id;
    }
    try {
      await api(`/api/workspaces/${workspaceId}/tasks`, { method: "POST", body: JSON.stringify(body) });
      setToast("Task added.");
      await refreshWorkspaceData();
      if (projectTimeline && input.project_id === projectTimeline.project?.id) {
        await openProject(projectTimeline.project);
      }
      if (personTimeline && input.assignee_id === personTimeline.person?.id) {
        await openPerson(personTimeline.person);
      }
    } catch (err) {
      setToast(err instanceof Error ? err.message : "Could not create task");
    }
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

  async function decideReview(
    reviewId: string,
    decision: "accept" | "reject",
    payload?: any,
    options?: { openAfterAccept?: boolean },
  ) {
    const res = await api(`/api/review-queue/${reviewId}/${decision}`, {
      method: "POST",
      body: JSON.stringify(decision === "accept" && payload ? { payload } : {}),
    });
    setReviewItems((current) => current.filter((item) => item.id !== reviewId));
    setToast(decision === "accept" ? "Suggestion accepted." : "Suggestion rejected.");
    if (decision === "accept" && options?.openAfterAccept) {
      const result = res?.data || res || {};
      const entityKind = result.entity_kind as MemoryRouteKind | undefined;
      const entityId = result.entity_id as string | undefined;
      if (entityKind && entityId && isMemoryRouteKind(entityKind)) {
        setReviewSheetOpen(false);
        await refreshWorkspaceData();
        const section = MEMORY_ROUTE_TO_SECTION[entityKind];
        openMemoryItem(section, { id: entityId });
        return;
      }
    }
    await refreshWorkspaceData();
  }

  useEffect(() => {
    if (quickCapture || typeof window === "undefined") return undefined;
    const onPopState = () => setRouteTarget(routeFromPath(window.location.pathname, window.location.search));
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, [quickCapture]);

  useEffect(() => {
    if (quickCapture) return;
    const key = routeKey(routeTarget);
    if (appliedRouteRef.current === key) return;
    if (routeTarget.kind === "dashboard") {
      appliedRouteRef.current = key;
      setActiveProject(null);
      setSelectedProjectIds([]);
      setPersonTimeline(null);
      setProjectTimeline(null);
      setSelectedNote(null);
      setSelectedMemory(null);
      setSheetOpen(false);
      return;
    }
    if (routeTarget.kind === "project" && routeTarget.id) {
      const project = state?.projects.find((item) => item.id === routeTarget.id);
      if (!project) return;
      appliedRouteRef.current = key;
      openProject(project, { push: false }).catch((err) => {
        appliedRouteRef.current = "";
        setToast(err.message);
      });
      return;
    }
    if (routeTarget.kind === "person" && routeTarget.id) {
      const person = state?.people.find((item) => item.id === routeTarget.id) || { id: routeTarget.id, name: "Person" };
      if (!state?.workspace) return;
      appliedRouteRef.current = key;
      openPerson(person, { push: false }).catch((err) => {
        appliedRouteRef.current = "";
        setToast(err.message);
      });
      return;
    }
    if (routeTarget.kind === "note" && routeTarget.id && (isSignedIn || DEV_AUTH)) {
      appliedRouteRef.current = key;
      openNote(routeTarget.id, { push: false }).catch((err) => {
        appliedRouteRef.current = "";
        setToast(err.message);
      });
      return;
    }
    if (isMemoryRouteKind(routeTarget.kind) && routeTarget.id && (isSignedIn || DEV_AUTH)) {
      if (!workspaceId) return;
      appliedRouteRef.current = key;
      openMemoryItemRef.current?.(MEMORY_ROUTE_TO_SECTION[routeTarget.kind], { id: routeTarget.id }, { push: false }).catch((err) => {
        appliedRouteRef.current = "";
        setToast(err.message);
      });
    }
  }, [isSignedIn, openNote, openPerson, openProject, quickCapture, routeTarget, state?.people, state?.projects, state?.workspace, workspaceId]);

  useEffect(() => {
    if (!landingProjectId || !state?.projects?.length) return;
    const project = state.projects.find((item) => item.id === landingProjectId);
    if (!project) return;
    setLandingProjectId(null);
    openProject(project).catch((err) => setToast(err.message));
  }, [landingProjectId, openProject, state?.projects]);

  const activeProjectRecord = state?.projects.find((project) => project.id === activeProject) || null;
  const projectOpenTaskCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const task of (home?.open_tasks || []) as any[]) {
      const projects = Array.isArray(task.projects) ? task.projects : [];
      for (const project of projects) {
        const id = project?.id ? String(project.id) : null;
        if (!id) continue;
        counts[id] = (counts[id] || 0) + 1;
      }
    }
    return counts;
  }, [home?.open_tasks]);
  const personOpenTaskCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const task of (home?.open_tasks || []) as any[]) {
      const directAssignee = task.assignee_id ? String(task.assignee_id) : null;
      if (directAssignee) {
        counts[directAssignee] = (counts[directAssignee] || 0) + 1;
        continue;
      }
      const peopleRows = Array.isArray(task.people) ? task.people : [];
      const assignee = peopleRows.find((person: any) => person.relation === "assignee");
      if (assignee?.id) {
        counts[String(assignee.id)] = (counts[String(assignee.id)] || 0) + 1;
      }
    }
    return counts;
  }, [home?.open_tasks]);
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
  const overdueTasks = useMemo(() => {
    const list: any[] = [];
    for (const task of openTasks) {
      if (!task.due_at || task.status === "done" || task.status === "archived") continue;
      const days = daysSinceNow(task.due_at);
      if (days !== null && days >= 1) list.push(task);
    }
    return list.slice().sort((a: any, b: any) => new Date(a.due_at).getTime() - new Date(b.due_at).getTime()).slice(0, 6);
  }, [openTasks]);
  const dueTodayTasks = useMemo(() => {
    const list: any[] = [];
    for (const task of openTasks) {
      if (!task.due_at || task.status === "done" || task.status === "archived") continue;
      const days = daysSinceNow(task.due_at);
      if (days === 0) list.push(task);
    }
    return list.slice(0, 6);
  }, [openTasks]);
  const meetingsCalls = (
    home?.meetings_calls?.length
      ? home.meetings_calls
      : [...(home?.meetings || []), ...(home?.calls || [])].length
        ? [...(home?.meetings || []), ...(home?.calls || [])]
        : dashboardNotes.filter((note) => ["meeting", "call"].includes(note.note_kind))
  );
  const todaysMeetings: any[] = [];
  for (const meeting of meetingsCalls as any[]) {
    const at = meeting.occurred_at || meeting.created_at;
    if (!at) continue;
    const days = daysSinceNow(at);
    if (days === 0) todaysMeetings.push(meeting);
    if (todaysMeetings.length >= 6) break;
  }
  const reportsBriefs = (
    home?.reports_briefs?.length
      ? home.reports_briefs
      : [...(home?.reports || []), ...(home?.briefs || [])].length
        ? [...(home?.reports || []), ...(home?.briefs || [])]
        : dashboardNotes.filter((note) => note.note_kind === "report")
  );
  const workflows = home?.workflows || [];
  const sidebarWorkflows = useMemo(() => {
    const list = [...(home?.workflows || [])];
    list.sort((a: any, b: any) => {
      const aActive = (a.status || "active") === "active" ? 0 : 1;
      const bActive = (b.status || "active") === "active" ? 0 : 1;
      if (aActive !== bActive) return aActive - bActive;
      const aDate = String(a.updated_at || a.created_at || "");
      const bDate = String(b.updated_at || b.created_at || "");
      return bDate.localeCompare(aDate);
    });
    return list.slice(0, 5);
  }, [home?.workflows]);
  const companies = useMemo(() => home?.companies || [], [home?.companies]);
  const looseEnds = home?.loose_ends || {};
  const looseNotesWithoutProject = (looseEnds.notes_without_project || []) as any[];
  const looseTasksWithoutOwner = (looseEnds.tasks_without_owner || []) as any[];
  const loosePeopleWithoutCompany = (looseEnds.people_without_company || []) as any[];
  const looseStaleReviews = Number(looseEnds.stale_reviews_count || 0);
  const looseEndsTotal =
    looseNotesWithoutProject.length +
    looseTasksWithoutOwner.length +
    loosePeopleWithoutCompany.length +
    (looseStaleReviews > 0 ? 1 : 0);
  const pipelineCounts: PipelineCounts = home?.pipeline_counts || {
    received: 0,
    processing: 0,
    needs_review: 0,
    accepted: 0,
    failed: 0,
  };
  const pipelineRecentFailed = home?.pipeline_recent_failed || [];
  const pipelineRecentReceived = home?.pipeline_recent_received || [];
  const pipelineTotal =
    pipelineCounts.received +
    pipelineCounts.processing +
    pipelineCounts.needs_review +
    pipelineCounts.accepted +
    pipelineCounts.failed;
  const pipelineStages: { id: keyof PipelineCounts; label: string; tone: string }[] = [
    { id: "received", label: "Received", tone: "neutral" },
    { id: "processing", label: "Processing", tone: "info" },
    { id: "needs_review", label: "Needs review", tone: "warn" },
    { id: "accepted", label: "Accepted", tone: "ok" },
    { id: "failed", label: "Failed", tone: "danger" },
  ];
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
  const tasksByAssignee = useMemo(() => {
    const groups: Record<string, { id: string; name: string; count: number }> = {};
    let unassigned = 0;
    for (const task of openTasks) {
      const assigneeId = task.assignee_id || (task.people || []).find((person: any) => person.relation === "assignee")?.id;
      const assigneeName = task.assignee_name || (task.people || []).find((person: any) => person.relation === "assignee")?.name;
      if (!assigneeId) {
        unassigned += 1;
        continue;
      }
      const key = String(assigneeId);
      if (!groups[key]) groups[key] = { id: key, name: String(assigneeName || "Unknown"), count: 0 };
      groups[key].count += 1;
    }
    return { groups: Object.values(groups).sort((a, b) => b.count - a.count), unassigned };
  }, [openTasks]);

  const filteredOpenTasks = useMemo(() => {
    if (taskAssigneeFilter === "all") return openTasks;
    if (taskAssigneeFilter === "unassigned") {
      return openTasks.filter((task) => {
        const assigneeId = task.assignee_id || (task.people || []).find((person: any) => person.relation === "assignee")?.id;
        return !assigneeId;
      });
    }
    return openTasks.filter((task) => {
      const assigneeId = task.assignee_id || (task.people || []).find((person: any) => person.relation === "assignee")?.id;
      return String(assigneeId || "") === taskAssigneeFilter;
    });
  }, [openTasks, taskAssigneeFilter]);

  const memorySections = [
    {
      id: "tasks",
      title: "Open tasks",
      icon: ClipboardList,
      items: filteredOpenTasks,
      empty: taskAssigneeFilter === "all"
        ? "No open tasks found. Capture follow-ups as Task memories."
        : `No open tasks for that owner.`,
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

  const composerRows = useMemo(() => {
    const minRows = quickCapture ? 9 : 5;
    const newlineCount = body.split("\n").length;
    const wrapEstimate = Math.ceil(body.length / 90);
    return Math.min(20, Math.max(minRows, newlineCount + 1, wrapEstimate));
  }, [body, quickCapture]);

  const composerHints = useMemo(() => {
    const trimmed = body.trim();
    if (trimmed.length < 3) return [] as Array<{ kind: "project" | "person" | "company"; id: string; label: string; color?: string }>;
    const lower = trimmed.toLowerCase();
    const hits: Array<{ kind: "project" | "person" | "company"; id: string; label: string; color?: string }> = [];
    for (const project of state?.projects || []) {
      if (!project?.name || project.kind === "personal" || project.kind === "inbox") continue;
      const name = String(project.name).toLowerCase();
      if (name.length >= 3 && lower.includes(name)) {
        hits.push({ kind: "project", id: project.id, label: project.name, color: project.color_hex });
      }
    }
    for (const person of state?.people || []) {
      if (!person?.name) continue;
      const parts = String(person.name).toLowerCase().split(/\s+/).filter(Boolean);
      const fullName = parts.join(" ");
      if (fullName.length >= 3 && lower.includes(fullName)) {
        hits.push({ kind: "person", id: person.id, label: person.name });
        continue;
      }
      if (parts.length > 1) {
        const tokens = trimmed.split(/[^A-Za-zÀ-ſ]+/).filter(Boolean);
        const allMatch = parts.every((part) =>
          tokens.some((token) => token.length >= 3 && token.toLowerCase() === part),
        );
        if (allMatch) hits.push({ kind: "person", id: person.id, label: person.name });
      }
    }
    for (const company of companies || []) {
      if (!company?.name) continue;
      const name = String(company.name).toLowerCase();
      if (name.length >= 3 && lower.includes(name)) {
        hits.push({ kind: "company", id: company.id, label: company.name });
      }
    }
    const seen = new Set<string>();
    return hits.filter((hit) => {
      const key = `${hit.kind}:${hit.id}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    }).slice(0, 6);
  }, [body, state?.projects, state?.people, companies]);

  const composerSection = (
    <section className={`composer ${quickCapture ? "" : "dashboard-composer"}`}>
      {state?.inbound_address && (
        <div className="composer-inbound-hint">
          <span><Send size={13} /> Forward email to</span>
          <button
            type="button"
            onClick={() => navigator.clipboard.writeText(String(state.inbound_address))}
            aria-label="Copy inbound email address"
          >
            <Copy size={12} /> {state.inbound_address}
          </button>
          <small>Anything you forward lands here as a note.</small>
        </div>
      )}
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
        rows={composerRows}
      />
      {composerHints.length > 0 && (
        <div className="composer-detected" aria-live="polite">
          <span>We see:</span>
          {composerHints.map((hint) => (
            <span key={`${hint.kind}-${hint.id}`} className={`composer-detected-chip composer-detected-${hint.kind}`}>
              {hint.kind === "project" && <span className="dot" style={{ background: hint.color || "#7c3aed" }} />}
              {hint.label}
            </span>
          ))}
        </div>
      )}
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
        <button className={`nav-item ${!activeProject ? "active" : ""}`} onClick={openDashboard}>
          <Archive size={17} /> Home
        </button>
        {inbox && (
          <button className={`nav-item ${activeProject === inbox.id ? "active" : ""}`} onClick={() => openProject(inbox)}>
            <Inbox size={17} /> Inbox
            {pipelineCounts.received > 0 && <span className="sidebar-count" aria-label={`${pipelineCounts.received} unprocessed`}>{pipelineCounts.received}</span>}
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
          .map((project) => {
            const count = projectOpenTaskCounts[project.id] || 0;
            return (
              <button key={project.id} className={`nav-item ${activeProject === project.id ? "active" : ""}`} onClick={() => openProject(project)}>
                <span className="dot" style={{ background: project.color_hex || "#7c3aed" }} /> {project.name}
                {count > 0 && <span className="sidebar-count" aria-label={`${count} open tasks`}>{count}</span>}
                {activityByProject.has(project.id) && <span className="activity-dot" title="Collaborator active" />}
              </button>
            );
          })}
        <div className="sidebar-create">
          <input value={projectName} onChange={(e) => setProjectName(e.target.value)} placeholder="New project" />
          <button className="icon-btn" onClick={createProject} aria-label="Create project">
            <Plus size={18} />
          </button>
        </div>
        {(state?.people || []).length > 0 && (
          <>
            <div className="sidebar-label">People</div>
            {dashboardPeople.slice(0, 5).map((person) => {
              const count = personOpenTaskCounts[person.id] || 0;
              return (
                <button
                  key={person.id}
                  className={`nav-item ${personTimeline?.person?.id === person.id ? "active" : ""}`}
                  onClick={() => openPerson(person)}
                  aria-label={`Open ${person.name} timeline`}
                >
                  <UserRound size={15} /> {person.name}
                  {count > 0 && <span className="sidebar-count" aria-label={`${count} tasks assigned`}>{count}</span>}
                </button>
              );
            })}
          </>
        )}
        {(companies || []).length > 0 && (
          <>
            <div className="sidebar-label">Companies</div>
            {companies.slice(0, 5).map((company: any) => (
              <button
                key={company.id}
                className="nav-item"
                onClick={() => openMemoryItem("companies", company)}
                aria-label={`Open ${company.name}`}
              >
                <Building2 size={15} /> {company.name}
              </button>
            ))}
          </>
        )}
        {sidebarWorkflows.length > 0 && (
          <>
            <div className="sidebar-label">Workflows</div>
            {sidebarWorkflows.map((workflow: any) => (
              <button
                key={workflow.id}
                className="nav-item"
                onClick={() => openMemoryItem("workflows", workflow)}
                aria-label={`Open workflow ${workflow.name || workflow.title}`}
              >
                <Workflow size={15} /> {workflow.name || workflow.title || "Workflow"}
                {workflow.status && workflow.status !== "active" && (
                  <span className={`workflow-status-pill workflow-status-${workflow.status}`} aria-label={`Status ${workflow.status}`}>
                    {workflow.status}
                  </span>
                )}
              </button>
            ))}
          </>
        )}
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
            <input
              ref={searchInputRef}
              value={query}
              onChange={(e) => scheduleSearch(e.target.value)}
              placeholder="Search notes, people, projects... (press / to focus)"
            />
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
                {(() => {
                  const todayCounts = home?.today_counts || {};
                  const parts: string[] = [];
                  const newNotes = Number(todayCounts.new_notes || 0);
                  const tasksDone = Number(todayCounts.tasks_done || 0);
                  const reviewsAccepted = Number(todayCounts.reviews_accepted || 0);
                  if (newNotes > 0) parts.push(`${newNotes} new note${newNotes === 1 ? "" : "s"}`);
                  if (tasksDone > 0) parts.push(`${tasksDone} task${tasksDone === 1 ? "" : "s"} done`);
                  if (reviewsAccepted > 0) parts.push(`${reviewsAccepted} review${reviewsAccepted === 1 ? "" : "s"} accepted`);
                  if (parts.length === 0) return null;
                  return <p className="dashboard-today">Today: {parts.join(" - ")}</p>;
                })()}
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
                    <Inbox size={16} /> Inbox{pipelineCounts.received > 0 ? ` (${pipelineCounts.received})` : ""}
                  </button>
                )}
              </div>
            </div>

            <section className="dashboard-ask" aria-label="Ask memory">
              <div className="ask-prompt">
                <span><Sparkles size={16} /> Ask memory</span>
                <div className="ask-row">
                  <input
                    value={askQuestion}
                    onChange={(event) => setAskQuestion(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") askMemory();
                    }}
                    placeholder={activeProjectRecord ? `Ask about ${activeProjectRecord.name}` : "Ask across notes, people, tasks, meetings, and reports"}
                    aria-label="Ask memory question"
                  />
                  <button type="button" onClick={askMemory} disabled={busy || askQuestion.trim().length < 3}>
                    <Search size={16} /> Ask
                  </button>
                </div>
              </div>
              {askResult && (
                <div className="ask-answer">
                  <div>
                    <strong>{Math.round(Number(askResult.confidence || 0) * 100)}% grounded</strong>
                    <span>{askResult.source_counts?.notes || 0} notes / {askResult.source_counts?.memory || 0} memories</span>
                  </div>
                  {String(askResult.answer || "")
                    .split("\n")
                    .map((line) => line.trim())
                    .filter(Boolean)
                    .slice(0, 8)
                    .map((line, index) => (
                      <p key={`${line}-${index}`}>{line.replace(/^#+\s*/, "")}</p>
                    ))}
                  {!!askResult.citations?.length && (
                    <div className="citation-row" role="group" aria-label="Answer citations">
                      {askResult.citations.slice(0, 16).map((citation: any) => (
                        <button
                          key={`${citation.kind}-${citation.id}-${citation.label}`}
                          type="button"
                          onClick={() => citation.kind === "note" ? openNote(citation.id) : openGraphNode(citation)}
                          aria-label={`Open ${citation.kind} ${citation.title || citation.label}`}
                        >
                          <span>{citation.label}</span>
                          {citation.title || citation.kind}
                        </button>
                      ))}
                      {askResult.citations.length > 16 && (
                        <span className="muted">+{askResult.citations.length - 16} more</span>
                      )}
                    </div>
                  )}
                  <div className="sheet-actions ask-actions">
                    <button type="button" onClick={copyAskAnswer}>
                      <Copy size={16} /> Copy answer
                    </button>
                    <button type="button" onClick={saveAskAsReport} disabled={busy || askResult.saved_report_id}>
                      <FileText size={16} /> {askResult.saved_report_id ? "Report saved" : "Save report"}
                    </button>
                    <button type="button" onClick={createTaskFromAsk} disabled={busy}>
                      <ClipboardList size={16} /> Create task
                    </button>
                  </div>
                </div>
              )}
            </section>

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
              <section className="dashboard-panel attention-panel">
                <div className="panel-head">
                  <h2>Needs attention</h2>
                  <Bell size={18} />
                </div>
                {dashboardReviewItems.length || dashboardFlagged.length || upcomingReminders.length || overdueTasks.length || dueTodayTasks.length || todaysMeetings.length ? (
                  <div className="attention-groups">
                    {todaysMeetings.length > 0 && (
                      <div className="attention-group">
                        <div className="attention-group-head">
                          <span className="attention-group-label">Meetings today</span>
                          <strong>{todaysMeetings.length}</strong>
                        </div>
                        <div className="attention-grid">
                          {todaysMeetings.map((meeting: any) => (
                            <button key={`meeting-today-${meeting.id}`} className="dashboard-row" type="button" onClick={() => openMemoryItem("meetings", meeting)}>
                              <span className="row-icon"><CalendarDays size={15} /></span>
                              <span>
                                <strong>{meeting.title}</strong>
                                <small>{meeting.occurred_at ? new Date(meeting.occurred_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "Today"}{meeting.project_name ? ` - ${meeting.project_name}` : ""}</small>
                              </span>
                            </button>
                          ))}
                        </div>
                      </div>
                    )}
                    {overdueTasks.length > 0 && (
                      <div className="attention-group">
                        <div className="attention-group-head">
                          <span className="attention-group-label" style={{ color: "#6b1818" }}>Overdue</span>
                          <strong style={{ background: "#fbf3f2", borderColor: "#d8a3a0", color: "#6b1818" }}>{overdueTasks.length}</strong>
                        </div>
                        <div className="attention-grid">
                          {overdueTasks.map((task: any) => (
                            <div key={`overdue-${task.id}`} className="task-row-with-action">
                              <button className="dashboard-row warning" type="button" onClick={() => openMemoryItem("tasks", task)}>
                                <span className="row-icon warning"><CalendarDays size={15} /></span>
                                <span>
                                  <strong>{task.title}</strong>
                                  <small>Due {new Date(task.due_at).toLocaleDateString()}{task.assignee_name ? ` - ${task.assignee_name}` : ""}</small>
                                </span>
                              </button>
                              <button
                                type="button"
                                className="task-row-done"
                                aria-label={`Mark ${task.title} done`}
                                onClick={(event) => {
                                  event.stopPropagation();
                                  updateTaskStatus(task.id, "done");
                                }}
                              >
                                <CheckCircle2 size={14} /> Done
                              </button>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                    {dueTodayTasks.length > 0 && (
                      <div className="attention-group">
                        <div className="attention-group-head">
                          <span className="attention-group-label">Due today</span>
                          <strong>{dueTodayTasks.length}</strong>
                        </div>
                        <div className="attention-grid">
                          {dueTodayTasks.map((task: any) => (
                            <div key={`due-today-${task.id}`} className="task-row-with-action">
                              <button className="dashboard-row" type="button" onClick={() => openMemoryItem("tasks", task)}>
                                <span className="row-icon"><CalendarDays size={15} /></span>
                                <span>
                                  <strong>{task.title}</strong>
                                  <small>Today{task.assignee_name ? ` - ${task.assignee_name}` : ""}</small>
                                </span>
                              </button>
                              <button
                                type="button"
                                className="task-row-done"
                                aria-label={`Mark ${task.title} done`}
                                onClick={(event) => {
                                  event.stopPropagation();
                                  updateTaskStatus(task.id, "done");
                                }}
                              >
                                <CheckCircle2 size={14} /> Done
                              </button>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                    {upcomingReminders.length > 0 && (
                      <div className="attention-group">
                        <div className="attention-group-head">
                          <span className="attention-group-label">Reminders</span>
                          <strong>{upcomingReminders.length}</strong>
                        </div>
                        <div className="attention-grid">
                          {upcomingReminders.map((task) => (
                            <button key={`reminder-${task.id}`} className="dashboard-row" type="button" onClick={() => openMemoryItem("tasks", task)}>
                              <span className="row-icon"><CalendarDays size={15} /></span>
                              <span>
                                <strong>{task.title}</strong>
                                <small>Due {new Date(task.attention_at || task.remind_at || task.due_at).toLocaleDateString()}</small>
                              </span>
                            </button>
                          ))}
                        </div>
                      </div>
                    )}
                    {dashboardReviewItems.length > 0 && (
                      <div className="attention-group">
                        <div className="attention-group-head">
                          <span className="attention-group-label">AI suggestions</span>
                          <strong>{dashboardReviewCount || dashboardReviewItems.length}</strong>
                          <button type="button" className="attention-group-link" onClick={openReviewQueue}>
                            Review all
                          </button>
                        </div>
                        <div className="attention-grid">
                          {dashboardReviewItems.slice(0, 6).map((item) => {
                            const conf = Number(item.payload?.confidence || item.confidence || 0);
                            const sourceKind = item.source_note_kind === "email" ? "Email" : "AI";
                            return (
                              <button key={item.id} className="dashboard-row" type="button" onClick={openReviewQueue}>
                                <span className="row-icon"><Bell size={15} /></span>
                                <span>
                                  <strong>{item.payload?.name || item.payload?.title || `New ${item.entity_kind}`}</strong>
                                  <small>
                                    {sourceKind} {item.entity_kind}
                                    {conf > 0 ? ` - ${Math.round(conf * 100)}%` : ""}
                                  </small>
                                </span>
                              </button>
                            );
                          })}
                        </div>
                      </div>
                    )}
                    {dashboardFlagged.length > 0 && (
                      <div className="attention-group">
                        <div className="attention-group-head">
                          <span className="attention-group-label">Flagged</span>
                          <strong>{dashboardFlagged.length}</strong>
                        </div>
                        <div className="attention-grid">
                          {dashboardFlagged.slice(0, 6).map((item) => (
                            <button key={item.id} className="dashboard-row" type="button" onClick={() => item.note_id && openNote(item.note_id)}>
                              <span className="row-icon warning"><Flag size={15} /></span>
                              <span>
                                <strong>{item.label || item.target_kind}</strong>
                                <small>Flagged {item.target_kind}</small>
                              </span>
                            </button>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                ) : (
                  <p className="dashboard-empty">Caught up. No reminders, no review suggestions, nothing flagged.</p>
                )}
              </section>

              <section className="dashboard-panel capture-panel">
                <div className="panel-head">
                  <h2>Capture</h2>
                  <Send size={18} />
                </div>
                {composerSection}
              </section>

              <section className="dashboard-panel pipeline-panel">
                <div className="panel-head">
                  <h2>Processing lane</h2>
                  <Workflow size={18} />
                </div>
                <div className="pipeline-stages" role="list" aria-label="Note processing pipeline">
                  {pipelineStages.map((stage) => (
                    <div
                      key={stage.id}
                      role="listitem"
                      className={`pipeline-stage pipeline-stage-${stage.tone}${pipelineCounts[stage.id] ? "" : " pipeline-stage-zero"}`}
                    >
                      <strong>{pipelineCounts[stage.id]}</strong>
                      <span>{stage.label}</span>
                    </div>
                  ))}
                </div>
                {pipelineTotal === 0 ? (
                  <p className="dashboard-empty">No notes captured yet.</p>
                ) : (
                  <div className="pipeline-detail">
                    {pipelineRecentReceived.length > 0 && (
                      <div className="pipeline-bucket">
                        <span className="pipeline-bucket-label">Awaiting extraction</span>
                        {pipelineRecentReceived.map((note: any) => (
                          <button
                            key={`pipe-recv-${note.id}`}
                            type="button"
                            className="dashboard-row pipeline-row"
                            onClick={() => openNote(note.id)}
                          >
                            <span className="row-icon"><Inbox size={14} /></span>
                            <span>
                              <strong>{note.title || "Untitled"}</strong>
                              <small>{NOTE_KIND_LABELS[note.note_kind || "note"] || "Note"} - click to extract memory</small>
                            </span>
                          </button>
                        ))}
                      </div>
                    )}
                    {pipelineRecentFailed.length > 0 && (
                      <div className="pipeline-bucket">
                        <span className="pipeline-bucket-label">Failed</span>
                        {pipelineRecentFailed.map((note: any) => (
                          <div key={`pipe-fail-${note.id}`} className="pipeline-row-with-action">
                            <button
                              type="button"
                              className="dashboard-row pipeline-row pipeline-row-failed"
                              onClick={() => openNote(note.id)}
                            >
                              <span className="row-icon warning"><X size={14} /></span>
                              <span>
                                <strong>{note.title || "Untitled"}</strong>
                                <small>{note.ai_processing_error ? String(note.ai_processing_error).slice(0, 80) : "Click to open"}</small>
                              </span>
                            </button>
                            <button
                              type="button"
                              className="pipeline-retry"
                              aria-label={`Retry extraction for ${note.title || "note"}`}
                              onClick={(event) => {
                                event.stopPropagation();
                                processWithAI(note.id);
                              }}
                            >
                              <Sparkles size={13} /> Retry
                            </button>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </section>

              <section className="dashboard-panel memory-system-panel">
                <div className="panel-head">
                  <h2>Active work</h2>
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
                {activeMemorySection.id === "tasks" && openTasks.length > 0 && (
                  <div className="task-view-toggle" role="tablist" aria-label="Task layout">
                    <button
                      type="button"
                      role="tab"
                      aria-selected={tasksViewMode === "cards"}
                      className={tasksViewMode === "cards" ? "active" : ""}
                      onClick={() => setTasksViewMode("cards")}
                    >
                      List
                    </button>
                    <button
                      type="button"
                      role="tab"
                      aria-selected={tasksViewMode === "board"}
                      className={tasksViewMode === "board" ? "active" : ""}
                      onClick={() => setTasksViewMode("board")}
                    >
                      Board
                    </button>
                  </div>
                )}
                {activeMemorySection.id === "tasks" && (tasksByAssignee.groups.length > 0 || tasksByAssignee.unassigned > 0) && (
                  <div className="task-assignee-filter" role="tablist" aria-label="Filter tasks by assignee">
                    <button
                      type="button"
                      role="tab"
                      aria-selected={taskAssigneeFilter === "all"}
                      className={taskAssigneeFilter === "all" ? "assignee-chip active" : "assignee-chip"}
                      onClick={() => setTaskAssigneeFilter("all")}
                    >
                      All <strong>{openTasks.length}</strong>
                    </button>
                    {tasksByAssignee.unassigned > 0 && (
                      <button
                        type="button"
                        role="tab"
                        aria-selected={taskAssigneeFilter === "unassigned"}
                        className={taskAssigneeFilter === "unassigned" ? "assignee-chip warn active" : "assignee-chip warn"}
                        onClick={() => setTaskAssigneeFilter("unassigned")}
                      >
                        Unassigned <strong>{tasksByAssignee.unassigned}</strong>
                      </button>
                    )}
                    {tasksByAssignee.groups.slice(0, 6).map((group) => (
                      <button
                        key={group.id}
                        type="button"
                        role="tab"
                        aria-selected={taskAssigneeFilter === group.id}
                        className={taskAssigneeFilter === group.id ? "assignee-chip active" : "assignee-chip"}
                        onClick={() => setTaskAssigneeFilter(group.id)}
                      >
                        {group.name} <strong>{group.count}</strong>
                      </button>
                    ))}
                  </div>
                )}
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
                {activeMemorySection.id === "tasks" && tasksViewMode === "board" ? (
                  <TaskStatusBoard
                    tasks={filteredOpenTasks}
                    emptyMessage={activeMemorySection.empty}
                    onOpenTask={(task) => openMemoryItem("tasks", task)}
                    onStatusChange={updateTaskStatus}
                  />
                ) : (
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
                )}
              </section>

              <section className="dashboard-panel relationships-panel">
                <div className="panel-head">
                  <h2>Active projects</h2>
                  <Archive size={18} />
                </div>
                {dashboardProjects.length ? (
                  <div className="dashboard-list">
                    {dashboardProjects.slice(0, 5).map((project) => {
                      const last = project.last_note_at;
                      const daysSince = last ? daysSinceNow(last) : null;
                      const stale = daysSince !== null && daysSince > 14;
                      const openTasks = Number(project.open_task_count || 0);
                      const blocked = Number(project.blocked_task_count || 0);
                      const notes = Number(project.mention_count || 0);
                      const facts: string[] = [];
                      if (openTasks > 0) {
                        facts.push(blocked > 0 ? `${openTasks} open (${blocked} blocked)` : `${openTasks} open task${openTasks === 1 ? "" : "s"}`);
                      }
                      if (notes > 0) facts.push(`${notes} note${notes === 1 ? "" : "s"}`);
                      if (!facts.length) facts.push(project.kind === "inbox" ? "Inbox" : "Project");
                      return (
                        <button
                          key={project.id}
                          className={stale ? "dashboard-row stale" : "dashboard-row"}
                          type="button"
                          onClick={() => openProject(project)}
                          aria-label={`Open project ${project.name}`}
                        >
                          <span className="dot" style={{ background: project.color_hex || "#7c3aed" }} />
                          <span>
                            <strong>{project.name}</strong>
                            <small>
                              {facts.join(" - ")}
                              {daysSince !== null && ` - ${humanRelativeTime(last)}`}
                            </small>
                          </span>
                        </button>
                      );
                    })}
                  </div>
                ) : (
                  <p className="dashboard-empty">No active projects yet. Capture a note and tag it to start a project here.</p>
                )}
              </section>

              <section className="dashboard-panel relationships-panel">
                <div className="panel-head">
                  <h2>People</h2>
                  <Users size={18} />
                </div>
                {dashboardPeople.length ? (
                  <div className="dashboard-list">
                    {dashboardPeople.slice(0, 5).map((person) => {
                      const last = person.last_note_at;
                      const daysSince = last ? daysSinceNow(last) : null;
                      const stale = daysSince !== null && daysSince > 30;
                      const company = person.company;
                      const noteCount = Number(person.mention_count || person.confirmed_note_count || 0);
                      const tasksOwned = personOpenTaskCounts[person.id] || 0;
                      const facts: string[] = [];
                      if (tasksOwned > 0) facts.push(`${tasksOwned} open task${tasksOwned === 1 ? "" : "s"}`);
                      if (company) facts.push(company);
                      if (noteCount > 0) facts.push(`${noteCount} note${noteCount === 1 ? "" : "s"}`);
                      if (!facts.length) facts.push("Person");
                      return (
                        <button
                          key={person.id}
                          className={stale ? "dashboard-row stale" : "dashboard-row"}
                          type="button"
                          onClick={() => openPerson(person)}
                          aria-label={`Open ${person.name} timeline`}
                        >
                          <span className="row-icon"><UserRound size={15} /></span>
                          <span>
                            <strong>{person.name}</strong>
                            <small>
                              {facts.join(" - ")}
                              {daysSince !== null && ` - ${humanRelativeTime(last)}`}
                            </small>
                          </span>
                        </button>
                      );
                    })}
                  </div>
                ) : (
                  <p className="dashboard-empty">No people yet. People you mention in notes or who arrive via forwarded email will appear here.</p>
                )}
              </section>

              <section className="dashboard-panel recent-memory">
                <div className="panel-head">
                  <h2>Recent memory</h2>
                  <Sparkles size={18} />
                </div>
                {(() => {
                  const kindCounts: Record<string, number> = {};
                  for (const note of dashboardNotes) {
                    const k = String(note.note_kind || "note");
                    kindCounts[k] = (kindCounts[k] || 0) + 1;
                  }
                  const tabs = [{ id: "all", label: "All" }, ...Object.keys(kindCounts).sort().map((id) => ({ id, label: NOTE_KIND_LABELS[id] || id }))];
                  if (tabs.length <= 2) return null;
                  return (
                    <div className="recent-memory-tabs" role="tablist" aria-label="Filter recent memory">
                      {tabs.map((tab) => {
                        const count = tab.id === "all" ? dashboardNotes.length : kindCounts[tab.id] || 0;
                        const active = recentMemoryKindFilter === tab.id;
                        return (
                          <button
                            key={tab.id}
                            type="button"
                            role="tab"
                            aria-selected={active}
                            className={active ? "search-scope-tab active" : "search-scope-tab"}
                            onClick={() => setRecentMemoryKindFilter(tab.id)}
                          >
                            {tab.label}
                            <strong>{count}</strong>
                          </button>
                        );
                      })}
                    </div>
                  );
                })()}
                {(() => {
                  const filtered = recentMemoryKindFilter === "all"
                    ? dashboardNotes
                    : dashboardNotes.filter((note) => (note.note_kind || "note") === recentMemoryKindFilter);
                  if (!dashboardNotes.length) {
                    return <p className="dashboard-empty">No notes yet. Paste a meeting note, forward an email, or hit Capture to start.</p>;
                  }
                  if (filtered.length === 0) {
                    return <p className="dashboard-empty">No {NOTE_KIND_LABELS[recentMemoryKindFilter] || recentMemoryKindFilter} notes yet.</p>;
                  }
                  return (
                    <div className="dashboard-list">
                      {filtered.slice(0, 6).map((note) => {
                        const status = pipelineStatusForNote(note);
                        const kindLabel = NOTE_KIND_LABELS[note.note_kind || "note"] || "Note";
                        const isEmail = note.note_kind === "email" || !!note.raw_email_metadata;
                        const relative = humanRelativeTime(note.occurred_at || note.created_at);
                        return (
                          <button key={note.id} className="dashboard-row memory-row" type="button" onClick={() => openNote(note.id)}>
                            <span className="memory-row-content">
                              <span className="memory-row-head">
                                <strong>{note.title}</strong>
                                {status && (
                                  <span className={`pipeline-pill pipeline-pill-${status.tone}`}>{status.label}</span>
                                )}
                                {isEmail && (
                                  <span className="pipeline-pill pipeline-pill-email">Email</span>
                                )}
                                {relative && <span className="recent-memory-when">{relative}</span>}
                              </span>
                              <small className="memory-row-body">{kindLabel}{note.body ? ` - ${truncateInline(note.body, 140)}` : ""}</small>
                            </span>
                          </button>
                        );
                      })}
                    </div>
                  );
                })()}
              </section>

              <section className="dashboard-panel loose-ends-panel">
                <div className="panel-head">
                  <h2>Loose ends</h2>
                  <ClipboardList size={18} />
                </div>
                {looseEndsTotal === 0 ? (
                  <p className="dashboard-empty">All tied up. Notes are tagged, tasks have owners, people have companies.</p>
                ) : (
                  <div className="loose-ends-groups">
                    {looseNotesWithoutProject.length > 0 && (
                      <div className="loose-ends-group">
                        <div className="loose-ends-head">
                          <span>Notes without a project</span>
                          <strong>{looseNotesWithoutProject.length}</strong>
                        </div>
                        <div className="dashboard-list">
                          {looseNotesWithoutProject.slice(0, 3).map((note: any) => (
                            <button
                              key={`loose-note-${note.id}`}
                              className="dashboard-row"
                              type="button"
                              onClick={() => openNote(note.id)}
                            >
                              <span className="row-icon"><FileText size={15} /></span>
                              <span>
                                <strong>{note.title || "Untitled note"}</strong>
                                <small>{NOTE_KIND_LABELS[note.note_kind || "note"] || "Note"} - tag a project</small>
                              </span>
                            </button>
                          ))}
                        </div>
                      </div>
                    )}
                    {looseTasksWithoutOwner.length > 0 && (
                      <div className="loose-ends-group">
                        <div className="loose-ends-head">
                          <span>Tasks without an owner</span>
                          <strong>{looseTasksWithoutOwner.length}</strong>
                        </div>
                        <div className="dashboard-list">
                          {looseTasksWithoutOwner.slice(0, 3).map((task: any) => (
                            <button
                              key={`loose-task-${task.id}`}
                              className="dashboard-row"
                              type="button"
                              onClick={() => openMemoryItem("tasks", task)}
                            >
                              <span className="row-icon"><ClipboardList size={15} /></span>
                              <span>
                                <strong>{task.title || "Untitled task"}</strong>
                                <small>{task.status || "todo"} - assign someone</small>
                              </span>
                            </button>
                          ))}
                        </div>
                      </div>
                    )}
                    {loosePeopleWithoutCompany.length > 0 && (
                      <div className="loose-ends-group">
                        <div className="loose-ends-head">
                          <span>People without a company</span>
                          <strong>{loosePeopleWithoutCompany.length}</strong>
                        </div>
                        <div className="dashboard-list">
                          {loosePeopleWithoutCompany.slice(0, 3).map((person: any) => (
                            <button
                              key={`loose-person-${person.id}`}
                              className="dashboard-row"
                              type="button"
                              onClick={() => openPerson(person)}
                            >
                              <span className="row-icon"><UserRound size={15} /></span>
                              <span>
                                <strong>{person.name}</strong>
                                <small>Set a company</small>
                              </span>
                            </button>
                          ))}
                        </div>
                      </div>
                    )}
                    {looseStaleReviews > 0 && (
                      <div className="loose-ends-group">
                        <div className="loose-ends-head">
                          <span>Stale review suggestions</span>
                          <strong>{looseStaleReviews}</strong>
                        </div>
                        <button type="button" className="dashboard-row stale-review-row" onClick={openReviewQueue}>
                          <span className="row-icon"><Bell size={15} /></span>
                          <span>
                            <strong>{looseStaleReviews} suggestion{looseStaleReviews === 1 ? "" : "s"} waiting &gt; 7 days</strong>
                            <small>Open the review queue to decide or dismiss</small>
                          </span>
                        </button>
                      </div>
                    )}
                  </div>
                )}
              </section>

              {memoryGraph.nodes.length >= 12 && (
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
                  </>
                ) : (
                  <p className="dashboard-empty">Links appear here once notes connect to people, projects, tasks, meetings, reports, workflows, or companies.</p>
                )}
              </section>
              )}
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
                  {(() => {
                    const kindCounts: Record<string, number> = {};
                    for (const result of memorySearchResults as any[]) {
                      const kind = String(result.kind || "other");
                      kindCounts[kind] = (kindCounts[kind] || 0) + 1;
                    }
                    const tabs: { id: string; label: string }[] = [
                      { id: "all", label: "All" },
                      ...Object.keys(kindCounts).sort().map((id) => ({ id, label: id })),
                    ];
                    const filtered = memorySearchKind === "all"
                      ? memorySearchResults
                      : memorySearchResults.filter((item: any) => item.kind === memorySearchKind);
                    return (
                      <>
                        <div className="search-scope-tabs" role="tablist" aria-label="Filter memory matches">
                          {tabs.map((tab) => {
                            const count = tab.id === "all" ? memorySearchResults.length : kindCounts[tab.id] || 0;
                            const active = memorySearchKind === tab.id;
                            return (
                              <button
                                key={tab.id}
                                type="button"
                                role="tab"
                                aria-selected={active}
                                className={active ? "search-scope-tab active" : "search-scope-tab"}
                                onClick={() => setMemorySearchKind(tab.id)}
                              >
                                {tab.label}
                                <strong>{count}</strong>
                              </button>
                            );
                          })}
                        </div>
                        <div className="memory-search-grid">
                          {filtered.slice(0, 12).map((item: any) => (
                            <button key={`${item.kind}-${item.id}`} type="button" onClick={() => openGraphNode(item)}>
                              <span>{item.kind}</span>
                              <strong>{item.title}</strong>
                              {item.subtitle && <small>{item.subtitle}</small>}
                            </button>
                          ))}
                          {filtered.length === 0 && <p className="muted">No {memorySearchKind} matches.</p>}
                        </div>
                      </>
                    );
                  })()}
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
                  onCopyLink={() => copyRouteLink({ kind: "person", id: personTimeline.person.id }, "Person")}
                  onFlag={() => flag({ person_id: personTimeline.person.id })}
                  onMerge={mergePerson}
                  onCreateTask={createTaskForAnchor}
                  onRename={(next) => renamePerson(personTimeline.person.id, next)}
                  onBack={closePersonTimeline}
                />
              ) : projectTimeline ? (
                <TimelinePanel
                  timeline={projectTimeline}
                  kind="project"
                  people={state?.people || []}
                  onOpenNote={openNote}
                  onOpenMemory={openMemoryItem}
                  onCopy={() => copyBrief("project", projectTimeline.project)}
                  onCopyLink={() => copyRouteLink({ kind: "project", id: projectTimeline.project.id }, "Project")}
                  onFlag={() => flag({ project_id: projectTimeline.project.id })}
                  onMerge={mergePerson}
                  inviteEmail={inviteEmail}
                  onInviteEmailChange={setInviteEmail}
                  onInvite={inviteProjectMember}
                  onGenerateReport={generateProjectReport}
                  onCreateTask={createTaskForAnchor}
                  onRename={projectTimeline.project?.kind === "user" ? (next) => renameProject(projectTimeline.project.id, next) : undefined}
                  onBack={closeProjectTimeline}
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
        onOpenSource={openNote}
        allProjects={state?.projects || []}
        allPeople={state?.people || []}
        allCompanies={companies}
      />

      <MemoryDetailSheet
        memory={selectedMemory}
        allProjects={state?.projects || []}
        allPeople={state?.people || []}
        allCompanies={companies}
        onClose={closeMemorySheet}
        onTaskStatusChange={updateTaskStatus}
        onUpdateMemory={updateMemoryItem}
        onUpdateReminder={updateReminder}
        onCopyBrief={(sectionId, item, variant) => copyBrief(memoryBriefKind(sectionId), item, variant)}
        onCopyLink={copyMemoryLink}
        onCopyReportMarkdown={copyReportMarkdown}
        onDownloadReportMarkdown={downloadReportMarkdown}
        onOpenNote={openNote}
        onOpenProject={(projectId) => {
          const project = (state?.projects || []).find((candidate) => candidate.id === projectId);
          if (project) openProject(project);
        }}
        onOpenMemory={openMemoryItem}
        onCreateReminder={async (taskId, remindAt) => {
          try {
            await api(`/api/tasks/${taskId}/reminders`, {
              method: "POST",
              body: JSON.stringify({ remind_at: remindAt }),
            });
            setToast("Reminder set.");
            if (selectedMemory?.sectionId === "tasks" && selectedMemory.item?.id === taskId) {
              await openMemoryItem("tasks", selectedMemory.item);
            }
          } catch (err) {
            setToast(err instanceof Error ? err.message : "Could not set reminder");
          }
        }}
        onCreateTaskForCompany={async (companyId, title, dueAt, assigneeId) => {
          if (!workspaceId) return;
          const body: Record<string, unknown> = { title, company_ids: [companyId] };
          if (dueAt) body.due_at = dueAt;
          if (assigneeId) {
            body.person_ids = [assigneeId];
            body.assignee_id = assigneeId;
          }
          try {
            await api(`/api/workspaces/${workspaceId}/tasks`, { method: "POST", body: JSON.stringify(body) });
            setToast("Task added.");
            await refreshWorkspaceData();
            if (selectedMemory?.sectionId === "companies" && selectedMemory.item?.id === companyId) {
              await openMemoryItem("companies", selectedMemory.item);
            }
          } catch (err) {
            setToast(err instanceof Error ? err.message : "Could not create task");
          }
        }}
      />

      <LinkedSheet
        open={sheetOpen}
        note={selectedNote}
        projects={state?.projects || []}
        people={state?.people || []}
        onClose={closeNoteSheet}
        onCopy={() => selectedNote && copyBrief("note", selectedNote)}
        onCopyLink={() => selectedNote && copyRouteLink({ kind: "note", id: selectedNote.id }, "Note")}
        onFullCopy={() => selectedNote && copyBrief("note", selectedNote, "full")}
        onFlag={() => selectedNote && flag({ note_id: selectedNote.id })}
        onProcess={() => selectedNote && processWithAI(selectedNote.id)}
        onBlockSender={() => selectedNote && blockSender(selectedNote)}
        onArchive={async () => {
          if (!selectedNote) return;
          const target = selectedNote.archived_at ? "restore" : "archive";
          try {
            await api(`/api/notes/${selectedNote.id}/${target}`, { method: "POST" });
            setToast(target === "archive" ? "Note archived." : "Note restored.");
            closeNoteSheet();
            await refreshWorkspaceData();
          } catch (err) {
            setToast(err instanceof Error ? err.message : "Could not update note");
          }
        }}
        onUpdate={updateNote}
        onSetProjects={setNoteProjects}
        onReviewDecision={async (reviewId, decision) => {
          await decideReview(reviewId, decision);
          if (selectedNote) await openNote(selectedNote.id);
        }}
        onSuggestionQueued={() => setToast("Suggestion sent to Review.")}
        onOpenMemory={openMemoryItem}
        onOpenReview={openReviewQueue}
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

      {paletteOpen && (
        <div
          className="palette-backdrop"
          role="dialog"
          aria-modal="true"
          aria-label="Quick switcher"
          onClick={() => setPaletteOpen(false)}
        >
          <div className="palette" onClick={(e) => e.stopPropagation()}>
            <div className="palette-input-row">
              <Search size={16} />
              <input
                ref={paletteInputRef}
                value={paletteQuery}
                onChange={(e) => schedulePaletteSearch(e.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "ArrowDown") {
                    event.preventDefault();
                    setPaletteIndex((i) => Math.min(i + 1, Math.max(paletteResults.length - 1, 0)));
                  } else if (event.key === "ArrowUp") {
                    event.preventDefault();
                    setPaletteIndex((i) => Math.max(i - 1, 0));
                  } else if (event.key === "Enter") {
                    const target = paletteResults[paletteIndex];
                    if (target) {
                      setPaletteOpen(false);
                      openGraphNode(target).catch((err) => setToast(err instanceof Error ? err.message : "Could not open"));
                    }
                  }
                }}
                placeholder="Jump to a note, person, project, task..."
                aria-label="Quick switcher search"
                autoComplete="off"
                spellCheck={false}
              />
              <span className="palette-kbd">Esc</span>
            </div>
            <div className="palette-results" role="listbox" aria-label="Quick switcher results">
              {paletteLoading && !paletteResults.length && <div className="palette-empty">Searching...</div>}
              {!paletteLoading && !paletteResults.length && paletteQuery.trim() && (
                <div className="palette-empty">No matches.</div>
              )}
              {!paletteQuery.trim() && (
                <div className="palette-empty palette-hint">
                  Type to search across notes, people, companies, projects, tasks, meetings, reports.
                  <br />
                  <span className="muted">Use <span className="palette-kbd">↑</span> <span className="palette-kbd">↓</span> to navigate, <span className="palette-kbd">Enter</span> to open.</span>
                </div>
              )}
              {paletteResults.map((row, idx) => (
                <button
                  key={`${row.kind}-${row.id}`}
                  type="button"
                  className={`palette-row ${idx === paletteIndex ? "active" : ""}`}
                  role="option"
                  aria-selected={idx === paletteIndex}
                  onMouseEnter={() => setPaletteIndex(idx)}
                  onClick={() => {
                    setPaletteOpen(false);
                    openGraphNode(row).catch((err) => setToast(err instanceof Error ? err.message : "Could not open"));
                  }}
                >
                  <span className={`palette-kind palette-kind-${row.kind}`}>{paletteKindLabel(row.kind)}</span>
                  <span className="palette-title">{row.title}</span>
                  {row.subtitle && <span className="palette-subtitle">{row.subtitle}</span>}
                </button>
              ))}
            </div>
          </div>
        </div>
      )}
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

const TASK_BOARD_COLUMNS: Array<{ status: "todo" | "doing" | "blocked"; label: string }> = [
  { status: "todo", label: "To do" },
  { status: "doing", label: "Doing" },
  { status: "blocked", label: "Blocked" },
];

function TaskStatusBoard({
  tasks,
  emptyMessage,
  onOpenTask,
  onStatusChange,
}: {
  tasks: any[];
  emptyMessage: string;
  onOpenTask: (task: any) => void;
  onStatusChange: (taskId: string, status: "todo" | "doing" | "blocked" | "done") => Promise<void>;
}) {
  const byStatus = TASK_BOARD_COLUMNS.map((col) => ({
    ...col,
    items: tasks.filter((task) => (task.status || "todo") === col.status),
  }));
  if (!tasks.length) {
    return <p className="dashboard-empty memory-empty">{emptyMessage}</p>;
  }
  return (
    <div className="task-board" role="tabpanel" aria-label="Tasks by status">
      {byStatus.map((column) => (
        <div className={`task-board-column task-board-${column.status}`} key={column.status}>
          <header>
            <span className="task-board-label">{column.label}</span>
            <strong>{column.items.length}</strong>
          </header>
          <div className="task-board-stack">
            {column.items.length ? (
              column.items.map((task) => {
                const dueAt = task.due_at || task.due_date;
                const priorityRaw = String(task.priority || "").toLowerCase();
                const priorityLabel = priorityRaw && priorityRaw !== "p3" ? priorityRaw.toUpperCase() : "";
                const priorityTone = priorityRaw === "p1" || priorityRaw === "p2" ? "urgent" : priorityRaw === "p5" ? "muted" : "";
                const overdue = isOverdue(dueAt);
                return (
                  <article
                    key={task.id}
                    className="task-board-card"
                    role="button"
                    tabIndex={0}
                    onClick={() => onOpenTask(task)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        onOpenTask(task);
                      }
                    }}
                  >
                    <div className="task-board-card-title">{task.title || "Untitled task"}</div>
                    <div className="task-board-card-meta">
                      {task.assignee_name && <span className="task-board-assignee">{task.assignee_name}</span>}
                      {!task.assignee_name && <span className="task-board-unassigned">Unassigned</span>}
                      {priorityLabel && (
                        <span className={`task-board-priority${priorityTone ? ` task-board-priority-${priorityTone}` : ""}`}>{priorityLabel}</span>
                      )}
                      {dueAt && (
                        <span className={`task-board-due${overdue ? " task-board-due-overdue" : ""}`}>
                          {overdue ? "Overdue " : ""}Due {humanRelativeTime(dueAt)}
                        </span>
                      )}
                    </div>
                    <div className="task-board-card-actions" onClick={(event) => event.stopPropagation()}>
                      {column.status !== "doing" && (
                        <button type="button" onClick={() => onStatusChange(task.id, "doing")} aria-label={`Move ${task.title} to Doing`}>
                          → Doing
                        </button>
                      )}
                      {column.status !== "blocked" && (
                        <button type="button" onClick={() => onStatusChange(task.id, "blocked")} aria-label={`Move ${task.title} to Blocked`}>
                          → Blocked
                        </button>
                      )}
                      <button type="button" className="task-board-done" onClick={() => onStatusChange(task.id, "done")} aria-label={`Mark ${task.title} done`}>
                        <Check size={13} /> Done
                      </button>
                    </div>
                  </article>
                );
              })
            ) : (
              <p className="task-board-empty">No tasks in this column.</p>
            )}
          </div>
        </div>
      ))}
    </div>
  );
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
        {isTask && Number(item.priority) <= 2 && Number(item.priority) >= 1 && (
          <span className="priority-chip priority-high">P{Number(item.priority)}</span>
        )}
        {isTask && Number(item.priority) === 5 && (
          <span className="priority-chip priority-low">Low</span>
        )}
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
  onOpenSource,
  allProjects,
  allPeople,
  allCompanies,
}: {
  open: boolean;
  items: any[];
  reviewCount: number;
  onClose: () => void;
  onDecide: (
    reviewId: string,
    decision: "accept" | "reject",
    payload?: any,
    options?: { openAfterAccept?: boolean },
  ) => Promise<void>;
  onOpenSource: (noteId: string) => void;
  allProjects: any[];
  allPeople: any[];
  allCompanies: any[];
}) {
  const reviewItems = useMemo(() => (Array.isArray(items) ? items : []), [items]);
  const [payloadDrafts, setPayloadDrafts] = useState<Record<string, any>>({});
  const [filterKind, setFilterKind] = useState<string>("all");
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [bulkBusy, setBulkBusy] = useState(false);

  useEffect(() => {
    if (!open) setSelectedIds(new Set());
  }, [open]);

  useEffect(() => {
    if (!open) return;
    setPayloadDrafts((current) => {
      const next: Record<string, any> = {};
      for (const item of reviewItems) {
        if (current[item.id]) {
          next[item.id] = current[item.id];
          continue;
        }
        const payload = item.payload || {};
        const seededProjects = Array.isArray(payload.project_ids) && payload.project_ids.length
          ? payload.project_ids
          : Array.isArray(item.projects)
            ? item.projects.map((project: any) => String(project.id))
            : [];
        const seededPeople = Array.isArray(payload.person_ids) && payload.person_ids.length
          ? payload.person_ids
          : Array.isArray(item.source_people)
            ? item.source_people.map((person: any) => String(person.id))
            : [];
        const seededCompanies = Array.isArray(payload.company_ids) && payload.company_ids.length
          ? payload.company_ids
          : Array.isArray(item.source_companies)
            ? item.source_companies.map((company: any) => String(company.id))
            : [];
        next[item.id] = {
          ...payload,
          project_ids: seededProjects,
          person_ids: seededPeople,
          company_ids: seededCompanies,
        };
      }
      return next;
    });
  }, [open, reviewItems]);

  function toggleLinkId(itemId: string, field: "project_ids" | "person_ids" | "company_ids", id: string) {
    setPayloadDrafts((current) => {
      const draft = current[itemId] || {};
      const arr: string[] = Array.isArray(draft[field]) ? draft[field] : [];
      const next = arr.includes(id) ? arr.filter((existing) => existing !== id) : [...arr, id];
      return { ...current, [itemId]: { ...draft, [field]: next } };
    });
  }

  const kindCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const item of reviewItems) {
      const k = String(item.entity_kind || "other");
      counts[k] = (counts[k] || 0) + 1;
    }
    return counts;
  }, [reviewItems]);

  const filteredItems = useMemo(() => {
    if (filterKind === "all") return reviewItems;
    return reviewItems.filter((item) => item.entity_kind === filterKind);
  }, [reviewItems, filterKind]);

  if (!open) return null;

  function updatePayload(itemId: string, key: string, value: string) {
    setPayloadDrafts((current) => ({
      ...current,
      [itemId]: nextReviewPayload(current[itemId] || {}, key, value),
    }));
  }

  const filterChips: { id: string; label: string }[] = [
    { id: "all", label: "All" },
    ...Object.keys(kindCounts)
      .sort()
      .map((id) => ({ id, label: id })),
  ];

  function toggleSelected(itemId: string) {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (next.has(itemId)) next.delete(itemId);
      else next.add(itemId);
      return next;
    });
  }

  function selectAllVisible() {
    setSelectedIds((current) => {
      const next = new Set(current);
      for (const item of filteredItems) next.add(item.id);
      return next;
    });
  }

  function clearSelection() {
    setSelectedIds(new Set());
  }

  async function bulkDecide(decision: "accept" | "reject") {
    if (selectedIds.size === 0 || bulkBusy) return;
    setBulkBusy(true);
    const ids = Array.from(selectedIds);
    try {
      for (const id of ids) {
        const item = reviewItems.find((candidate) => candidate.id === id);
        if (!item) continue;
        const draft = payloadDrafts[id] || item.payload || {};
        const isStructured = STRUCTURED_REVIEW_KINDS.has(item.entity_kind);
        if (decision === "accept") {
          await onDecide(id, "accept", isStructured ? draft : undefined);
        } else {
          await onDecide(id, "reject");
        }
      }
    } finally {
      clearSelection();
      setBulkBusy(false);
    }
  }

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
        {!!reviewItems.length && (
          <div className="review-filter-row" role="tablist" aria-label="Filter review queue by kind">
            {filterChips.map((chip) => {
              const count = chip.id === "all" ? reviewItems.length : kindCounts[chip.id] || 0;
              const active = filterKind === chip.id;
              return (
                <button
                  key={chip.id}
                  type="button"
                  role="tab"
                  aria-selected={active}
                  className={active ? "review-filter-chip active" : "review-filter-chip"}
                  onClick={() => setFilterKind(chip.id)}
                >
                  {chip.label}
                  <strong>{count}</strong>
                </button>
              );
            })}
          </div>
        )}
        {!!reviewItems.length && (
          <div className="review-bulk-bar" role="toolbar" aria-label="Bulk review actions">
            {selectedIds.size === 0 ? (
              <button type="button" className="review-bulk-link" onClick={selectAllVisible}>
                Select all {filteredItems.length} {filterKind === "all" ? "" : filterKind} suggestions
              </button>
            ) : (
              <>
                <span className="review-bulk-count">
                  <strong>{selectedIds.size}</strong> selected
                </span>
                <button
                  type="button"
                  className="review-bulk-action primary"
                  disabled={bulkBusy}
                  onClick={() => bulkDecide("accept")}
                >
                  <Check size={14} /> Accept selected
                </button>
                <button
                  type="button"
                  className="review-bulk-action"
                  disabled={bulkBusy}
                  onClick={() => bulkDecide("reject")}
                >
                  <X size={14} /> Reject selected
                </button>
                <button type="button" className="review-bulk-link" onClick={clearSelection}>
                  Clear
                </button>
              </>
            )}
          </div>
        )}
        <div className="review-sheet-list">
          {filteredItems.map((item) => {
            const draft = payloadDrafts[item.id] || item.payload || {};
            const isStructured = STRUCTURED_REVIEW_KINDS.has(item.entity_kind);
            const fields = STRUCTURED_REVIEW_FIELDS[item.entity_kind] || [];
            const confidence = Number(item.payload?.confidence || item.confidence || 0);
            const sourceNoteId = item.entity_id;
            const sourceNoteKind = item.source_note_kind;
            const evidenceSource = sourceNoteKind === "email" ? "email" : "ai";
            const evidenceLabel = sourceNoteKind === "email" ? "From email" : "AI suggestion";
            const reasonText = item.reason ? humanReviewReason(item.reason) : null;
            const headlineFallback = item.entity_kind ? `New ${item.entity_kind}` : "Suggestion";
            return (
              <article key={item.id} className={selectedIds.has(item.id) ? "review-card-selected" : ""}>
                <header className="review-card-head">
                  <label className="review-select" aria-label={`Select ${item.entity_kind} suggestion for bulk action`}>
                    <input
                      type="checkbox"
                      checked={selectedIds.has(item.id)}
                      onChange={() => toggleSelected(item.id)}
                    />
                  </label>
                  <strong>
                    {draft.name ||
                      draft.title ||
                      item.payload?.name ||
                      item.payload?.title ||
                      headlineFallback}
                  </strong>
                  <div className="review-badges">
                    <span className={`evidence-badge evidence-${evidenceSource}`}>{evidenceLabel}</span>
                    {confidence > 0 && (
                      <span className="evidence-badge evidence-confidence">
                        {Math.round(confidence * 100)}%
                      </span>
                    )}
                    <span className="evidence-badge evidence-kind">{item.entity_kind}</span>
                  </div>
                </header>
                {reasonText && <span className="review-reason">{reasonText}</span>}
                {item.source_note_title && <small>From: {item.source_note_title}</small>}
                {item.source_snippet && <p>{item.source_snippet}</p>}
                {isStructured && (
                  <div className="sheet-editor">
                    {fields.map((field) => (
                      <label key={field.key}>
                        {field.label}
                        {field.multiline ? (
                          <textarea
                            value={reviewPayloadValue(draft[field.key])}
                            onChange={(event) => updatePayload(item.id, field.key, event.target.value)}
                            rows={2}
                            aria-label={field.label}
                          />
                        ) : (
                          <input
                            value={reviewPayloadValue(draft[field.key])}
                            onChange={(event) => updatePayload(item.id, field.key, event.target.value)}
                            aria-label={field.label}
                          />
                        )}
                      </label>
                    ))}
                  </div>
                )}
                {isStructured && (
                  <div className="review-link-pickers">
                    {!!allProjects.length && (
                      <div className="review-link-row" aria-label="Linked projects">
                        <span className="review-link-label">Projects</span>
                        <div className="review-link-chips">
                          {allProjects.slice(0, 8).map((project) => {
                            const active = Array.isArray(draft.project_ids) && draft.project_ids.includes(project.id);
                            return (
                              <button
                                key={project.id}
                                type="button"
                                className={active ? "review-link-chip active" : "review-link-chip"}
                                onClick={() => toggleLinkId(item.id, "project_ids", project.id)}
                              >
                                <span className="dot" style={{ background: project.color_hex || "#7c3aed" }} />
                                {project.name}
                              </button>
                            );
                          })}
                        </div>
                      </div>
                    )}
                    {!!allPeople.length && (
                      <div className="review-link-row" aria-label="Linked people">
                        <span className="review-link-label">People</span>
                        <div className="review-link-chips">
                          {allPeople.slice(0, 8).map((person) => {
                            const active = Array.isArray(draft.person_ids) && draft.person_ids.includes(person.id);
                            return (
                              <button
                                key={person.id}
                                type="button"
                                className={active ? "review-link-chip active" : "review-link-chip"}
                                onClick={() => toggleLinkId(item.id, "person_ids", person.id)}
                              >
                                {person.name}
                              </button>
                            );
                          })}
                        </div>
                      </div>
                    )}
                    {!!allCompanies.length && (
                      <div className="review-link-row" aria-label="Linked companies">
                        <span className="review-link-label">Companies</span>
                        <div className="review-link-chips">
                          {allCompanies.slice(0, 8).map((company) => {
                            const active = Array.isArray(draft.company_ids) && draft.company_ids.includes(company.id);
                            return (
                              <button
                                key={company.id}
                                type="button"
                                className={active ? "review-link-chip active" : "review-link-chip"}
                                onClick={() => toggleLinkId(item.id, "company_ids", company.id)}
                              >
                                {company.name}
                              </button>
                            );
                          })}
                        </div>
                      </div>
                    )}
                  </div>
                )}
                {!isStructured && !!item.projects?.length && (
                  <div className="review-projects">
                    {item.projects.slice(0, 3).map((project: any) => (
                      <span key={project.id}>
                        <span className="dot" style={{ background: project.color_hex || "#7c3aed" }} />
                        {project.name}
                      </span>
                    ))}
                  </div>
                )}
                <div className="review-card-actions">
                  <button
                    type="button"
                    className="primary"
                    onClick={() => onDecide(item.id, "accept", isStructured ? draft : undefined)}
                  >
                    <Check size={15} /> Accept
                  </button>
                  {isStructured && (
                    <button
                      type="button"
                      className="primary"
                      onClick={() => onDecide(item.id, "accept", draft, { openAfterAccept: true })}
                    >
                      <Check size={15} /> Accept &amp; open
                    </button>
                  )}
                  <button type="button" onClick={() => onDecide(item.id, "reject")}>
                    <X size={15} /> Reject
                  </button>
                  {sourceNoteId && (
                    <button
                      type="button"
                      className="ghost"
                      onClick={() => {
                        onClose();
                        onOpenSource(sourceNoteId);
                      }}
                    >
                      <FileText size={15} /> Open source note
                    </button>
                  )}
                </div>
              </article>
            );
          })}
          {!reviewItems.length && <p className="muted">Caught up.</p>}
          {!!reviewItems.length && filteredItems.length === 0 && (
            <p className="muted">No {filterKind} suggestions right now.</p>
          )}
        </div>
      </aside>
    </div>
  );
}

function truncateInline(text: string, max: number): string {
  if (!text) return "";
  const collapsed = String(text).replace(/\s+/g, " ").trim();
  if (collapsed.length <= max) return collapsed;
  return `${collapsed.slice(0, max - 1).trimEnd()}…`;
}

function pipelineStatusForNote(note: any): { label: string; tone: string } | null {
  const status = note?.ai_processing_status;
  if (status === "processing") return { label: "Processing", tone: "info" };
  if (status === "failed") return { label: "Failed", tone: "danger" };
  if (status === "processed") return { label: "Accepted", tone: "ok" };
  if (status === "skipped" || status === "unprocessed") return { label: "Awaiting", tone: "neutral" };
  return null;
}

function daysSinceNow(value?: string | null): number | null {
  if (!value) return null;
  const ts = new Date(value).getTime();
  if (Number.isNaN(ts)) return null;
  const diff = Date.now() - ts;
  return Math.max(0, Math.floor(diff / (1000 * 60 * 60 * 24)));
}

function isOverdue(value?: string | null): boolean {
  if (!value) return false;
  const ts = new Date(value).getTime();
  if (Number.isNaN(ts)) return false;
  return ts < Date.now();
}

function eventAgeBucket(value?: string | null): "Today" | "Yesterday" | "This week" | "Earlier" {
  const days = daysSinceNow(value);
  if (days === null) return "Earlier";
  if (days === 0) return "Today";
  if (days === 1) return "Yesterday";
  if (days <= 7) return "This week";
  return "Earlier";
}

function humanRelativeTime(value?: string | null): string {
  const days = daysSinceNow(value);
  if (days === null) return "";
  if (days === 0) return "today";
  if (days === 1) return "1 day ago";
  if (days < 7) return `${days} days ago`;
  if (days < 30) return `${Math.floor(days / 7)} weeks ago`;
  if (days < 365) return `${Math.floor(days / 30)} months ago`;
  return `${Math.floor(days / 365)} years ago`;
}

function linkedViaBadge(value?: string | null): { label: string; className: string } | null {
  const normalised = (value || "").toLowerCase();
  if (!normalised) return null;
  if (normalised === "ai" || normalised === "ai_extraction" || normalised === "review_accept") {
    return { label: "AI", className: "evidence-ai" };
  }
  if (normalised === "email" || normalised === "inbound_email") {
    return { label: "Email", className: "evidence-email" };
  }
  if (normalised === "collaborator" || normalised === "collaborator_suggestion") {
    return { label: "Collab", className: "evidence-collaborator" };
  }
  if (normalised === "manual" || normalised === "user") {
    return { label: "Manual", className: "evidence-manual" };
  }
  return null;
}

function personSourceLabel(source?: string, state?: string): string | null {
  const src = (source || "").toLowerCase();
  if (src === "manual" || src === "user" || src === "human") return "Manual";
  if (src === "email" || src === "inbound_email") return "Email";
  if (src === "collaborator_suggestion" || src === "collaborator") return "Collaborator";
  if (src === "ai" || src === "ai_extraction") return "AI";
  if (state === "auto_linked") return "AI";
  if (state === "confirmed") return "Manual";
  return null;
}

function personSourceBadgeClass(source?: string, state?: string): string {
  const label = personSourceLabel(source, state);
  if (label === "AI") return "evidence-ai";
  if (label === "Email") return "evidence-email";
  if (label === "Collaborator") return "evidence-collaborator";
  if (label === "Manual") return "evidence-manual";
  return "";
}

function ProfileNameEditor({ initial, onSave }: { initial: string; onSave: (next: string) => Promise<void> }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(initial);
  useEffect(() => { setValue(initial); }, [initial]);
  if (!editing) {
    return (
      <strong className="profile-name-display">
        {initial}
        <button type="button" className="profile-name-edit" aria-label="Rename" onClick={() => setEditing(true)}>
          <Settings size={13} />
        </button>
      </strong>
    );
  }
  return (
    <span className="profile-name-edit-row">
      <input
        value={value}
        onChange={(event) => setValue(event.target.value)}
        aria-label="New name"
        autoFocus
        onKeyDown={(event) => {
          if (event.key === "Escape") { setEditing(false); setValue(initial); }
          if (event.key === "Enter" && value.trim() && value.trim() !== initial) {
            setEditing(false);
            void onSave(value.trim());
          }
        }}
      />
      <button
        type="button"
        disabled={!value.trim() || value.trim() === initial}
        onClick={() => {
          setEditing(false);
          void onSave(value.trim());
        }}
      >
        <Check size={14} /> Save
      </button>
      <button type="button" onClick={() => { setEditing(false); setValue(initial); }}>
        <X size={14} /> Cancel
      </button>
    </span>
  );
}

function humanReviewReason(reason: string): string {
  const map: Record<string, string> = {
    new_person: "AI thinks this is a new person",
    person_match: "AI matched to an existing person",
    project_match: "AI matched to an existing project",
    new_project: "AI thinks this is a new project",
    new_task: "AI extracted a task",
    new_meeting: "AI extracted a meeting",
    new_report: "AI extracted a report",
    new_workflow: "AI extracted a workflow",
    new_company: "AI extracted a company",
    collaborator_suggestion: "Suggested by a collaborator",
  };
  if (map[reason]) return map[reason];
  return reason.replace(/_/g, " ");
}

function MemoryDetailSheet({
  memory,
  allProjects,
  allPeople,
  allCompanies,
  onClose,
  onTaskStatusChange,
  onUpdateMemory,
  onUpdateReminder,
  onCopyBrief,
  onCopyLink,
  onCopyReportMarkdown,
  onDownloadReportMarkdown,
  onOpenNote,
  onOpenProject,
  onOpenMemory,
  onCreateTaskForCompany,
  onCreateReminder,
}: {
  memory: { sectionId: string; item: any } | null;
  allProjects: any[];
  allPeople: any[];
  allCompanies: any[];
  onClose: () => void;
  onTaskStatusChange: (taskId: string, status: "todo" | "doing" | "blocked" | "done") => Promise<void>;
  onUpdateMemory: (sectionId: string, itemId: string, payload: Record<string, unknown>) => Promise<void>;
  onUpdateReminder: (reminderId: string, payload: Record<string, unknown>) => Promise<void>;
  onCopyBrief: (sectionId: string, item: any, variant: "quick" | "full") => Promise<void>;
  onCopyLink: (sectionId: string, item: any) => Promise<void>;
  onCopyReportMarkdown: (item: any) => Promise<void>;
  onDownloadReportMarkdown: (item: any) => void;
  onOpenNote: (noteId: string) => Promise<void>;
  onOpenProject: (projectId: string) => void;
  onOpenMemory: (sectionId: string, item: any) => Promise<void>;
  onCreateTaskForCompany?: (companyId: string, title: string, dueAt: string | null, assigneeId: string | null) => Promise<void>;
  onCreateReminder?: (taskId: string, remindAt: string) => Promise<void>;
}) {
  const sectionId = memory?.sectionId || "";
  const item = memory?.item || {};
  const title = item.title || item.name || "Memory";
  const body = item.description || item.summary || item.body || item.subtitle || "";
  const [draftTitle, setDraftTitle] = useState(title);
  const [draftBody, setDraftBody] = useState(body);
  const [draftStatus, setDraftStatus] = useState(item.status || "");
  const [draftPriority, setDraftPriority] = useState<string>(item.priority ? String(item.priority) : "3");
  const [newReminderAt, setNewReminderAt] = useState<string>("");
  const [draftDate, setDraftDate] = useState(inputDate(item.due_at || item.occurred_at || null));
  const [draftProjectIds, setDraftProjectIds] = useState<string[]>(relationIds(item.projects));
  const [draftPersonIds, setDraftPersonIds] = useState<string[]>(relationIds(item.people));
  const [draftCompanyIds, setDraftCompanyIds] = useState<string[]>(relationIds(item.companies));
  const initialAssignee = useMemo(() => {
    if (item.assignee_id) return String(item.assignee_id);
    const assigneePerson = (item.people || []).find((person: any) => person.relation === "assignee");
    return assigneePerson ? String(assigneePerson.id) : "";
  }, [item.assignee_id, item.people]);
  const [draftAssigneeId, setDraftAssigneeId] = useState<string>(initialAssignee);
  const [companyQuickTaskTitle, setCompanyQuickTaskTitle] = useState("");
  const [companyQuickTaskDue, setCompanyQuickTaskDue] = useState("");
  const [companyQuickTaskAssignee, setCompanyQuickTaskAssignee] = useState("");
  useEffect(() => {
    setDraftTitle(title);
    setDraftBody(body);
    setDraftStatus(item.status || "");
    setDraftPriority(item.priority ? String(item.priority) : "3");
    setDraftDate(inputDate(item.due_at || item.occurred_at || null));
    setDraftProjectIds(relationIds(item.projects));
    setDraftPersonIds(relationIds(item.people));
    setDraftCompanyIds(relationIds(item.companies));
    setDraftAssigneeId(initialAssignee);
  }, [body, initialAssignee, item.companies, item.due_at, item.id, item.occurred_at, item.people, item.priority, item.projects, item.status, title]);
  if (!memory) return null;
  const projects = item.projects || [];
  const people = item.people || [];
  const notes = item.notes || [];
  const tasks = item.tasks || [];
  const meetings = item.meetings || [];
  const companies = item.companies || [];
  const reminders = Array.isArray(item.reminders) && item.reminders.length
    ? item.reminders
    : item.reminder_id
      ? [{
          id: item.reminder_id,
          remind_at: item.remind_at,
          state: item.reminder_state || "pending",
          snoozed_until: item.snoozed_until,
          attention_at: item.attention_at,
        }]
      : [];
  const sourceCounts = item.source_counts || null;
  const isTask = sectionId === "tasks";
  const sourceNoteFallback = Boolean(item.note_id && item.id === item.note_id && ["meetings", "reports"].includes(sectionId));
  const canEdit = ["tasks", "meetings", "reports", "workflows", "companies"].includes(sectionId) && !sourceNoteFallback;
  const canCopyBrief = Boolean(item.id) && canEdit;
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
      const priorityNum = Number(draftPriority);
      if (!Number.isNaN(priorityNum) && priorityNum >= 1 && priorityNum <= 5) {
        payload.priority = priorityNum;
      }
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
    if (["tasks", "meetings", "reports", "workflows", "companies"].includes(sectionId)) {
      payload.project_ids = draftProjectIds;
      payload.person_ids = draftPersonIds;
    }
    if (["tasks", "meetings", "reports", "workflows"].includes(sectionId)) payload.company_ids = draftCompanyIds;
    if (sectionId === "tasks") {
      payload.assignee_id = draftAssigneeId || null;
    }
    await onUpdateMemory(sectionId, item.id, payload);
  }
  function snoozeUntilTomorrow() {
    const tomorrow = new Date();
    tomorrow.setDate(tomorrow.getDate() + 1);
    tomorrow.setHours(9, 0, 0, 0);
    return tomorrow.toISOString();
  }
  const kindLabel: Record<string, string> = {
    tasks: "Task",
    meetings: "Meeting/call",
    reports: "Report/brief",
    workflows: "Workflow",
    companies: "Company",
  };
  const editableProjects = allProjects.filter((project) => project.kind !== "inbox");
  const editablePeople = allPeople.filter((person) => !person.clerk_user_id);
  const editableCompanies = allCompanies;
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
        {canCopyBrief && (
          <div className="sheet-actions memory-brief-actions">
            <button type="button" onClick={() => onCopyBrief(sectionId, item, "quick")}>
              <Copy size={16} /> Quick brief
            </button>
            <button type="button" onClick={() => onCopyBrief(sectionId, item, "full")}>
              <FileText size={16} /> Full brief
            </button>
            <button type="button" onClick={() => onCopyLink(sectionId, item)}>
              <Link size={16} /> Copy link
            </button>
            {sectionId === "reports" && (
              <>
                <button type="button" onClick={() => onCopyReportMarkdown(item)}>
                  <Copy size={16} /> Copy markdown
                </button>
                <button type="button" onClick={() => onDownloadReportMarkdown(item)}>
                  <Download size={16} /> Download .md
                </button>
              </>
            )}
          </div>
        )}
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
            {isTask && (
              <select value={draftPriority} onChange={(event) => setDraftPriority(event.target.value)} aria-label="Task priority">
                <option value="1">P1 - urgent</option>
                <option value="2">P2 - high</option>
                <option value="3">P3 - normal</option>
                <option value="4">P4 - low</option>
                <option value="5">P5 - someday</option>
              </select>
            )}
            <textarea value={draftBody} onChange={(event) => setDraftBody(event.target.value)} rows={4} aria-label="Memory body" />
            {!!editableProjects.length && (
              <div className="relation-editor" role="group" aria-label="Linked projects">
                <strong>Projects</strong>
                {editableProjects.map((project) => (
                  <label key={project.id} className={draftProjectIds.includes(project.id) ? "relation-chip active" : "relation-chip"}>
                    <input
                      type="checkbox"
                      checked={draftProjectIds.includes(project.id)}
                      onChange={() => setDraftProjectIds((current) => toggleId(current, project.id))}
                    />
                    <span className="dot" style={{ background: project.color_hex || "#7c3aed" }} />
                    {project.name}
                  </label>
                ))}
              </div>
            )}
            {isTask && !!editablePeople.length && (
              <label className="relation-assignee" aria-label="Task assignee">
                <span>Assigned to</span>
                <select
                  value={draftAssigneeId}
                  onChange={(event) => {
                    const next = event.target.value;
                    setDraftAssigneeId(next);
                    if (next && !draftPersonIds.includes(next)) {
                      setDraftPersonIds((current) => [...current, next]);
                    }
                  }}
                >
                  <option value="">Nobody yet</option>
                  {editablePeople.map((person) => (
                    <option key={person.id} value={person.id}>{person.name}</option>
                  ))}
                </select>
              </label>
            )}
            {!!editablePeople.length && (
              <div className="relation-editor" role="group" aria-label="Linked people">
                <strong>{isTask ? "Watchers" : "People"}</strong>
                {editablePeople.map((person) => {
                  const isAssignee = isTask && person.id === draftAssigneeId;
                  return (
                  <label key={person.id} className={draftPersonIds.includes(person.id) ? "relation-chip active" : "relation-chip"}>
                    <input
                      type="checkbox"
                      checked={draftPersonIds.includes(person.id)}
                      onChange={() => setDraftPersonIds((current) => toggleId(current, person.id))}
                      disabled={isAssignee}
                    />
                    {person.name}
                    {isAssignee && <span className="mini-relation-tag">assignee</span>}
                  </label>
                );
                })}
              </div>
            )}
            {["tasks", "meetings", "reports", "workflows"].includes(sectionId) && !!editableCompanies.length && (
              <div className="relation-editor" role="group" aria-label="Linked companies">
                <strong>Companies</strong>
                {editableCompanies.map((company) => (
                  <label key={company.id} className={draftCompanyIds.includes(company.id) ? "relation-chip active" : "relation-chip"}>
                    <input
                      type="checkbox"
                      checked={draftCompanyIds.includes(company.id)}
                      onChange={() => setDraftCompanyIds((current) => toggleId(current, company.id))}
                    />
                    {company.name}
                  </label>
                ))}
              </div>
            )}
            <button type="button" onClick={saveEdits} disabled={!draftTitle.trim()}>
              <Check size={15} /> Save memory
            </button>
          </div>
        )}
        {!canEdit && body && <p>{body}</p>}
        {(() => {
          const sourcePayload = item.source_payload || {};
          const decisions = Array.isArray(sourcePayload.decisions) ? sourcePayload.decisions : [];
          const hints = Array.isArray(sourcePayload.relationship_hints) ? sourcePayload.relationship_hints : [];
          const followUps = Array.isArray(sourcePayload.follow_ups || sourcePayload.followups) ? sourcePayload.follow_ups || sourcePayload.followups : [];
          const allEmpty = decisions.length === 0 && hints.length === 0 && followUps.length === 0;
          if (allEmpty) return null;
          return (
            <div className="ai-extracted-extras">
              {decisions.length > 0 && (
                <div className="ai-extracted-block ai-extracted-decisions">
                  <strong>Decisions</strong>
                  <ul>
                    {decisions.slice(0, 6).map((line: any, idx: number) => (
                      <li key={`decision-${idx}`}>{String(line)}</li>
                    ))}
                  </ul>
                </div>
              )}
              {followUps.length > 0 && (
                <div className="ai-extracted-block ai-extracted-followups">
                  <strong>Follow-ups</strong>
                  <ul>
                    {followUps.slice(0, 6).map((line: any, idx: number) => (
                      <li key={`followup-${idx}`}>{String(line)}</li>
                    ))}
                  </ul>
                </div>
              )}
              {hints.length > 0 && (
                <div className="ai-extracted-block ai-extracted-hints">
                  <strong>AI relationship hints</strong>
                  <ul>
                    {hints.slice(0, 6).map((line: any, idx: number) => (
                      <li key={`hint-${idx}`}>{String(line)}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          );
        })()}
        {isTask && (
          <div className="memory-status-actions">
            <button disabled={item.status === "todo"} onClick={() => onTaskStatusChange(item.id, "todo")}>Todo</button>
            <button disabled={item.status === "doing"} onClick={() => onTaskStatusChange(item.id, "doing")}>Doing</button>
            <button disabled={item.status === "blocked"} onClick={() => onTaskStatusChange(item.id, "blocked")}>Blocked</button>
            <button disabled={item.status === "done"} onClick={() => onTaskStatusChange(item.id, "done")}><CheckCircle2 size={15} /> Done</button>
          </div>
        )}
        {isTask && !!reminders.length && (
          <div className="reminder-panel">
            <strong>Reminders</strong>
            {reminders.map((reminder: any) => (
              <article key={reminder.id}>
                <span>
                  <Bell size={15} />
                  {new Date(reminder.snoozed_until || reminder.remind_at || reminder.attention_at).toLocaleString()}
                </span>
                <small>{reminder.state || "pending"}</small>
                <div>
                  <button type="button" onClick={() => onUpdateReminder(reminder.id, { state: "snoozed", snoozed_until: snoozeUntilTomorrow() })}>
                    <CalendarDays size={15} /> Snooze 1 day
                  </button>
                  {reminder.state === "snoozed" && (
                    <button type="button" onClick={() => onUpdateReminder(reminder.id, { state: "pending" })}>
                      <Bell size={15} /> Resume
                    </button>
                  )}
                  <button type="button" onClick={() => onUpdateReminder(reminder.id, { state: "dismissed" })}>
                    <X size={15} /> Dismiss
                  </button>
                </div>
              </article>
            ))}
          </div>
        )}
        {isTask && item.id && onCreateReminder && reminders.length === 0 && (
          <div className="reminder-add-row">
            <span>Set a custom reminder</span>
            <input
              type="datetime-local"
              value={newReminderAt}
              onChange={(event) => setNewReminderAt(event.target.value)}
              aria-label="Reminder time"
            />
            <button
              type="button"
              disabled={!newReminderAt}
              onClick={async () => {
                if (!newReminderAt) return;
                await onCreateReminder(String(item.id), new Date(newReminderAt).toISOString());
                setNewReminderAt("");
              }}
            >
              <Bell size={15} /> Add reminder
            </button>
          </div>
        )}
        {!!projects.length && (
          <div className="mini-section">
            <strong>Projects</strong>
            {projects.map((project: any) => {
              const provenance = linkedViaBadge(project.linked_via);
              return (
                <button key={project.id} type="button" onClick={() => onOpenProject(project.id)}>
                  <span className="dot" style={{ background: project.color_hex || "#7c3aed" }} />
                  {project.name}
                  {provenance && <span className={`evidence-badge ${provenance.className}`}>{provenance.label}</span>}
                </button>
              );
            })}
          </div>
        )}
        {!!people.length && (
          <div className="mini-section">
            <strong>People</strong>
            {people.map((person: any) => {
              const role = person.role || person.relation || person.attendance_status;
              const company = person.company;
              const provenance = linkedViaBadge(person.linked_via);
              return (
                <span key={`${person.id}-${role || "person"}`} className="mini-relation">
                  <span>{person.name}</span>
                  {role && <span className="mini-relation-tag">{role}</span>}
                  {provenance && <span className={`evidence-badge ${provenance.className}`}>{provenance.label}</span>}
                  {company && <small>{company}</small>}
                </span>
              );
            })}
          </div>
        )}
        {!!companies.length && (
          <div className="mini-section">
            <strong>Companies</strong>
            {companies.map((company: any) => {
              const provenance = linkedViaBadge(company.linked_via);
              return (
                <span key={company.id} className="mini-relation">
                  <span>{company.name}</span>
                  {provenance && <span className={`evidence-badge ${provenance.className}`}>{provenance.label}</span>}
                  {company.domain && <small>{company.domain}</small>}
                </span>
              );
            })}
          </div>
        )}
        {sectionId === "companies" && item.id && onCreateTaskForCompany && (
          <div className="quick-task-row task-create-row" aria-label="Quick task for this company">
            <input
              value={companyQuickTaskTitle}
              onChange={(event) => setCompanyQuickTaskTitle(event.target.value)}
              placeholder={`Add a task for ${item.name || "this company"}`}
              aria-label="Quick task title"
            />
            <input
              type="date"
              value={companyQuickTaskDue}
              onChange={(event) => setCompanyQuickTaskDue(event.target.value)}
              aria-label="Quick task due date"
            />
            <select
              value={companyQuickTaskAssignee}
              onChange={(event) => setCompanyQuickTaskAssignee(event.target.value)}
              aria-label="Quick task assignee"
            >
              <option value="">No assignee</option>
              {allPeople.filter((person) => !person.clerk_user_id).map((person) => (
                <option key={person.id} value={person.id}>{person.name}</option>
              ))}
            </select>
            <button
              type="button"
              disabled={!companyQuickTaskTitle.trim()}
              onClick={async () => {
                if (!onCreateTaskForCompany || !companyQuickTaskTitle.trim()) return;
                await onCreateTaskForCompany(
                  String(item.id),
                  companyQuickTaskTitle.trim(),
                  companyQuickTaskDue ? `${companyQuickTaskDue}T12:00:00` : null,
                  companyQuickTaskAssignee || null,
                );
                setCompanyQuickTaskTitle("");
                setCompanyQuickTaskDue("");
                setCompanyQuickTaskAssignee("");
              }}
            >
              <Plus size={16} /> Add task
            </button>
          </div>
        )}
        {!!tasks.length && (
          <div className="timeline-list">
            {tasks.slice(0, 6).map((task: any) => (
              <article key={task.id} onClick={() => onOpenMemory("tasks", task)}>
                <strong>{task.title}</strong>
                <span>
                  {task.status || "todo"}
                  {task.due_at ? ` - due ${new Date(task.due_at).toLocaleDateString()}` : ""}
                  {task.assignee_name ? ` - ${task.assignee_name}` : ""}
                </span>
                {task.description && <p>{task.description}</p>}
              </article>
            ))}
          </div>
        )}
        {!!meetings.length && (
          <div className="timeline-list">
            {meetings.slice(0, 5).map((meeting: any) => (
              <article key={meeting.id} onClick={() => onOpenMemory("meetings", meeting)}>
                <strong>{meeting.title}</strong>
                <span>
                  {meeting.occurred_at
                    ? new Date(meeting.occurred_at).toLocaleDateString()
                    : new Date(meeting.created_at).toLocaleDateString()}
                </span>
                {meeting.summary && <p>{String(meeting.summary).slice(0, 200)}</p>}
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
  onCopyLink,
  onFlag,
  onMerge,
  onCreateTask,
  onRename,
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
  onCopyLink: () => void;
  onFlag: () => void;
  onMerge: (sourcePersonId: string, targetPersonId: string) => Promise<void>;
  onCreateTask?: (input: { title: string; due_at?: string | null; project_id?: string | null; assignee_id?: string | null }) => Promise<void>;
  onRename?: (nextName: string) => Promise<void>;
  inviteEmail?: string;
  onInviteEmailChange?: (email: string) => void;
  onInvite?: (project: any, email: string) => Promise<void>;
  onGenerateReport?: (project: any) => Promise<void>;
  onBack: () => void;
}) {
  const [mergeTargetId, setMergeTargetId] = useState("");
  const [quickTaskTitle, setQuickTaskTitle] = useState("");
  const [quickTaskDue, setQuickTaskDue] = useState("");
  const [quickTaskAssignee, setQuickTaskAssignee] = useState("");
  const [personTaskFilter, setPersonTaskFilter] = useState<"all" | "owner" | "watcher">("all");
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
  const recentEventCount = useMemo(() => {
    return (events as any[]).filter((event: any) => {
      const days = daysSinceNow(event.event_at);
      return days !== null && days <= 7;
    }).length;
  }, [events]);
  const eventBuckets = useMemo(() => {
    const buckets: Record<string, any[]> = { Today: [], Yesterday: [], "This week": [], Earlier: [] };
    for (const event of events as any[]) {
      const bucket = eventAgeBucket(event.event_at);
      buckets[bucket].push(event);
    }
    return buckets;
  }, [events]);
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
        <button onClick={onCopyLink}><Link size={16} /> Copy link</button>
        <button onClick={onFlag}><Flag size={16} /> Flag</button>
        {kind === "project" && onGenerateReport && (
          <button onClick={() => onGenerateReport(timeline.project)}><FileText size={16} /> Generate report</button>
        )}
        <button onClick={onBack}><X size={16} /> Close</button>
      </div>
      <div className="memory-profile-card">
        <div>
          <span>{kind === "project" ? "Project profile" : "Person profile"}</span>
          {onRename ? (
            <ProfileNameEditor
              initial={String((kind === "project" ? timeline.project?.name : timeline.person?.name) || "Untitled")}
              onSave={(next) => onRename(next)}
            />
          ) : (
            <strong>{profile.headline || (kind === "project" ? timeline.project?.name : timeline.person?.name)}</strong>
          )}
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
      {kind === "project" && Array.isArray(timeline.tasks) && timeline.tasks.length > 0 && (() => {
        const buckets: Record<string, { name: string; count: number; blocked: number }> = {};
        let unassigned = 0;
        for (const task of timeline.tasks) {
          if (task.status === "done" || task.status === "archived") continue;
          const id = task.assignee_id ? String(task.assignee_id) : null;
          if (!id) {
            unassigned += 1;
            continue;
          }
          if (!buckets[id]) buckets[id] = { name: String(task.assignee_name || "Unknown"), count: 0, blocked: 0 };
          buckets[id].count += 1;
          if (task.status === "blocked") buckets[id].blocked += 1;
        }
        const owners = Object.values(buckets).sort((a, b) => b.count - a.count);
        if (owners.length === 0 && unassigned === 0) return null;
        return (
          <div className="mini-section workload-section">
            <strong>Team workload</strong>
            <div className="workload-grid">
              {owners.map((owner) => (
                <span key={owner.name} className="workload-chip">
                  <strong>{owner.name}</strong>
                  <small>{owner.count} open{owner.blocked > 0 ? ` - ${owner.blocked} blocked` : ""}</small>
                </span>
              ))}
              {unassigned > 0 && (
                <span className="workload-chip workload-warn">
                  <strong>Unassigned</strong>
                  <small>{unassigned} open</small>
                </span>
              )}
            </div>
          </div>
        );
      })()}
      {onCreateTask && (
        <div className="quick-task-row task-create-row" aria-label="Quick add task">
          <input
            value={quickTaskTitle}
            onChange={(event) => setQuickTaskTitle(event.target.value)}
            placeholder={kind === "person"
              ? `Assign a task to ${timeline.person?.name || "this person"}`
              : `Add a task for ${timeline.project?.name || "this project"}`}
            aria-label="Quick task title"
          />
          <input
            type="date"
            value={quickTaskDue}
            onChange={(event) => setQuickTaskDue(event.target.value)}
            aria-label="Quick task due date"
          />
          {kind === "project" && (
            <select
              value={quickTaskAssignee}
              onChange={(event) => setQuickTaskAssignee(event.target.value)}
              aria-label="Quick task assignee"
            >
              <option value="">No assignee</option>
              {people.filter((person) => !person.clerk_user_id).map((person) => (
                <option key={person.id} value={person.id}>{person.name}</option>
              ))}
            </select>
          )}
          <button
            type="button"
            disabled={!quickTaskTitle.trim() || !onCreateTask}
            onClick={async () => {
              if (!onCreateTask || !quickTaskTitle.trim()) return;
              const assigneeId = kind === "person"
                ? timeline.person?.id || null
                : kind === "project"
                  ? quickTaskAssignee || null
                  : null;
              await onCreateTask({
                title: quickTaskTitle.trim(),
                due_at: quickTaskDue ? `${quickTaskDue}T12:00:00` : null,
                project_id: kind === "project" ? timeline.project?.id || null : null,
                assignee_id: assigneeId,
              });
              setQuickTaskTitle("");
              setQuickTaskDue("");
              setQuickTaskAssignee("");
            }}
          >
            <Plus size={16} /> Add task
          </button>
        </div>
      )}
      {!!timeline.tasks?.length && (() => {
        const filtered = kind === "person" && personTaskFilter !== "all"
          ? timeline.tasks.filter((task: any) => personTaskFilter === "owner" ? task.is_assignee === true : task.is_assignee === false)
          : timeline.tasks;
        const ownerCount = timeline.tasks.filter((task: any) => task.is_assignee === true).length;
        const watcherCount = timeline.tasks.filter((task: any) => task.is_assignee === false).length;
        return (
          <div className="mini-section">
            <strong>Tasks</strong>
            {kind === "person" && (ownerCount > 0 || watcherCount > 0) && (
              <div className="search-scope-tabs" role="tablist" aria-label="Filter person tasks by role">
                <button type="button" role="tab" aria-selected={personTaskFilter === "all"} className={personTaskFilter === "all" ? "search-scope-tab active" : "search-scope-tab"} onClick={() => setPersonTaskFilter("all")}>All <strong>{timeline.tasks.length}</strong></button>
                {ownerCount > 0 && (
                  <button type="button" role="tab" aria-selected={personTaskFilter === "owner"} className={personTaskFilter === "owner" ? "search-scope-tab active" : "search-scope-tab"} onClick={() => setPersonTaskFilter("owner")}>Owner <strong>{ownerCount}</strong></button>
                )}
                {watcherCount > 0 && (
                  <button type="button" role="tab" aria-selected={personTaskFilter === "watcher"} className={personTaskFilter === "watcher" ? "search-scope-tab active" : "search-scope-tab"} onClick={() => setPersonTaskFilter("watcher")}>Watching <strong>{watcherCount}</strong></button>
                )}
              </div>
            )}
            {filtered.slice(0, 8).map((task: any) => (
              <span key={task.id} className="mini-relation">
                <span>{task.title}</span>
                <span className="mini-relation-tag">{task.status}</span>
                {kind === "person" && task.is_assignee && <span className="mini-relation-tag" style={{ background: "#f4faf4", borderColor: "#b3d7b6", color: "#1f4d27" }}>owner</span>}
                {kind === "person" && task.is_assignee === false && <span className="mini-relation-tag" style={{ background: "#fffefb" }}>watcher</span>}
                {kind !== "person" && task.assignee_name && <small>{task.assignee_name}</small>}
                {task.project_name && kind !== "project" && <small>{task.project_name}</small>}
              </span>
            ))}
            {filtered.length === 0 && <span className="muted">No matching tasks.</span>}
          </div>
        );
      })()}
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
        <div className="timeline-event-head">
          <strong>Interaction history</strong>
          {events.length > 0 && (
            <small>
              <strong>{events.length}</strong> total
              {recentEventCount > 0 && <> &middot; <strong>{recentEventCount}</strong> in the last 7 days</>}
            </small>
          )}
        </div>
        {(() => {
          const sections: Array<[string, any[]]> = (Object.entries(eventBuckets) as Array<[string, any[]]>).filter(([, list]) => list.length > 0);
          return sections.map(([label, list]) => (
            <div key={label} className="timeline-event-section">
              <span className="timeline-event-section-label">{label}</span>
              {list.map((event: any) => (
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
            </div>
          ));
        })()}
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
  onCopyLink,
  onFullCopy,
  onFlag,
  onProcess,
  onBlockSender,
  onArchive,
  onUpdate,
  onSetProjects,
  onReviewDecision,
  onSuggestionQueued,
  onOpenMemory,
  onOpenReview,
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
  onCopyLink: () => void;
  onFullCopy: () => void;
  onFlag: () => void;
  onProcess: () => void;
  onBlockSender: () => void;
  onArchive?: () => Promise<void>;
  onUpdate: (noteId: string, title: string, body: string, noteKind: string, occurredAt: string) => Promise<void>;
  onSetProjects: (note: any, projectIds: string[], confirmPersonalMove?: boolean) => Promise<void>;
  onReviewDecision: (reviewId: string, decision: "accept" | "reject") => Promise<void>;
  onSuggestionQueued: () => void;
  onOpenMemory: (sectionId: string, item: any) => Promise<void>;
  onOpenReview: () => void;
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
  useEffect(() => {
    if (!open || !note) return;
    if (note.ai_processing_status !== "processing" && note.ai_processing_status !== "queued" && note.ai_processing_status !== "pending") return;
    let cancelled = false;
    let attempts = 0;
    const tick = async () => {
      if (cancelled) return;
      attempts += 1;
      try {
        await refresh();
      } catch {
        // network jitter is fine; we'll try again
      }
      if (!cancelled && attempts < 20) {
        timer = setTimeout(tick, 3000);
      }
    };
    let timer: ReturnType<typeof setTimeout> = setTimeout(tick, 3000);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [open, note, refresh]);
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
        {note.raw_email_metadata && (() => {
          const meta = note.raw_email_metadata;
          const sender = meta.sender || meta.from || "unknown sender";
          const subject = meta.subject || "No subject";
          const receivedAt = meta.received_at || meta.date || note.created_at;
          const replyAddr = meta.reply_to || meta.sender_email || (typeof sender === "string" ? sender.match(/<([^>]+)>/)?.[1] : null);
          const replyHref = replyAddr ? `mailto:${encodeURIComponent(replyAddr)}?subject=${encodeURIComponent(`Re: ${subject}`)}` : null;
          return (
            <div className="email-meta-card">
              <div className="email-meta-row">
                <span className="email-meta-label">From</span>
                <span className="email-meta-value">{sender}</span>
              </div>
              <div className="email-meta-row">
                <span className="email-meta-label">Subject</span>
                <span className="email-meta-value email-meta-subject">{subject}</span>
              </div>
              {receivedAt && (
                <div className="email-meta-row">
                  <span className="email-meta-label">Received</span>
                  <span className="email-meta-value">{new Date(receivedAt).toLocaleString()}</span>
                </div>
              )}
              {replyHref && (
                <a className="email-meta-reply" href={replyHref}>
                  <Send size={13} /> Reply by email
                </a>
              )}
            </div>
          );
        })()}
        {!editMode && (() => {
          const status = note.ai_processing_status;
          const summaryParts: string[] = [];
          for (const [kind, count] of Object.entries(memoryCounts) as [string, number][]) {
            summaryParts.push(`${count} ${kind}${count === 1 ? "" : "s"}`);
          }
          const summaryText = summaryParts.length ? summaryParts.join(", ") : "no memory yet";
          if (status === "processing" || status === "queued" || status === "pending") {
            return (
              <div className="extraction-banner extraction-banner-progress" role="status">
                <span className="extraction-spinner" aria-hidden="true" />
                <div>
                  <strong>Extracting memory…</strong>
                  <small>Reading the note for tasks, meetings, people, projects, and companies. This usually takes a few seconds.</small>
                </div>
              </div>
            );
          }
          if (status === "failed") {
            return (
              <div className="extraction-banner extraction-banner-failed" role="alert">
                <X size={18} />
                <div>
                  <strong>Extraction failed</strong>
                  <small>{note.ai_processing_error ? String(note.ai_processing_error).slice(0, 200) : "No detail recorded."}</small>
                </div>
                <button type="button" className="extraction-banner-action" onClick={onProcess}>
                  <Sparkles size={14} /> Retry
                </button>
              </div>
            );
          }
          if (status === "processed") {
            return (
              <div className="extraction-banner extraction-banner-done">
                <Sparkles size={18} />
                <div>
                  <strong>Found {summaryText}{suggestions.length ? `. ${suggestions.length} need${suggestions.length === 1 ? "s" : ""} your review.` : "."}</strong>
                  <small>Source-backed and editable. Open any item to refine its relationships.</small>
                </div>
                {suggestions.length > 0 && (
                  <button
                    type="button"
                    className="extraction-banner-action primary"
                    onClick={() => {
                      onClose();
                      onOpenReview();
                    }}
                  >
                    Review now
                  </button>
                )}
              </div>
            );
          }
          if (status === "skipped" || status === "unprocessed" || !status) {
            return (
              <div className="extraction-banner extraction-banner-idle">
                <Sparkles size={18} />
                <div>
                  <strong>Memory not extracted yet</strong>
                  <small>You&apos;re in manual mode. Extract memory pulls tasks, people, companies, meetings, and follow-ups out of this note.</small>
                </div>
                <button type="button" className="extraction-banner-action primary" onClick={onProcess}>
                  <Sparkles size={14} /> Extract memory
                </button>
              </div>
            );
          }
          return null;
        })()}
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
          {(note.people || []).map((person: any) => {
            const sourceLabel = personSourceLabel(person.source, person.state);
            const sourceClass = personSourceBadgeClass(person.source, person.state);
            return (
              <span className="chip person-chip" key={person.id}>
                {person.name}
                {sourceLabel && <span className={`evidence-badge ${sourceClass}`}>{sourceLabel}</span>}
                {person.confidence && person.source !== "manual" ? (
                  <span className="evidence-badge evidence-confidence">{Math.round(person.confidence * 100)}%</span>
                ) : null}
              </span>
            );
          })}
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
          <button onClick={onCopyLink}><Link size={17} /> Copy link</button>
          <button onClick={onFullCopy}><Copy size={17} /> Full brief</button>
          <button onClick={onFlag}><Flag size={17} /> Flag</button>
          <button onClick={() => setEditMode(true)}><Settings size={17} /> Edit</button>
          <button onClick={onProcess}><Sparkles size={17} /> Extract memory</button>
          {note.raw_email_metadata && <button onClick={onBlockSender}><X size={17} /> Block sender</button>}
          {onArchive && (
            note.archived_at
              ? <button onClick={onArchive}><Archive size={17} /> Restore</button>
              : <button onClick={onArchive}><Archive size={17} /> Archive</button>
          )}
        </div>
      </aside>
    </div>
  );
}
