"use client";

import StarButton from "@/components/screener/StarButton";
import { useWatchlist } from "@/app/providers";

// Watchlist toggle for the (otherwise server-rendered) company header. Small
// client island so the header itself can stay a server component. SSRs in the
// unstarred state and corrects on hydration, same as everywhere else.
export default function CompanyStar({ symbol, size = 20 }: { symbol: string; size?: number }) {
  const { defaultMembers, toggleWatchlist } = useWatchlist();
  return (
    <StarButton
      active={defaultMembers.has(symbol)}
      onClick={(e) => {
        e.preventDefault();
        e.stopPropagation();
        toggleWatchlist(symbol);
      }}
      size={size}
    />
  );
}
