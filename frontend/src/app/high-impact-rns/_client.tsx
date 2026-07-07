"use client";

import { useRouter } from "next/navigation";
import { companyHref } from "@/lib/company";
import HighImpactRnsTab from "@/components/HighImpactRnsTab";

export default function HighImpactRnsPageClient() {
  const router = useRouter();
  return <HighImpactRnsTab onSelect={(sym: string) => router.push(companyHref(sym))} />;
}
