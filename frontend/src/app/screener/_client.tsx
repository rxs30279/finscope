"use client";

import { useRouter } from "next/navigation";
import { useWatchlist, useRefresh } from "@/app/providers";
import { companyHref } from "@/lib/company";
import Screener from "@/components/screener/Screener";

export default function ScreenerPageClient() {
  const router = useRouter();
  const { defaultMembers, toggleWatchlist } = useWatchlist();
  const { highlightSymbol } = useRefresh();

  return (
    <Screener
      onSelect={(sym, tab) => router.push(companyHref(sym, tab))}
      highlightSymbol={highlightSymbol}
      watchlist={defaultMembers}
      onToggleWatchlist={toggleWatchlist}
    />
  );
}
