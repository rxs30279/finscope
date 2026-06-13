"use client";

import { useRouter } from "next/navigation";
import { useRefresh } from "@/app/providers";
import Sidebar from "@/components/Sidebar";

export default function BenchmarksPage() {
  const router = useRouter();
  const { refreshKey } = useRefresh();

  return (
    <Sidebar
      refreshKey={refreshKey}
      onNavigate={(page: string) => router.push(`/${page}`)}
      mobile
    />
  );
}
