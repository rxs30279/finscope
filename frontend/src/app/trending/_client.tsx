"use client";

import { useRouter } from "next/navigation";
import { companyHref } from "@/lib/company";
import TrendingTab from "@/components/trending/TrendingTab";

export default function TrendingPageClient() {
  const router = useRouter();
  return (
    <TrendingTab
      onSelect={(sym: string) => router.push(companyHref(sym))}
    />
  );
}
