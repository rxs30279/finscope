"use client";

import { useRouter } from "next/navigation";
import { useRefresh } from "@/app/providers";
import RnsTab from "@/components/RnsTab";

export default function RnsPageClient() {
  const router = useRouter();
  const { refreshKey } = useRefresh();

  return (
    <RnsTab
      refreshKey={refreshKey}
      onSelect={(sym: string) => router.push(`/company?symbol=${encodeURIComponent(sym)}`)}
    />
  );
}
