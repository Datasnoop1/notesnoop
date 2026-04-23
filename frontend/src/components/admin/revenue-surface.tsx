"use client";

import { useDeferredValue, useState } from "react";
import { CreditCard, Receipt, RefreshCw, Sparkles, Wallet } from "lucide-react";
import type { InvoiceRow, RevenueData } from "@/components/admin/admin-types";
import { KpiCard } from "@/components/admin/kpi-card";
import {
  SectionCard,
  SurfaceEmptyState,
  SurfaceErrorState,
  SurfaceFrame,
  SurfaceLoadingState,
  SurfaceStatGrid,
} from "@/components/admin/surface-frame";
import {
  adminFetch,
  formatCurrency,
  formatNumber,
  toBelgianDate,
  toBelgianDateTime,
  useAdminResource,
} from "@/lib/admin-fetch";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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

function centsToCurrency(amountCents: number | null, currency?: string | null) {
  if (amountCents == null) return "—";
  return formatCurrency(amountCents / 100, {
    currency: (currency || "EUR").toUpperCase(),
  });
}

export default function RevenueSurface({
  enabled,
}: {
  enabled: boolean;
}) {
  const revenue = useAdminResource<RevenueData>({
    enabled,
    fetcher: async () => {
      const [payments, costs, arr, pnl, llm, invoices] = await Promise.all([
        adminFetch<RevenueData["payments"]>("/api/admin/payments").catch(
          () => null,
        ),
        adminFetch<RevenueData["costs"]>("/api/admin/costs").catch(() => null),
        adminFetch<RevenueData["arr"]>("/api/admin/arr").catch(() => null),
        adminFetch<RevenueData["pnl"]>("/api/admin/pnl-summary").catch(
          () => null,
        ),
        adminFetch<RevenueData["llm"]>("/api/admin/llm-cost-breakdown").catch(
          () => null,
        ),
        adminFetch<RevenueData["invoices"]>("/api/admin/invoices").catch(
          () => null,
        ),
      ]);

      return { payments, costs, arr, pnl, llm, invoices };
    },
  });

  const [activeTab, setActiveTab] = useState("summary");
  const [invoiceSearch, setInvoiceSearch] = useState("");
  const [actionKey, setActionKey] = useState<string | null>(null);
  const deferredInvoiceSearch = useDeferredValue(invoiceSearch);

  if (revenue.isLoading && !revenue.data) {
    return <SurfaceLoadingState label="Loading revenue operations…" />;
  }

  if (revenue.error && !revenue.data) {
    return (
      <SurfaceErrorState
        message={revenue.error.message}
        onRetry={() => void revenue.refresh()}
      />
    );
  }

  const filteredInvoices =
    revenue.data?.invoices?.invoices.filter((invoice) => {
      const query = deferredInvoiceSearch.trim().toLowerCase();
      if (!query) return true;

      return [invoice.sender, invoice.subject, invoice.vendor, invoice.category]
        .filter(Boolean)
        .some((value) => value!.toLowerCase().includes(query));
    }) || [];

  const confirmInvoice = async (invoice: InvoiceRow) => {
    setActionKey(`invoice:${invoice.id}`);
    try {
      await adminFetch(`/api/admin/invoices/${invoice.id}/confirm`, {
        method: "POST",
        body: JSON.stringify({}),
      });
      await revenue.refresh();
    } finally {
      setActionKey(null);
    }
  };

  const reclassifyInvoices = async () => {
    setActionKey("invoice:reclassify");
    try {
      await adminFetch("/api/admin/invoices/classify-all", { method: "POST" });
      await revenue.refresh();
    } finally {
      setActionKey(null);
    }
  };

  const monthly = revenue.data?.pnl?.monthly;
  const sixMonth = revenue.data?.pnl?.sixMonth;
  const yearly = revenue.data?.pnl?.yearly;

  return (
    <SurfaceFrame
      title="Revenue & Costs"
      description="Billing, invoices, P&L, and AI costs in one place, without forcing the operator through several unrelated old tabs."
      actions={
        <Button variant="outline" size="sm" onClick={() => void revenue.refresh()}>
          <RefreshCw className="mr-2 size-4" />
          Refresh revenue data
        </Button>
      }
    >
      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList className="flex h-auto w-full flex-wrap justify-start gap-2 rounded-2xl bg-transparent p-0">
          <TabsTrigger value="summary">Summary</TabsTrigger>
          <TabsTrigger value="invoices">Invoices</TabsTrigger>
          <TabsTrigger value="payments">Payments</TabsTrigger>
          <TabsTrigger value="ai">AI Costs</TabsTrigger>
        </TabsList>

        <TabsContent value="summary" className="mt-5 space-y-5">
          <SurfaceStatGrid>
            <KpiCard
              label="ARR"
              value={formatCurrency(revenue.data?.arr?.arr_eur ?? null)}
              hint={`${formatNumber(revenue.data?.arr?.active_subscribers ?? 0)} active subscribers`}
              icon={Wallet}
            />
            <KpiCard
              label="Last 4 Weeks"
              value={formatCurrency(revenue.data?.arr?.last_4w_eur ?? null)}
              hint={`×${formatNumber(revenue.data?.arr?.multiplier ?? 0)} run-rate multiplier`}
              icon={CreditCard}
              accentClass="text-sky-700"
            />
            <KpiCard
              label="Stripe Revenue"
              value={formatCurrency(
                ((revenue.data?.payments?.total_revenue || 0) / 100) || null,
              )}
              hint={`${formatNumber(revenue.data?.payments?.payments.length ?? 0)} recent sessions`}
              icon={Receipt}
              accentClass="text-emerald-700"
            />
            <KpiCard
              label="OpenRouter"
              value={formatCurrency(revenue.data?.costs?.openrouter_usage_usd ?? null, {
                currency: "USD",
              })}
              hint={revenue.data?.costs
                ? `Limit ${formatCurrency(revenue.data.costs.openrouter_limit_usd, {
                    currency: "USD",
                  })}`
                : "No cost data"}
              icon={Sparkles}
              accentClass="text-amber-700"
            />
          </SurfaceStatGrid>

          <div className="grid gap-4 xl:grid-cols-3">
            <PeriodCard
              title="This Month"
              period={monthly || null}
              accentClass="text-slate-900"
            />
            <PeriodCard
              title="Six Months"
              period={sixMonth || null}
              accentClass="text-sky-700"
            />
            <PeriodCard
              title="This Year"
              period={yearly || null}
              accentClass="text-emerald-700"
            />
          </div>

          <div className="grid gap-4 xl:grid-cols-[0.9fr_1.1fr]">
            <SectionCard
              title="Invoice Monthly Totals"
              description="A compact view of recent invoice totals without needing spreadsheet exports."
            >
              {revenue.data?.invoices?.monthly.length ? (
                <div className="space-y-3">
                  {revenue.data.invoices.monthly.map((month) => (
                    <div
                      key={month.ym}
                      className="flex items-center justify-between rounded-2xl bg-slate-50 px-4 py-3"
                    >
                      <div>
                        <div className="text-sm font-medium text-slate-900">{month.ym}</div>
                        <div className="body-sm text-slate-500">
                          {formatNumber(month.invoices)} invoices
                        </div>
                      </div>
                      <div className="text-sm font-semibold text-slate-900">
                        {formatCurrency(month.eur_total)}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <SurfaceEmptyState
                  title="No monthly invoice totals yet"
                  description="This fills in once invoice ingestion has enough rows."
                />
              )}
            </SectionCard>

            <SectionCard
              title="Fixed Cost Items"
              description="Operator-maintained costs still matter for the P&L picture."
            >
              {revenue.data?.costs?.cost_items.length ? (
                <div className="space-y-3">
                  {revenue.data.costs.cost_items.map((item) => (
                    <div
                      key={`${item.name}-${item.frequency}`}
                      className="flex items-center justify-between rounded-2xl bg-slate-50 px-4 py-3"
                    >
                      <div>
                        <div className="text-sm font-medium text-slate-900">{item.name}</div>
                        <div className="body-sm text-slate-500">{item.frequency}</div>
                      </div>
                      <div className="text-sm font-semibold text-slate-900">
                        {formatCurrency(item.amount)}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <SurfaceEmptyState
                  title="No cost items configured"
                  description="The costs endpoint is ready, but there are no custom fixed-cost rows right now."
                />
              )}
            </SectionCard>
          </div>
        </TabsContent>

        <TabsContent value="invoices" className="mt-5 space-y-5">
          <SectionCard
            title="Invoices"
            description="Confirm or reclassify invoice rows here instead of digging through the old mixed-use P&L tab."
            actions={
              <div className="flex flex-col gap-2 sm:flex-row">
                <Input
                  value={invoiceSearch}
                  onChange={(event) => setInvoiceSearch(event.target.value)}
                  placeholder="Filter invoices by sender, vendor, or category"
                  className="sm:w-80"
                />
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => void reclassifyInvoices()}
                >
                  {actionKey === "invoice:reclassify" ? "Reclassifying…" : "Re-classify invoices"}
                </Button>
              </div>
            }
          >
            {filteredInvoices.length ? (
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="sticky left-0 z-[5] bg-white shadow-[1px_0_0_rgba(226,232,240,1)]">
                        Vendor
                      </TableHead>
                      <TableHead className="hidden md:table-cell">Sender</TableHead>
                      <TableHead>Category</TableHead>
                      <TableHead className="hidden md:table-cell">Invoice Date</TableHead>
                      <TableHead>Amount</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead className="w-[1%] text-right">Action</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {filteredInvoices.map((invoice) => (
                      <TableRow key={invoice.id}>
                        <TableCell className="sticky left-0 z-[5] bg-white shadow-[1px_0_0_rgba(226,232,240,1)]">
                          <div className="min-w-[220px]">
                            <div className="text-sm font-medium text-slate-900">
                              {invoice.vendor || invoice.subject || "Unknown vendor"}
                            </div>
                            <div className="body-sm text-slate-500 md:hidden">
                              {invoice.sender || "No sender"}
                            </div>
                          </div>
                        </TableCell>
                        <TableCell className="hidden md:table-cell">
                          {invoice.sender || "—"}
                        </TableCell>
                        <TableCell>{invoice.category || "Other"}</TableCell>
                        <TableCell className="hidden md:table-cell">
                          {toBelgianDate(invoice.invoice_date || invoice.received_at)}
                        </TableCell>
                        <TableCell>
                          {centsToCurrency(invoice.amount_cents, invoice.currency)}
                        </TableCell>
                        <TableCell>
                          <Badge variant={invoice.confirmed ? "default" : "secondary"}>
                            {invoice.confirmed ? "Confirmed" : "Unconfirmed"}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-right">
                          {invoice.confirmed ? (
                            <Badge variant="outline">Reviewed</Badge>
                          ) : (
                            <Button
                              variant="outline"
                              size="sm"
                              onClick={() => void confirmInvoice(invoice)}
                            >
                              {actionKey === `invoice:${invoice.id}` ? "Confirming…" : "Confirm"}
                            </Button>
                          )}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            ) : (
              <SurfaceEmptyState
                title="No invoices matched"
                description="Try a different filter or wait for invoice ingestion."
              />
            )}
          </SectionCard>
        </TabsContent>

        <TabsContent value="payments" className="mt-5">
          <SectionCard
            title="Stripe Sessions"
            description="A recent list is enough for operator spot checks; this view is meant to stay readable."
          >
            {revenue.data?.payments?.payments.length ? (
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Created</TableHead>
                      <TableHead>Email</TableHead>
                      <TableHead>Mode</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead>Amount</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {revenue.data.payments.payments.map((payment) => (
                      <TableRow key={payment.id}>
                        <TableCell>{toBelgianDateTime(payment.created)}</TableCell>
                        <TableCell>{payment.email || "—"}</TableCell>
                        <TableCell>{payment.mode}</TableCell>
                        <TableCell>
                          <Badge variant={payment.status === "paid" ? "default" : "secondary"}>
                            {payment.status}
                          </Badge>
                        </TableCell>
                        <TableCell>
                          {formatCurrency(payment.amount / 100, {
                            currency: (payment.currency || "EUR").toUpperCase(),
                          })}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            ) : (
              <SurfaceEmptyState
                title="No recent Stripe sessions"
                description="If billing is configured, recent sessions show up here."
              />
            )}
          </SectionCard>
        </TabsContent>

        <TabsContent value="ai" className="mt-5 space-y-5">
          <SurfaceStatGrid>
            <KpiCard
              label="OpenRouter Usage"
              value={formatCurrency(revenue.data?.costs?.openrouter_usage_usd ?? null, {
                currency: "USD",
              })}
              hint={revenue.data?.costs
                ? `Limit ${formatCurrency(revenue.data.costs.openrouter_limit_usd, {
                    currency: "USD",
                  })}`
                : "No data"}
              icon={Sparkles}
            />
            <KpiCard
              label="LLM Calls"
              value={formatNumber(revenue.data?.llm?.calls_total ?? 0)}
              hint={
                revenue.data?.llm
                  ? `${formatCurrency(revenue.data.llm.est_total_usd, {
                      currency: "USD",
                    })} estimated total`
                  : "No breakdown"
              }
              icon={Sparkles}
              accentClass="text-sky-700"
            />
          </SurfaceStatGrid>

          <div className="grid gap-4 xl:grid-cols-[0.9fr_1.1fr]">
            <SectionCard
              title="AI Calls (30 Days)"
              description="These are the operator-facing activity counts behind the spend."
            >
              {revenue.data?.costs ? (
                <div className="space-y-3">
                  {Object.entries(revenue.data.costs.ai_calls_30d).map(
                    ([key, value]) => (
                      <div
                        key={key}
                        className="flex items-center justify-between rounded-2xl bg-slate-50 px-4 py-3"
                      >
                        <div className="text-sm font-medium capitalize text-slate-900">
                          {key.replaceAll("_", " ")}
                        </div>
                        <Badge variant="secondary">{formatNumber(value)}</Badge>
                      </div>
                    ),
                  )}
                </div>
              ) : (
                <SurfaceEmptyState
                  title="No AI call summary"
                  description="The costs endpoint did not return AI call counts."
                />
              )}
            </SectionCard>

            <SectionCard
              title="LLM Cost Breakdown"
              description="Grouped by user-facing feature so the operator can see what is actually burning money."
            >
              {revenue.data?.llm?.breakdown.length ? (
                <div className="overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Feature</TableHead>
                        <TableHead>Calls</TableHead>
                        <TableHead>Avg / Call</TableHead>
                        <TableHead>Total</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {revenue.data.llm.breakdown.map((row) => (
                        <TableRow key={row.kind}>
                          <TableCell>{row.kind}</TableCell>
                          <TableCell>{formatNumber(row.calls)}</TableCell>
                          <TableCell>
                            {formatCurrency(row.est_cost_per_call_usd, {
                              currency: "USD",
                              maximumFractionDigits: 4,
                            })}
                          </TableCell>
                          <TableCell>
                            {formatCurrency(row.est_total_usd, {
                              currency: "USD",
                              maximumFractionDigits: 4,
                            })}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              ) : (
                <SurfaceEmptyState
                  title="No LLM breakdown yet"
                  description="Once LLM costs are logged, the per-feature breakdown appears here."
                />
              )}
            </SectionCard>
          </div>
        </TabsContent>
      </Tabs>
    </SurfaceFrame>
  );
}

function PeriodCard({
  title,
  period,
  accentClass,
}: {
  title: string;
  period: RevenueData["pnl"] extends infer T
    ? T extends { monthly: infer P } ? P | null : never
    : never;
  accentClass?: string;
}) {
  return (
    <SectionCard
      title={title}
      description={
        period
          ? `${toBelgianDate(period.window_start)} to ${toBelgianDate(period.window_end)}`
          : "No period summary available"
      }
      className="h-full"
    >
      {period ? (
        <div className="space-y-4">
          <div className={`text-3xl font-semibold tracking-tight ${accentClass || "text-slate-900"}`}>
            {formatCurrency(period.net_eur)}
          </div>
          <div className="grid gap-3 sm:grid-cols-3">
            <div className="rounded-2xl bg-slate-50 p-4">
              <div className="body-sm text-slate-500">Revenue</div>
              <div className="mt-1 text-lg font-semibold text-slate-900">
                {formatCurrency(period.revenue_eur)}
              </div>
            </div>
            <div className="rounded-2xl bg-slate-50 p-4">
              <div className="body-sm text-slate-500">OpenRouter</div>
              <div className="mt-1 text-lg font-semibold text-slate-900">
                {formatCurrency(period.openrouter_eur)}
              </div>
            </div>
            <div className="rounded-2xl bg-slate-50 p-4">
              <div className="body-sm text-slate-500">Invoices</div>
              <div className="mt-1 text-lg font-semibold text-slate-900">
                {formatCurrency(period.invoices_total_eur)}
              </div>
            </div>
          </div>
        </div>
      ) : (
        <SurfaceEmptyState
          title="No P&L summary"
          description="This period card fills in once the backend summary is available."
        />
      )}
    </SectionCard>
  );
}
