"use client";

/* eslint-disable react-hooks/set-state-in-effect, @next/next/no-img-element */

import {
  Archive,
  Bell,
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
  const [personName, setPersonName] = useState("");
  const [projectName, setProjectName] = useState("");
  const [activeProject, setActiveProject] = useState<string | null>(null);
  const [mobileNav, setMobileNav] = useState(false);
  const [sheetOpen, setSheetOpen] = useState(false);
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

  useEffect(() => {
    if (isSignedIn || DEV_AUTH) refresh().catch((err) => setToast(err.message));
  }, [isSignedIn, refresh]);

  useEffect(() => {
    refreshWorkspaceData().catch((err) => setToast(err.message));
  }, [refreshWorkspaceData]);

  async function saveNote() {
    if (!workspaceId || !body.trim()) return;
    setBusy(true);
    try {
      const res = await api(`/api/workspaces/${workspaceId}/notes`, {
        method: "POST",
        body: JSON.stringify({
          title: title || null,
          body,
          project_ids: activeProject ? [activeProject] : undefined,
        }),
      });
      setSelectedNote(res.data);
      setBody("");
      setTitle("");
      setSheetOpen(true);
      setToast("Saved. AI structuring is queued when allowed.");
      await refreshWorkspaceData();
    } catch (err) {
      setToast(err instanceof Error ? err.message : "Could not save note");
    } finally {
      setBusy(false);
    }
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

  async function runSearch(nextQuery: string) {
    setQuery(nextQuery);
    if (!workspaceId) return;
    const res = await api(`/api/workspaces/${workspaceId}/search?q=${encodeURIComponent(nextQuery)}`);
    setNotes(res.data);
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

  async function copyBrief(kind: "note" | "project" | "person", item: any) {
    const res = await api(`/api/briefs/${kind}/${item.id}?variant=quick`);
    await navigator.clipboard.writeText(res.data.markdown);
    setToast("Brief copied.");
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
        <button className={`nav-item ${!activeProject ? "active" : ""}`} onClick={() => setActiveProject(null)}>
          <Archive size={17} /> Home
        </button>
        {inbox && (
          <button className={`nav-item ${activeProject === inbox.id ? "active" : ""}`} onClick={() => setActiveProject(inbox.id)}>
            <Inbox size={17} /> Inbox
          </button>
        )}
        {personal && (
          <button className={`nav-item ${activeProject === personal.id ? "active" : ""}`} onClick={() => setActiveProject(personal.id)}>
            <UserRound size={17} /> Personal
          </button>
        )}
        <div className="sidebar-label">Projects</div>
        {state?.projects
          .filter((p) => p.kind === "user")
          .map((project) => (
            <button key={project.id} className={`nav-item ${activeProject === project.id ? "active" : ""}`} onClick={() => setActiveProject(project.id)}>
              <span className="dot" style={{ background: project.color_hex || "#7c3aed" }} /> {project.name}
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
          <button className="icon-btn" title="Email AI is Manual by default">
            <Settings size={18} />
          </button>
          <UserButton />
        </header>

        {!quickCapture && (
        <div className="review-strip">
          <Bell size={17} />
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

        <section className="composer">
          <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Optional title" />
          <textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            placeholder="Dump a note. Names, projects, rough thoughts, half-sentences all belong here."
            rows={quickCapture ? 9 : 6}
          />
          <div className="composer-actions">
            <span>{activeProject ? "Saving to selected project" : "Saving to Inbox"}</span>
            <button onClick={saveNote} disabled={busy || !body.trim()}>
              <Send size={17} /> Save
            </button>
          </div>
        </section>

        {!quickCapture && (
          <div className="content-grid">
            <section className="list-pane">
              <div className="section-head">
                <h2>Notes</h2>
                <Sparkles size={18} />
              </div>
              {notes.map((note) => (
                <article key={note.id} className="note-row" onClick={() => { setSelectedNote(note); setSheetOpen(true); }}>
                  <div>
                    <h3 className={note.title_is_derived ? "derived" : ""}>{note.title}</h3>
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
                <h2>People</h2>
                <Users size={18} />
              </div>
              <div className="inline-create">
                <input value={personName} onChange={(e) => setPersonName(e.target.value)} placeholder="Quick-add person" />
                <button className="icon-btn" onClick={createPerson} aria-label="Add person">
                  <Plus size={18} />
                </button>
              </div>
              {state?.people.map((person) => (
                <div className="entity-row" key={person.id}>
                  <UserRound size={17} />
                  <div>
                    <strong>{person.name}</strong>
                    <span>{person.company || `${person.confirmed_note_count || 0} notes`}</span>
                  </div>
                  <button className="icon-btn" onClick={() => copyBrief("person", person)} aria-label="Copy person brief">
                    <Copy size={16} />
                  </button>
                </div>
              ))}
            </section>
          </div>
        )}
      </section>

      {toast && (
        <button className="toast" onClick={() => setToast("")}>
          <Check size={16} /> {toast}
        </button>
      )}

      <LinkedSheet
        open={sheetOpen}
        note={selectedNote}
        people={state?.people || []}
        onClose={() => setSheetOpen(false)}
        onCopy={() => selectedNote && copyBrief("note", selectedNote)}
        onFlag={() => selectedNote && flag({ note_id: selectedNote.id })}
        onProcess={() => selectedNote && processWithAI(selectedNote.id)}
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

function LinkedSheet({
  open,
  note,
  people,
  onClose,
  onCopy,
  onFlag,
  onProcess,
  api,
  refresh,
}: {
  open: boolean;
  note: any | null;
  people: any[];
  onClose: () => void;
  onCopy: () => void;
  onFlag: () => void;
  onProcess: () => void;
  api: (path: string, init?: RequestInit) => Promise<any>;
  refresh: () => Promise<void>;
}) {
  const [personId, setPersonId] = useState("");
  if (!open || !note) return null;
  async function link() {
    if (!personId) return;
    await api(`/api/notes/${note.id}/people`, {
      method: "POST",
      body: JSON.stringify({ person_id: personId, state: "confirmed", source: "user" }),
    });
    await refresh();
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
        <p>{note.body}</p>
        <div className="chip-row">
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
        <div className="sheet-actions">
          <button onClick={onCopy}><Copy size={17} /> Quick brief</button>
          <button onClick={onFlag}><Flag size={17} /> Flag</button>
          <button onClick={onProcess}><Sparkles size={17} /> Process with AI</button>
        </div>
      </aside>
    </div>
  );
}
