"use client";

import { useState } from "react";
import Image from "next/image";
import { Check, RefreshCw, Wrench } from "lucide-react";
import type { SiteConfig } from "@/components/admin/admin-types";
import {
  SectionCard,
  SurfaceFrame,
  SurfaceLoadingState,
} from "@/components/admin/surface-frame";
import {
  adminFetch,
  useAdminResource,
} from "@/lib/admin-fetch";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

const LOGO_OPTIONS = [
  { path: "/logo.svg", label: "Mountain peak" },
  { path: "/logos/dog-a-warm.svg", label: "Dog - warm" },
  { path: "/logos/dog-telescope.jpg", label: "Dog - indigo" },
  { path: "/logos/dog-c-teal.svg", label: "Dog - teal" },
  { path: "/logos/datasnoop-logo-1-magnifier.svg", label: "Magnifier" },
  { path: "/logos/datasnoop-logo-2-eye.svg", label: "Eye" },
  { path: "/logos/datasnoop-logo-3-radar.svg", label: "Radar" },
] as const;

export default function SettingsSurface({
  enabled,
}: {
  enabled: boolean;
}) {
  const config = useAdminResource<SiteConfig>({
    enabled,
    fetcher: () => adminFetch<SiteConfig>("/api/admin/site-config"),
  });
  const [savingLogo, setSavingLogo] = useState<string | null>(null);
  const [runningMaintenance, setRunningMaintenance] = useState(false);
  const [maintenanceNote, setMaintenanceNote] = useState<string | null>(null);

  const currentLogo = config.data?.site_logo || "/logos/dog-telescope.jpg";

  const setLogo = async (path: string) => {
    setSavingLogo(path);
    try {
      await adminFetch("/api/admin/site-config", {
        method: "PUT",
        body: JSON.stringify({ site_logo: path }),
      });
      config.setData((prev) => ({ ...(prev || { site_logo: path }), site_logo: path }));
    } finally {
      setSavingLogo(null);
    }
  };

  const normalizeNames = async () => {
    setRunningMaintenance(true);
    setMaintenanceNote(null);

    try {
      const result = await adminFetch<{ rows_updated: number }>(
        "/api/admin/normalize-names",
        { method: "POST" },
      );
      setMaintenanceNote(
        `Name normalization completed for ${result.rows_updated.toLocaleString()} rows.`,
      );
    } catch (error) {
      setMaintenanceNote(
        error instanceof Error ? error.message : "Name normalization failed.",
      );
    } finally {
      setRunningMaintenance(false);
    }
  };

  if (config.isLoading && !config.data) {
    return <SurfaceLoadingState label="Loading admin settings…" />;
  }

  return (
    <SurfaceFrame
      title="Settings"
      description="Small platform-wide controls and maintenance tools that belong in admin, not hidden in a giant misc tab."
      actions={
        <Button variant="outline" size="sm" onClick={() => void config.refresh()}>
          <RefreshCw className="mr-2 size-4" />
          Refresh settings
        </Button>
      }
    >
      <SectionCard
        title="Site Logo"
        description="Choose which logo appears in the platform header. This is one of the few true platform-wide switches the operator actually uses."
      >
        <div className="space-y-5">
          <div className="flex items-center gap-3 rounded-2xl border border-slate-200 bg-slate-50 p-4">
            <Image
              src={currentLogo}
              alt="Current logo"
              width={48}
              height={48}
              className="h-12 w-12 rounded-xl bg-white object-contain p-1 shadow-sm"
            />
            <div className="space-y-1">
              <div className="text-sm font-semibold text-slate-900">Active logo</div>
              <div className="body-sm font-mono text-slate-500">{currentLogo}</div>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-4">
            {LOGO_OPTIONS.map((logo) => {
              const active = currentLogo === logo.path;
              const busy = savingLogo === logo.path;

              return (
                <button
                  key={logo.path}
                  type="button"
                  disabled={savingLogo != null}
                  onClick={() => void setLogo(logo.path)}
                  className={`relative rounded-2xl border p-4 text-left transition ${
                    active
                      ? "border-sky-500 bg-sky-50 ring-2 ring-sky-200"
                      : "border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50"
                  } ${savingLogo != null ? "cursor-wait opacity-75" : ""}`}
                >
                  {active ? (
                    <div className="absolute right-2 top-2 rounded-full bg-sky-600 p-1 text-white">
                      <Check className="size-3" />
                    </div>
                  ) : null}
                  <div className="flex items-center gap-3">
                    <div className="rounded-xl bg-slate-100 p-3">
                      <Image
                        src={logo.path}
                        alt={logo.label}
                        width={40}
                        height={40}
                        className="h-10 w-10 object-contain"
                      />
                    </div>
                    <div className="space-y-1">
                      <div className="text-sm font-medium text-slate-900">{logo.label}</div>
                      <div className="body-sm text-slate-500">
                        {busy ? "Saving…" : active ? "Currently active" : "Click to activate"}
                      </div>
                    </div>
                  </div>
                </button>
              );
            })}
          </div>
        </div>
      </SectionCard>

      <SectionCard
        title="Maintenance"
        description="Keep one-off operational utilities here so they stay discoverable and don’t get buried in unrelated tabs."
      >
        <div className="space-y-4">
          <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
            <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
              <div className="flex items-start gap-3">
                <div className="rounded-2xl bg-white p-3 text-slate-700 shadow-sm">
                  <Wrench className="size-5" />
                </div>
                <div className="space-y-1">
                  <div className="text-sm font-semibold text-slate-900">
                    Re-normalize company names
                  </div>
                  <div className="body text-slate-600">
                    Refreshes the normalized-name column used for fuzzy matching after data refreshes or parsing fixes.
                  </div>
                </div>
              </div>
              <Button
                variant="outline"
                size="sm"
                disabled={runningMaintenance}
                onClick={() => void normalizeNames()}
              >
                {runningMaintenance ? "Running…" : "Run normalization"}
              </Button>
            </div>
          </div>

          {maintenanceNote ? (
            <Badge variant="secondary" className="px-3 py-1.5">
              {maintenanceNote}
            </Badge>
          ) : null}
        </div>
      </SectionCard>
    </SurfaceFrame>
  );
}
