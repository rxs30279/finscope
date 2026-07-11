"use client";

import { useRouter } from "next/navigation";
import { companyHref } from "@/lib/company";
import HighImpactRnsTab from "@/components/HighImpactRnsTab";
import type { ShowcaseRow } from "@/lib/showcase";

export default function HighImpactRnsPageClient({
  initialRows,
}: {
  initialRows: ShowcaseRow[] | null;
}) {
  const router = useRouter();
  return (
    <HighImpactRnsTab
      initialRows={initialRows}
      onSelect={(sym: string) => router.push(companyHref(sym))}
    />
  );
}
