"use client";

import { useRouter } from "next/navigation";
import { useIsAdmin } from "@/hooks/useAdmin";
import { companyHref } from "@/lib/company";
import HighImpactRnsTab from "@/components/HighImpactRnsTab";

export default function HighImpactRnsArchiveClient() {
  const isAdmin = useIsAdmin();
  const router = useRouter();

  if (!isAdmin) {
    return (
      <div style={{ padding: "80px 24px", textAlign: "center", color: "#94a3b8", fontFamily: "monospace", fontSize: 14 }}>
        Admins only. Unlock with <code>/?admin=&lt;token&gt;</code>.
      </div>
    );
  }

  return <HighImpactRnsTab archiveOnly onSelect={(sym: string) => router.push(companyHref(sym))} />;
}
