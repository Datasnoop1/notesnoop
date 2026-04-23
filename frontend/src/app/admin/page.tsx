import { Suspense } from "react";
import { AdminShell } from "@/components/admin/admin-shell";
import { SurfaceLoadingState } from "@/components/admin/surface-frame";

export default function AdminPage() {
  return (
    <div className="min-h-screen bg-[radial-gradient(circle_at_top_left,_rgba(14,165,233,0.10),_transparent_28%),linear-gradient(180deg,#f8fafc_0%,#eef2ff_100%)]">
      <div className="mx-auto max-w-[1536px] px-4 py-6 sm:px-6 lg:px-8">
        <Suspense fallback={<SurfaceLoadingState label="Loading admin shell…" />}>
          <AdminShell />
        </Suspense>
      </div>
    </div>
  );
}
