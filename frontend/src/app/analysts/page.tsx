"use client";

import { useRouter } from "next/navigation";
import { useRefresh } from "@/app/providers";
import AnalystMonitorTab from "@/components/AnalystMonitorTab";

export default function AnalystsPage() {
  const router = useRouter();
  const { refreshKey } = useRefresh();

  return (
    <AnalystMonitorTab
      refreshKey={refreshKey}
      onSelect={(sym: string, tab?: string) =>
        router.push(
          `/company?symbol=${encodeURIComponent(sym)}${tab ? `&tab=${encodeURIComponent(tab)}` : ""}`,
        )
      }
    />
  );
}
