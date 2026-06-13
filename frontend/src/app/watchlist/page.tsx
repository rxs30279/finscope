"use client";

import { useRouter } from "next/navigation";
import { useWatchlist } from "@/app/providers";
import WatchlistTab from "@/components/WatchlistTab";

export default function WatchlistPage() {
  const router = useRouter();
  const {
    watchlists,
    createWatchlist,
    renameWatchlist,
    deleteWatchlist,
    addToWatchlist,
    removeFromWatchlist,
  } = useWatchlist();

  return (
    <WatchlistTab
      watchlists={watchlists}
      onSelect={(sym: string) => router.push(`/company?symbol=${encodeURIComponent(sym)}`)}
      onCreateList={createWatchlist}
      onRenameList={renameWatchlist}
      onDeleteList={deleteWatchlist}
      onAddSymbol={addToWatchlist}
      onRemoveSymbol={removeFromWatchlist}
    />
  );
}
