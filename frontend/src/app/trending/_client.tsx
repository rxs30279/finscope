"use client";

import { useRouter } from "next/navigation";
import TrendingTab from "@/components/trending/TrendingTab";

export default function TrendingPageClient() {
  const router = useRouter();
  return (
    <TrendingTab
      onSelect={(sym: string) => router.push(`/company?symbol=${encodeURIComponent(sym)}`)}
    />
  );
}
