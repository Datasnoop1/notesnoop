"use client";

import { useDeferredValue, useEffect, useState } from "react";
import {
  MoreHorizontal,
  RefreshCw,
  Search,
  Shield,
} from "lucide-react";
import type {
  FeedbackRow,
  PeopleData,
  TierConfig,
} from "@/components/admin/admin-types";
import {
  SectionCard,
  SurfaceEmptyState,
  SurfaceErrorState,
  SurfaceFrame,
  SurfaceLoadingState,
} from "@/components/admin/surface-frame";
import {
  adminFetch,
  formatNumber,
  toBelgianDateTime,
  useAdminResource,
} from "@/lib/admin-fetch";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";

const TIER_FIELDS: Array<{
  key: keyof Pick<
    TierConfig,
    | "page_views_per_day"
    | "searches_per_day"
    | "company_views_per_day"
    | "ai_enrichments_per_day"
    | "export_per_day"
    | "screener_results_limit"
  >;
  label: string;
}> = [
  { key: "page_views_per_day", label: "Page views / day" },
  { key: "searches_per_day", label: "Searches / day" },
  { key: "company_views_per_day", label: "Company views / day" },
  { key: "ai_enrichments_per_day", label: "AI enrichments / day" },
  { key: "export_per_day", label: "Exports / day" },
  { key: "screener_results_limit", label: "Screener limit" },
];

