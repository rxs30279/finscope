"use client";

import { useRouter } from "next/navigation";
import { useRefresh } from "@/app/providers";
import HeatmapTab from "@/components/HeatmapTab";

export default function HeatmapPage() {
  const router = useRouter();
  const { refreshKey } = useRefresh();

  return (
    <HeatmapTab
      refreshKey={refreshKey}
      onSelect={(sym: string) => router.push(`/company?symbol=${encodeURIComponent(sym)}`)}
    />
  );
}
