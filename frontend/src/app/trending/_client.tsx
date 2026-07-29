"use client";

import { useRouter } from "next/navigation";
import { companyHref } from "@/lib/company";
import TrendingTab from "@/components/trending/TrendingTab";
import type { Trending } from "@/lib/trending";

export default function TrendingPageClient({
  initialData,
}: {
  initialData: Trending | null;
}) {
  const router = useRouter();
  return (
    <TrendingTab
      initialData={initialData}
      onSelect={(sym: string) => router.push(companyHref(sym))}
    />
  );
}
