"use client";

/* eslint-disable react-hooks/set-state-in-effect, @next/next/no-img-element */

import {
  Archive,
  Bell,
  CalendarDays,
  Check,
  Copy,
  Flag,
  Inbox,
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
import { useCallback, useEffect, useMemo, useState } from "react";

type ApiState = {
  user?: any;
  workspace?: any;
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
};

type SearchFilters = {
  person_id?: string;
  date_from?: string;
  date_to?: string;
  flagged_only?: boolean;
};

const API_BASE = process.env.NEXT_PUBLIC_NOTESNOOP_API_URL || "";
const DEV_AUTH = process.env.NEXT_PUBLIC_NOTESNOOP_DEV_AUTH === "true";

export function NoteSnoopApp({ quickCapture }: { quickCapture: boolean }) {
  const { getToken, isSignedIn, isLoaded } = useAuth();
  const [state, setState] = useState<ApiState | null>(null);
  const [home, setHome] = useState<HomeState | null>(null);
  const [notes, setNotes] = useState<any[]>([]);
  const [selectedNote, setSelectedNote] = useState<any | null>(null);
  const [body, setBody] = useState("");
  const [title, setTitle] = useState("");
  const [query, setQuery] = useState("");
  const [searchFilters, setSearchFilters] = useState<SearchFilters>({});
  const [searchMeta, setSearchMeta] = useState<any | null>(null);
  const [personName, setPersonName] = useState("");
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
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState("");

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
    const me = await api("/api/me");
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
      projects: me.data.projects || [],
      people: me.data.people || [],
      inbound_address: me.data.inbound_address,
    });
  }, [api]);

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
    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.register("/sw.js").catch(() => undefined);
    }
  }, []);

  useEffect(() => {
    refreshWorkspaceData().catch((err) => setToast(err.message));
  }, [refreshWorkspaceData]);

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
        }),
      });
      setSelectedNote(res.data);
      setBody("");
      setTitle("");
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

  async function updateNote(noteId: string, nextTitle: string, nextBody: string) {
    const res = await api(`/api/notes/${noteId}`, {
      method: "PATCH",
      body: JSON.stringify({ title: nextTitle || null, body: nextBody }),
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
      body: JSON.stringify({ name: personName }),
    });
    setPersonName("");
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

  async function applySearchFilters(nextFilters: SearchFilters) {
    setSearchFilters(nextFilters);
    await runSearch(query, nextFilters);
  }

  async function openProject(project: any) {
    setActiveProject(project.id);
    setSelectedProjectIds([]);
    setPersonTimeline(null);
    const res = await api(`/api/projects/${project.id}/timeline`);
    setProjectTimeline(res.data);
  }

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
            <input value={query} onChange={(e) => runSearch(e.target.value)} placeholder="Search notes, people, projects..." />
          </div>
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

        {!quickCapture && (
        <div className="review-strip">
          <Bell size={17} />
          {!!reviewCount && <strong>{reviewCount}</strong>}
          <button className="review-expand" onClick={() => setReviewSheetOpen(true)}>
            Review{reviewCount ? ` (${reviewCount})` : ""}
          </button>
          {home?.pending_review?.length ? (
            <div className="review-items">
              {home.pending_review.slice(0, 3).map((item) => (
                <span key={item.id} className="review-item">
                  {item.payload?.name || item.entity_kind}
                  <button onClick={() => decideReview(item.id, "accept")} aria-label="Accept suggestion">
                    <Check size={14} />
                  </button>
                  <button onClick={() => decideReview(item.id, "reject")} aria-label="Reject suggestion">
                    <X size={14} />
                  </button>
                </span>
              ))}
            </div>
          ) : "Caught up"}
        </div>
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

        <section className="composer">
          <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Optional title" />
          <textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            placeholder="Dump a note. Names, projects, rough thoughts, half-sentences all belong here."
            rows={quickCapture ? 9 : 6}
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
                      {note.raw_email_metadata && <span className="raw-badge">Email</span>}
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
                  <div className="inline-create">
                    <input value={personName} onChange={(e) => setPersonName(e.target.value)} placeholder="Quick-add person" />
                    <button className="icon-btn" onClick={createPerson} aria-label="Add person">
                      <Plus size={18} />
                    </button>
                  </div>
                  {state?.people.map((person) => (
                    <div className="entity-row" key={person.id} onClick={() => openPerson(person)}>
                      <UserRound size={17} />
                      <div>
                        <strong>{person.name}</strong>
                        <span>{person.company || `${person.confirmed_note_count || 0} notes`}</span>
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
            <span>{new Date(note.created_at).toLocaleDateString()}</span>
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
  onUpdate: (noteId: string, title: string, body: string) => Promise<void>;
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
  const [newProjectName, setNewProjectName] = useState("");
  useEffect(() => {
    if (!note) return;
    setDraftTitle(note.title || "");
    setDraftBody(note.body || "");
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
            <textarea value={draftBody} onChange={(e) => setDraftBody(e.target.value)} rows={7} aria-label="Note body" />
            <div className="sheet-actions">
              <button onClick={() => onUpdate(note.id, draftTitle, draftBody)}><Check size={17} /> Save changes</button>
              <button onClick={() => setEditMode(false)}><X size={17} /> Cancel</button>
            </div>
          </div>
        ) : (
          <p>{note.body}</p>
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