export default function PeopleSurface({
  enabled,
}: {
  enabled: boolean;
}) {
  const people = useAdminResource<PeopleData>({
    enabled,
    fetcher: async () => {
      const [users, feedback, polls, tiers] = await Promise.all([
        adminFetch<PeopleData["users"]>("/api/admin/users"),
        adminFetch<PeopleData["feedback"]>("/api/admin/feedback"),
        adminFetch<PeopleData["polls"]>("/api/polls"),
        adminFetch<PeopleData["tiers"]>("/api/admin/tiers"),
      ]);

      return { users, feedback, polls, tiers };
    },
  });

  const [activeTab, setActiveTab] = useState("users");
  const [userSearch, setUserSearch] = useState("");
  const [actionKey, setActionKey] = useState<string | null>(null);
  const [replyDrafts, setReplyDrafts] = useState<Record<number, string>>({});
  const [tierDrafts, setTierDrafts] = useState<Record<string, TierConfig>>({});
  const [newPollTitle, setNewPollTitle] = useState("");
  const [newPollQuestion, setNewPollQuestion] = useState("");
  const [newPollOptions, setNewPollOptions] = useState("");
  const [pollOptionDrafts, setPollOptionDrafts] = useState<Record<number, string>>(
    {},
  );
  const deferredUserSearch = useDeferredValue(userSearch);

  useEffect(() => {
    if (!people.data) return;

    const nextReplies: Record<number, string> = {};
    for (const item of people.data.feedback) {
      nextReplies[item.id] = item.reply || "";
    }
    setReplyDrafts(nextReplies);

    const nextTiers: Record<string, TierConfig> = {};
    for (const tier of people.data.tiers) {
      nextTiers[tier.tier] = { ...tier };
    }
    setTierDrafts(nextTiers);
  }, [people.data]);

  if (people.isLoading && !people.data) {
    return <SurfaceLoadingState label="Loading people operations…" />;
  }

  if (people.error && !people.data) {
    return (
      <SurfaceErrorState
        message={people.error.message}
        onRetry={() => void people.refresh()}
      />
    );
  }

  const users =
    people.data?.users.filter((user) => {
      const query = deferredUserSearch.trim().toLowerCase();
      if (!query) return true;
      return (
        user.email.toLowerCase().includes(query) ||
        user.role.toLowerCase().includes(query)
      );
    }) || [];

  const polls = people.data?.polls || [];
  const activePolls = polls.filter((poll) => poll.status === "active");
  const archivedPolls = polls.filter((poll) => poll.status !== "active");
  const tiers = people.data?.tiers || [];
  const limitsEnabled = tiers.some((tier) => tier.enabled);

  const runUserRoleAction = async (email: string, role: string) => {
    setActionKey(`role:${email}:${role}`);
    try {
      await adminFetch(`/api/admin/users/${encodeURIComponent(email)}/role`, {
        method: "POST",
        body: JSON.stringify({ role }),
      });
      await people.refresh();
    } finally {
      setActionKey(null);
    }
  };

  const deleteUser = async (email: string) => {
    setActionKey(`delete:${email}`);
    try {
      await adminFetch(`/api/admin/users/${encodeURIComponent(email)}`, {
        method: "DELETE",
      });
      await people.refresh();
    } finally {
      setActionKey(null);
    }
  };

  const replyToFeedback = async (feedback: FeedbackRow) => {
    const message = replyDrafts[feedback.id]?.trim();
    if (!message) return;

    setActionKey(`reply:${feedback.id}`);
    try {
      await adminFetch(`/api/admin/feedback/${feedback.id}/reply`, {
        method: "POST",
        body: JSON.stringify({ message }),
      });
      await people.refresh();
    } finally {
      setActionKey(null);
    }
  };

  const deleteFeedback = async (feedbackId: number) => {
    setActionKey(`feedback:${feedbackId}`);
    try {
      await adminFetch(`/api/admin/feedback/${feedbackId}`, { method: "DELETE" });
      await people.refresh();
    } finally {
      setActionKey(null);
    }
  };

  const createPoll = async () => {
    const options = newPollOptions
      .split(",")
      .map((option) => option.trim())
      .filter(Boolean);

    if (!newPollTitle.trim() || !newPollQuestion.trim() || options.length < 2) {
      return;
    }

    setActionKey("poll:create");
    try {
      await adminFetch("/api/polls", {
        method: "POST",
        body: JSON.stringify({
          title: newPollTitle.trim(),
          question: newPollQuestion.trim(),
          options,
        }),
      });
      setNewPollTitle("");
      setNewPollQuestion("");
      setNewPollOptions("");
      await people.refresh();
    } finally {
      setActionKey(null);
    }
  };

  const archivePoll = async (pollId: number) => {
    setActionKey(`poll:archive:${pollId}`);
    try {
      await adminFetch(`/api/polls/${pollId}/archive`, { method: "POST" });
      await people.refresh();
    } finally {
      setActionKey(null);
    }
  };

  const activatePoll = async (pollId: number) => {
    setActionKey(`poll:activate:${pollId}`);
    try {
      await adminFetch(`/api/polls/${pollId}/activate`, { method: "POST" });
      await people.refresh();
    } finally {
      setActionKey(null);
    }
  };

  const addPollOptions = async (pollId: number) => {
    const options = (pollOptionDrafts[pollId] || "")
      .split(",")
      .map((option) => option.trim())
      .filter(Boolean);

    if (!options.length) return;

    setActionKey(`poll:add:${pollId}`);
    try {
      await adminFetch(`/api/polls/${pollId}/add-options`, {
        method: "POST",
        body: JSON.stringify({ options }),
      });
      setPollOptionDrafts((current) => ({ ...current, [pollId]: "" }));
      await people.refresh();
    } finally {
      setActionKey(null);
    }
  };

  const updateTierField = (
    tier: string,
    field: keyof TierConfig,
    value: number,
  ) => {
    setTierDrafts((current) => ({
      ...current,
      [tier]: {
        ...(current[tier] || ({} as TierConfig)),
        [field]: value,
      },
    }));
  };

  const saveTier = async (tierName: string) => {
    const original = people.data?.tiers.find((tier) => tier.tier === tierName);
    const draft = tierDrafts[tierName];
    if (!original || !draft) return;

    const payload: Record<string, number> = {};
    for (const { key } of TIER_FIELDS) {
      if (draft[key] !== original[key]) {
        payload[key] = draft[key];
      }
    }

    if (!Object.keys(payload).length) return;

    setActionKey(`tier:${tierName}`);
    try {
      await adminFetch(`/api/admin/tiers/${tierName}`, {
        method: "PUT",
        body: JSON.stringify(payload),
      });
      await people.refresh();
    } finally {
      setActionKey(null);
    }
  };

  const toggleLimits = async () => {
    setActionKey("tier:toggle");
    try {
      await adminFetch("/api/admin/tiers/toggle", {
        method: "POST",
        body: JSON.stringify({ enabled: !limitsEnabled }),
      });
      await people.refresh();
    } finally {
      setActionKey(null);
    }
  };

  return (
    <SurfaceFrame
      title="People Operations"
      description="Users, feedback, polls, and tier limits live together here so operator work feels coherent instead of chaotic."
      actions={
        <Button variant="outline" size="sm" onClick={() => void people.refresh()}>
          <RefreshCw className="mr-2 size-4" />
          Refresh people data
        </Button>
      }
    >
      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList className="flex h-auto w-full flex-wrap justify-start gap-2 rounded-2xl bg-transparent p-0">
          <TabsTrigger value="users">Users</TabsTrigger>
          <TabsTrigger value="feedback">Feedback</TabsTrigger>
          <TabsTrigger value="polls">Polls</TabsTrigger>
          <TabsTrigger value="tiers">Tiers</TabsTrigger>
        </TabsList>

        <TabsContent value="users" className="mt-5 space-y-5">
          <SectionCard
            title="Users"
            description="Search, promote, block, or remove users without the old cramped inline-action layout."
            actions={
              <div className="relative w-full sm:w-80">
                <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-slate-400" />
                <Input
                  value={userSearch}
                  onChange={(event) => setUserSearch(event.target.value)}
                  placeholder="Filter by email or role"
                  className="pl-9"
                />
              </div>
            }
          >
            {users.length ? (
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="sticky left-0 z-[5] bg-white shadow-[1px_0_0_rgba(226,232,240,1)]">
                        Email
                      </TableHead>
                      <TableHead>Role</TableHead>
                      <TableHead className="hidden md:table-cell">Joined</TableHead>
                      <TableHead className="hidden md:table-cell">Favourites</TableHead>
                      <TableHead className="hidden md:table-cell">Feedback</TableHead>
                      <TableHead className="w-[1%] text-right">Actions</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {users.map((user) => (
                      <TableRow key={user.email}>
                        <TableCell className="sticky left-0 z-[5] bg-white font-medium shadow-[1px_0_0_rgba(226,232,240,1)]">
                          <div className="min-w-[220px]">
                            <div className="text-sm text-slate-900">{user.email}</div>
                            <div className="body-sm text-slate-500 md:hidden">
                              {toBelgianDateTime(user.created_at)}
                            </div>
                          </div>
                        </TableCell>
                        <TableCell>
                          <Badge variant={user.role === "blocked" ? "destructive" : "secondary"}>
                            {user.role}
                          </Badge>
                        </TableCell>
                        <TableCell className="hidden md:table-cell">
                          {toBelgianDateTime(user.created_at)}
                        </TableCell>
                        <TableCell className="hidden md:table-cell">
                          {formatNumber(user.favourites_count)}
                        </TableCell>
                        <TableCell className="hidden md:table-cell">
                          {formatNumber(user.feedback_count)}
                        </TableCell>
                        <TableCell className="text-right">
                          <DropdownMenu>
                            <DropdownMenuTrigger>
                              <Button variant="ghost" size="icon-sm" aria-label={`Manage ${user.email}`}>
                                <MoreHorizontal className="size-4" />
                              </Button>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent align="end" className="min-w-44">
                              <DropdownMenuItem
                                className="cursor-pointer"
                                onClick={() => void runUserRoleAction(user.email, "user")}
                              >
                                Make user
                              </DropdownMenuItem>
                              <DropdownMenuItem
                                className="cursor-pointer"
                                onClick={() => void runUserRoleAction(user.email, "pro")}
                              >
                                Make pro
                              </DropdownMenuItem>
                              <DropdownMenuItem
                                className="cursor-pointer"
                                onClick={() => void runUserRoleAction(user.email, "admin")}
                              >
                                Make admin
                              </DropdownMenuItem>
                              <DropdownMenuItem
                                className="cursor-pointer"
                                onClick={() => void runUserRoleAction(user.email, "blocked")}
                              >
                                Block user
                              </DropdownMenuItem>
                              <DropdownMenuItem
                                className="cursor-pointer"
                                variant="destructive"
                                onClick={() => void deleteUser(user.email)}
                              >
                                Delete user
                              </DropdownMenuItem>
                            </DropdownMenuContent>
                          </DropdownMenu>
                          {actionKey?.startsWith(`role:${user.email}`) ||
                          actionKey === `delete:${user.email}` ? (
                            <div className="body-sm mt-1 text-slate-500">Working…</div>
                          ) : null}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            ) : (
              <SurfaceEmptyState
                title="No users matched that filter"
                description="Try a different email fragment or clear the search."
              />
            )}
          </SectionCard>
        </TabsContent>

        <TabsContent value="feedback" className="mt-5 space-y-5">
          {people.data?.feedback.length ? (
            people.data.feedback.map((item) => (
              <SectionCard
                key={item.id}
                title={item.type === "bug" ? "Bug report" : item.type}
                description={`${item.user_email || "Anonymous"} · ${toBelgianDateTime(item.created_at)}`}
                actions={
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => void deleteFeedback(item.id)}
                  >
                    {actionKey === `feedback:${item.id}` ? "Deleting…" : "Delete"}
                  </Button>
                }
              >
                <div className="space-y-4">
                  <div className="rounded-2xl bg-slate-50 p-4">
                    <div className="body text-slate-700">{item.description}</div>
                    {item.page ? (
                      <div className="mt-2 body-sm text-slate-500">Page: {item.page}</div>
                    ) : null}
                  </div>

                  {item.reply ? (
                    <div className="rounded-2xl border border-emerald-200 bg-emerald-50 p-4">
                      <div className="text-sm font-medium text-emerald-900">Last reply</div>
                      <div className="mt-1 body text-emerald-900">{item.reply}</div>
                      <div className="mt-2 body-sm text-emerald-700">
                        Sent {toBelgianDateTime(item.replied_at)}
                      </div>
                    </div>
                  ) : null}

                  <div className="space-y-3">
                    <div className="text-sm font-medium text-slate-900">
                      Reply draft
                    </div>
                    <Textarea
                      value={replyDrafts[item.id] || ""}
                      onChange={(event) =>
                        setReplyDrafts((current) => ({
                          ...current,
                          [item.id]: event.target.value,
                        }))
                      }
                      className="min-h-28 text-base md:min-h-24 md:text-sm"
                      placeholder="Type the operator reply here…"
                    />
                    <div className="flex justify-end">
                      <Button
                        size="sm"
                        onClick={() => void replyToFeedback(item)}
                        disabled={!replyDrafts[item.id]?.trim()}
                      >
                        {actionKey === `reply:${item.id}` ? "Sending…" : item.reply ? "Update reply" : "Send reply"}
                      </Button>
                    </div>
                  </div>
                </div>
              </SectionCard>
            ))
          ) : (
            <SurfaceEmptyState
              title="No feedback yet"
              description="When users send platform feedback, it will show up here."
            />
          )}
        </TabsContent>

        <TabsContent value="polls" className="mt-5 space-y-5">
          <SectionCard
            title="Create Poll"
            description="Creating a new poll automatically archives any currently active poll."
          >
            <div className="grid gap-4 lg:grid-cols-[1fr_1fr_auto]">
              <Input
                value={newPollTitle}
                onChange={(event) => setNewPollTitle(event.target.value)}
                placeholder="Poll title"
              />
              <Input
                value={newPollQuestion}
                onChange={(event) => setNewPollQuestion(event.target.value)}
                placeholder="Poll question"
              />
              <Button onClick={() => void createPoll()} disabled={actionKey === "poll:create"}>
                {actionKey === "poll:create" ? "Creating…" : "Create poll"}
              </Button>
            </div>
            <div className="mt-4">
              <Input
                value={newPollOptions}
                onChange={(event) => setNewPollOptions(event.target.value)}
                placeholder="Comma-separated options, for example: Yes, No, Maybe"
              />
            </div>
          </SectionCard>

          <SectionCard
            title="Active Polls"
            description="Usually there is just one, but the cards stay readable if history gets messy."
          >
            {activePolls.length ? (
              <div className="space-y-4">
                {activePolls.map((poll) => (
                  <PollCard
                    key={poll.id}
                    actionKey={actionKey}
                    draftValue={pollOptionDrafts[poll.id] || ""}
                    onArchive={() => void archivePoll(poll.id)}
                    onDraftChange={(value) =>
                      setPollOptionDrafts((current) => ({ ...current, [poll.id]: value }))
                    }
                    onAddOptions={() => void addPollOptions(poll.id)}
                    poll={poll}
                  />
                ))}
              </div>
            ) : (
              <SurfaceEmptyState
                title="No active polls"
                description="Create a new poll above or reactivate an archived one."
              />
            )}
          </SectionCard>

          <SectionCard
            title="Archived Polls"
            description="Past polls stay here for reactivation or history checks."
          >
            {archivedPolls.length ? (
              <div className="space-y-4">
                {archivedPolls.map((poll) => (
                  <PollCard
                    key={poll.id}
                    actionKey={actionKey}
                    draftValue={pollOptionDrafts[poll.id] || ""}
                    onActivate={() => void activatePoll(poll.id)}
                    onDraftChange={(value) =>
                      setPollOptionDrafts((current) => ({ ...current, [poll.id]: value }))
                    }
                    onAddOptions={() => void addPollOptions(poll.id)}
                    poll={poll}
                  />
                ))}
              </div>
            ) : (
              <SurfaceEmptyState
                title="No archived polls"
                description="Once polls are archived, they remain available here."
              />
            )}
          </SectionCard>
        </TabsContent>

        <TabsContent value="tiers" className="mt-5 space-y-5">
          <SectionCard
            title="Master Limit Switch"
            description="This is the operator-facing top-level switch for tier enforcement across the platform."
            actions={
              <Button variant="outline" size="sm" onClick={() => void toggleLimits()}>
                {actionKey === "tier:toggle"
                  ? "Updating…"
                  : limitsEnabled
                    ? "Disable all limits"
                    : "Enable all limits"}
              </Button>
            }
          >
            <div className="rounded-2xl bg-slate-50 p-4">
              <div className="flex items-center gap-2 text-sm font-medium text-slate-900">
                <Shield className="size-4 text-slate-600" />
                {limitsEnabled ? "Tier limits are enabled" : "Tier limits are disabled"}
              </div>
              <div className="mt-2 body text-slate-600">
                When disabled, the current thresholds stay stored but the middleware does not enforce them.
              </div>
            </div>
          </SectionCard>

          <div className="grid gap-4 xl:grid-cols-3">
            {tiers.map((tier) => {
              const draft = tierDrafts[tier.tier] || tier;
              const hasChanges = TIER_FIELDS.some(({ key }) => draft[key] !== tier[key]);

              return (
                <SectionCard
                  key={tier.tier}
                  title={tier.tier}
                  description="-1 means unlimited."
                  actions={
                    <Button
                      size="sm"
                      onClick={() => void saveTier(tier.tier)}
                      disabled={!hasChanges}
                    >
                      {actionKey === `tier:${tier.tier}` ? "Saving…" : "Save tier"}
                    </Button>
                  }
                >
                  <div className="grid gap-3">
                    {TIER_FIELDS.map(({ key, label }) => (
                      <label key={key} className="space-y-1">
                        <div className="body-sm text-slate-500">{label}</div>
                        <Input
                          type="number"
                          value={draft[key]}
                          onChange={(event) =>
                            updateTierField(
                              tier.tier,
                              key,
                              Number(event.target.value),
                            )
                          }
                        />
                      </label>
                    ))}
                  </div>
                </SectionCard>
              );
            })}
          </div>
        </TabsContent>
      </Tabs>
    </SurfaceFrame>
  );
}

function PollCard({
  poll,
  actionKey,
  draftValue,
  onDraftChange,
  onAddOptions,
  onArchive,
  onActivate,
}: {
  poll: PeopleData["polls"][number];
  actionKey: string | null;
  draftValue: string;
  onDraftChange: (value: string) => void;
  onAddOptions: () => void;
  onArchive?: () => void;
  onActivate?: () => void;
}) {
  return (
    <div className="rounded-3xl border border-slate-200 bg-slate-50 p-5">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <div className="text-base font-semibold text-slate-900">{poll.title}</div>
            <Badge variant={poll.status === "active" ? "default" : "secondary"}>
              {poll.status}
            </Badge>
            <Badge variant="outline">
              {formatNumber(poll.total_votes)} votes
            </Badge>
          </div>
          <div className="body text-slate-600">{poll.question}</div>
          <div className="flex flex-wrap gap-2">
            {poll.options.map((option) => (
              <Badge key={option} variant="secondary">
                {option}: {formatNumber(poll.votes[option] ?? 0)}
              </Badge>
            ))}
          </div>
        </div>

        <div className="flex flex-wrap gap-2">
          {onArchive ? (
            <Button variant="outline" size="sm" onClick={onArchive}>
              {actionKey === `poll:archive:${poll.id}` ? "Archiving…" : "Archive"}
            </Button>
          ) : null}
          {onActivate ? (
            <Button variant="outline" size="sm" onClick={onActivate}>
              {actionKey === `poll:activate:${poll.id}` ? "Re-activating…" : "Re-activate"}
            </Button>
          ) : null}
        </div>
      </div>

      <div className="mt-4 flex flex-col gap-3 md:flex-row">
        <Input
          value={draftValue}
          onChange={(event) => onDraftChange(event.target.value)}
          placeholder="Add more options, comma-separated"
        />
        <Button variant="outline" size="sm" onClick={onAddOptions}>
          {actionKey === `poll:add:${poll.id}` ? "Adding…" : "Add options"}
        </Button>
      </div>
    </div>
  );
}
