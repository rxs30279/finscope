"use client";

import { useRouter } from "next/navigation";
import { useWatchlist, useRefresh } from "@/app/providers";
import Screener from "@/components/screener/Screener";

export default function ScreenerPage() {
  const router = useRouter();
  const { defaultMembers, toggleWatchlist } = useWatchlist();
  const { highlightSymbol } = useRefresh();

  return (
    <Screener
      onSelect={(sym, tab) =>
        router.push(
          `/company/${encodeURIComponent(sym)}${tab ? `?tab=${encodeURIComponent(tab)}` : ""}`,
        )
      }
      highlightSymbol={highlightSymbol}
      watchlist={defaultMembers}
      onToggleWatchlist={toggleWatchlist}
    />
  );
}
