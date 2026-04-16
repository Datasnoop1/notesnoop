"use client";

import React, { useMemo, useState } from "react";
import Link from "next/link";
import {
  Tabs,
  TabsList,
  TabsTrigger,
  TabsContent,
} from "@/components/ui/tabs";
import {
  Table,
  TableHeader,
  TableHead,
  TableBody,
  TableRow,
  TableCell,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import {
  ArrowLeft,
  Landmark,
  Award,
  Sparkles,
  FlaskConical,
  HardHat,
  Building2,
  ShieldCheck,
  ExternalLink,
  Banknote,
  Rocket,
  AlertTriangle,
  UserPlus,
  UserMinus,
  TrendingUp,
  Leaf,
  MapPin,
  GitBranch,
  FileText,
  Info,
} from "lucide-react";

/* =========================================================
   MOCK DATA — Fictional company for preview purposes only
   ========================================================= */

const DEMO_COMPANY = {
  name: "NOVA FOOD & FACILITIES NV",
  cbe: "0765432109",
  cbeDisplay: "0765.432.109",
  status: "AC",
  street: "Industriezone Haven 42",
  zipcode: "1930",
  city: "Zaventem",
  naceCode: "56.290",
  naceLabel: "Other food service activities",
  website: "novafoodfacilities.be",
  incorporated: "2008-03-14",
};

/* --- Public Money --- */

const TENDERS = [
  {
    buyer: "Stad Gent",
    title: "School catering framework 2023–2026",
    date: "2023-06-18",
    value: 1_200_000,
    source: "TED",
  },
  {
    buyer: "FOD Financiën",
    title: "Canteen services HQ Brussels",
    date: "2022-11-02",
    value: 680_000,
    source: "TED",
  },
  {
    buyer: "AZ Groeninge",
    title: "Hospital meals supply (3 year)",
    date: "2024-03-21",
    value: 980_000,
    source: "e-Notification",
  },
  {
    buyer: "KU Leuven",
    title: "Student restaurant operations 2024",
    date: "2024-09-05",
    value: 520_000,
    source: "TED",
  },
  {
    buyer: "OCMW Antwerpen",
    title: "Elderly-home catering framework",
    date: "2025-02-14",
    value: 1_450_000,
    source: "e-Notification",
  },
];

const SUBSIDIES = [
  {
    scheme: "VLAIO Ecologiepremie+",
    year: 2023,
    amount: 340_000,
    source: "Subsidieregister Vlaanderen",
    purpose: "Heat-recovery installation kitchens",
  },
  {
    scheme: "VLAIO Strategic Transformation Support",
    year: 2024,
    amount: 580_000,
    source: "Subsidieregister Vlaanderen",
    purpose: "Automation & robotics central kitchen",
  },
  {
    scheme: "EU State Aid SA.58668 (COVID framework)",
    year: 2021,
    amount: 280_000,
    source: "EU TAM Transparency",
    purpose: "COVID operating-aid HORECA",
  },
  {
    scheme: "Fonds Voedselindustrie",
    year: 2022,
    amount: 95_000,
    source: "Subsidieregister Vlaanderen",
    purpose: "Sustainable packaging conversion",
  },
];

const HORIZON = [
  {
    acronym: "SUSTFOOD-27",
    title: "Sustainable meal production at scale for public catering",
    role: "Partner",
    budget: 850_000,
    status: "Active",
    period: "2023–2027",
  },
];

/* --- Fingerprint --- */

const FAVV_ACTIVITIES = [
  { pap: "PAP 57.28", label: "Production of prepared meals", status: "Approved" },
  { pap: "PAP 58.11", label: "Cold-storage distribution", status: "Approved" },
  { pap: "PAP 55.30", label: "On-site catering services", status: "Registered" },
];

const ERKENDE_AANNEMER = [
  { category: "D — General building", classLevel: "Class 5 (≤ €1.85M)", validUntil: "2026-11-30" },
  { category: "G1 — Drainage works", classLevel: "Class 2 (≤ €275k)", validUntil: "2026-11-30" },
];

const OTHER_ACCREDITATIONS = [
  { label: "VCA* safety certificate", status: "Valid", period: "2024–2027", icon: HardHat },
  { label: "ISO 22000 food safety", status: "Valid", period: "2023–2026", icon: ShieldCheck },
  { label: "FSMA registered intermediary", status: "Not applicable", period: null, icon: Landmark },
  { label: "KMO-portefeuille service provider", status: "Not applicable", period: null, icon: Sparkles },
  { label: "BELAC accredited lab", status: "Not applicable", period: null, icon: FlaskConical },
  { label: "BIPT telecom operator", status: "Not applicable", period: null, icon: Building2 },
];

/* --- Event Radar --- */

const EVENT_TYPES: Record<string, { label: string; color: string; icon: React.ComponentType<{ className?: string }> }> = {
  permit: { label: "Permit", color: "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200", icon: Leaf },
  appointment: { label: "Appointment", color: "bg-blue-50 text-blue-700 ring-1 ring-blue-200", icon: UserPlus },
  resignation: { label: "Resignation", color: "bg-slate-100 text-slate-600 ring-1 ring-slate-200", icon: UserMinus },
  capital: { label: "Capital change", color: "bg-indigo-50 text-indigo-700 ring-1 ring-indigo-200", icon: TrendingUp },
  office: { label: "Office move", color: "bg-cyan-50 text-cyan-700 ring-1 ring-cyan-200", icon: MapPin },
  statutes: { label: "Statutes", color: "bg-purple-50 text-purple-700 ring-1 ring-purple-200", icon: FileText },
  subsidiary: { label: "Subsidiary", color: "bg-amber-50 text-amber-700 ring-1 ring-amber-200", icon: GitBranch },
  distress: { label: "Distress", color: "bg-rose-50 text-rose-700 ring-1 ring-rose-200", icon: AlertTriangle },
};

const EVENTS = [
  {
    date: "2026-04-12",
    type: "permit",
    title: "Environmental permit filed (Class 2)",
    detail: "Expansion of cold-storage facility, Zaventem",
    source: "Omgevingsloket (VLAREM)",
  },
  {
    date: "2026-03-28",
    type: "appointment",
    title: "New director appointed",
    detail: "Marc De Wever (CFO) — appointed by AGM",
    source: "Staatsblad annex",
  },
  {
    date: "2026-02-14",
    type: "capital",
    title: "Capital increase",
    detail: "Share capital raised by €2.5M to €12.5M (cash contribution)",
    source: "Staatsblad annex",
  },
  {
    date: "2026-01-09",
    type: "office",
    title: "Registered office moved",
    detail: "From Brussels 1000 → Zaventem 1930",
    source: "Staatsblad annex",
  },
  {
    date: "2025-11-22",
    type: "resignation",
    title: "Director resigned",
    detail: "Anne Peeters (COO) — resignation tendered",
    source: "Staatsblad annex",
  },
  {
    date: "2025-10-05",
    type: "statutes",
    title: "Articles of association amended",
    detail: "Object clause expanded to include food-service consulting",
    source: "Staatsblad annex",
  },
  {
    date: "2025-09-14",
    type: "subsidiary",
    title: "Subsidiary incorporated",
    detail: "NOVA LOGISTICS BV (CBE 0812.345.678) — 100% owned",
    source: "Staatsblad annex",
  },
];

/* =========================================================
   HELPERS
   ========================================================= */

function fmtEur(v: number | null | undefined): string {
  if (v == null) return "—";
  if (Math.abs(v) >= 1_000_000) return `€${(v / 1_000_000).toFixed(2)}M`;
  if (Math.abs(v) >= 1_000) return `€${(v / 1_000).toFixed(0)}k`;
  return `€${v}`;
}

function fmtDate(d: string): string {
  return new Date(d).toLocaleDateString("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

/* =========================================================
   HEADER
   ========================================================= */

function DemoHeader() {
  const address = `${DEMO_COMPANY.street}, ${DEMO_COMPANY.zipcode} ${DEMO_COMPANY.city}`;
  return (
    <div className="mb-6">
      <div className="mb-3 flex items-center gap-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
        <Info className="h-3.5 w-3.5" />
        <span>
          <strong>Preview only.</strong> This is a static mock-up of a proposed
          enrichment profile with sample data. Nothing here is wired to the
          backend yet.
        </span>
      </div>

      <Link
        href="/"
        className="mb-3 inline-flex items-center gap-1 text-xs text-slate-500 hover:text-indigo-600"
      >
        <ArrowLeft className="h-3 w-3" /> Back
      </Link>

      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-xl font-semibold text-slate-900">
            {DEMO_COMPANY.name}
          </h1>
          <div className="mt-0.5 flex flex-wrap items-center gap-x-1.5 text-xs text-slate-400">
            <span className="inline-flex items-center gap-1.5">
              <span className="inline-block h-1.5 w-1.5 rounded-full bg-emerald-500" />
              <span className="font-mono">CBE {DEMO_COMPANY.cbeDisplay}</span>
            </span>
            <span className="text-slate-300">|</span>
            <span>{address}</span>
            <span className="text-slate-300">|</span>
            <a
              href={`https://${DEMO_COMPANY.website}`}
              target="_blank"
              rel="noopener noreferrer"
              className="text-indigo-500 hover:text-indigo-700"
            >
              {DEMO_COMPANY.website}
            </a>
            <span className="text-slate-300">|</span>
            <span>
              NACE {DEMO_COMPANY.naceCode} — {DEMO_COMPANY.naceLabel}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}

/* =========================================================
   TAB 1 — PUBLIC MONEY
   ========================================================= */

function PublicMoneyTab() {
  const totalTenders = TENDERS.reduce((s, t) => s + t.value, 0);
  const totalSubsidies = SUBSIDIES.reduce((s, t) => s + t.amount, 0);
  const totalHorizon = HORIZON.reduce((s, t) => s + t.budget, 0);
  const assumedRevenue = 18_500_000;
  const publicPct = Math.round(((totalTenders + totalSubsidies) / 5 / assumedRevenue) * 100);

  const kpis = [
    {
      label: "Public contracts won (5y)",
      value: fmtEur(totalTenders),
      hint: `${TENDERS.length} awards`,
      icon: Landmark,
      accent: "text-indigo-700 bg-indigo-50 ring-indigo-200",
    },
    {
      label: "Subsidies & grants (5y)",
      value: fmtEur(totalSubsidies),
      hint: `${SUBSIDIES.length} awards`,
      icon: Banknote,
      accent: "text-emerald-700 bg-emerald-50 ring-emerald-200",
    },
    {
      label: "Horizon Europe participation",
      value: fmtEur(totalHorizon),
      hint: HORIZON[0]?.acronym ?? "—",
      icon: Rocket,
      accent: "text-purple-700 bg-purple-50 ring-purple-200",
    },
    {
      label: "Public-revenue share (est.)",
      value: `~${publicPct}%`,
      hint: "Tenders ÷ 5y / revenue",
      icon: Award,
      accent: "text-amber-700 bg-amber-50 ring-amber-200",
    },
  ];

  return (
    <div className="space-y-6">
      {/* KPI cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {kpis.map((k) => (
          <div
            key={k.label}
            className={`rounded-lg ring-1 p-3 ${k.accent}`}
          >
            <div className="flex items-center gap-2 text-[10px] font-medium uppercase tracking-wider opacity-80">
              <k.icon className="h-3 w-3" />
              {k.label}
            </div>
            <div className="mt-1 text-xl font-bold">{k.value}</div>
            <div className="mt-0.5 text-[11px] opacity-75">{k.hint}</div>
          </div>
        ))}
      </div>

      {/* Public procurement */}
      <section>
        <h3 className="mb-2 text-xs font-bold uppercase tracking-wider text-slate-500 border-l-[3px] border-indigo-500 pl-2">
          Public procurement wins
        </h3>
        <div className="rounded-lg border bg-white overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow className="bg-slate-50">
                <TableHead className="text-xs">Buyer</TableHead>
                <TableHead className="text-xs">Contract</TableHead>
                <TableHead className="text-xs">Date</TableHead>
                <TableHead className="text-xs text-right">Value</TableHead>
                <TableHead className="text-xs">Source</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {TENDERS.map((t, i) => (
                <TableRow key={i}>
                  <TableCell className="text-xs text-slate-700 py-2">{t.buyer}</TableCell>
                  <TableCell className="text-xs text-slate-600 py-2">{t.title}</TableCell>
                  <TableCell className="text-xs text-slate-500 py-2">{fmtDate(t.date)}</TableCell>
                  <TableCell className="text-xs text-right font-mono py-2">{fmtEur(t.value)}</TableCell>
                  <TableCell className="py-2">
                    <Badge variant="outline" className="text-[10px]">{t.source}</Badge>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </section>

      {/* Subsidies */}
      <section>
        <h3 className="mb-2 text-xs font-bold uppercase tracking-wider text-slate-500 border-l-[3px] border-emerald-500 pl-2">
          Subsidies & grants
        </h3>
        <div className="rounded-lg border bg-white overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow className="bg-slate-50">
                <TableHead className="text-xs">Scheme</TableHead>
                <TableHead className="text-xs">Purpose</TableHead>
                <TableHead className="text-xs">Year</TableHead>
                <TableHead className="text-xs text-right">Amount</TableHead>
                <TableHead className="text-xs">Source</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {SUBSIDIES.map((s, i) => (
                <TableRow key={i}>
                  <TableCell className="text-xs text-slate-700 py-2">{s.scheme}</TableCell>
                  <TableCell className="text-xs text-slate-500 py-2">{s.purpose}</TableCell>
                  <TableCell className="text-xs text-slate-500 py-2">{s.year}</TableCell>
                  <TableCell className="text-xs text-right font-mono py-2">{fmtEur(s.amount)}</TableCell>
                  <TableCell className="py-2">
                    <Badge variant="outline" className="text-[10px]">{s.source}</Badge>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </section>

      {/* Horizon Europe */}
      <section>
        <h3 className="mb-2 text-xs font-bold uppercase tracking-wider text-slate-500 border-l-[3px] border-purple-500 pl-2">
          Horizon Europe participation
        </h3>
        <div className="rounded-lg border bg-white overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow className="bg-slate-50">
                <TableHead className="text-xs">Project</TableHead>
                <TableHead className="text-xs">Role</TableHead>
                <TableHead className="text-xs">Period</TableHead>
                <TableHead className="text-xs text-right">Budget share</TableHead>
                <TableHead className="text-xs">Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {HORIZON.map((h, i) => (
                <TableRow key={i}>
                  <TableCell className="text-xs py-2">
                    <div className="font-medium text-slate-700">{h.acronym}</div>
                    <div className="text-slate-500">{h.title}</div>
                  </TableCell>
                  <TableCell className="text-xs text-slate-600 py-2">{h.role}</TableCell>
                  <TableCell className="text-xs text-slate-500 py-2">{h.period}</TableCell>
                  <TableCell className="text-xs text-right font-mono py-2">{fmtEur(h.budget)}</TableCell>
                  <TableCell className="py-2">
                    <Badge className="bg-emerald-100 text-emerald-700 text-[10px]">{h.status}</Badge>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </section>

      <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-[11px] text-slate-500">
        <strong>Sources in production:</strong> TED (EU procurement API) ·
        e-Notification (BE national tenders) · EU State Aid Transparency (TAM)
        · CORDIS (Horizon Europe) · Subsidieregister Vlaanderen.
      </div>
    </div>
  );
}

/* =========================================================
   TAB 2 — FINGERPRINT
   ========================================================= */

function FingerprintTab() {
  return (
    <div className="space-y-6">
      {/* Summary row */}
      <div className="rounded-lg border border-slate-200 bg-slate-50 p-4">
        <div className="text-xs uppercase tracking-wider text-slate-500 mb-1">What this company actually does</div>
        <p className="text-sm text-slate-700">
          Beyond its NACE code ({DEMO_COMPANY.naceCode}), accreditation records
          reveal a dual profile: <strong>FAVV-approved food producer</strong>{" "}
          operating both a prepared-meals plant and cold-chain distribution, plus
          a <strong>recognised public-works contractor (Class 5)</strong> for
          building and drainage — a combination that enables both catering
          contracts and on-site kitchen fit-outs.
        </p>
      </div>

      {/* FAVV */}
      <section>
        <h3 className="mb-2 text-xs font-bold uppercase tracking-wider text-slate-500 border-l-[3px] border-emerald-500 pl-2 flex items-center gap-2">
          Food safety — FAVV / AFSCA
          <Badge className="bg-emerald-100 text-emerald-700 text-[10px]">3 activities</Badge>
        </h3>
        <div className="rounded-lg border bg-white overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow className="bg-slate-50">
                <TableHead className="text-xs">PAP code</TableHead>
                <TableHead className="text-xs">Activity</TableHead>
                <TableHead className="text-xs">Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {FAVV_ACTIVITIES.map((a, i) => (
                <TableRow key={i}>
                  <TableCell className="text-xs font-mono py-2">{a.pap}</TableCell>
                  <TableCell className="text-xs text-slate-600 py-2">{a.label}</TableCell>
                  <TableCell className="py-2">
                    <Badge className={a.status === "Approved"
                      ? "bg-emerald-100 text-emerald-700 text-[10px]"
                      : "bg-slate-100 text-slate-600 text-[10px]"}>
                      {a.status}
                    </Badge>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
        <p className="mt-1 text-[11px] text-slate-400">
          Status "Approved" (erkenning) is a higher bar than "Registered" —
          required for on-site preparation/processing of animal-origin food.
        </p>
      </section>

      {/* Erkende aannemer */}
      <section>
        <h3 className="mb-2 text-xs font-bold uppercase tracking-wider text-slate-500 border-l-[3px] border-indigo-500 pl-2 flex items-center gap-2">
          Public-works recognition — FOD Economie
          <Badge className="bg-indigo-100 text-indigo-700 text-[10px]">2 categories</Badge>
        </h3>
        <div className="rounded-lg border bg-white overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow className="bg-slate-50">
                <TableHead className="text-xs">Category</TableHead>
                <TableHead className="text-xs">Class</TableHead>
                <TableHead className="text-xs">Valid until</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {ERKENDE_AANNEMER.map((a, i) => (
                <TableRow key={i}>
                  <TableCell className="text-xs text-slate-700 py-2">{a.category}</TableCell>
                  <TableCell className="text-xs text-slate-600 py-2">{a.classLevel}</TableCell>
                  <TableCell className="text-xs text-slate-500 py-2">{a.validUntil}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
        <p className="mt-1 text-[11px] text-slate-400">
          Class 5 recognition gates the company into public-works tenders up to
          ~€1.85M per contract (category D, general building).
        </p>
      </section>

      {/* Other accreditations */}
      <section>
        <h3 className="mb-2 text-xs font-bold uppercase tracking-wider text-slate-500 border-l-[3px] border-slate-400 pl-2">
          Other regulatory registers
        </h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          {OTHER_ACCREDITATIONS.map((a, i) => {
            const Icon = a.icon;
            const active = a.status === "Valid";
            return (
              <div
                key={i}
                className={`flex items-center gap-3 rounded-lg border p-3 ${
                  active
                    ? "border-emerald-200 bg-emerald-50/50"
                    : "border-slate-200 bg-white"
                }`}
              >
                <Icon className={`h-4 w-4 ${active ? "text-emerald-600" : "text-slate-400"}`} />
                <div className="min-w-0 flex-1">
                  <div className="text-xs font-medium text-slate-700">{a.label}</div>
                  <div className="text-[11px] text-slate-500">
                    {a.status}{a.period ? ` · ${a.period}` : ""}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </section>

      {/* Sector context */}
      <section>
        <h3 className="mb-2 text-xs font-bold uppercase tracking-wider text-slate-500 border-l-[3px] border-amber-500 pl-2">
          Labour & sector context
        </h3>
        <div className="rounded-lg border border-slate-200 bg-white p-4 space-y-2">
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="text-xs font-medium text-slate-700">Joint Committee (PC)</div>
              <div className="text-[11px] text-slate-500">
                PC 200 — General white-collar workers · PC 118 — Food industry (blue-collar)
              </div>
            </div>
            <Badge variant="outline" className="text-[10px]">Mixed</Badge>
          </div>
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="text-xs font-medium text-slate-700">AEO customs status</div>
              <div className="text-[11px] text-slate-500">Authorised Economic Operator — AEO-C (customs simplifications)</div>
            </div>
            <Badge className="bg-blue-100 text-blue-700 text-[10px]">AEO-C</Badge>
          </div>
        </div>
      </section>

      <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-[11px] text-slate-500">
        <strong>Sources in production:</strong> FAVV/AFSCA operators CSV ·
        FOD Economie erkende aannemers · FSMA register · BELAC accredited bodies
        · BIPT operators · KMO-portefeuille service-provider list · EU AEO
        consultation portal · PC reference tables (FOD WASO).
      </div>
    </div>
  );
}

/* =========================================================
   TAB 3 — EVENT RADAR
   ========================================================= */

function EventRadarTab() {
  const [filter, setFilter] = useState<string>("all");

  const visible = useMemo(() => {
    if (filter === "all") return EVENTS;
    return EVENTS.filter((e) => e.type === filter);
  }, [filter]);

  const filterOptions = [
    { id: "all", label: "All" },
    { id: "capital", label: "Capital" },
    { id: "appointment", label: "Appointments" },
    { id: "resignation", label: "Resignations" },
    { id: "office", label: "Office moves" },
    { id: "permit", label: "Permits" },
    { id: "statutes", label: "Statutes" },
    { id: "subsidiary", label: "Subsidiaries" },
  ];

  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-indigo-200 bg-indigo-50 p-4">
        <div className="flex items-start gap-3">
          <Sparkles className="h-4 w-4 text-indigo-600 mt-0.5 shrink-0" />
          <div>
            <div className="text-sm font-medium text-indigo-900">Live event feed — last 90 days</div>
            <p className="text-[12px] text-indigo-800/80 mt-0.5">
              Staatsblad publications and environmental-permit filings, classified
              into event types. In production this updates within hours of
              publication. Users can save watchlists and get email alerts.
            </p>
          </div>
        </div>
      </div>

      {/* Filter chips */}
      <div className="flex flex-wrap gap-1.5">
        {filterOptions.map((opt) => {
          const active = filter === opt.id;
          return (
            <button
              key={opt.id}
              onClick={() => setFilter(opt.id)}
              className={`rounded-full px-3 py-1 text-[11px] font-medium transition ${
                active
                  ? "bg-indigo-600 text-white"
                  : "bg-white text-slate-600 ring-1 ring-slate-200 hover:ring-slate-300"
              }`}
            >
              {opt.label}
            </button>
          );
        })}
      </div>

      {/* Timeline */}
      <ol className="relative border-l border-slate-200 ml-2">
        {visible.map((e, i) => {
          const type = EVENT_TYPES[e.type];
          const Icon = type?.icon ?? FileText;
          return (
            <li key={i} className="mb-5 ml-6">
              <span className="absolute -left-3 flex h-6 w-6 items-center justify-center rounded-full bg-white ring-1 ring-slate-200">
                <Icon className="h-3 w-3 text-slate-500" />
              </span>
              <div className="rounded-lg border border-slate-200 bg-white p-3">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-medium ${type?.color}`}>
                        {type?.label}
                      </span>
                      <span className="text-[11px] text-slate-400">{fmtDate(e.date)}</span>
                    </div>
                    <div className="text-sm font-medium text-slate-800">{e.title}</div>
                    <div className="text-[12px] text-slate-600 mt-0.5">{e.detail}</div>
                  </div>
                  <a
                    href="#"
                    onClick={(ev) => ev.preventDefault()}
                    className="shrink-0 inline-flex items-center gap-1 text-[11px] text-indigo-600 hover:text-indigo-800"
                  >
                    {e.source} <ExternalLink className="h-3 w-3" />
                  </a>
                </div>
              </div>
            </li>
          );
        })}
      </ol>

      {visible.length === 0 && (
        <div className="py-8 text-center text-xs text-slate-400">
          No events of this type in the last 90 days.
        </div>
      )}

      <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-[11px] text-slate-500">
        <strong>Sources in production:</strong> Belgisch Staatsblad daily annex
        (already scraped — NLP classification to be added) · Omgevingsloket
        Vlaanderen (VLAREM permits) · openpermits.brussels · RegSol (bankruptcy
        proxy via Staatsblad).
      </div>
    </div>
  );
}

/* =========================================================
   PAGE
   ========================================================= */

export default function EnrichedProfilePreviewPage() {
  const [tab, setTab] = useState("publicmoney");

  return (
    <div className="mx-auto w-full max-w-[1200px] px-4 py-4">
      <DemoHeader />

      <Tabs value={tab} onValueChange={(v) => typeof v === "string" && setTab(v)}>
        <TabsList variant="line" className="border-b border-slate-100 gap-0 overflow-x-auto scrollbar-none">
          <TabsTrigger
            value="publicmoney"
            className="text-[11px] uppercase tracking-wider font-medium px-3 py-2 whitespace-nowrap data-active:text-indigo-600 data-active:after:bg-indigo-600"
          >
            <Landmark className="h-3 w-3 mr-1.5 inline" />
            Public Money
          </TabsTrigger>
          <TabsTrigger
            value="fingerprint"
            className="text-[11px] uppercase tracking-wider font-medium px-3 py-2 whitespace-nowrap data-active:text-indigo-600 data-active:after:bg-indigo-600"
          >
            <ShieldCheck className="h-3 w-3 mr-1.5 inline" />
            Fingerprint
          </TabsTrigger>
          <TabsTrigger
            value="events"
            className="text-[11px] uppercase tracking-wider font-medium px-3 py-2 whitespace-nowrap data-active:text-indigo-600 data-active:after:bg-indigo-600"
          >
            <Sparkles className="h-3 w-3 mr-1.5 inline" />
            Event Radar
          </TabsTrigger>
        </TabsList>

        <TabsContent value="publicmoney" className="mt-6">
          <PublicMoneyTab />
        </TabsContent>
        <TabsContent value="fingerprint" className="mt-6">
          <FingerprintTab />
        </TabsContent>
        <TabsContent value="events" className="mt-6">
          <EventRadarTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}
