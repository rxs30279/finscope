"use client";

import { useRouter } from "next/navigation";
import { useRefresh } from "@/app/providers";
import { companyHref } from "@/lib/company";
import AnalystMonitorTab from "@/components/AnalystMonitorTab";
import type { AnalystRow } from "@/lib/analysts";

export default function AnalystsPageClient({
  initialLatest = null,
  initialMovers = null,
}: {
  initialLatest?: AnalystRow[] | null;
  initialMovers?: AnalystRow[] | null;
}) {
  const router = useRouter();
  const { refreshKey } = useRefresh();

  return (
    <AnalystMonitorTab
      refreshKey={refreshKey}
      initialLatest={initialLatest}
      initialMovers={initialMovers}
      onSelect={(sym: string, tab?: string) => router.push(companyHref(sym, tab))}
    />
  );
}
