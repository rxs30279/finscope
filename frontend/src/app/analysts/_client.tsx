"use client";

import { useRouter } from "next/navigation";
import { useRefresh } from "@/app/providers";
import { companyHref } from "@/lib/company";
import AnalystMonitorTab from "@/components/AnalystMonitorTab";

export default function AnalystsPageClient() {
  const router = useRouter();
  const { refreshKey } = useRefresh();

  return (
    <AnalystMonitorTab
      refreshKey={refreshKey}
      onSelect={(sym: string, tab?: string) => router.push(companyHref(sym, tab))}
    />
  );
}
