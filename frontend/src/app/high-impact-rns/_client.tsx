"use client";

import { useRouter } from "next/navigation";
import { useIsAdmin } from "@/hooks/useAdmin";
import { companyHref } from "@/lib/company";
import HighImpactRnsTab from "@/components/HighImpactRnsTab";

// Preproduction gate: while the showcase is being monitored, only admins (a
// browser that visited /?admin=<token>) see it. useIsAdmin() returns false during
// SSR and the first client render, so anonymous visitors never see a flash of
// content. At public release, remove this gate and render the tab unconditionally.
export default function HighImpactRnsPageClient() {
  const router = useRouter();
  const isAdmin = useIsAdmin();

  if (!isAdmin) {
    return (
      <div
        style={{
          padding: "80px 24px",
          textAlign: "center",
          color: "#555",
          fontFamily: "monospace",
          fontSize: 14,
        }}
      >
        Nothing here yet.
      </div>
    );
  }

  return <HighImpactRnsTab onSelect={(sym: string) => router.push(companyHref(sym))} />;
}
