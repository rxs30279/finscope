"use client";

import { useRouter } from "next/navigation";
import { useRefresh } from "@/app/providers";
import { companyHref } from "@/lib/company";
import HeatmapTab from "@/components/HeatmapTab";

export default function HeatmapPageClient() {
  const router = useRouter();
  const { refreshKey } = useRefresh();

  return (
    <HeatmapTab
      refreshKey={refreshKey}
      onSelect={(sym: string) => router.push(companyHref(sym))}
    />
  );
}
